"""Engine B clip rendering: cut → native canvas → captions → audio → MP4.

Single-source, assembled and combined videos all keep the decoded source frame:
the output canvas is the source's own pixel size and mismatched sizes are fitted
and padded, never zoomed or cut. An explicitly entered custom crop is the only
crop applied. Geometry is deterministic; there is no face/subject tracking.
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


def _even_size(value: int) -> int:
    """Largest even pixel count at or below ``value`` (yuv420p requirement)."""
    return max(2, int(value) // 2 * 2)


def native_canvas(info: dict) -> tuple[int, int]:
    """Displayed native pixel size of a probed source, even-aligned.

    FFmpeg applies rotation before the filter graph, so the displayed size (not
    the coded width/height) is the canvas that preserves every decoded pixel.
    """
    w = int(info.get("display_width") or info.get("width") or 1280)
    h = int(info.get("display_height") or info.get("height") or 720)
    return _even_size(w), _even_size(h)


def resolve_custom_crop(crop: dict | None) -> dict | None:
    """Keep only an explicitly entered custom crop rectangle.

    Automatic centre/edge reframing is the "zoom" that cuts the source frame;
    it is no longer applied. A user-entered rectangle is a deliberate editorial
    choice, so it is still honoured as a pre-fit window.
    """
    if not isinstance(crop, dict) or str(crop.get("mode") or "").lower() != "custom":
        return None
    try:
        x, y = clamp01(crop.get("x", 0.0)), clamp01(crop.get("y", 0.0))
        w, h = clamp01(crop.get("w", 1.0)), clamp01(crop.get("h", 1.0))
    except (TypeError, ValueError):
        return None
    w, h = max(0.02, w), max(0.02, h)
    x, y = min(x, 1 - w), min(y, 1 - h)
    return {
        "mode": "custom",
        "x": round(max(0.0, x), 4), "y": round(max(0.0, y), 4),
        "w": round(w, 4), "h": round(h, 4),
    }


def _caption_style_for_canvas(caption_style: dict | None, aspect: str, height: int) -> dict:
    """Scale authored caption size to a native canvas without touching timing."""
    style = dict(caption_style or {})
    preset_h = ASPECTS.get(aspect, ASPECTS["9:16"])[1]
    if height != preset_h:
        base = float(style.get("size") or DEFAULT_CAPTION_STYLE["size"])
        style["size"] = max(24, int(round(base * height / preset_h)))
    return style


def _video_chain(
    src_w: int,
    src_h: int,
    aspect: str,
    crop: dict,
    fps: int,
    caption_file: str | None,
    output_size: tuple[int, int] | None = None,
) -> str:
    """Shared crop/scale/caption chain for one contiguous video stream.

    With ``output_size`` the full decoded frame is fitted *inside* the source's
    own canvas and padded: no automatic cover crop and no zoom. Only a caller's
    explicit custom crop is applied first. Without it, the legacy cover-crop to
    the aspect preset is retained (used only by the combine legacy branch).
    """
    if output_size is not None:
        tw, th = output_size
        steps: list[str] = []
        if crop:
            crop_w = _even(f"iw*{crop['w']}")
            crop_h = _even(f"ih*{crop['h']}")
            steps.append(
                f"crop={crop_w}:{crop_h}:"
                f"trunc(iw*{crop['x']}/2)*2:trunc(ih*{crop['y']}/2)*2"
            )
        steps.extend([
            "setsar=1",
            f"scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos",
            f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black",
            f"fps={fps},setsar=1",
        ])
        v = ",".join(steps)
    else:
        tw, th = ASPECTS.get(aspect, ASPECTS["9:16"])
        cw, ch, cx, cy = crop["w"], crop["h"], crop["x"], crop["y"]
        v = (
            f"crop={_even(f'iw*{cw}')}:{_even(f'ih*{ch}')}:"
            f"trunc(iw*{cx}/2)*2:trunc(ih*{cy}/2)*2,"
            f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},fps={fps},setsar=1"
        )
    if caption_file:
        v += f",subtitles={caption_file}"
    return v + ",format=yuv420p"


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
    output_size: tuple[int, int] | None = None,
) -> tuple[str, str | None]:
    v = _video_chain(src_w, src_h, aspect, crop, fps, caption_file, output_size)

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
    src_w, src_h = native_canvas(info)
    # The final preview and the exported file share this render. Keep the
    # source's own pixel canvas so nothing is zoomed, cut or downscaled.
    tw, th = src_w, src_h
    dur = max(0.2, round(end - start, 3))
    if start < 0 or end <= start:
        raise ValueError("Invalid clip range")
    if end > float(info.get("duration") or end) + 0.05:
        raise ValueError("Clip range is outside the source duration")

    aspect = aspect if aspect in ASPECTS else "9:16"
    # Only a user-entered rectangle counts as a crop; the old automatic
    # cover-crop was the zoom that enlarged the frame and cut its edges.
    rect = resolve_custom_crop(crop)
    aud = {**DEFAULT_AUDIO, **(audio or {})}
    music = Path(aud["music"]) if aud.get("music") else None
    if music and not music.exists():
        music = None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent
    cap_path = caption_file_for(
        cues or [], work, _caption_style_for_canvas(caption_style, aspect, th), tw, th,
    )
    cap_arg = cap_path.name if cap_path else None

    v_arg, a_arg = build_filters(
        src_w, src_h, aspect, rect, fps, cap_arg, aud, dur, bool(music),
        output_size=(tw, th),
    )
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
        # Re-encoded once at visually lossless quality so the preview keeps
        # the source's fidelity just like the native-resolution combine path.
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
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
        if proc.stdout:
            proc.stdout.close()
    err = (proc.stderr.read() if proc.stderr else "") or ""
    if proc.stderr:
        proc.stderr.close()
    if proc.returncode != 0 or not tmp_out.exists():
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg clip render failed ({proc.returncode}): {err[-1200:]}")
    tmp_out.replace(out_path)
    if on_progress:
        on_progress(100, "Clip rendered")

    return {
        "output": str(out_path),
        "requested_duration": dur,
        "aspect_ratio": aspect,  # project/preset file key, not the canvas
        "resolution": f"{tw}x{th}",
        "source_resolution": f"{tw}x{th}",
        "resolution_mode": "source-native",
        "crop": rect,  # None unless the user entered a custom rectangle
        "captions": bool(cap_path),
        "music": str(music) if music else None,
        "command": [c if " " not in c else f"'{c}'" for c in cmd[:14]],
        "probe": probe_media(out_path),
        "caption_file": str(cap_path) if cap_path else None,
    }


def render_assembly(
    source: Path,
    out_path: Path,
    segments: list[dict],
    aspect: str = "9:16",
    crop: dict | None = None,
    cues: list[dict] | None = None,
    caption_style: dict | None = None,
    audio: dict | None = None,
    fps: int = 30,
    on_progress: Callable[[int, str], None] | None = None,
    check: Callable[[], None] | None = None,
) -> dict:
    """Render ordered source ranges into one captioned native-resolution MP4.

    Every input range is a validated transcript-grounded segment. The ranges are
    concatenated in director order; captions are supplied already remapped to
    the assembled timeline by the caller. The source's own pixel canvas is kept
    so the Final preview shows the whole frame without zoom or cropping.
    """
    info = probe_media(source)
    src_w, src_h = native_canvas(info)
    tw, th = src_w, src_h
    src_duration = float(info.get("duration") or 0)
    validated: list[dict] = []
    ranges: list[tuple[float, float]] = []
    total = 0.0
    for index, segment in enumerate(segments or []):
        if not isinstance(segment, dict):
            raise ValueError(f"Assembly segment {index + 1} is invalid")
        try:
            start, end = float(segment["start"]), float(segment["end"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Assembly segment {index + 1} needs numeric start and end")
        if start < 0 or end <= start:
            raise ValueError(f"Assembly segment {index + 1} has an invalid range")
        if any(start < other_end - 0.001 and end > other_start + 0.001
               for other_start, other_end in ranges):
            raise ValueError("Assembly segments must be non-overlapping")
        if src_duration and end > src_duration + 0.05:
            raise ValueError("Assembly segment extends outside the source duration")
        duration = round(end - start, 3)
        validated.append({
            "index": index,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": duration,
            "role": segment.get("role"),
            "text": segment.get("text"),
        })
        ranges.append((start, end))
        total += duration
    if not validated or total < 0.2:
        raise ValueError("Assembly needs at least one non-empty segment")
    total = round(total, 3)

    aspect = aspect if aspect in ASPECTS else "9:16"
    rect = resolve_custom_crop(crop)
    aud = {**DEFAULT_AUDIO, **(audio or {})}
    music = Path(aud["music"]) if aud.get("music") else None
    if music and not music.exists():
        music = None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent
    cap_path = caption_file_for(
        cues or [], work, _caption_style_for_canvas(caption_style, aspect, th), tw, th,
    )
    cap_arg = cap_path.name if cap_path else None

    n = len(validated)
    graph_parts = [
        "[0:v]split=" + str(n) + " " + "".join(f"[vsrc{i}]" for i in range(n)),
        "[0:a]asplit=" + str(n) + " " + "".join(f"[asrc{i}]" for i in range(n)),
    ]
    for i, segment in enumerate(validated):
        graph_parts.append(
            f"[vsrc{i}]trim=start={segment['start']:.3f}:end={segment['end']:.3f},"
            f"setpts=PTS-STARTPTS[v{i}]"
        )
        graph_parts.append(
            f"[asrc{i}]atrim=start={segment['start']:.3f}:end={segment['end']:.3f},"
            f"asetpts=PTS-STARTPTS[a{i}]"
        )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
    graph_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[catv][cata]")
    graph_parts.append(
        f"[catv]{_video_chain(src_w, src_h, aspect, rect, fps, cap_arg, (tw, th))}[v]"
    )

    norm = "loudnorm=I=-16:TP=-1.5:LRA=11," if aud.get("normalize", True) else ""
    if music:
        vol = clamp01(aud.get("music_volume", 0.18))
        graph_parts.append(
            f"[cata]{norm}asplit=2[n1][n2];"
            f"[1:a]volume={vol:.2f},aloop=loop=-1:size=2147483647,"
            f"atrim=0:{total:.3f},afade=t=out:st={max(0.0, total - 0.8):.2f}:d=0.8[mus];"
            f"[mus][n2]sidechaincompress=threshold=0.06:ratio=6:attack=15:release=300[duck];"
            f"[n1][duck]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        graph_parts.append(f"[cata]{norm.rstrip(',')}[a]")
    graph = ";".join(graph_parts)

    cmd = [
        settings.ffmpeg, "-hide_banner", "-y", "-nostats", "-progress", "pipe:1",
        "-i", str(source),
    ]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    cmd += [
        "-filter_complex", graph,
        "-map", "[v]", "-map", "[a]",
        # One visually lossless encode keeps the assembled preview identical in
        # quality to the exported MP4, at the source's native dimensions.
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-t", f"{total:.3f}", "-avoid_negative_ts", "make_zero",
    ]

    tmp_out = out_path.with_suffix(".part.mp4")
    cmd.append(str(tmp_out))
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
            match = re.match(r"out_time_ms=(\d+)", line.strip())
            if match and on_progress:
                done = int(match.group(1)) / 1_000_000
                on_progress(min(99, int(100 * done / total)), "Rendering assembled video")
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    err = (proc.stderr.read() if proc.stderr else "") or ""
    if proc.stdout:
        proc.stdout.close()
    if proc.stderr:
        proc.stderr.close()
    if proc.returncode != 0 or not tmp_out.exists():
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg assembly render failed ({proc.returncode}): {err[-1200:]}")
    tmp_out.replace(out_path)
    if on_progress:
        on_progress(100, "Assembled video rendered")

    preview = [item[:200] + "…" if len(item) > 200 else item for item in cmd[:14]]
    return {
        "output": str(out_path),
        "requested_duration": total,
        "aspect_ratio": aspect,  # project/preset file key, not the canvas
        "resolution": f"{tw}x{th}",
        "source_resolution": f"{tw}x{th}",
        "resolution_mode": "source-native",
        "crop": rect,  # None unless the user entered a custom rectangle
        "captions": bool(cap_path),
        "music": str(music) if music else None,
        "command": preview,
        "probe": probe_media(out_path),
        "caption_file": str(cap_path) if cap_path else None,
        "assembly": {
            "segment_count": n,
            "source_ranges": [[s["start"], s["end"]] for s in validated],
            "roles": [s.get("role") for s in validated],
            "total_duration": total,
        },
    }


# ------------------------------------------------------------------- combine

# Automatic transitions are a deliberate, visible choice. The default is a
# short crossfade; "straightforward cuts" is the opt-out. Both are generated by
# one FFmpeg filter graph so the rendered MP4 is always a single file.
DEFAULT_TRANSITION_SECONDS = 0.6
MAX_TRANSITION_SECONDS = 1.5
MIN_TRANSITION_SECONDS = 0.1
MIN_COMBINE_SEGMENT_SECONDS = 0.2
MAX_COMBINE_TARGET_SECONDS = 180.0


def _combine_boundaries(
    durations: list[float],
    transitions: bool,
    transition_seconds: float,
) -> list[float]:
    """Crossfade lengths for each adjacent pair, or zeros for straight cuts."""
    boundaries = [0.0] * max(0, len(durations) - 1)
    if transitions and len(durations) > 1:
        requested = min(MAX_TRANSITION_SECONDS, max(
            MIN_TRANSITION_SECONDS, float(transition_seconds or DEFAULT_TRANSITION_SECONDS),
        ))
        for i in range(len(durations) - 1):
            safe = min(durations[i], durations[i + 1]) * 0.35
            boundaries[i] = round(max(MIN_TRANSITION_SECONDS, min(requested, safe)), 3)
    return boundaries


def max_combine_duration(
    durations: list[float],
    transitions: bool,
    transition_seconds: float = DEFAULT_TRANSITION_SECONDS,
) -> float:
    """Longest final timeline obtainable from these whole source durations."""
    values = [float(d) for d in durations if float(d) > 0]
    if not values:
        return 0.0
    boundaries = _combine_boundaries(values, transitions, transition_seconds)
    return round(sum(values) - sum(boundaries), 3)


def fit_combine_segments(
    sources: list[dict],
    target_duration: float,
    transitions: bool,
    transition_seconds: float = DEFAULT_TRANSITION_SECONDS,
) -> list[dict]:
    """Trim ordered whole sources so the final timeline fits a target duration.

    Every source stays in user order and gets a positive slice, proportional to
    its original duration. Crossfade overlap is included in the calculation, so
    the final MP4 (after any terminal trim in ``render_combine``) lands on the
    requested timeframe. No source is dropped, stretched or reordered.
    """
    try:
        target = float(target_duration)
    except (TypeError, ValueError):
        raise ValueError("target_duration must be a number")
    if not (MIN_COMBINE_SEGMENT_SECONDS <= target <= MAX_COMBINE_TARGET_SECONDS):
        raise ValueError(
            f"target_duration must be between {MIN_COMBINE_SEGMENT_SECONDS:g} and "
            f"{MAX_COMBINE_TARGET_SECONDS:g} seconds"
        )

    originals: list[float] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"Combine source {index + 1} is invalid")
        duration = float(source.get("duration") or 0)
        if not duration:
            try:
                duration = float(source.get("end", 0)) - float(source.get("start", 0))
            except (TypeError, ValueError):
                duration = 0.0
        if duration < MIN_COMBINE_SEGMENT_SECONDS:
            raise ValueError(
                f"Combine source {index + 1} is shorter than "
                f"{MIN_COMBINE_SEGMENT_SECONDS:g}s and cannot be trimmed"
            )
        originals.append(duration)

    maximum = max_combine_duration(originals, transitions, transition_seconds)
    if target > maximum + 0.05:
        raise ValueError(
            f"Target duration {target:.1f}s exceeds the {maximum:.1f}s available "
            "from the ordered sources; add a longer source or choose a shorter target"
        )

    # Aim a hair above the target so 3-decimal trim rounding can never leave the
    # assembled timeline short. render_combine() trims the final frame exactly.
    aim = min(maximum, target + 0.02)
    low = max(MIN_COMBINE_SEGMENT_SECONDS / d for d in originals)
    high = 1.0

    def length_for(scale: float) -> float:
        chosen = [d * scale for d in originals]
        boundaries = _combine_boundaries(chosen, transitions, transition_seconds)
        return sum(chosen) - sum(boundaries)

    if low > high:
        raise ValueError("Combine sources cannot fit the target duration")
    aim = max(aim, length_for(low))
    for _ in range(50):
        middle = (low + high) / 2
        if length_for(middle) >= aim:
            high = middle
        else:
            low = middle
    scale = min(1.0, high + 1e-5)

    fitted: list[dict] = []
    for source, original in zip(sources, originals):
        duration = round(min(original, original * scale), 3)
        item = dict(source)
        item["start"] = 0.0
        item["end"] = duration
        item["duration"] = duration
        fitted.append(item)
    return fitted


def normalize_combine_segments(
    segments: list[dict],
    probes: list[dict],
    transitions: bool,
    transition_seconds: float = DEFAULT_TRANSITION_SECONDS,
) -> tuple[list[dict], list[float], list[float], float]:
    """Validate source ranges and compute crossfade boundaries and offsets.

    Returns (validated_segments, boundary_durations, xfade_offsets, total).
    Boundary durations and offsets are zero/unused when transitions are off.
    """
    if not segments:
        raise ValueError("Combine needs at least one source video")
    if len(segments) != len(probes):
        raise ValueError("Each combine segment needs a probed source")
    validated: list[dict] = []
    for index, (segment, probe) in enumerate(zip(segments, probes)):
        if not isinstance(segment, dict):
            raise ValueError(f"Combine source {index + 1} is invalid")
        probe = probe or {}
        source_duration = float(probe.get("duration") or 0)
        try:
            start = float(segment.get("start", 0.0) or 0.0)
            end = float(segment.get("end", source_duration or 0.0) or 0.0)
        except (TypeError, ValueError):
            raise ValueError(f"Combine source {index + 1} needs numeric start and end")
        if start < 0:
            raise ValueError(f"Combine source {index + 1} has a negative start")
        if not source_duration:
            raise ValueError(f"Combine source {index + 1} has no readable duration")
        end = min(end, source_duration)
        if end <= start:
            raise ValueError(f"Combine source {index + 1} has an empty range")
        duration = round(end - start, 3)
        if duration < 0.2:
            raise ValueError(f"Combine source {index + 1} is shorter than 0.2s")
        validated.append({
            "index": index,
            "source_id": segment.get("source_id"),
            "name": segment.get("name"),
            "path": str(segment.get("path") or ""),
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": duration,
            # Prefer the displayed dimensions so a rotated source selects the
            # right canvas. Every input is normalised in the graph regardless.
            "width": int(probe.get("display_width") or probe.get("width") or 1280),
            "height": int(probe.get("display_height") or probe.get("height") or 720),
        })

    n = len(validated)
    durations = [s["duration"] for s in validated]
    boundaries = _combine_boundaries(durations, bool(transitions), transition_seconds)
    offsets: list[float] = []
    running = durations[0]
    for i in range(1, n):
        fade = boundaries[i - 1]
        offsets.append(round(running - fade, 3))
        running = round(running + durations[i] - fade, 3)
    return validated, boundaries, offsets, round(running, 3)


def shift_combine_cues(
    source_cues: list[list[dict]] | None,
    segments: list[dict],
    boundaries: list[float],
    offsets: list[float],
    total: float,
) -> list[dict]:
    """Place per-source subtitle cues on the final combined timeline.

    ``offsets[i-1]`` is where source ``i`` starts after earlier crossfades.
    Cues are clipped at the fade midpoint to avoid two overlapping lines. When
    a cue carries word-level detail, words outside the visible span are dropped
    so the displayed text matches the words audible at that point in the
    crossfade (and at the final target-duration trim).
    """
    if not source_cues:
        return []
    cues: list[dict] = []
    # Detect CJK text so word fragments join without spaces (as in the
    # transcript's own language-aware grouping).
    cjk = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
    joiner = "" if any(cjk.search(str(c.get("text") or "")) for part in source_cues for c in (part or [])) else " "
    for index, part in enumerate(source_cues[:len(segments)]):
        segment = segments[index]
        start_offset = 0.0 if index == 0 else float(offsets[index - 1])
        fade_before = float(boundaries[index - 1]) if index > 0 else 0.0
        fade_after = float(boundaries[index]) if index < len(boundaries) else 0.0
        visible_start = max(0.0, start_offset + fade_before / 2)
        visible_end = min(total, start_offset + float(segment["duration"]) - fade_after / 2)
        for cue in part or []:
            try:
                start = start_offset + float(cue.get("start", 0))
                end = start_offset + float(cue.get("end", 0))
            except (TypeError, ValueError):
                continue
            words = cue.get("_words")
            if words:
                kept = []
                for word in words:
                    try:
                        ws = start_offset + float(word["start"])
                        we = start_offset + float(word["end"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    ws, we = max(ws, visible_start), min(we, visible_end)
                    if we > ws + 0.02:
                        kept.append({
                            "start": ws, "end": we,
                            "text": str(word.get("text") or ""),
                        })
                if not kept:
                    continue
                cues.append({
                    "start": round(kept[0]["start"], 3),
                    "end": round(kept[-1]["end"], 3),
                    "text": joiner.join(w["text"] for w in kept),
                })
                continue
            start, end = max(start, visible_start), min(end, visible_end)
            if end > start + 0.001:
                cues.append({
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": str(cue.get("text") or ""),
                })
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    return cues


def build_combine_graph(
    segments: list[dict],
    aspect: str,
    fps: int,
    boundaries: list[float],
    offsets: list[float],
    total: float,
    caption_file: str | None,
    audio: dict,
    has_music: bool,
    music_index: int,
    final_duration: float | None = None,
    output_size: tuple[int, int] | None = None,
) -> str:
    """Build the transition/audio graph for a multi-source combine render.

    ``total`` is the assembled source timeline; ``final_duration`` is the
    optional user target used for the terminal trim and music tail.

    When ``output_size`` is supplied it is the first source's native pixel
    dimensions. Every input is explicitly normalised to that canvas: sources
    already at that size scale 1:1 (pixel-identical), other sizes fit *inside*
    the canvas with padding. Nothing is cropped. Normalising every input is
    essential — probe-reported dimensions can disagree with decoded frame size
    (rotation side data, SAR, stale probe), and xfade/concat require all inputs
    to have exactly the same dimensions. Without ``output_size``, the legacy
    cover-crop-to-preset behaviour is retained.
    """
    tw, th = output_size or ASPECTS.get(aspect, ASPECTS["9:16"])
    native = output_size is not None
    out_duration = float(final_duration) if final_duration is not None else float(total)
    parts: list[str] = []
    for segment in segments:
        i = segment["index"]
        if native:
            # Force *every* input to the canvas. A source whose probe says it
            # already matches may still decode at a different size (rotation
            # metadata, SAR, stale probe); skipping scale would give xfade two
            # differently sized links and fail with "parameters do not match".
            # setsar=1 first makes the 1:1 case a pixel-identical no-op.
            chain = (
                f"setsar=1,scale={tw}:{th}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"fps={fps},setsar=1,settb=AVTB,format=yuv420p"
            )
        else:
            rect = resolve_crop(None, segment["width"], segment["height"], aspect)
            crop_w = _even("iw*%.4f" % rect["w"])
            crop_h = _even("ih*%.4f" % rect["h"])
            chain = (
                f"crop={crop_w}:{crop_h}:"
                f"trunc(iw*{rect['x']:.4f}/2)*2:trunc(ih*{rect['y']:.4f}/2)*2,"
                f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
                f"crop={tw}:{th},fps={fps},setsar=1,settb=AVTB,format=yuv420p"
            )
        parts.append(
            f"[{i}:v]trim=start={segment['start']:.3f}:end={segment['end']:.3f},"
            f"setpts=PTS-STARTPTS,{chain}[v{i}]"
        )
        parts.append(
            f"[{i}:a]atrim=start={segment['start']:.3f}:end={segment['end']:.3f},"
            f"asetpts=PTS-STARTPTS,apad,atrim=0:{segment['duration']:.3f},"
            f"aresample=48000,aformat=channel_layouts=stereo[a{i}]"
        )

    n = len(segments)
    smooth = n > 1 and any(b > 0 for b in boundaries)
    video_label, audio_label = "v0", "a0"
    if smooth:
        for i in range(1, n):
            fade = boundaries[i - 1]
            parts.append(
                f"[{video_label}][v{i}]xfade=transition=fade:duration={fade:.3f}:"
                f"offset={offsets[i - 1]:.3f}[vx{i}]"
            )
            video_label = f"vx{i}"
            parts.append(f"[{audio_label}][a{i}]acrossfade=d={fade:.3f}[ax{i}]")
            audio_label = f"ax{i}"
    elif n > 1:
        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[vcat][acat]")
        video_label, audio_label = "vcat", "acat"

    if caption_file:
        parts.append(f"[{video_label}]subtitles={caption_file}[vcap]")
        video_label = "vcap"
    parts.append(f"[{video_label}]format=yuv420p[v]")

    norm = "loudnorm=I=-16:TP=-1.5:LRA=11," if audio.get("normalize", True) else ""
    if has_music:
        vol = clamp01(audio.get("music_volume", 0.18))
        parts.append(
            f"[{audio_label}]{norm}asplit=2[cn1][cn2];"
            f"[{music_index}:a]volume={vol:.2f},aloop=loop=-1:size=2147483647,"
            f"atrim=0:{max(0.1, out_duration):.3f},"
            f"afade=t=out:st={max(0.0, out_duration - 0.8):.2f}:d=0.8[cmus];"
            f"[cmus][cn2]sidechaincompress=threshold=0.06:ratio=6:attack=15:release=300[duck];"
            f"[cn1][duck]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        parts.append(f"[{audio_label}]{norm.rstrip(',') if norm else 'anull'}[a]")
    return ";".join(parts)


def render_combine(
    sources: list[dict],
    out_path: Path,
    aspect: str = "9:16",
    crop: dict | None = None,
    cues: list[dict] | None = None,
    source_cues: list[list[dict]] | None = None,
    caption_style: dict | None = None,
    audio: dict | None = None,
    fps: int = 30,
    transitions: bool = True,
    transition_seconds: float = DEFAULT_TRANSITION_SECONDS,
    target_duration: float | None = None,
    on_progress: Callable[[int, str], None] | None = None,
    check: Callable[[], None] | None = None,
) -> dict:
    """Combine ordered source ranges into one captioned native-resolution MP4.

    Each entry in ``sources`` is ``{path, start, end, source_id, name}``. With
    ``transitions=True`` adjacent clips are joined by a short crossfade
    (xfade/acrossfade); with ``False`` they are joined by straightforward cuts
    (concat). Both modes produce one auditable MP4.

    The output canvas is the first ordered source's own pixel dimensions: no
    cover crop and no forced 720p/aspect-preset downscale. Sources with a
    different size are scaled to fit inside that canvas and padded, never cut.

    ``target_duration`` is the user-facing timeframe for the final file. The
    assembled source timeline must cover it; the renderer trims the tail to land
    exactly on the target instead of returning the sum of all source lengths.
    """
    probes = [probe_media(Path(item["path"])) for item in sources]
    validated, boundaries, offsets, assembled_duration = normalize_combine_segments(
        sources, probes, bool(transitions), transition_seconds,
    )
    if source_cues and len(source_cues) != len(sources):
        raise ValueError("source_cues must have one cue list per combine source")
    target: float | None = None
    if target_duration is not None:
        try:
            target = float(target_duration)
        except (TypeError, ValueError):
            raise ValueError("target_duration must be a number")
        if not (MIN_COMBINE_SEGMENT_SECONDS <= target <= MAX_COMBINE_TARGET_SECONDS):
            raise ValueError(
                f"target_duration must be between {MIN_COMBINE_SEGMENT_SECONDS:g} and "
                f"{MAX_COMBINE_TARGET_SECONDS:g} seconds"
            )
        if assembled_duration + 0.05 < target:
            raise ValueError(
                f"Target duration {target:.1f}s exceeds the {assembled_duration:.1f}s "
                "assembled from the ordered sources"
            )
    total = round(target if target is not None else assembled_duration, 3)
    aspect = aspect if aspect in ASPECTS else "9:16"
    # Preserve the first source's native canvas. All combine renders (preview,
    # re-render and export) share this path, so the preview matches the file.
    tw = _even_size(int(validated[0]["width"] or 1280))
    th = _even_size(int(validated[0]["height"] or 720))
    source_resolution = f"{tw}x{th}"
    aud = {**DEFAULT_AUDIO, **(audio or {})}
    music = Path(aud["music"]) if aud.get("music") else None
    if music and not music.exists():
        music = None

    combined_cues = cues or shift_combine_cues(source_cues, validated, boundaries, offsets, total)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent
    # Keep captions legible when the native canvas is taller/shorter than the
    # preset size the style was authored for. Cue timing is untouched.
    native_style = _caption_style_for_canvas(caption_style, aspect, th)
    cap_path = caption_file_for(combined_cues, work, native_style, tw, th, name="combine_captions.ass")
    cap_arg = cap_path.name if cap_path else None
    graph = build_combine_graph(
        validated, aspect, fps, boundaries, offsets, assembled_duration,
        cap_arg, aud, bool(music), len(validated), total,
        output_size=(tw, th),
    )

    cmd = [
        settings.ffmpeg, "-hide_banner", "-y", "-nostats", "-progress", "pipe:1",
    ]
    for segment in validated:
        cmd += ["-i", segment["path"]]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    cmd += [
        "-filter_complex", graph,
        "-map", "[v]", "-map", "[a]",
        # Native-resolution combine is re-encoded once, at visually lossless
        # quality so the Final preview keeps the source's fidelity.
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-t", f"{total:.3f}", "-avoid_negative_ts", "make_zero",
    ]

    tmp_out = out_path.with_suffix(".part.mp4")
    cmd.append(str(tmp_out))
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
            match = re.match(r"out_time_ms=(\d+)", line.strip())
            if match and on_progress:
                done = int(match.group(1)) / 1_000_000
                on_progress(min(99, int(100 * done / max(0.1, total))), "Combining source videos")
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    err = (proc.stderr.read() if proc.stderr else "") or ""
    if proc.stdout:
        proc.stdout.close()
    if proc.stderr:
        proc.stderr.close()
    if proc.returncode != 0 or not tmp_out.exists():
        tmp_out.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg combine render failed ({proc.returncode}): {err[-1200:]}")
    tmp_out.replace(out_path)
    if on_progress:
        on_progress(100, "Combined video rendered")

    preview = [item[:200] + "…" if len(item) > 200 else item for item in cmd[:12]]
    return {
        "output": str(out_path),
        "requested_duration": total,
        "target_duration": target,
        "aspect_ratio": aspect,  # kept as the project/preset file key
        "resolution": source_resolution,
        "source_resolution": source_resolution,
        "resolution_mode": "source-native",
        # No reframing happens in native mode: the canvas is the first source's
        # own size, and mismatched sources are padded rather than cropped.
        "crop": None,
        "captions": bool(cap_path),
        "music": str(music) if music else None,
        "command": preview,
        "probe": probe_media(out_path),
        "caption_file": str(cap_path) if cap_path else None,
        "cue_count": len(combined_cues),
        "transition": {
            "enabled": bool(transitions and len(validated) > 1),
            "mode": "fade" if transitions and len(validated) > 1 else "cut",
            "requested_seconds": float(transition_seconds),
            "boundaries": boundaries,
            "offsets": offsets,
        },
        "combine": {
            "source_count": len(validated),
            "sources": [
                {
                    "source_id": s["source_id"], "name": s["name"],
                    "start": s["start"], "end": s["end"], "duration": s["duration"],
                } for s in validated
            ],
            "total_duration": total,
            "source_timeline_duration": assembled_duration,
            "target_duration": target,
        },
    }


def validate_render(result: dict, aspect: str, expected_duration: float) -> dict:
    p = result.get("probe") or {}
    tw, th = ASPECTS.get(aspect, ASPECTS["9:16"])
    # Native-resolution combine renders report their actual output canvas in
    # ``resolution``; prefer it so a 320x180 or 1280x720 combine validates
    # against the file that was really written instead of the preset size.
    declared = str(result.get("resolution") or "")
    if declared and "x" in declared.lower():
        try:
            dw, dh = (int(part) for part in declared.lower().split("x")[:2])
            tw, th = dw, dh
        except ValueError:
            pass
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
