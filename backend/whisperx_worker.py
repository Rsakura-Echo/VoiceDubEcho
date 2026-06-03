"""WhisperX pipeline — diarization-segment-based splitting. V3"""
import subprocess
import whisperx
from .config import get_project_dir
from .model_cache import get_transcribe_model, get_align_model, get_diarize_model, get_device
from .punctuation import restore_punctuation


def _clean_punctuation(text: str) -> str:
    """Remove leading punctuation and fix consecutive punctuation marks."""
    import re

    # 1. Strip leading punctuation
    cleaned = re.sub(r'^[\s,，。！？：、；""''.．!?;:\"\'\-–—…]+', '', text)

    # 2. Fix consecutive punctuation (with or without space between)
    PRIORITY = {'？': 5, '?': 5, '！': 4, '!': 4, '，': 3, ',': 3, '。': 2, '.': 2, '：': 1, ':': 1, '；': 0, ';': 0}
    def _pick_best(match):
        chars = match.group(0).replace(' ', '')
        if not chars: return ''
        best = max(chars, key=lambda c: PRIORITY.get(c, -1))
        if best in ('。', '.') and len(chars) >= 3:
            return best * 3
        return best
    # Adjacent punctuation
    cleaned = re.sub(r'[，。！？：、；,\.\!\?\:\;]{2,}', _pick_best, cleaned)
    # Punctuation separated by whitespace: "。 ," → ","
    cleaned = re.sub(r'[，。！？：、；,\.\!\?\:\;]\s+[，。！？：、；,\.\!\?\:\;]', _pick_best, cleaned)

    # 3. Fix English+Chinese punctuation pair (e.g. "? ?" → "？")
    cleaned = re.sub(r'？\s*\?', '？', cleaned)
    cleaned = re.sub(r'\?\s*？', '？', cleaned)
    cleaned = re.sub(r'!\s*！', '！', cleaned)
    cleaned = re.sub(r'！\s*!', '！', cleaned)

    return cleaned


def run_whisperx(audio_path: str, project_id: str, hf_token: str,
                 model_name: str = "large-v3",
                 num_speakers: int = None,
                 on_step=None) -> list[dict]:
    device, _ = get_device()

    def step(name, detail=""):
        if on_step:
            on_step(name, detail)

    step("load_model", "获取模型...")
    model = get_transcribe_model(model_name, vad_options={})

    step("load_audio", "读取音频...")
    audio = whisperx.load_audio(audio_path)

    step("transcribe", "语音转文字...")
    result = model.transcribe(audio, batch_size=16)
    language = result["language"]

    step("align", "文字对齐...")
    model_a, metadata = get_align_model(language)
    result = whisperx.align(result["segments"], model_a, metadata, audio, device,
                            return_char_alignments=False)

    step("diarize", "识别说话人...")
    diarize_model = get_diarize_model(hf_token)
    diarize_kwargs = {}
    if num_speakers and num_speakers > 0:
        diarize_kwargs["num_speakers"] = num_speakers
    else:
        diarize_kwargs["min_speakers"] = 1
        diarize_kwargs["max_speakers"] = 10
    diarize_df = diarize_model(audio, **diarize_kwargs)

    # Get raw diarization segments with precise timestamps
    raw_segments = []
    for _, row in diarize_df.iterrows():
        raw_segments.append({
            "start": float(row["start"]),
            "end": float(row["end"]),
            "speaker": row["speaker"],
        })

    # Assign word speakers
    result = whisperx.assign_word_speakers(diarize_df, result)

    # Collect ALL words with their timestamps and speakers
    all_words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            all_words.append({
                "word": w["word"],
                "start": w.get("start", 0),
                "end": w.get("end", 0),
                "speaker": w.get("speaker", "UNKNOWN"),
            })

    # Map each diarization segment to the words that overlap it
    speaker_map = {}
    speaker_counter = [0]

    def label_for(raw_label: str) -> str:
        if raw_label not in speaker_map:
            speaker_map[raw_label] = chr(ord("A") + speaker_counter[0])
            speaker_counter[0] += 1
        return speaker_map[raw_label]

    segments = []
    project_dir = get_project_dir(project_id)
    seg_idx = 0
    word_idx = 0

    step("punctuation", "添加标点...")

    for ds in raw_segments:
        # Collect words that overlap this diarization segment
        seg_words = []
        while word_idx < len(all_words):
            w = all_words[word_idx]
            # Word overlaps diarization segment if word end > segment start
            if w["end"] <= ds["start"]:
                word_idx += 1
                continue
            if w["start"] >= ds["end"]:
                break
            seg_words.append(w)
            word_idx += 1

        if not seg_words:
            continue

        label = label_for(ds["speaker"])
        raw_text = "".join(w["word"] for w in seg_words).strip()
        if not raw_text:
            continue

        punctuated = _clean_punctuation(restore_punctuation(raw_text))

        step("segment", f"片段 {seg_idx + 1} (说话人 {label})")
        seg_path = project_dir / f"seg_{seg_idx:03d}.wav"
        sd = ds["end"] - ds["start"]
        if sd > 0.01:
            subprocess.run([
                "ffmpeg", "-y", "-i", audio_path,
                "-ss", str(ds["start"]), "-to", str(ds["end"]),
                "-acodec", "pcm_s16le", str(seg_path),
            ], capture_output=True, check=True)
        else:
            subprocess.run([
                "ffmpeg", "-y", "-i", audio_path,
                "-ss", str(ds["start"]), "-t", "0.1",
                "-acodec", "pcm_s16le", str(seg_path),
            ], capture_output=True, check=True)

        segments.append({
            "speaker": label,
            "start_time": ds["start"],
            "end_time": ds["end"],
            "text": punctuated,
            "seg_audio_path": str(seg_path),
        })
        seg_idx += 1

    return segments
