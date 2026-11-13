from __future__ import annotations
import subprocess
from pathlib import Path
from ..core.config import settings

def concat_wavs(wav_paths: list[Path], out_wav: Path) -> Path:
    """Concatenate WAV files in order (same format assumed/normalized)."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if not wav_paths:
        raise ValueError("no wavs")
    if len(wav_paths) == 1:
        subprocess.run([settings.ffmpeg, "-y", "-i", str(wav_paths[0]), "-ar", "48000", "-ac", "2", str(out_wav)],
                       check=True, capture_output=True)
        return out_wav
    # use concat demuxer
    list_file = out_wav.with_suffix('.txt')
    list_file.write_text("\n".join([f"file '{p.as_posix()}'" for p in wav_paths]), encoding='utf-8')
    subprocess.run([settings.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-ar", "48000", "-ac", "2", str(out_wav)],
                   check=True, capture_output=True)
    try: list_file.unlink()
    except Exception: pass
    return out_wav

def mix_narration_music(narration_wav: Path, out_wav: Path, music_path: Path | None = None, music_volume: float = 0.12) -> Path:
    """Mix narration with optional background music, ducking music under narration."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if not music_path or not music_path.exists():
        subprocess.run([settings.ffmpeg, "-y", "-i", str(narration_wav), "-ar", "48000", "-ac", "2", str(out_wav)],
                       check=True, capture_output=True)
        return out_wav
    # simple ducking: lower music volume; loop music to narration length
    filter_complex = (
        f"[1:a]volume={music_volume},aloop=loop=-1:size=2e+09[m];"
        f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=2,alimiter=limit=0.95[out]"
    )
    subprocess.run([settings.ffmpeg, "-y", "-i", str(narration_wav), "-i", str(music_path),
                    "-filter_complex", filter_complex, "-map", "[out]", "-ar", "48000", "-ac", "2", str(out_wav)],
                   check=True, capture_output=True)
    return out_wav
