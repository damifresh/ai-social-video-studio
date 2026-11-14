from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..services.render import probe_video_info


def _ffprobe_available() -> bool:
    p = settings.ffprobe
    return bool(p and (Path(p).exists() or shutil.which(p)))


def probe(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "valid": False}
    # Prefer ffprobe JSON when available
    if _ffprobe_available():
        cmd = [
            settings.ffprobe, "-v", "error",
            "-show_format", "-show_streams",
            "-of", "json", str(path),
        ]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=40)
            data = json.loads(out)
            streams = data.get("streams") or []
            v = next((s for s in streams if s.get("codec_type") == "video"), None)
            a = next((s for s in streams if s.get("codec_type") == "audio"), None)
            fmt = data.get("format") or {}
            duration = None
            try:
                duration = float(fmt.get("duration") or (v or {}).get("duration") or 0) or None
            except Exception:
                duration = None
            size = 0
            try:
                size = int(fmt.get("size") or path.stat().st_size)
            except Exception:
                size = path.stat().st_size if path.exists() else 0
            return {
                "exists": True, "path": str(path), "valid": True, "source": "ffprobe",
                "container": fmt.get("format_name"), "duration_sec": duration, "size_bytes": size,
                "bit_rate": fmt.get("bit_rate"),
                "video": {"codec": (v or {}).get("codec_name"), "profile": (v or {}).get("profile"), "width": (v or {}).get("width"), "height": (v or {}).get("height"), "pix_fmt": (v or {}).get("pix_fmt"), "r_frame_rate": (v or {}).get("r_frame_rate"), "avg_frame_rate": (v or {}).get("avg_frame_rate")} if v else None,
                "audio": {"codec": (a or {}).get("codec_name"), "sample_rate": (a or {}).get("sample_rate"), "channels": (a or {}).get("channels")} if a else None,
            }
        except Exception:
            pass
    # Fallback: ffmpeg-based parser already used by pipeline
    try:
        info = probe_video_info(path)
    except Exception as e:
        return {"exists": True, "path": str(path), "valid": False, "source": "ffmpeg_fallback_error", "error": str(e)}
    if not info or not info.get("width"):
        return {"exists": True, "path": str(path), "valid": False, "source": "ffmpeg_fallback", "probe_info": info}
    vcodec = (info.get("video_codec") or "").split()[0] if info.get("video_codec") else None
    acodec = (info.get("audio_codec") or "").split()[0] if info.get("audio_codec") else None
    return {
        "exists": True, "path": str(path), "valid": True, "source": "ffmpeg_fallback",
        "container": "mov,mp4,m4a,3gp,3g2,mj2", "duration_sec": info.get("duration"), "size_bytes": info.get("size_bytes"),
        "bit_rate": str(int((info.get("bitrate_kbps") or 0) * 1000)) if info.get("bitrate_kbps") else None,
        "video": {"codec": vcodec, "width": info.get("width"), "height": info.get("height"), "pix_fmt": info.get("pix_fmt"), "avg_frame_rate": str(info.get("fps")) if info.get("fps") else None},
        "audio": {"codec": acodec, "sample_rate": info.get("sample_rate"), "channels": 2 if info.get("audio_codec") else None} if info.get("audio_codec") else None,
        "probe_info": info,
    }


def validate_export(path: Path, expected_aspect: str | None = None, target_height: int = 720) -> dict[str, Any]:
    info = probe(path)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("file_exists", info.get("exists"))
    add("probe_valid", info.get("valid"))
    v = info.get("video") or {}
    a = info.get("audio") or {}
    add("has_video_stream", bool(v.get("codec")), v.get("codec"))
    add("has_audio_stream", bool(a.get("codec")), a.get("codec"))
    add("video_codec_h264", v.get("codec") == "h264", v.get("codec"))
    add("audio_codec_aac", v.get("codec") == "aac" or a.get("codec") == "aac", a.get("codec") or v.get("codec"))
    # wait, audio codec check above is wrong logic; fix properly
    return _validate_with_info(path, expected_aspect, target_height, info)


def _validate_with_info(path: Path, expected_aspect: str | None, target_height: int, info: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("file_exists", info.get("exists"))
    add("probe_valid", info.get("valid"))
    v = info.get("video") or {}
    a = info.get("audio") or {}
    add("has_video_stream", bool(v.get("codec")), v.get("codec"))
    add("has_audio_stream", bool(a.get("codec")), a.get("codec"))
    add("video_codec_h264", v.get("codec") == "h264", v.get("codec"))
    add("audio_codec_aac", a.get("codec") == "aac", a.get("codec"))
    w, h = v.get("width"), v.get("height")
    is_720 = (h == target_height) or (w == target_height)
    add("resolution_720p_target", is_720, {"width": w, "height": h, "target": target_height})
    if expected_aspect and w and h:
        ratio = w / h
        expected = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}.get(expected_aspect)
        if expected:
            add("aspect_ratio", abs(ratio - expected) < 0.03, {"actual": round(ratio, 4), "expected": expected_aspect})
    dur = info.get("duration_sec")
    add("duration_positive", isinstance(dur, (int, float)) and dur > 0, dur)
    add("file_size_positive", (info.get("size_bytes") or 0) > 0, info.get("size_bytes"))
    add("valid_mp4_container", "mp4" in str(info.get("container") or ""), info.get("container"))
    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "checks": checks, "probe": info}
