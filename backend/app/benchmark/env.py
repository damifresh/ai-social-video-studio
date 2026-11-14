from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.config import APP_VERSION, detect_engines, settings


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        return out.strip()
    except Exception:
        return ""


def git_info(repo_root: Path) -> dict[str, Any]:
    commit = _run(["git", "-C", str(repo_root), "rev-parse", "HEAD"])
    short = _run(["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"])
    date = _run(["git", "-C", str(repo_root), "log", "-1", "--format=%cI"])
    dirty = bool(_run(["git", "-C", str(repo_root), "status", "--porcelain"]))
    return {"commit": commit or None, "short": short or None, "date": date or None, "dirty": dirty}


def ffmpeg_version(ffmpeg_path: str) -> str:
    out = _run([ffmpeg_path, "-version"])
    return (out.splitlines() or [""])[0]


def ffprobe_version(ffprobe_path: str) -> str:
    out = _run([ffprobe_path, "-version"])
    return (out.splitlines() or [""])[0]


def hardware_info() -> dict[str, Any]:
    mem_bytes = 0
    try:
        mem_bytes = int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except Exception:
        pass
    brand = _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor()
    cpu_count = os.cpu_count()
    return {
        "processor": brand or platform.machine(),
        "machine": platform.machine(),
        "cpu_logical": cpu_count,
        "memory_bytes": mem_bytes,
        "memory_gb": round(mem_bytes / (1024**3), 2) if mem_bytes else None,
    }


def software_info(repo_root: Path) -> dict[str, Any]:
    engines = detect_engines()
    try:
        import imageio_ffmpeg  # type: ignore

        ioff_ver = getattr(imageio_ffmpeg, "__version__", None)
    except Exception:
        ioff_ver = None
    return {
        "app_version": APP_VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "macos_version": platform.mac_ver()[0],
        "sw_vers": _run(["sw_vers"]),
        "ffmpeg_path": settings.ffmpeg,
        "ffprobe_path": settings.ffprobe,
        "ffmpeg_version": ffmpeg_version(settings.ffmpeg),
        "ffprobe_version": ffprobe_version(settings.ffprobe),
        "imageio_ffmpeg": ioff_ver,
        "engines": engines,
        "git": git_info(repo_root),
    }


def disk_info(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(str(path))
        return {
            "total_gb": round(usage.total / 1024**3, 2),
            "free_gb": round(usage.free / 1024**3, 2),
            "used_gb": round((usage.total - usage.free) / 1024**3, 2),
        }
    except Exception:
        return {}


def capture_environment(repo_root: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    env = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "hardware": hardware_info(),
        "software": software_info(repo_root),
        "disk": disk_info(Path(settings.data_dir)),
        "config": {
            "sequential_jobs": True,
            "target_resolution": "720p",
            "data_dir": settings.data_dir,
            "models_dir": settings.models_dir,
            "assets_dir": settings.assets_dir,
            "ffmpeg": settings.ffmpeg,
        },
        "background_workload_note": "Not automatically isolated; record manually if other heavy apps are running.",
    }
    if extra:
        env.update(extra)
    return env
