"""FastAPI application entry point."""
import shutil
import json
import asyncio
import uuid
import warnings
from pathlib import Path
from datetime import datetime

# whisperx/pyannote warns about torchcodec — not needed, we use torchaudio
warnings.filterwarnings("ignore", category=UserWarning)

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from . import database, config, models
from .whisperx_worker import run_whisperx
from .model_cache import unload_processing_models
from .rh_client import run_dubbing, run_clone_dubbing, check_comfyui_available
from .indextts_client import local_tts, local_clone_tts, stop_server, is_worker_ready, _ensure_server

app = FastAPI(title="VoiceDub")

# Global semaphore for RH API concurrency control
_rh_semaphore = None

def _get_rh_semaphore():
    global _rh_semaphore
    if _rh_semaphore is None:
        settings = config.load_settings()
        concurrency = max(1, int(settings.get("rh_concurrency", 3)))
        _rh_semaphore = asyncio.Semaphore(concurrency)
    return _rh_semaphore

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
PROJECT_ROOT = Path(__file__).parent.parent
NLTK_BUNDLED_DIR = PROJECT_ROOT / "python" / "nltk_data"
MODEL_DIR = PROJECT_ROOT / "model"


@app.on_event("startup")
def startup():
    database.init_db()
    config.ensure_directories()
    # Pre-load punctuation model in background (avoids blocking first insert)
    import threading
    def _warmup_punct():
        try:
            from .punctuation import _ensure_loaded
            _ensure_loaded()
            print("[voicedub] punctuation model ready")
        except Exception as e:
            print(f"[voicedub] punctuation warmup skipped: {e}")
    threading.Thread(target=_warmup_punct, daemon=True).start()


@app.on_event("shutdown")
def shutdown():
    try:
        stop_server()
    except Exception:
        pass


# === Settings ===

@app.get("/api/settings")
def get_settings():
    return config.load_settings()


@app.put("/api/settings")
def update_settings(data: dict):
    config.save_settings(data)
    return config.load_settings()


# === Voice Library ===

VOICES_DIR = MODEL_DIR / "voices"


def _ensure_voices_dir():
    VOICES_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/api/voices")
def list_voices():
    _ensure_voices_dir()
    voices = []
    for d in sorted(VOICES_DIR.iterdir(), key=lambda x: x.name):
        if d.is_dir():
            pf = d / "profile.json"
            if pf.exists():
                try:
                    info = json.loads(pf.read_text(encoding="utf-8"))
                    info["id"] = d.name
                    # Find reference audio
                    for f in d.iterdir():
                        if f.suffix.lower() in (".wav", ".mp3"):
                            info["audio_path"] = str(f)
                            break
                    voices.append(info)
                except Exception:
                    pass
    return voices


@app.post("/api/voices")
async def upload_voice(name: str = Form(""), file: UploadFile = File(...)):
    if not name:
        raise HTTPException(400, "音色名称不能为空")
    ext = Path(file.filename).suffix.lower() if file.filename else ".wav"
    if ext not in (".wav", ".mp3"):
        raise HTTPException(400, "不支持的音频格式")

    _ensure_voices_dir()
    voice_id = str(uuid.uuid4())[:8]
    voice_dir = VOICES_DIR / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)

    ref_path = voice_dir / f"reference{ext}"
    ref_path.write_bytes(await file.read())

    profile = {"name": name, "created_at": datetime.now().isoformat()}
    (voice_dir / "profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

    profile["id"] = voice_id
    profile["audio_path"] = str(ref_path)
    return profile


@app.delete("/api/voices/{voice_id}")
def delete_voice(voice_id: str):
    voice_dir = VOICES_DIR / voice_id
    if not voice_dir.exists():
        raise HTTPException(404, "音色不存在")
    import shutil
    shutil.rmtree(voice_dir)
    return {"ok": True}


@app.get("/api/voices/{voice_id}/audio")
def get_voice_audio(voice_id: str):
    voice_dir = VOICES_DIR / voice_id
    if not voice_dir.exists():
        raise HTTPException(404, "音色不存在")
    for f in voice_dir.iterdir():
        if f.suffix.lower() in (".wav", ".mp3"):
            return FileResponse(str(f), media_type="audio/wav",
                                headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "音色音频文件不存在")


# === Projects ===

@app.get("/api/projects")
def list_projects():
    return database.get_projects()


@app.post("/api/projects", response_model=models.ProjectResponse)
def create_project(body: models.ProjectCreate):
    return database.create_project(body.name)


@app.get("/api/projects/{project_id}", response_model=models.ProjectDetailResponse)
def get_project_detail(project_id: str):
    proj = database.get_project(project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")
    segments = database.get_segments(project_id)
    proj["segments"] = segments
    return proj


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    proj = database.get_project(project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")
    project_dir = config.get_project_dir(project_id)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    database.delete_project(project_id)
    return {"ok": True}


# === Upload & Processing ===

@app.post("/api/projects/{project_id}/upload")
async def upload_audio(project_id: str, file: UploadFile = File(...)):
    proj = database.get_project(project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")

    ext = Path(file.filename).suffix.lower() if file.filename else ".wav"
    if ext not in (".wav", ".mp3", ".m4a", ".aac"):
        raise HTTPException(400, f"不支持的音频格式: {ext}")

    project_dir = config.get_project_dir(project_id)
    original_path = project_dir / f"original{ext}"
    content = await file.read()
    original_path.write_bytes(content)

    database.update_project(project_id, audio_path=str(original_path), status="processing")
    return {"status": "uploaded", "project_id": project_id}


def _emit(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/projects/{project_id}/process")
async def process_audio(project_id: str, num_speakers: int = 0):
    proj = database.get_project(project_id)
    if not proj or not proj["audio_path"]:
        raise HTTPException(404, "项目不存在或未上传音频")

    settings = config.load_settings()
    hf_token = settings.get("hf_token", "")
    model_name = settings.get("whisperx_model", "large-v3")
    audio_path = proj["audio_path"]

    async def stream():
        yield ":ok\n\n"

        venv_python = str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe")
        cli_script = str(Path(__file__).parent / "whisperx_cli.py")
        cmd = [
            venv_python, cli_script,
            "--audio", str(audio_path),
            "--project-id", project_id,
            "--hf-token", hf_token,
            "--model", model_name,
        ]
        if num_speakers > 0:
            cmd += ["--num-speakers", str(num_speakers)]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
        )
        # Drain stderr in background to prevent pipe blocking
        stderr_chunks = []
        async def _drain_stderr():
            async for chunk in proc.stderr:
                stderr_chunks.append(chunk)
        _stderr_task = asyncio.ensure_future(_drain_stderr())

        segments_result = []

        async for line in proc.stdout:
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            if msg.get("done"):
                segments_result = msg.get("segments", [])
                break
            elif msg.get("step"):
                yield _emit("step", msg)
            else:
                yield _emit("tick", {"detail": str(msg)})

        await proc.wait()
        _stderr_task.cancel()
        # Subprocess exited — GPU memory automatically freed

        if segments_result:
            database.clear_segments(project_id)
            for seg in segments_result:
                database.create_segment(
                    project_id=project_id, speaker=seg["speaker"],
                    start_time=seg["start_time"], end_time=seg["end_time"],
                    original_text=seg["text"],
                )
                seg_records = database.get_segments(project_id)
                matching = [s for s in seg_records
                            if abs(s["start_time"] - seg["start_time"]) < 0.01
                            and s["speaker"] == seg["speaker"]]
                if matching:
                    database.update_segment(matching[-1]["id"], seg_audio_path=seg["seg_audio_path"])
            database.update_project(project_id, status="done")
            yield _emit("done", {"segments": len(segments_result),
                                 "speakers": len(set(s["speaker"] for s in segments_result))})
        else:
            _stderr_task.cancel()
            err = b"".join(stderr_chunks).decode("utf-8", errors="replace")[:500] if stderr_chunks else "未知错误"
            database.update_project(project_id, status="error")
            yield _emit("fail", {"message": err})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.get("/api/projects/{project_id}/segments")
def list_segments(project_id: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(content=database.get_segments(project_id),
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# === Segment Update & Dubbing ===

@app.put("/api/segments/{segment_id}")
def update_segment_text(segment_id: str, body: models.SegmentUpdate):
    seg = database.get_segment(segment_id)
    if not seg:
        raise HTTPException(404, "片段不存在")
    updates = {}
    if body.edited_text is not None:
        updates["edited_text"] = body.edited_text
    if hasattr(body, 'emotion') and body.emotion is not None:
        updates["emotion"] = body.emotion
    database.update_segment(segment_id, **updates)
    return database.get_segment(segment_id)


async def _do_dub(segment_id: str):
    """Background task: run RH dubbing with global concurrency control."""
    seg = database.get_segment(segment_id)
    if not seg or not seg["seg_audio_path"]:
        database.update_segment(segment_id, dub_status="error")
        return
    settings = config.load_settings()
    api_url = settings.get("rh_api_url", "")
    api_key = settings.get("rh_api_key", "")
    workflow_id = settings.get("rh_workflow_id", "")
    project_segments = database.get_segments(seg["project_id"])
    seg_index = next((i for i, s in enumerate(project_segments) if s["id"] == segment_id), 0)

    sem = _get_rh_semaphore()
    try:
        async with sem:
            dubbed_path = await run_dubbing(
                reference_audio_path=seg["seg_audio_path"],
                text=seg["edited_text"] or seg["original_text"] or "",
                project_id=seg["project_id"],
                segment_id=segment_id,
                segment_index=seg_index,
                api_url=api_url,
                api_key=api_key,
                workflow_id=workflow_id,
                emotion=seg.get("emotion", ""),
                timeout=600,
            )
        database.update_segment(segment_id, dubbed_audio_path=dubbed_path, dub_status="done")
        print(f"[voicedub] dub done: {segment_id}")
    except Exception as e:
        database.update_segment(segment_id, dub_status="error")
        print(f"[voicedub] dub error: {segment_id}: {e}")


_local_tts_sem = asyncio.Semaphore(1)  # Single GPU — queue tasks, one at a time

async def _do_local_dub(segment_id: str):
    """Background task: run IndexTTS2 locally."""
    seg = database.get_segment(segment_id)
    if not seg or not seg["seg_audio_path"]:
        database.update_segment(segment_id, dub_status="error")
        return
    async with _local_tts_sem:
        try:
            project_dir = config.get_project_dir(seg["project_id"])
            out_path = project_dir / f"seg_{segment_id[:8]}_dub.wav"
            text = seg["edited_text"] or seg["original_text"] or ""
            _, elapsed = await local_tts(
                text,
                seg["seg_audio_path"],
                str(out_path),
                seg["original_text"] or "",
                seg["seg_audio_path"],
            )
            database.update_segment(segment_id, dubbed_audio_path=str(out_path),
                                    dub_status="done", dub_time=elapsed)
            print(f"[voicedub] local dub done: {segment_id}")
        except Exception as e:
            database.update_segment(segment_id, dub_status="error")
            print(f"[voicedub] local dub error: {segment_id}: {e}")



async def _do_local_clone_dub(segment_id: str, voice_audio: str):
    """Background task: run IndexTTS2 locally with voice library audio."""
    seg = database.get_segment(segment_id)
    if not seg or not seg["seg_audio_path"]:
        database.update_segment(segment_id, dub_status="error")
        return
    async with _local_tts_sem:
        try:
            project_dir = config.get_project_dir(seg["project_id"])
            out_path = project_dir / f"seg_{segment_id[:8]}_clone.wav"
            text = seg["edited_text"] or seg["original_text"] or ""
            _, elapsed = await local_clone_tts(
                text,
                voice_audio,
                str(out_path),
                seg["original_text"] or "",
                seg["seg_audio_path"],
            )
            database.update_segment(segment_id, dubbed_audio_path=str(out_path),
                                    dub_status="done", dub_time=elapsed)
            print(f"[voicedub] local clone dub done: {segment_id}")
        except Exception as e:
            database.update_segment(segment_id, dub_status="error")
            print(f"[voicedub] local clone dub error: {segment_id}: {e}")


async def _do_clone_dub(segment_id: str, voice_audio: str):
    """Background task: run RH voice-clone dubbing."""
    print(f"[voicedub] _do_clone_dub start: {segment_id}, voice={voice_audio}")
    seg = database.get_segment(segment_id)
    if not seg:
        print(f"[voicedub] clone: segment {segment_id} not found")
        database.update_segment(segment_id, dub_status="error")
        return
    if not seg["seg_audio_path"]:
        print(f"[voicedub] clone: segment {segment_id} no seg_audio_path")
        database.update_segment(segment_id, dub_status="error")
        return
    settings = config.load_settings()
    api_url = settings.get("rh_api_url", "")
    api_key = settings.get("rh_api_key", "")
    clone_workflow_id = settings.get("rh_clone_workflow_id", "")
    print(f"[voicedub] clone: api_key={'***' if api_key else 'EMPTY'}, wf={clone_workflow_id}")

    sem = _get_rh_semaphore()
    print(f"[voicedub] clone: acquiring semaphore for {segment_id}...")
    try:
        async with sem:
            print(f"[voicedub] clone: semaphore acquired, calling run_clone_dubbing...")
            dubbed_path = await run_clone_dubbing(
                voice_audio_path=voice_audio,
                segment_audio_path=seg["seg_audio_path"],
                text=seg["edited_text"] or seg["original_text"] or "",
                project_id=seg["project_id"],
                segment_id=segment_id,
                api_url=api_url,
                api_key=api_key,
                clone_workflow_id=clone_workflow_id,
            )
        database.update_segment(segment_id, dubbed_audio_path=dubbed_path, dub_status="done")
        print(f"[voicedub] clone dub done: {segment_id} -> {dubbed_path}")
    except Exception as e:
        import traceback
        print(f"[voicedub] clone dub error: {segment_id}: {e}")
        traceback.print_exc()
        database.update_segment(segment_id, dub_status="error")


@app.get("/api/segments/{segment_id}")
def get_single_segment(segment_id: str):
    seg = database.get_segment(segment_id)
    if not seg:
        raise HTTPException(404, "片段不存在")
    return seg


@app.post("/api/segments/{segment_id}/dub")
async def dub_segment(segment_id: str, background_tasks: BackgroundTasks):
    seg = database.get_segment(segment_id)
    if not seg:
        raise HTTPException(404, "片段不存在")
    if not seg["seg_audio_path"]:
        raise HTTPException(400, "片段音频尚未生成")
    if seg["dub_status"] == "processing":
        raise HTTPException(400, "片段正在配音中")

    database.update_segment(segment_id, dub_status="processing")

    settings = config.load_settings()
    if settings.get("use_local_tts", False):
        if not is_worker_ready():
            raise HTTPException(400, '本地模型未启动，请先在系统设置中启动本地模型')
        background_tasks.add_task(_do_local_dub, segment_id)
    else:
        background_tasks.add_task(_do_dub, segment_id)
    return {"status": "queued", "segment_id": segment_id}


@app.post("/api/segments/{segment_id}/clone-dub")
async def clone_dub_segment(segment_id: str, body: dict, background_tasks: BackgroundTasks):
    seg = database.get_segment(segment_id)
    if not seg:
        raise HTTPException(404, "片段不存在")
    if not seg["seg_audio_path"]:
        raise HTTPException(400, "片段音频尚未生成")
    if seg["dub_status"] == "processing":
        raise HTTPException(400, "片段正在配音中")

    voice_audio = body.get("voice_audio", "")
    if not voice_audio:
        raise HTTPException(400, "请选择音色")
    # Normalize path (frontend sends forward slashes to avoid JSON escaping issues)
    voice_audio = voice_audio.replace("/", "\\")
    if not Path(voice_audio).exists():
        raise HTTPException(400, f"音色参考音频不存在")

    database.update_segment(segment_id, dub_status="processing")

    settings = config.load_settings()
    if settings.get("use_local_tts", False):
        if not is_worker_ready():
            raise HTTPException(400, '本地模型未启动，请先在系统设置中启动本地模型')
        background_tasks.add_task(_do_local_clone_dub, segment_id, voice_audio)
    else:
        background_tasks.add_task(_do_clone_dub, segment_id, voice_audio)
    return {"status": "queued", "segment_id": segment_id}


@app.get("/api/segments/batch-dub")
async def batch_dub_segments(segment_ids: str = "", concurrency: int = 3):
    seg_id_list = [s for s in segment_ids.split(",") if s]
    concurrency = max(1, min(20, concurrency))
    settings = config.load_settings()
    api_key = settings.get("rh_api_key", "")
    workflow_id = settings.get("rh_workflow_id", "")

    sem = asyncio.Semaphore(concurrency)

    async def dub_one(seg_id: str):
        async with sem:
            seg = database.get_segment(seg_id)
            if not seg or not seg["seg_audio_path"]:
                return {"segment_id": seg_id, "status": "error", "message": "片段音频不存在"}

            project_segments = database.get_segments(seg["project_id"])
            seg_index = next((i for i, s in enumerate(project_segments) if s["id"] == seg_id), 0)

            database.update_segment(seg_id, dub_status="processing")

            rh_sem = _get_rh_semaphore()
            try:
                async with rh_sem:
                    dubbed_path = await run_dubbing(
                        reference_audio_path=seg["seg_audio_path"],
                        text=seg["edited_text"],
                        project_id=seg["project_id"],
                        segment_id=seg_id,
                        segment_index=seg_index,
                        api_key=api_key,
                        workflow_id=workflow_id,
                        emotion=seg.get("emotion", ""),
                        timeout=600,
                    )
                database.update_segment(seg_id, dubbed_audio_path=dubbed_path, dub_status="done")
                return {"segment_id": seg_id, "status": "done"}
            except Exception as e:
                database.update_segment(seg_id, dub_status="error")
                return {"segment_id": seg_id, "status": "error", "message": str(e)}

    async def stream():
        yield ":ok\n\n"

        if not seg_id_list:
            yield _emit("error", {"message": "请选择要配音的片段"})
            return

        tasks = [dub_one(sid) for sid in seg_id_list]
        done_count = 0
        total = len(seg_id_list)

        for coro in asyncio.as_completed(tasks):
            result = await coro
            done_count += 1
            yield _emit("progress", {"segment_id": result["segment_id"],
                                      "status": result["status"],
                                      "message": result.get("message", ""),
                                      "done": done_count, "total": total})

        yield _emit("done", {"total": total, "done": done_count})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


async def _delayed_clone_dub(seg_id: str, voice_audio: str, delay: float):
    """Clone dub with a staggered start to avoid file access overlap."""
    if delay > 0:
        await asyncio.sleep(delay)
    await _do_clone_dub(seg_id, voice_audio)


@app.get("/api/segments/batch-clone-dub")
async def batch_clone_dub_sse(project_id: str = "", segment_ids: str = "", voice_audio: str = ""):
    seg_id_list = [s for s in segment_ids.split(",") if s]
    voice_audio = voice_audio.replace("/", "\\")
    if not seg_id_list:
        raise HTTPException(400, "请选择要配音的片段")
    if not voice_audio or not Path(voice_audio).exists():
        raise HTTPException(400, "音色参考音频不存在")

    settings = config.load_settings()
    use_local = settings.get("use_local_tts", False)

    sem = asyncio.Semaphore(1)  # clone dub one at a time to avoid GPU contention

    async def clone_one(seg_id: str):
        async with sem:
            seg = database.get_segment(seg_id)
            if not seg or not seg["seg_audio_path"]:
                return {"segment_id": seg_id, "status": "error", "message": "片段音频不存在"}

            database.update_segment(seg_id, dub_status="processing")

            try:
                if use_local:
                    await _do_local_clone_dub(seg_id, voice_audio)
                else:
                    await _do_clone_dub(seg_id, voice_audio)
                database.update_segment(seg_id, dub_status="done")
                return {"segment_id": seg_id, "status": "done"}
            except Exception as e:
                database.update_segment(seg_id, dub_status="error")
                return {"segment_id": seg_id, "status": "error", "message": str(e)}

    async def stream():
        yield ":ok\n\n"
        done_count = 0
        total = len(seg_id_list)

        for coro in asyncio.as_completed([clone_one(sid) for sid in seg_id_list]):
            result = await coro
            done_count += 1
            yield _emit("progress", {"segment_id": result["segment_id"],
                                      "status": result["status"],
                                      "message": result.get("message", ""),
                                      "done": done_count, "total": total})

        yield _emit("done", {"total": total, "done": done_count})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# === Word Cache Helper ===

def _get_text_for_range(project_id: str, start: float, end: float) -> str:
    """Extract transcript text for a time range from the cached word timestamps."""
    cache_path = config.get_project_dir(project_id) / "words_cache.json"
    if not cache_path.exists():
        return ""
    try:
        words = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    text_parts = []
    for w in words:
        w_mid = (w["start"] + w["end"]) / 2
        if start <= w_mid <= end:
            text_parts.append(w["word"])
    raw = "".join(text_parts)
    if raw:
        from .punctuation import restore_punctuation
        return restore_punctuation(raw)
    return ""


@app.delete("/api/segments/{segment_id}")
def delete_single_segment(segment_id: str):
    seg = database.get_segment(segment_id)
    if not seg:
        raise HTTPException(404, "片段不存在")
    database.delete_segment(segment_id)
    return {"ok": True}


# === Segment Insert ===

@app.post("/api/segments/insert")
def insert_segment(body: dict):
    project_id = body.get("project_id", "")
    start_time = float(body.get("start_time", 0))
    end_time = float(body.get("end_time", 0))
    speaker = body.get("speaker", "")

    if not project_id:
        raise HTTPException(400, "缺少项目 ID")
    if end_time - start_time < 0.1:
        raise HTTPException(400, "时间区间太短（需 >= 0.1秒）")

    proj = database.get_project(project_id)
    if not proj or not proj["audio_path"]:
        raise HTTPException(400, "原始音频不存在")

    from . import audio_utils
    project_dir = config.get_project_dir(project_id)

    if not speaker:
        speaker = "A"

    existing = database.get_segments(project_id)
    seg_idx = len(existing)

    seg_path = project_dir / f"seg_{seg_idx:03d}.wav"
    audio_utils.trim_wav(Path(proj["audio_path"]), start_time, end_time, seg_path)

    # Get real transcript from word cache
    text = _get_text_for_range(project_id, start_time, end_time)
    if not text:
        text = "[插入片段]"

    seg = database.create_segment(project_id, speaker, start_time, end_time, text)
    database.update_segment(seg["id"], seg_audio_path=str(seg_path), edited_text=text)

    return database.get_segment(seg["id"])


# === Segment Merge / Split / Trim ===

@app.post("/api/segments/merge")
def merge_segments(body: dict):
    seg_ids = body.get("segment_ids", [])
    if len(seg_ids) != 2:
        raise HTTPException(400, "需要两个片段 ID")
    a = database.get_segment(seg_ids[0])
    b = database.get_segment(seg_ids[1])
    if not a or not b:
        raise HTTPException(404, "片段不存在")
    if a["project_id"] != b["project_id"]:
        raise HTTPException(400, "只能合并同一项目的片段")

    project_dir = config.get_project_dir(a["project_id"])
    from . import audio_utils

    # Merge: extract from original audio A.start → B.end (includes gap/silence)
    merged_path = project_dir / f"merged_{a['id'][:8]}_{b['id'][:8]}.wav"
    proj = database.get_project(a["project_id"])
    if proj and proj.get("audio_path"):
        audio_utils.trim_wav(Path(proj["audio_path"]), a["start_time"], b["end_time"], merged_path)
    else:
        # Fallback: merge segment files directly
        audio_paths = [Path(p) for p in [a["seg_audio_path"], b["seg_audio_path"]] if p]
        if len(audio_paths) == 2:
            audio_utils.merge_wavs(audio_paths, merged_path)
        elif len(audio_paths) == 1:
            import shutil
            shutil.copy(audio_paths[0], merged_path)
        else:
            merged_path = None

    # Merge text
    merged_original = (a["original_text"] or "") + (b["original_text"] or "")
    merged_edited = (a["edited_text"] or a["original_text"] or "") + (b["edited_text"] or b["original_text"] or "")

    # Determine time range
    start_t = min(a["start_time"], b["start_time"])
    end_t = max(a["end_time"], b["end_time"])

    # Delete old segments, create new merged one
    database.delete_segment(a["id"])
    database.delete_segment(b["id"])
    new_seg = database.create_segment(a["project_id"], a["speaker"], start_t, end_t, merged_original)
    database.update_segment(new_seg["id"], edited_text=merged_edited,
                            seg_audio_path=str(merged_path) if merged_path else None,
                            emotion=a.get("emotion", ""))
    return database.get_segment(new_seg["id"])


@app.post("/api/segments/{segment_id}/split")
def split_segment(segment_id: str, body: dict):
    seg = database.get_segment(segment_id)
    if not seg:
        raise HTTPException(404, "片段不存在")
    split_at = float(body.get("split_at", 0))
    duration = seg["end_time"] - seg["start_time"]
    if split_at <= 0 or split_at >= duration:
        raise HTTPException(400, f"切割点需在 0 到 {duration:.1f}s 之间")

    project_dir = config.get_project_dir(seg["project_id"])
    from . import audio_utils

    seg_path = Path(seg["seg_audio_path"])
    out_a = project_dir / f"split_{seg['id'][:8]}_a.wav"
    out_b = project_dir / f"split_{seg['id'][:8]}_b.wav"
    audio_utils.split_wav(seg_path, split_at, out_a, out_b)

    # Split text at nearest natural break (punctuation), not just proportional
    text = seg["original_text"] or ""
    ratio = split_at / duration if duration > 0 else 0.5
    raw_pos = max(1, int(len(text) * ratio))
    # Look for punctuation near the proportional split point (±25% window)
    puncts = "，。！？；、,.;!?\n"
    margin = max(2, len(text) // 4)
    search_start = max(1, raw_pos - margin)
    search_end = min(len(text) - 1, raw_pos + margin)
    best_pos = raw_pos
    best_dist = margin + 1
    for i in range(search_start, search_end):
        if text[i] in puncts:
            dist = abs(i - raw_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = i + 1  # split AFTER the punctuation
    text_a = text[:best_pos]
    text_b = text[best_pos:]

    # Split edited_text at the same natural break
    edited = seg["edited_text"] or text
    raw_pos_e = max(1, int(len(edited) * ratio))
    margin_e = max(2, len(edited) // 4)
    best_pos_e = raw_pos_e
    best_dist_e = margin_e + 1
    for i in range(max(1, raw_pos_e - margin_e), min(len(edited) - 1, raw_pos_e + margin_e)):
        if edited[i] in puncts:
            dist = abs(i - raw_pos_e)
            if dist < best_dist_e:
                best_dist_e = dist
                best_pos_e = i + 1
    edited_a = edited[:best_pos_e]
    edited_b = edited[best_pos_e:]

    # Delete original, create two new segments
    database.delete_segment(segment_id)
    time_a_start = seg["start_time"]
    time_a_end = seg["start_time"] + split_at
    time_b_start = time_a_end
    time_b_end = seg["end_time"]

    seg_a = database.create_segment(seg["project_id"], seg["speaker"], time_a_start, time_a_end, text_a)
    seg_b = database.create_segment(seg["project_id"], seg["speaker"], time_b_start, time_b_end, text_b)
    database.update_segment(seg_a["id"], seg_audio_path=str(out_a), edited_text=edited_a, emotion=seg.get("emotion", ""))
    database.update_segment(seg_b["id"], seg_audio_path=str(out_b), edited_text=edited_b, emotion=seg.get("emotion", ""))

    return [database.get_segment(seg_a["id"]), database.get_segment(seg_b["id"])]


@app.post("/api/segments/{segment_id}/trim")
def trim_segment(segment_id: str, body: dict):
    seg = database.get_segment(segment_id)
    if not seg:
        raise HTTPException(404, "片段不存在")
    new_start = float(body.get("start_time", seg["start_time"]))
    new_end = float(body.get("end_time", seg["end_time"]))

    proj = database.get_project(seg["project_id"])
    original_audio = proj["audio_path"] if proj else None
    if not original_audio or not Path(original_audio).exists():
        raise HTTPException(400, "原始音频文件不存在")

    from . import audio_utils
    project_dir = config.get_project_dir(seg["project_id"])
    new_path = project_dir / f"trim_{seg['id'][:8]}.wav"
    audio_utils.trim_wav(Path(original_audio), new_start, new_end, new_path)

    # Use word cache for precise text trimming
    new_text = _get_text_for_range(seg["project_id"], new_start, new_end)
    if not new_text:
        new_text = seg["original_text"] or seg["edited_text"] or ""

    database.update_segment(segment_id, start_time=new_start, end_time=new_end,
                            seg_audio_path=str(new_path),
                            original_text=new_text, edited_text=new_text)
    return database.get_segment(segment_id)


@app.get("/api/segments/{segment_id}/waveform")
def get_segment_waveform(segment_id: str, context_before: float = 0, context_after: float = 0):
    seg = database.get_segment(segment_id)
    if not seg:
        raise HTTPException(404, "片段不存在")
    seg_path = Path(seg["seg_audio_path"])
    if not seg_path.exists():
        raise HTTPException(404, "音频文件不存在")

    from . import audio_utils
    result = {
        "segment_peaks": audio_utils.get_waveform_peaks(seg_path),
        "duration": audio_utils.get_audio_duration(seg_path),
        "sample_rate": 44100,
    }

    if context_before > 0 or context_after > 0:
        proj = database.get_project(seg["project_id"])
        original_audio = proj["audio_path"] if proj else None
        if original_audio and Path(original_audio).exists():
            project_dir = config.get_project_dir(seg["project_id"])
            ctx_path = project_dir / f"ctx_{seg['id'][:8]}.wav"
            audio_utils.get_context_audio(
                Path(original_audio), seg["start_time"], seg["end_time"],
                context_before, context_after, ctx_path)
            result["context_total_duration"] = audio_utils.get_audio_duration(ctx_path)
            result["context_start_time"] = max(0, seg["start_time"] - context_before)
            result["segment_start_in_context"] = min(context_before, seg["start_time"])
            result["segment_end_in_context"] = result["segment_start_in_context"] + (seg["end_time"] - seg["start_time"])
            result["context_peaks"] = audio_utils.get_waveform_peaks(ctx_path)
            # Clean up temp file
            try:
                ctx_path.unlink()
            except Exception:
                pass

    return result


@app.get("/api/projects/{project_id}/waveform")
def get_project_waveform(project_id: str, start: float = 0, end: float = 0):
    proj = database.get_project(project_id)
    if not proj or not proj["audio_path"]:
        raise HTTPException(400, "原始音频不存在")
    from . import audio_utils
    project_dir = config.get_project_dir(project_id)
    tmp_path = project_dir / f"wf_tmp_{start}_{end}.wav"
    dur = end - start if end > start else 60
    audio_utils.trim_wav(Path(proj["audio_path"]), start, start + dur, tmp_path)
    peaks = audio_utils.get_waveform_peaks(tmp_path)
    try:
        tmp_path.unlink()
    except Exception:
        pass
    return {"peaks": peaks, "start": start, "end": start + dur}


# === Audio Serving ===

@app.get("/api/audio/raw")
def get_raw_audio(path: str = "", project_id: str = ""):
    """Serve raw audio — by project_id (for insert preview) or by path."""
    if project_id:
        proj = database.get_project(project_id)
        if not proj or not proj.get("audio_path"):
            raise HTTPException(404, "项目原始音频不存在")
        resolved = Path(proj["audio_path"])
    elif path:
        resolved = Path(path).resolve()
        data_root = config.DATA_DIR.resolve()
        if not str(resolved).startswith(str(data_root)) or not resolved.exists():
            raise HTTPException(404, "音频文件不存在")
    else:
        raise HTTPException(400, "需要 project_id 或 path 参数")
    if not resolved.exists():
        raise HTTPException(404, "音频文件不存在")
    mt = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac"}
    ext = resolved.suffix.lower()
    return FileResponse(str(resolved), media_type=mt.get(ext, "audio/wav"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/audio/{segment_id}")
def get_segment_audio(segment_id: str):
    seg = database.get_segment(segment_id)
    if not seg or not seg["seg_audio_path"]:
        raise HTTPException(404, "音频不存在")
    return FileResponse(seg["seg_audio_path"], media_type="audio/wav",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/api/audio/{segment_id}/dub")
def get_dubbed_audio(segment_id: str):
    seg = database.get_segment(segment_id)
    if not seg or not seg["dubbed_audio_path"]:
        raise HTTPException(404, "配音音频不存在")
    return FileResponse(seg["dubbed_audio_path"], media_type="audio/wav",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.post("/api/segments/{segment_id}/reset-dub")
def reset_dub_status(segment_id: str):
    seg = database.get_segment(segment_id)
    if not seg:
        raise HTTPException(404, "片段不存在")
    database.update_segment(segment_id, dub_status="pending", dubbed_audio_path=None)
    return {"ok": True}


# === IndexTTS Server Control ===

@app.post("/api/indextts/start")
async def start_indextts_server():
    # GPU 检测：IndexTTS2 必须要有 NVIDIA GPU
    try:
        import torch
        if not torch.cuda.is_available():
            raise HTTPException(
                400,
                "本地配音需要 NVIDIA GPU，当前未检测到。请确认已安装 NVIDIA 驱动 + CUDA 12.x，显卡建议 RTX 30/40/50 系列（≥8GB 显存）。无 GPU 请使用「云端模式」。"
            )
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        print(f"[indextts] GPU: {gpu_name} ({gpu_mem:.1f} GB)")
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(
            400,
            "未安装 PyTorch，请先在模型管理面板下载 PyTorch CUDA 版本"
        )
    except Exception as e:
        raise HTTPException(500, f"GPU检测失败: {str(e)}")

    try:
        await _ensure_server()
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(500, f"IndexTTS启动失败: {str(e)}")


@app.post("/api/indextts/stop")
def stop_indextts_server():
    stop_server()
    return {"status": "stopped"}


@app.get("/api/indextts/status")
def indextts_status():
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"running": is_worker_ready()},
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# === Export ===

@app.post("/api/projects/{project_id}/export-audio")
def export_merged_audio(project_id: str, body: dict):
    proj = database.get_project(project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")
    segments = database.get_segments(project_id)
    if not segments:
        raise HTTPException(400, "没有可导出的片段")

    mode = body.get("mode", "sequential")
    if mode not in ("sequential", "stretch"):
        raise HTTPException(400, "mode 必须是 sequential 或 stretch")

    project_dir = config.get_project_dir(project_id)
    output_path = project_dir / f"{proj['name']}_export.wav"

    from . import audio_utils
    audio_utils.export_merged_audio(segments, output_path, mode)

    return {"path": str(output_path), "filename": output_path.name}


@app.get("/api/projects/{project_id}/export-audio/download")
def download_exported_audio(project_id: str, mode: str = "sequential"):
    proj = database.get_project(project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")
    project_dir = config.get_project_dir(project_id)
    filepath = project_dir / f"{proj['name']}_export.wav"
    if not filepath.exists():
        raise HTTPException(404, "请先生成导出音频")
    return FileResponse(str(filepath), media_type="audio/wav",
                        filename=filepath.name,
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/projects/{project_id}/export/subtitle")
def export_subtitle(project_id: str, format: str = "srt"):
    proj = database.get_project(project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")
    segments = database.get_segments(project_id)
    if not segments:
        raise HTTPException(400, "没有可导出的片段")

    if format == "srt":
        lines = []
        speakers = list(set(s.get("speaker", "") for s in segments))
        for i, seg in enumerate(segments, 1):
            text = seg.get("edited_text") or seg.get("original_text") or ""
            start = _format_srt_time(seg["start_time"])
            end = _format_srt_time(seg["end_time"])
            speaker = seg.get("speaker", "")
            lines.append(f"{i}\n{start} --> {end}\n{text}\n")
        content = "\n".join(lines)

    elif format == "ass":
        header = ("[Script Info]\nTitle: VoiceDub Export\nScriptType: v4.00+\n\n"
                  "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
                  "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY,"
                  "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR,"
                  "MarginV, Encoding\n"
                  "Style: Default,Microsoft YaHei,24,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
                  "0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1\n\n"
                  "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

        events = []
        for seg in segments:
            text = seg.get("edited_text") or seg.get("original_text") or ""
            start = _format_ass_time(seg["start_time"])
            end = _format_ass_time(seg["end_time"])
            speaker = seg.get("speaker", "")
            events.append(f"Dialogue: 0,{start},{end},Default,{speaker},0,0,0,,{text}")

        content = header + "\n".join(events)
    else:
        raise HTTPException(400, "format 必须是 srt 或 ass")

    return {"content": content, "format": format, "filename": f"{proj['name']}.{format}"}


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"


# === Task Log ===

@app.get("/api/projects/{project_id}/task-log")
def get_task_log(project_id: str, limit: int = 10, offset: int = 0):
    """Return segments with dub activity, ordered by most recent first."""
    conn = database.get_connection()
    rows = conn.execute(
        """SELECT id, speaker, start_time, end_time, edited_text, original_text,
           dub_status, dubbed_audio_path, emotion, updated_at
           FROM segments WHERE project_id = ? AND dub_status != 'pending'
           ORDER BY updated_at DESC LIMIT ? OFFSET ?""",
        (project_id, limit, offset)
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM segments WHERE project_id = ? AND dub_status != 'pending'",
        (project_id,)
    ).fetchone()[0]
    conn.close()
    return {"items": [dict(r) for r in rows], "total": total}


# === Status ===

@app.get("/api/model-warmup-status")
def model_warmup_status():
    """Return model preloading progress for the frontend warmup screen."""
    from . import model_cache
    return model_cache.get_warmup_status()


@app.get("/api/whisperx/status")
def whisperx_status():
    settings = config.load_settings()
    model_name = settings.get("whisperx_model", "large-v3")
    try:
        from huggingface_hub import try_to_load_from_cache
        cached = try_to_load_from_cache(
            repo_id=f"m-bain/whisperx-{model_name}",
            filename="model.bin",
        )
        return {"model_name": model_name, "is_downloaded": cached is not None,
                "is_processing": False}
    except Exception:
        return {"model_name": model_name, "is_downloaded": False,
                "is_processing": False}


HF_MIRROR = "https://hf-mirror.com"


@app.get("/api/models/status")
def models_status():
    import os
    os.environ.setdefault("HF_ENDPOINT", HF_MIRROR)

    # === PyTorch runtime status ===
    try:
        import torch
        has_cuda = torch.cuda.is_available()
        torch_ver = torch.__version__
        gpu_name = torch.cuda.get_device_name(0) if has_cuda else ""
    except Exception:
        has_cuda = False
        torch_ver = "unknown"
        gpu_name = ""

    if not gpu_name:
        try:
            import subprocess
            r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                gpu_name = r.stdout.strip()
        except Exception:
            pass

    # === NLTK punkt_tab status ===
    try:
        import nltk
        p = os.path.join(nltk.data.path[0], "tokenizers", "punkt_tab") if nltk.data.path else ""
        nltk_ok = bool(p) and os.path.isdir(p)
        if not nltk_ok and NLTK_BUNDLED_DIR.is_dir():
            nltk.data.path.insert(0, str(NLTK_BUNDLED_DIR))
            nltk_ok = os.path.isdir(os.path.join(str(NLTK_BUNDLED_DIR), "tokenizers", "punkt_tab"))
    except Exception:
        nltk_ok = False

    # === Speaker diarization model (local model/speaker/) ===
    speaker_dir = MODEL_DIR / "speaker"
    speaker_ok = speaker_dir.is_dir() and (speaker_dir / "config.yaml").exists()

    # === Whisper model (HF cache) ===
    try:
        from huggingface_hub import try_to_load_from_cache
        whisper_cached = try_to_load_from_cache(
            repo_id="Systran/faster-whisper-large-v3", filename="model.bin")
        whisper_ok = whisper_cached is not None
    except Exception:
        whisper_ok = False

    # FunASR punctuation model
    funasr_dir = MODEL_DIR / "punctuation_funasr"
    funasr_ok = funasr_dir.is_dir() and (funasr_dir / "model.pt").exists()

    return {
        "runtime": {
            "variant": "CUDA" if has_cuda else "CPU",
            "torch_version": torch_ver,
            "gpu_name": gpu_name,
            "cuda_available": has_cuda,
        },
        "installed": {
            "nltk_punkt": nltk_ok,
            "whisper": whisper_ok,
            "speaker": speaker_ok,
            "funasr_punkt": funasr_ok,
        },
        "downloadable": [
            {"id": "faster-whisper-large-v3", "name": "Whisper 转录模型 large-v3",
             "repo": "Systran/faster-whisper-large-v3", "size": "~3 GB",
             "desc": "语音转文字核心模型，国内源可下载",
             "installed": whisper_ok, "source": "hf-mirror.com"},
        ],
        "manual": [
            {"id": "speaker-diarization", "name": "说话人分离模型",
             "repo": "pyannote/speaker-diarization-community-1", "size": "~500 MB",
             "desc": "识别不同说话人声音，需 VPN 手动下载后放入 model/speaker/",
             "installed": speaker_ok, "source": "HuggingFace (gated)",
             "hf_url": "https://hf.co/pyannote/speaker-diarization-community-1"},
            {"id": "funasr-punctuation", "name": "FunASR 中文标点模型",
             "repo": "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
             "size": "~283 MB", "desc": "中文专用标点恢复，准确率高，国内可下载。放入 model/punctuation_funasr/",
             "installed": funasr_ok, "source": "ModelScope (国内直连)",
             "modelscope_url": "https://modelscope.cn/models/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"},
        ],
    }


@app.post("/api/models/download/{model_id}")
async def download_model(model_id: str):
    if model_id == "torch-cuda":
        return _switch_torch_cuda()

    if model_id == "nltk-punkt":
        return _download_nltk_punkt()

    if model_id == "faster-whisper-large-v3":
        import os
        os.environ["HF_ENDPOINT"] = HF_MIRROR
        old_offline = os.environ.pop("HF_HUB_OFFLINE", None)
        old_toff = os.environ.pop("TRANSFORMERS_OFFLINE", None)
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id="Systran/faster-whisper-large-v3")
            return {"status": "done", "model_id": model_id}
        except Exception as e:
            raise HTTPException(500, f"下载失败: {str(e)}")
        finally:
            if old_offline is not None: os.environ["HF_HUB_OFFLINE"] = old_offline
            if old_toff is not None: os.environ["TRANSFORMERS_OFFLINE"] = old_toff

    if model_id == "speaker-diarization":
        settings = config.load_settings()
        hf_token = settings.get("hf_token", "")
        if not hf_token:
            raise HTTPException(400, "请先在模型管理页面填写 HuggingFace Token")
        import os
        os.environ["HF_TOKEN"] = hf_token
        os.environ["HF_ENDPOINT"] = HF_MIRROR
        old_offline = os.environ.pop("HF_HUB_OFFLINE", None)
        old_toff = os.environ.pop("TRANSFORMERS_OFFLINE", None)
        try:
            from huggingface_hub import snapshot_download
            repo = "pyannote/speaker-diarization-3.1"
            snapshot_download(repo_id=repo, token=hf_token)
            # Also download segmentation model
            snapshot_download(repo_id="pyannote/segmentation-3.0", token=hf_token)
            return {"status": "done", "model_id": model_id}
        except Exception as e:
            msg = str(e)
            if "403" in msg or "gated" in msg.lower():
                raise HTTPException(403, "访问被拒。请确认已在 HF 网页上同意该模型的使用条款")
            raise HTTPException(500, f"下载失败: {msg}")
        finally:
            if old_offline is not None: os.environ["HF_HUB_OFFLINE"] = old_offline
            if old_toff is not None: os.environ["TRANSFORMERS_OFFLINE"] = old_toff

    if model_id == "funasr-punctuation":
        target_dir = MODEL_DIR / "punctuation_funasr"
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            from modelscope import snapshot_download
            snapshot_download("iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
                            cache_dir=str(target_dir.parent))
            return {"status": "done", "model_id": model_id}
        except ImportError:
            # Fallback: try huggingface with offline disabled
            import os
            old_offline = os.environ.pop("HF_HUB_OFFLINE", None)
            try:
                from huggingface_hub import snapshot_download
                snapshot_download(repo_id="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
                                local_dir=str(target_dir))
                return {"status": "done", "model_id": model_id}
            except Exception as e:
                raise HTTPException(500, f"下载失败: {str(e)}")
            finally:
                if old_offline is not None: os.environ["HF_HUB_OFFLINE"] = old_offline

    raise HTTPException(404, f"未知模型: {model_id}")


def _switch_torch_cuda():
    import subprocess, sys, importlib
    try:
        import torch
        if torch.cuda.is_available():
            return {"status": "done", "model_id": "torch-cuda", "message": "已是 CUDA 版本"}
    except Exception:
        pass

    # 优先使用本地 wheel 文件
    local_wheel = MODEL_DIR / "torch-2.8.0+cu128-cp311-cp311-win_amd64.whl"
    if local_wheel.exists():
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", str(local_wheel),
            "--force-reinstall", "--no-deps",
        ])
        return {"status": "done", "model_id": "torch-cuda", "message": "CUDA 版本安装完成（本地）"}

    # NJU 镜像作为后备
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "torch==2.8.0+cu128",
            "--index-url", "https://mirrors.nju.edu.cn/pytorch/whl/cu128",
            "--no-deps", "--force-reinstall",
        ])
        return {"status": "done", "model_id": "torch-cuda", "message": "CUDA 版本安装完成（镜像）"}
    except Exception as e:
        raise HTTPException(500, f"安装 CUDA 版本失败: {str(e)}")


def _download_nltk_punkt():
    import nltk, os as _os
    target = _os.path.join(nltk.data.path[0], "tokenizers")
    _os.makedirs(target, exist_ok=True)

    # 优先从本地捆绑包复制
    src = NLTK_BUNDLED_DIR / "tokenizers" / "punkt_tab"
    if src.is_dir():
        dst = _os.path.join(target, "punkt_tab")
        if _os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(str(src), dst)
        return {"status": "done", "model_id": "nltk-punkt", "source": "local"}

    # 网络下载作为后备
    import zipfile, io, urllib.request, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    urls = [
        "https://ghproxy.com/https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/tokenizers/punkt_tab.zip",
        "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/tokenizers/punkt_tab.zip",
    ]

    last_err = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "VoiceDub"})
            resp = urllib.request.urlopen(req, context=ctx, timeout=30)
            data = resp.read()
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(target)
            return {"status": "done", "model_id": "nltk-punkt", "source": "download"}
        except Exception as e:
            last_err = e
            continue
    raise HTTPException(500, f"NLTK 数据下载失败: {last_err}")


VERSION_FILE = PROJECT_ROOT / "VERSION"

@app.get("/api/version")
def get_version():
    try:
        return {"version": VERSION_FILE.read_text(encoding="utf-8").strip()}
    except Exception:
        return {"version": "dev"}


@app.get("/api/health")
def health_check():
    settings = config.load_settings()
    rh_ok = check_comfyui_available("")
    return {"status": "ok", "runninghub_reachable": rh_ok}


# === Static Files & SPA ===

if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")


@app.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_spa(full_path: str = ""):
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>VoiceDub</h1><p>Frontend not found.</p>")
