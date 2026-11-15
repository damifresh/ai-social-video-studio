"""Engine B clip rendering: cut → reframe (manual crop) → captions → audio → MP4.

Reframing is deterministic geometry (cover-crop + optional manual rectangle).
There is no face/subject tracking, and none is claimed anywhere in the UI.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable

from ..core.config import settings
from ..services.subtitles import DEFAULT_STYLE, build_ass
from .probe import probe_media

ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (720, 1280),
    "16:9": (1280, 720),
    "1:1": (720, 720),
}

PRESETS: dict[str, dict] = {
    "tiktok": {"label": "TikTok", "aspect": "9:16"},
    "reels": {"label": "Instagram Reels", "aspect": "9:16"},
    "shorts": {"label": "YouTube Shorts", "aspect": "9:16"},
    "youtube": {"label": "YouTube (landscape)", "aspect": "16:9"},
    "square": {"label": "Square feed", "aspect": "1:1"},
}

DEFAULT_CAPTION_STYLE = {
    **DEFAULT_STYLE,
    "size": 54,
    "position": "bottom",
    "primary": "#FFFFFF",
    "highlight": "#FFD166",
    "outline": "#000000",
    "keyword_highlight": True,
    "max_chars": 32,
}

DEFAULT_AUDIO = {"normalize": True, "music": None, "music_volume": 0.18}


class RenderCanceled(RuntimeError):
    pass


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def default_crop(src_w: int, src_h: int, aspect: str) -> dict:
    """Largest rect of the target aspect that fits the source, centred."""
    tw, th = ASPECTS.get(aspect, ASPECTS["9:16"])
    target_ar = tw / th
    src_ar = (src_w or tw) / (src_h or th)
    if src_ar > target_ar:
        h = 1.0
        w = target_ar / src_ar
    else:
        w = 1.0
        h = src_ar / target_ar
    return {"mode": "center", "x": round((1 - w) / 2, 4), "y": round((1 - h) / 2, 4),
            "w": round(w, 4), "h": round(h, 4)}


def resolve_crop(crop: dict | None, src_w: int, src_h: int, aspect: str) -> dict:
    """Return a valid, in-bounds rect whose pixel aspect matches the target."""
    base = default_crop(src_w, src_h, aspect)
    c = {**base, **(crop or {})}
    mode = (c.get("mode") or "center").lower()
    w, h = clamp01(c.get("w", base["w"])), clamp01(c.get("h", base["h"]))
    tw, th = ASPECTS.get(aspect, ASPECTS["9:16"])
    if mode == "custom":
        # force the requested width to the target aspect, then clamp
        h = (w * (src_w or tw) * th) / ((src_h or th) * tw)
        if h > 1.0:
            h = 1.0
            w = (h * (src_h or th) * tw) / ((src_w or tw) * th)
    else:
        w, h = base["w"], base["h"]
    x = clamp01(c.get("x", (1 - w) / 2)) if mode in ("custom", "left", "right") else (1 - w) / 2
    y = clamp01(c.get("y", (1 - h) / 2)) if mode in ("custom", "top", "bottom") else (1 - h) / 2
    if mode == "left":
        x = 0.0
    elif mode == "right":
        x = 1 - w
    elif mode == "top":
        y = 0.0
    elif mode == "bottom":
        y = 1 - h
    x = min(x, 1 - w)
    y = min(y, 1 - h)
    return {"mode": mode, "x": round(max(0.0, x), 4), "y": round(max(0.0, y), 4),
            "w": round(w, 4), "h": round(h, 4)}


def _even(expr: str) -> str:
    return f"trunc({expr}/2)*2"


def build_filters(
    src_w: int,
    src_h: int,
    aspect: str,
    crop: dict,
    fps: int,
    caption_file: str | None,
    audio: dict,
    duration: float,
    has_music: bool,
) -> tuple[str, str | None]:
    tw, th = ASPECTS.get(aspect, ASPECTS["9:16"])
    cw, ch, cx, cy = crop["w"], crop["h"], crop["x"], crop["y"]
    crop_w = _even(f"iw*{cw}")
    crop_h = _even(f"ih*{ch}")
    v = (
        f"crop={crop_w}:{crop_h}:"
        f"trunc(iw*{cx}/2)*2:trunc(ih*{cy}/2)*2,"
        f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
        f"crop={tw}:{th},fps={fps},setsar=1"
    )
    if caption_file:
        v += f",subtitles={caption_file}"
    v += ",format=yuv420p"

    if not has_music:
        a = "loudnorm=I=-16:TP=-1.5:LRA=11" if audio.get("normalize", True) else "anull"
        return v, a

    vol = clamp01(audio.get("music_volume", 0.18))
    norm = "loudnorm=I=-16:TP=-1.5:LRA=11," if audio.get("normalize", True) else ""
    graph = (
        f"[0:v]{v}[v];"
        f"[0:a]{norm}asplit=2[n1][n2];"
        f"[1:a]volume={vol:.2f},aloop=loop=-1:size=2147483647,atrim=0:{max(0.1, duration):.3f},"
        f"afade=t=out:st={max(0.0, duration - 0.8):.2f}:d=0.8[mus];"
        f"[mus][n2]sidechaincompress=threshold=0.06:ratio=6:attack=15:release=300[duck];"
        f"[n1][duck]amix=inputs=2:duration=first:normalize=0[a]"
    )
    return graph, None


def caption_file_for(
    cues: list[dict],
    out_dir: Path,
    style: dict | None,
    width: int,
    height: int,
    name: str = "captions.ass",
) -> Path | None:
    if not cues:
        return None
    out = out_dir / name
    build_ass(cues, out, style={**DEFAULT_CAPTION_STYLE, **(style or {})}, width=width, height=height)
    return out


def render_clip(
    source: Path,
    out_path: Path,
    start: float,
    end: float,
    aspect: str = "9:16",
    crop: dict | None = None,
    cues: list[dict] | None = None,
    caption_style: dict | None = None,
    audio: dict | None = None,
    fps: int = 30,
    on_progress: Callable[[int, str], None] | None = None,
    check: Callable[[], None] | None = None,
) -> dict:
    info = probe_media(source)
    src_w, src_h = int(info.get("width") or 1280), int(info.get("height") or 720)
    dur = max(0.2, round(end - start, 3))
    if start < 0 or end <= start:
        raise ValueError("Invalid clip range")
    if end > float(info.get("duration") or end) + 0.05:
        raise ValueError("Clip range is outside the source duration")

    aspect = aspect if aspect in ASPECTS else "9:16"
    tw, th = ASPECTS[aspect]
    rect = resolve_crop(crop, src_w, src_h, aspect)
    aud = {**DEFAULT_AUDIO, **(audio or {})}
    music = Path(aud["music"]) if aud.get("music") else None
    if music and not music.exists():
        music = None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent
    cap_path = caption_file_for(cues or [], work, caption_style, tw, th)
    cap_arg = cap_path.name if cap_path else None

    v_arg, a_arg = build_filters(src_w, src_h, aspect, rect, fps, cap_arg, aud, dur, bool(music))
    if music:
        cmd = [
            settings.ffmpeg, "-hide_banner", "-y", "-nostats", "-progress", "pipe:1",
            "-ss", f"{max(0.0, start):.3f}", "-t", f"{dur:.3f}", "-i", str(source),
            "-stream_loop", "-1", "-i", str(music),
            "-filter_complex", v_arg,
            "-map", "[v]", "-map", "[a]",
        ]
    else:
        cmd = [
            settings.ffmpeg, "-hide_banner", "-y", "-nostats", "-progress", "pipe:1",
            "-ss", f"{max(0.0, start):.3f}", "-t", f"{dur:.3f}", "-i", str(source),
            "-vf", v_arg, "-af", a_arg,
        ]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-t", f"{dur:.3f}", "-avoid_negative_ts", "make_zero",
        str(out_path),
    ]

    tmp_out = out_path.with_suffix(".part.mp4")
    cmd[-1] = str(tmp_out)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(work))
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if check:
                try:
                    check()
                except Exception:
                    proc.kill()
                    raise
            m = re.match(r"out_time_ms=(\d+)", line.strip())
            if m and on_progress:
                done = int(m.group(1)) / 1_000_000
                on_progress(min(99, int(100 * done / dur)), "Rendering clip")
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    err = (proc.stderr.read() if proc.stderr else "") or ""
    if proc.returncode != 0 or not tmp_out.exists():
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg clip render failed ({proc.returncode}): {err[-1200:]}")
    tmp_out.replace(out_path)
    if on_progress:
        on_progress(100, "Clip rendered")

    return {
        "output": str(out_path),
        "requested_duration": dur,
        "aspect_ratio": aspect,
        "resolution": f"{tw}x{th}",
        "crop": rect,
        "captions": bool(cap_path),
        "music": str(music) if music else None,
        "command": [c if " " not in c else f"'{c}'" for c in cmd[:14]],
        "probe": probe_media(out_path),
        "caption_file": str(cap_path) if cap_path else None,
    }


def validate_render(result: dict, aspect: str, expected_duration: float) -> dict:
    p = result.get("probe") or {}
    tw, th = ASPECTS.get(aspect, ASPECTS["9:16"])
    checks = {
        "exists": Path(result.get("output", "")).exists(),
        "resolution_ok": (p.get("width"), p.get("height")) == (tw, th),
        "video_codec_h264": (p.get("video_codec") or "").startswith("h264"),
        "audio_codec_aac": (p.get("audio_codec") or "").startswith("aac"),
        "duration_ok": abs(float(p.get("duration") or 0) - expected_duration) <= 0.2,
        "audio_present": int(p.get("audio_streams") or 0) >= 1,
        "size_ok": int(p.get("size_bytes") or 0) > 10_000,
    }
    vd, ad = p.get("video_duration"), p.get("audio_duration")
    if vd and ad:
        checks["av_sync_ok"] = abs(float(vd) - float(ad)) < 0.1
    checks["ok"] = all(checks.values())
    return checks


def crop_presets() -> list[dict]:
    return [{"id": "center", "label": "Center"} , {"id": "left", "label": "Left"},
            {"id": "right", "label": "Right"}, {"id": "top", "label": "Top"},
            {"id": "bottom", "label": "Bottom"}, {"id": "custom", "label": "Manual rect"}]
