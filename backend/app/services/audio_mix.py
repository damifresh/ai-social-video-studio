from __future__ import annotations

import subprocess
from pathlib import Path

from ..core.config import settings


def concat_wavs(wav_paths: list[Path], out_wav: Path) -> Path:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    if not wav_paths:
        raise ValueError("no narration wavs")
    if len(wav_paths) == 1:
        subprocess.run(
            [settings.ffmpeg, "-y", "-i", str(wav_paths[0]), "-ar", "48000", "-ac", "2", str(out_wav)],
            check=True, capture_output=True, timeout=600,
        )
        return out_wav
    list_file = out_wav.with_suffix(".txt")
    list_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in wav_paths), encoding="utf-8")
    try:
        subprocess.run(
            [settings.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-ar", "48000", "-ac", "2", str(out_wav)],
            check=True, capture_output=True, timeout=900,
        )
    finally:
        list_file.unlink(missing_ok=True)
    return out_wav


def _probe_duration(path: Path) -> float:
    try:
        p = subprocess.run([settings.ffmpeg, "-i", str(path)], capture_output=True, text=True, timeout=30)
        import re

        m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return 0.0


def pad_audio_to(path: Path, seconds: float) -> Path:
    """Pad a narration clip with silence so scene audio exactly matches scene video."""
    target = max(0.2, float(seconds))
    tmp = path.with_name(path.stem + ".pad" + path.suffix)
    subprocess.run(
        [settings.ffmpeg, "-y", "-i", str(path), "-af", "apad", "-t", f"{target:.3f}",
         "-ar", "24000", "-ac", "1", str(tmp)],
        check=True, capture_output=True, timeout=300,
    )
    tmp.replace(path)
    return path


def mix_narration_music(
    narration_wav: Path,
    out_wav: Path,
    music_path: Path | None = None,
    music_volume: float = 0.10,
    fade_out: float = 2.0,
    sfx_events: list[dict] | None = None,
) -> Path:
    """Mix narration with looped, ducked background music and optional timed SFX.

    Uses sidechain compression so music drops under narration, plus a gentle limiter.
    """
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    narration_dur = _probe_duration(narration_wav)
    sfx_events = [e for e in (sfx_events or []) if Path(e.get("path", "")).exists()][:20]
    has_music = bool(music_path and Path(music_path).exists())

    if not has_music and not sfx_events:
        subprocess.run(
            [settings.ffmpeg, "-y", "-i", str(narration_wav), "-af",
             f"afade=t=out:st={max(0.0, narration_dur - fade_out):.2f}:d={fade_out},"
             "loudnorm=I=-16:TP=-1.5:LRA=11,alimiter=limit=0.95",
             "-ar", "48000", "-ac", "2", str(out_wav)],
            check=True, capture_output=True, timeout=600,
        )
        return out_wav

    inputs = ["-i", str(narration_wav)]
    chains: list[str] = []
    mix_inputs: list[str] = ["[0:a]"]
    idx = 1

    if has_music:
        inputs += ["-i", str(music_path)]
        # UI level 0-50% maps to a -34…-6 dB bed; 10% is a subtle bed under speech.
        gain = max(0.02, min(0.9, float(music_volume) * 4.0))
        chains.append(
            f"[{idx}:a]volume={gain:.3f},aloop=loop=-1:size=2e+09,atrim=0:{narration_dur:.3f},"
            f"afade=t=out:st={max(0.0, narration_dur - fade_out):.2f}:d={fade_out}[music]"
        )
        # sidechain: [main][sidechain]sidechaincompress
        chains.append("[music][0:a]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=350[ducked]")
        mix_inputs.append("[ducked]")
        idx += 1

    for i, ev in enumerate(sfx_events):
        inputs += ["-i", str(ev["path"])]
        delay_ms = max(0, int(float(ev.get("start", 0)) * 1000))
        vol = float(ev.get("volume", 0.6))
        label = f"sfx{i}"
        chains.append(f"[{idx}:a]volume={vol:.2f},adelay={delay_ms}|{delay_ms},atrim=0:{narration_dur:.3f}[{label}]")
        mix_inputs.append(f"[{label}]")
        idx += 1

    filter_complex = ";".join(chains) + (
        f";{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=2:normalize=0,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,alimiter=limit=0.95[out]"
    )
    cmd = [settings.ffmpeg, "-y", *inputs, "-filter_complex", filter_complex,
           "-map", "[out]", "-ar", "48000", "-ac", "2", str(out_wav)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=1200)
    return out_wav
