"""Singleton model cache — load once, reuse across all requests."""
import os
from pathlib import Path
import whisperx

PROJECT_ROOT = Path(__file__).parent.parent
MODEL_DIR = PROJECT_ROOT / "model"

# All models stored locally under model/huggingface/
os.environ.setdefault("HF_HUB_CACHE", str(MODEL_DIR / "huggingface"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_cache = {}


def get_device():
    try:
        import torch
        return ("cuda", "float16") if torch.cuda.is_available() else ("cpu", "int8")
    except ImportError:
        return ("cpu", "int8")


def get_transcribe_model(model_name: str = "large-v3", **kwargs):
    if "transcribe" not in _cache:
        device, compute_type = get_device()
        _cache["transcribe"] = whisperx.load_model(model_name, device, compute_type=compute_type, **kwargs)
    return _cache["transcribe"]


def get_align_model(language: str):
    key = f"align_{language}"
    if key not in _cache:
        device, _ = get_device()
        _cache[key] = whisperx.load_align_model(language_code=language, device=device)
    return _cache[key]


def get_diarize_model(hf_token: str = ""):
    if "diarize" not in _cache:
        device, _ = get_device()
        from whisperx.diarize import DiarizationPipeline
        speaker_dir = MODEL_DIR / "speaker"
        if speaker_dir.is_dir() and (speaker_dir / "config.yaml").exists():
            _cache["diarize"] = DiarizationPipeline(
                model_name=str(speaker_dir), token=hf_token, device=device)
        else:
            raise FileNotFoundError(
                f"说话人分离模型未找到。请从 https://hf.co/pyannote/speaker-diarization-community-1 "
                f"下载所有文件到 {speaker_dir}/")
    return _cache["diarize"]


def unload_processing_models():
    """Free GPU memory used by ASR/diarization models — call before loading TTS."""
    import gc
    keys = ["transcribe", "align", "align_en", "diarize"]
    cleared = False
    for k in list(_cache.keys()):
        if k in keys or k.startswith("align_"):
            val = _cache.pop(k, None)
            if val is not None:
                # Try various ways to move model off GPU
                for attr in ('model', 'pipeline', '_model'):
                    obj = getattr(val, attr, None)
                    if obj is not None and hasattr(obj, 'cpu'):
                        try: obj.cpu()
                        except: pass
                if hasattr(val, 'to'):
                    try: val.to('cpu')
                    except: pass
                if hasattr(val, 'cpu'):
                    try: val.cpu()
                    except: pass
                del val
                cleared = True

    if cleared:
        # Multiple rounds of GC to ensure all references are freed
        for _ in range(3):
            gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass
