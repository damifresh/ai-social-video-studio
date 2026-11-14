from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..core.config import settings

ASPECT_RES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (720, 720),
}


def run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({p.returncode}): {' '.join(cmd[:8])}...\n{p.stderr[-2500:]}")
    return p


def _motion_expr(motion: str, frames: int) -> tuple[str, str, str]:
    if motion == "slow_zoom_out":
        return (f"if(lte(zoom,1.0),1.10,max(1.001,zoom-0.0007))", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)")
    if motion == "slow_pan_right":
        return ("1.08", f"min(iw-iw/zoom,(iw-iw/zoom)*on/{frames})", "ih/2-(ih/zoom/2)")
    if motion == "slow_pan_left":
        return ("1.08", f"max(0,(iw-iw/zoom)*(1-on/{frames}))", "ih/2-(ih/zoom/2)")
    if motion == "pan_up":
        return ("1.08", "iw/2-(iw/zoom/2)", f"max(0,(ih-ih/zoom)*(1-on/{frames}))")
    if motion == "pan_down":
        return ("1.08", "iw/2-(iw/zoom/2)", f"min(ih-ih/zoom,(ih-ih/zoom)*on/{frames})")
    return ("min(zoom+0.0007,1.14)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)")


def _transition_filters(transition: str, duration: float) -> str:
    fade_d = 0.45 if duration > 2 else 0.2
    t = (transition or "").lower()
    if t in ("fade", "fadeblack", "dissolve", "crossfade", "fadeblack"):
        color = "black" if t == "fadeblack" else "black"
        return (
            f",fade=t=in:st=0:d={fade_d},"
            f"fade=t=out:st={max(0.0, duration - fade_d):.3f}:d={fade_d}:color={color}"
        )
    if t in ("slide", "wipe"):
        return f",fade=t=in:st=0:d={fade_d * 0.7}"
    return ""


def render_scene_segment(
    image_path: Path,
    duration: float,
    out_path: Path,
    aspect: str = "16:9",
    motion: str = "slow_zoom_in",
    fps: int = 30,
    transition: str = "",
) -> Path:
    width, height = ASPECT_RES.get(aspect, (1280, 720))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(duration * fps))
    z, x, y = _motion_expr(motion, frames)
    vf = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
        f"format=yuv420p"
        f"{_transition_filters(transition, duration)}"
    )
    cmd = [
        settings.ffmpeg, "-y", "-loop", "1", "-i", str(image_path),
        "-vf", vf, "-t", f"{duration:.3f}", "-r", str(fps),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    run(cmd)
    return out_path


def concat_segments(segment_paths: list[Path], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not segment_paths:
        raise ValueError("no segments to concat")
    if len(segment_paths) == 1:
        shutil.copyfile(segment_paths[0], out_path)
        return out_path
    lst = out_path.with_suffix(".concat.txt")
    lst.write_text("\n".join(f"file '{p.as_posix()}'" for p in segment_paths), encoding="utf-8")
    try:
        subprocess.run(
            [settings.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out_path)],
            check=True, capture_output=True, timeout=1800,
        )
    except Exception:
        run([
            settings.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-an", str(out_path),
        ])
    finally:
        lst.unlink(missing_ok=True)
    return out_path


def mux_final(
    video_path: Path,
    audio_path: Path,
    out_path: Path,
    ass_path: Path | None = None,
    burn_subs: bool = False,
) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    burned = False
    if burn_subs and ass_path and ass_path.exists():
        # Copy to a temp path with no spaces/colons so libass filter escaping is unambiguous.
        tmpdir = Path(tempfile.mkdtemp(prefix="lavs_subs_"))
        safe_ass = tmpdir / "subs.ass"
        shutil.copyfile(ass_path, safe_ass)
        cmd = [
            settings.ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path),
            "-vf", f"ass={safe_ass}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_path),
        ]
        try:
            run(cmd)
            burned = True
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    if not burned:
        cmd = [
            settings.ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_path),
        ]
        try:
            run(cmd)
        except Exception:
            run([
                settings.ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_path),
            ])
    return {"path": str(out_path), "burned_subtitles": burned}


def probe_duration(path: Path) -> float:
    info = probe_video_info(path)
    return float(info.get("duration") or 0.0)


def probe_video_info(path: Path) -> dict:
    if not path or not Path(path).exists():
        return {}
    try:
        p = subprocess.run([settings.ffmpeg, "-i", str(path)], capture_output=True, text=True, timeout=60)
        err = p.stderr
        out: dict = {}
        m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", err)
        if m:
            h, mi, s = m.groups()
            out["duration"] = round(int(h) * 3600 + int(mi) * 60 + float(s), 2)
        v = re.search(r"Video: ([^,]+), ([^,]+), (\d+)x(\d+)", err)
        if v:
            out["video_codec"] = v.group(1).strip()
            out["pix_fmt"] = v.group(2).strip()
            out["width"] = int(v.group(3))
            out["height"] = int(v.group(4))
        a = re.search(r"Audio: ([^,]+), (\d+) Hz", err)
        if a:
            out["audio_codec"] = a.group(1).strip()
            out["sample_rate"] = int(a.group(2))
        fps = re.search(r"(\d+(?:\.\d+)?) fps", err)
        if fps:
            out["fps"] = float(fps.group(1))
        br = re.search(r"bitrate: (\d+) kb/s", err)
        if br:
            out["bitrate_kbps"] = int(br.group(1))
        out["size_bytes"] = Path(path).stat().st_size
        return out
    except Exception:
        return {}
