from __future__ import annotations
import subprocess, json, math, shlex
from pathlib import Path
from ..core.config import settings

ASPECT_RES = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (720, 720),
}

def run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({p.returncode}): {' '.join(cmd[:6])}...\n{p.stderr[-2000:]}")
    return p

def render_scene_segment(image_path: Path, duration: float, out_path: Path, aspect: str = "16:9", motion: str = "slow_zoom_in", fps: int = 30) -> Path:
    W,H = ASPECT_RES.get(aspect, (1280,720))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(duration * fps))
    # zoompan expressions (gentle, deterministic-ish)
    if motion == "slow_zoom_out":
        z = f"if(lte(zoom,1.0),1.08,max(1.001,zoom-0.0008))"
        x = "iw/2-(iw/zoom/2)"; y = "ih/2-(ih/zoom/2)"
    elif motion == "slow_pan_right":
        z = "1.08"; x = f"min(iw-iw/zoom,(iw-iw/zoom)*on/{frames})"; y = "ih/2-(ih/zoom/2)"
    elif motion == "slow_pan_left":
        z = "1.08"; x = f"max(0,(iw-iw/zoom)*(1-on/{frames}))"; y = "ih/2-(ih/zoom/2)"
    else: # slow_zoom_in
        z = f"min(zoom+0.0008,1.15)"
        x = "iw/2-(iw/zoom/2)"; y = "ih/2-(ih/zoom/2)"
    vf = (
        f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={fps},format=yuv420p"
    )
    cmd = [
        settings.ffmpeg, "-y", "-loop", "1", "-i", str(image_path),
        "-vf", vf, "-t", f"{duration:.3f}", "-r", str(fps),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        str(out_path)
    ]
    run(cmd, timeout=900)
    return out_path

def concat_segments(segment_paths: list[Path], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if len(segment_paths) == 1:
        import shutil; shutil.copyfile(segment_paths[0], out_path); return out_path
    lst = out_path.with_suffix('.concat.txt')
    lst.write_text("\n".join([f"file '{p.as_posix()}'" for p in segment_paths]), encoding='utf-8')
    cmd = [settings.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out_path)]
    try:
        run(cmd, timeout=900)
    except Exception:
        # fallback re-encode concat
        cmd = [settings.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", str(out_path)]
        run(cmd, timeout=1200)
    try: lst.unlink()
    except Exception: pass
    return out_path

def mux_final(video_path: Path, audio_path: Path, out_path: Path, srt_path: Path | None = None, burn_subs: bool = False) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if burn_subs and srt_path and srt_path.exists():
        # burn subtitles (requires libass in ffmpeg build; if fails, fallback to soft/no subs mux)
        esc = srt_path.as_posix().replace(':', r'\:')
        vf = f"subtitles='{esc}'"
        cmd = [settings.ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path),
               "-vf", vf, "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k",
               "-shortest", str(out_path)]
        try:
            run(cmd, timeout=1200)
            return out_path
        except Exception:
            pass
    # mux without burn-in (SRT delivered as sidecar)
    cmd = [settings.ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path),
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)]
    try:
        run(cmd, timeout=600)
    except Exception:
        cmd = [settings.ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path),
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)]
        run(cmd, timeout=1200)
    return out_path

def probe_duration(path: Path) -> float:
    try:
        p = subprocess.run([settings.ffmpeg, "-i", str(path)], capture_output=True, text=True, timeout=30)
        import re
        m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
        if m:
            h, mi, s = m.groups(); return int(h)*3600 + int(mi)*60 + float(s)
    except Exception: pass
    return 0.0
