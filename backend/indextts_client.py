"""IndexTTS2 local TTS — stdin/stdout worker, no HTTP, no ports.
All I/O runs in executor thread — event loop never blocked."""
import subprocess
import json
import asyncio
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
INDEXTTS_DIR = PROJECT_ROOT / "model" / "indextts_repo"
UV_EXE = PROJECT_ROOT / "python" / "Scripts" / "uv.exe"

_worker = None       # Popen handle
_worker_lock = threading.Lock()
_worker_stderr = []  # captured stderr lines (last 200)
_READY_FILE = INDEXTTS_DIR / ".tts_worker.ready"


def _drain_stderr(proc):
    """Read stderr lines in background, keep last 200 for debugging."""
    global _worker_stderr
    for line in proc.stderr:
        line = line.strip()
        if line:
            _worker_stderr.append(line)
            _worker_stderr = _worker_stderr[-200:]
            print(f"[indextts-worker] {line}", flush=True)


_worker_first_infer = True  # first inference needs extra time for CUDA JIT compile


def _ensure_worker():
    """Start worker if not running. Called from executor thread."""
    global _worker, _worker_stderr
    if _worker is not None and _worker.poll() is None:
        return  # worker alive, nothing to do

    # Worker is dead or never started — any ready file on disk is stale
    if _READY_FILE.exists():
        _READY_FILE.unlink(missing_ok=True)

    print("[indextts] starting worker...")
    _worker_stderr = []
    _worker = subprocess.Popen(
        [str(UV_EXE), "run", "python", "tts_worker.py"],
        cwd=str(INDEXTTS_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Background thread to capture stderr so pipe never fills up
    threading.Thread(target=_drain_stderr, args=(_worker,), daemon=True).start()

    # Wait for ready file (written after model loaded)
    for _ in range(180):
        if _READY_FILE.exists():
            print("[indextts] worker ready")
            return
        import time as _time
        _time.sleep(1)
    # Timeout — collect stderr for diagnostics
    errs = "\n".join(_worker_stderr[-20:])
    raise RuntimeError(f"Worker failed to start in 3 minutes.\nLast stderr:\n{errs}")


def _sync_tts(text: str, ref_audio_path: str, output_path: str,
              prompt_text: str = "", emo_ref_path: str = "", timeout: int = None) -> dict:
    """Send TTS request to worker via stdin, read response from stdout.
    Runs in executor thread — blocking is fine here.
    After `timeout` seconds, kills the worker and raises an error
    so the next call auto-recovers with a fresh worker."""
    global _worker, _worker_stderr
    with _worker_lock:
        _ensure_worker()
        _worker_stderr.clear()

        payload = {
            "text": text,
            "ref": str(Path(ref_audio_path).resolve()),
            "output": str(Path(output_path).resolve()),
        }
        if prompt_text:
            payload["prompt_text"] = prompt_text
        if emo_ref_path:
            payload["emo_ref"] = str(Path(emo_ref_path).resolve())

        _worker.stdin.write(json.dumps(payload) + "\n")
        _worker.stdin.flush()

        # Watchdog: if worker hangs (GPU freeze), kill it so we recover
        # First inference after worker start needs extra time for CUDA JIT compile
        if timeout is None:
            global _worker_first_infer
            timeout = 300  # 5 min — CUDA JIT + long text
            if _worker_first_infer:
                _worker_first_infer = False
                print(f"[indextts] first inference, timeout={timeout}s (CUDA warmup)")
        import time as _time
        killed = [False]
        deadline = _time.time() + timeout

        def _watchdog():
            killed[0] = True
            pid = _worker.pid
            # taskkill /F /T kills the entire process tree — works even on GPU-stuck processes
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=10,
                )
            except Exception:
                try:
                    _worker.kill()
                except Exception:
                    pass

        watchdog_timer = threading.Timer(timeout, _watchdog)
        watchdog_timer.daemon = True
        watchdog_timer.start()
        try:
            resp_line = _worker.stdout.readline()
        finally:
            watchdog_timer.cancel()

        if killed[0]:
            # Worker was stuck for >timeout — clean up so next call restarts
            try:
                _worker.wait(timeout=5)
            except Exception:
                pass
            _worker = None
            _READY_FILE.unlink(missing_ok=True)
            raise RuntimeError(
                f"Worker infer timed out after {timeout}s (GPU likely frozen). "
                f"Worker killed, next dub will auto-restart."
            )

        if not resp_line:
            # Worker died on its own — check exit code and stderr
            rc = _worker.poll()
            _worker = None
            _READY_FILE.unlink(missing_ok=True)
            errs = "\n".join(_worker_stderr[-30:])
            raise RuntimeError(
                f"Worker process exited (rc={rc}) before responding.\n"
                f"Last stderr:\n{errs}"
            )
        try:
            return json.loads(resp_line)
        except json.JSONDecodeError:
            errs = "\n".join(_worker_stderr[-30:])
            raise RuntimeError(
                f"Worker returned non-JSON: {resp_line[:200]!r}\n"
                f"Last stderr:\n{errs}"
            )


async def _ensure_server():
    """Pre-start the worker (for API endpoint). Called via executor."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _ensure_worker)


def is_worker_ready():
    """Check if TTS worker is running and model loaded.
    Only returns True if WE started the worker and it's alive — a ready file
    without a live _worker handle means stale state from a previous session."""
    if _worker is None:
        return False
    if _worker.poll() is not None:
        return False
    return _READY_FILE.exists()


async def local_tts(text: str, ref_audio_path: str, output_path: str,
                    prompt_text: str = "", emo_ref_path: str = "") -> tuple:
    """Normal dub — runs in executor, event loop stays free.
    Returns (output_path, elapsed_seconds)."""
    if not Path(ref_audio_path).exists():
        raise RuntimeError(f"参考音频不存在: {ref_audio_path}")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"[indextts] requesting: text='{text[:30]}...' ref='{Path(ref_audio_path).name}'")

    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _sync_tts,
        text, ref_audio_path, output_path, prompt_text, emo_ref_path)

    if data.get("status") != "ok":
        raise RuntimeError(f"IndexTTS失败: {data.get('message', 'unknown')}")

    elapsed = data.get("time", 0)
    print(f"[indextts] done: {elapsed:.1f}s -> {Path(output_path).name}")
    return output_path, elapsed


async def local_clone_tts(text: str, ref_audio_path: str, output_path: str,
                          prompt_text: str = "", emo_ref_path: str = "") -> tuple:
    """Clone dub — same worker, different params.
    Returns (output_path, elapsed_seconds)."""
    return await local_tts(text, ref_audio_path, output_path,
                           prompt_text, emo_ref_path)


def stop_server():
    """Kill the TTS worker process tree (including GPU-holding child)."""
    global _worker
    if _worker is not None:
        pid = _worker.pid
        # taskkill /T kills the entire tree — ensures GPU memory is released
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        except Exception:
            try:
                _worker.kill()
            except Exception:
                pass
        try:
            _worker.wait(timeout=5)
        except Exception:
            pass
        _worker = None
    _READY_FILE.unlink(missing_ok=True)
    print("[indextts] worker stopped, GPU memory released")
