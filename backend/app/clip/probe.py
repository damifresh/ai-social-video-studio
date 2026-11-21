"""Container/stream probing for Engine B.

Uses a standalone ``ffprobe`` when one is available (JSON output, exact stream
data) and falls back to parsing the bundled FFmpeg's stderr (same approach the
Engine A pipeline already uses). The active source is always reported as
``probe_source`` so results are never mistaken for ffprobe output.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..core.config import settings


def _ffprobe_bin() -> str | None:
    cand = settings.ffprobe
    if cand and (Path(cand).exists() or shutil.which(cand)):
        try:
            p = subprocess.run([cand, "-version"], capture_output=True, text=True, timeout=10)
            if p.returncode == 0:
                return cand
        except Exception:
            return None
    return None


def _from_ffprobe(path: Path, exe: str) -> dict:
    p = subprocess.run(
        [exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=120,
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr[-400:]}")
    data = json.loads(p.stdout or "{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), {}) or {}
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    audio = audio_streams[0] if audio_streams else {}
    fps = 0.0
    try:
        num, den = (video.get("avg_frame_rate") or "0/1").split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except Exception:
        fps = 0.0
    # ffprobe reports the coded width/height and carries orientation separately
    # in side data. Combiners need the dimensions as actually displayed, or a
    # 90/270-degree source becomes a letterboxed landscape canvas.
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    rotation = 0.0
    for side in video.get("side_data_list") or []:
        if isinstance(side, dict) and side.get("rotation") is not None:
            try:
                rotation = float(side["rotation"])
            except (TypeError, ValueError):
                pass
            break
    if not rotation:
        try:
            rotation = float((video.get("tags") or {}).get("rotate") or 0)
        except (TypeError, ValueError):
            rotation = 0.0
    swapped = bool(rotation) and round(abs(rotation)) % 180 == 90
    return {
        "probe_source": "ffprobe",
        "rotation": rotation,
        "display_width": height if swapped else width,
        "display_height": width if swapped else height,
        "duration": float(video.get("duration") or fmt.get("duration") or 0.0),
        "video_duration": float(video.get("duration") or 0.0) or None,
        "audio_duration": float(audio.get("duration") or 0.0) or None,
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "video_codec": (video.get("codec_name") or "").lower(),
        "audio_codec": (audio.get("codec_name") or "").lower(),
        "audio_streams": len(audio_streams),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
        "bitrate_kbps": int(float(fmt.get("bit_rate") or 0) / 1000) or None,
        "container": fmt.get("format_name") or path.suffix.lstrip("."),
        "size_bytes": int(os_size(path)),
    }


def os_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return 0


def _from_ffmpeg(path: Path) -> dict:
    p = subprocess.run([settings.ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=120)
    err = p.stderr or ""
    out: dict = {"probe_source": "ffmpeg_fallback", "size_bytes": os_size(path)}
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        h, mi, s = m.groups()
        out["duration"] = round(int(h) * 3600 + int(mi) * 60 + float(s), 3)
    # Parse the whole "Stream #n:m: Video: ..." line. Splitting on commas is
    # unsafe here: pixel formats look like "yuv420p(tv, progressive)" which
    # contains a comma (Matroska/WebM always print the range form).
    vline = next((ln for ln in err.splitlines() if re.search(r": Video:", ln)), "")
    if vline:
        codec = re.search(r"Video:\s*([A-Za-z0-9_\-]+)", vline)
        if codec:
            out["video_codec"] = codec.group(1).strip().lower()
        dims = re.search(r"(?<![\d])(\d{2,5})x(\d{2,5})(?![\d])", vline)
        if dims:
            out["width"] = int(dims.group(1))
            out["height"] = int(dims.group(2))
        pix = re.search(r"Video:\s*\S+(?:\s*\([^)]*\))?,\s*([A-Za-z0-9_]+(?:\([^)]*\))?)", vline)
        if pix:
            out["pix_fmt"] = pix.group(1).strip()
    # The ffmpeg fallback sees coded dimensions too; honour a rotation side
    # data line when it is printed so combine picks the displayed canvas.
    rm = re.search(r"rotation of\s*(-?\d+(?:\.\d+)?)\s*degrees", err, re.I)
    rotation = float(rm.group(1)) if rm else 0.0
    vw, vh = int(out.get("width") or 0), int(out.get("height") or 0)
    swapped = bool(rotation) and round(abs(rotation)) % 180 == 90
    out["rotation"] = rotation
    out["display_width"] = vh if swapped else vw
    out["display_height"] = vw if swapped else vh
    a = re.search(r"Audio: ([^,\s]+)(?:[^,]*), (\d+) Hz, ([^,]+)", err)
    if a:
        out["audio_codec"] = a.group(1).strip().lower()
        out["sample_rate"] = int(a.group(2))
        ch = a.group(3).strip().lower()
        out["channels"] = 2 if "stereo" in ch else (1 if "mono" in ch else 0)
    out["audio_streams"] = len(re.findall(r"Stream #\d+:\d+.*?: Audio:", err))
    fps = re.search(r"(\d+(?:\.\d+)?) fps", err)
    if fps:
        out["fps"] = round(float(fps.group(1)), 3)
    br = re.search(r"bitrate: (\d+) kb/s", err)
    if br:
        out["bitrate_kbps"] = int(br.group(1))
    cm = re.search(r"Input #0, ([^,]+),", err)
    if cm:
        out["container"] = cm.group(1).strip()
    out["video_duration"] = out.get("duration")
    out["audio_duration"] = out.get("duration") if out.get("audio_streams") else None
    return out


def probe_media(path: str | Path) -> dict:
    """Return normalised metadata for a media file, or ``{}`` on failure."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {}
    exe = _ffprobe_bin()
    if exe:
        try:
            return _from_ffprobe(p, exe)
        except Exception:
            pass
    try:
        return _from_ffmpeg(p)
    except Exception:
        return {}


def is_playable_mp4(path: str | Path) -> dict:
    """Validation used by clip rendering and tests (no optimistic defaults)."""
    info = probe_media(path)
    ok = bool(
        info.get("duration", 0) > 0
        and info.get("width", 0) > 0
        and info.get("height", 0) > 0
        and (info.get("video_codec") or "").startswith("h264")
        and (info.get("audio_codec") or "").startswith("aac")
        and info.get("audio_streams", 0) >= 1
    )
    return {"ok": ok, "probe": info}
