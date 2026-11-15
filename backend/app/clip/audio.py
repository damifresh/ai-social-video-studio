"""Audio extraction and structural analysis (no ML).

Everything here is deterministic FFmpeg/PCM processing. Values are recorded
with the thresholds used so the highlight scoring can be audited later.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from typing import Callable

from ..core.config import settings


class NoAudioTrack(Exception):
    pass


def _run(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])}... {p.stderr[-800:]}")
    return p


def extract_analysis_audio(source: Path, out_wav: Path) -> Path:
    """Mono 16 kHz PCM WAV used for ASR; small, deterministic, stream-friendly."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    _run([
        settings.ffmpeg, "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(out_wav),
    ])
    if not out_wav.exists() or out_wav.stat().st_size < 1000:
        raise NoAudioTrack("Source has no usable audio track (extracted WAV is empty).")
    return out_wav


def rms_envelope(
    wav: Path,
    window_sec: float = 0.1,
    analysis_rate: int = 8000,
    on_progress: Callable[[float, float], None] | None = None,
    check: Callable[[], None] | None = None,
) -> dict:
    """Stream PCM and compute a windowed RMS/peak envelope (dBFS).

    Streaming keeps memory flat regardless of source length (a 60-minute file
    is processed in fixed 8 kHz chunks).
    """
    cmd = [
        settings.ffmpeg, "-v", "error", "-i", str(wav), "-f", "s16le",
        "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(analysis_rate), "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    frame_bytes = 2 * max(1, int(analysis_rate * window_sec))
    windows: list[dict] = []
    idx = 0
    try:
        while True:
            chunk = proc.stdout.read(frame_bytes)
            if not chunk:
                break
            if check:
                check()
            usable = len(chunk) - (len(chunk) % 2)
            if usable <= 0:
                continue
            samples = memoryview(chunk)[:usable].cast("h")
            peak = 0.0
            total = 0.0
            for s in samples:
                v = s / 32768.0
                total += v * v
                av = abs(v)
                if av > peak:
                    peak = av
            n = max(1, len(samples))
            rms = math.sqrt(total / n) or 1e-9
            windows.append({
                "t": round(idx * window_sec, 3),
                "db": round(20 * math.log10(max(rms, 1e-9)), 2),
                "peak_db": round(20 * math.log10(max(peak, 1e-9)), 2),
            })
            idx += 1
            if on_progress and idx % 200 == 0:
                on_progress(idx * window_sec, 0)
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
    err = b""
    try:
        err = proc.stderr.read() if proc.stderr else b""
    except Exception:
        pass
    if proc.wait() not in (0, -9) and not windows:
        raise RuntimeError(f"audio decode failed: {err[-400:]!r}")
    return {"window_sec": window_sec, "analysis_rate": analysis_rate, "windows": windows}


def mean_db(envelope: dict, start: float, end: float) -> float | None:
    w = envelope.get("window_sec") or 0.1
    vals = [
        x["db"] for x in envelope.get("windows", [])
        if start <= x["t"] < end
    ]
    if not vals:
        return None
    # energy average
    energy = sum(10 ** (v / 10) for v in vals) / len(vals)
    return round(10 * math.log10(max(energy, 1e-12)), 2)


def silence_ratio(envelope: dict, start: float, end: float, threshold_db: float = -38.0) -> float:
    w = envelope.get("window_sec") or 0.1
    vals = [x["db"] for x in envelope.get("windows", []) if start <= x["t"] < end]
    if not vals:
        return 0.0
    quiet = sum(1 for v in vals if v <= threshold_db)
    return round(quiet / len(vals), 3)


def detect_silence(wav: Path, noise_db: int = -32, min_gap: float = 0.35) -> dict:
    p = subprocess.run(
        [settings.ffmpeg, "-hide_banner", "-nostats", "-i", str(wav),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_gap}", "-f", "null", "-"],
        capture_output=True, text=True, timeout=3600,
    )
    err = p.stderr or ""
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    gaps = [{"start": round(s, 3), "end": round(e, 3)} for s, e in zip(starts, ends)]
    return {"noise_db": noise_db, "min_gap_sec": min_gap, "gaps": gaps}


def detect_scene_cuts(source: Path, threshold: float = 0.32, sample_fps: float = 2.0) -> dict:
    """Downscaled scene-change scan. Approximate by design (2 fps, 320px wide)."""
    p = subprocess.run(
        [settings.ffmpeg, "-hide_banner", "-nostats", "-i", str(source), "-an",
         "-vf", f"fps={sample_fps},scale=320:-2,select='gt(scene,{threshold})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=3600,
    )
    err = p.stderr or ""
    cuts = sorted({round(float(x), 3) for x in re.findall(r"pts_time:([\d.]+)", err)})
    return {"threshold": threshold, "sample_fps": sample_fps, "cuts": cuts}


def measure_loudness(path: Path) -> dict:
    """Integrated loudness + true peak of a rendered clip (EBU R128)."""
    p = subprocess.run(
        [settings.ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, timeout=900,
    )
    err = p.stderr or ""
    summary = err.split("Summary:")[-1] if "Summary:" in err else err
    i = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", summary)
    tp = re.search(r"Peak:\s*(-?[\d.]+)\s*dBFS", summary)
    lra = re.search(r"LRA:\s*(-?[\d.]+)\s*LU", summary)
    return {
        "integrated_lufs": float(i.group(1)) if i else None,
        "true_peak_dbfs": float(tp.group(1)) if tp else None,
        "lra_lu": float(lra.group(1)) if lra else None,
    }
