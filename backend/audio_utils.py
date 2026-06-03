"""Audio utility functions using pydub + ffmpeg."""
import subprocess
from pathlib import Path
from pydub import AudioSegment


def merge_wavs(input_paths: list[Path], output_path: Path) -> Path:
    """Concatenate WAV files into one."""
    combined = AudioSegment.empty()
    for p in input_paths:
        combined += AudioSegment.from_wav(str(p))
    combined.export(str(output_path), format="wav")
    return output_path


def split_wav(input_path: Path, split_sec: float, out_a: Path, out_b: Path) -> tuple[Path, Path]:
    """Split a WAV file at split_sec (seconds from start)."""
    audio = AudioSegment.from_wav(str(input_path))
    split_ms = int(split_sec * 1000)
    part_a = audio[:split_ms]
    part_b = audio[split_ms:]
    part_a.export(str(out_a), format="wav")
    part_b.export(str(out_b), format="wav")
    return out_a, out_b


def trim_wav(original_path: Path, start_sec: float, end_sec: float, output_path: Path) -> Path:
    """Extract a segment from the original audio using ffmpeg."""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(original_path),
        "-ss", str(start_sec), "-to", str(end_sec),
        "-acodec", "pcm_s16le", str(output_path),
    ], capture_output=True, check=True)
    return output_path


def get_waveform_peaks(audio_path: Path, num_peaks: int = 800) -> list[float]:
    """Return normalized waveform peak data for visualization."""
    audio = AudioSegment.from_wav(str(audio_path))
    samples = audio.get_array_of_samples()
    channels = audio.channels

    if channels > 1:
        # Take left channel peaks
        samples = samples[::channels]

    if len(samples) == 0:
        return [0.0] * num_peaks

    # Downsample to num_peaks buckets, taking max absolute value per bucket
    bucket_size = max(1, len(samples) // num_peaks)
    peaks = []
    max_val = float(2 ** (audio.sample_width * 8 - 1))

    for i in range(num_peaks):
        start = i * bucket_size
        end = min(start + bucket_size, len(samples))
        if start >= len(samples):
            peaks.append(0.0)
        else:
            chunk = samples[start:end]
            peak = max(abs(min(chunk)), abs(max(chunk))) / max_val
            peaks.append(round(peak, 4))

    return peaks


def get_context_audio(original_path: Path, seg_start: float, seg_end: float,
                      before: float, after: float, output_path: Path) -> Path:
    """Extract segment + context audio from original file."""
    ctx_start = max(0, seg_start - before)
    ctx_end = seg_end + after
    return trim_wav(original_path, ctx_start, ctx_end, output_path)


def get_audio_duration(audio_path: Path) -> float:
    """Return duration of a WAV file in seconds."""
    audio = AudioSegment.from_wav(str(audio_path))
    return len(audio) / 1000.0


def export_merged_audio(segments: list[dict], output_path: Path, mode: str = "sequential") -> Path:
    """Export merged audio from segments.

    mode: "sequential" — natural playback, preserve gaps, no overlap
          "stretch" — time-stretch each segment to match original duration, exact timeline
    """
    combined = AudioSegment.empty()
    cursor_s = 0.0  # current position in output timeline (seconds)

    for i, seg in enumerate(segments):
        audio_path = seg.get("dubbed_audio_path") or seg.get("seg_audio_path")
        if not audio_path or not Path(audio_path).exists():
            continue

        seg_audio = AudioSegment.from_wav(str(audio_path))
        original_dur = seg["end_time"] - seg["start_time"]
        actual_dur = len(seg_audio) / 1000.0

        if mode == "stretch" and actual_dur > 0 and abs(actual_dur - original_dur) > 0.05:
            seg_audio = seg_audio.speedup(playback_speed=actual_dur / original_dur)
            actual_dur = original_dur

        if mode == "stretch":
            # Align to original timeline: add silence to reach start_time
            target_start = seg["start_time"]
            if target_start > cursor_s + 0.01:
                combined += AudioSegment.silent(duration=int((target_start - cursor_s) * 1000))
                cursor_s = target_start
        else:
            # Sequential mode: add original gap between segments
            if i > 0:
                gap = seg["start_time"] - (segments[i - 1]["end_time"])
                if gap > 0.01:
                    combined += AudioSegment.silent(duration=int(gap * 1000))
                    cursor_s += gap

        combined += seg_audio
        cursor_s += actual_dur

    combined.export(str(output_path), format="wav")
    return output_path
