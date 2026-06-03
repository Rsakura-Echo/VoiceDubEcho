"""WhisperX CLI — runs in a subprocess, outputs segment JSON to stdout.
Subprocess exit = automatic GPU memory release."""
import sys, os, json, argparse

# Add project root to sys.path for absolute imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set model cache before any model imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_HUB_CACHE", os.path.join(PROJECT_ROOT, "model", "huggingface"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import whisperx
from backend.config import get_project_dir
from backend.model_cache import get_transcribe_model, get_align_model, get_diarize_model, get_device
from backend.punctuation import restore_punctuation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--hf-token", default="")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--num-speakers", type=int, default=0)
    args = parser.parse_args()

    device, _ = get_device()

    def step(name, detail=""):
        print(json.dumps({"step": name, "detail": detail}), flush=True)

    step("load_model", "获取模型...")
    model = get_transcribe_model(args.model, vad_options={})

    step("load_audio", "读取音频...")
    audio = whisperx.load_audio(args.audio)

    step("transcribe", "语音转文字...")
    result = model.transcribe(audio, batch_size=16)
    language = result["language"]

    step("align", "文字对齐...")
    model_a, metadata = get_align_model(language)
    result = whisperx.align(result["segments"], model_a, metadata, audio, device,
                            return_char_alignments=False)

    step("diarize", "识别说话人...")
    diarize_model = get_diarize_model(args.hf_token)
    diarize_kwargs = {}
    if args.num_speakers > 0:
        diarize_kwargs["num_speakers"] = args.num_speakers
    else:
        diarize_kwargs["min_speakers"] = 1
        diarize_kwargs["max_speakers"] = 10
    diarize_df = diarize_model(audio, **diarize_kwargs)

    raw_segments = []
    for _, row in diarize_df.iterrows():
        raw_segments.append({"start": float(row["start"]), "end": float(row["end"]), "speaker": row["speaker"]})

    result = whisperx.assign_word_speakers(diarize_df, result)

    all_words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            all_words.append({"word": w["word"], "start": w.get("start", 0), "end": w.get("end", 0), "speaker": w.get("speaker", "UNKNOWN")})

    speaker_map = {}
    speaker_counter = [0]

    def label_for(raw_label):
        if raw_label not in speaker_map:
            speaker_map[raw_label] = chr(ord("A") + speaker_counter[0])
            speaker_counter[0] += 1
        return speaker_map[raw_label]

    segments = []
    project_dir = get_project_dir(args.project_id)
    seg_idx = 0
    word_idx = 0

    step("punctuation", "添加标点...")

    for ds in raw_segments:
        seg_words = []
        while word_idx < len(all_words):
            w = all_words[word_idx]
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

        from backend.whisperx_worker import _clean_punctuation
        punctuated = _clean_punctuation(restore_punctuation(raw_text))

        step("segment", f"片段 {seg_idx + 1} (说话人 {label})")
        seg_path = project_dir / f"seg_{seg_idx:03d}.wav"
        sd = ds["end"] - ds["start"]
        import subprocess as sp
        if sd > 0.01:
            sp.run(["ffmpeg", "-y", "-i", args.audio, "-ss", str(ds["start"]), "-to", str(ds["end"]), "-acodec", "pcm_s16le", str(seg_path)], capture_output=True, check=True)
        else:
            sp.run(["ffmpeg", "-y", "-i", args.audio, "-ss", str(ds["start"]), "-t", "0.1", "-acodec", "pcm_s16le", str(seg_path)], capture_output=True, check=True)

        segments.append({"speaker": label, "start_time": ds["start"], "end_time": ds["end"], "text": punctuated, "seg_audio_path": str(seg_path)})
        seg_idx += 1

    # Save word cache for precise trim/insert text extraction
    cache_path = project_dir / "words_cache.json"
    cache_path.write_text(json.dumps(all_words, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({"done": True, "segments": segments, "speakers": len(speaker_map)}), flush=True)


if __name__ == "__main__":
    main()
