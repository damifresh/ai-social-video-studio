from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

from pydantic import BaseModel

APP_NAME = "AI Social Video Studio"
APP_VERSION = "1.0.0"

ROOT = Path(__file__).resolve().parents[3]  # local-ai-video-studio/ (dev) or app resources root


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if raw:
        return Path(raw).expanduser().resolve()
    return default


DATA_DIR = _env_path("LAVS_DATA_DIR", ROOT / "data")
PROJECTS_DIR = DATA_DIR / "projects"
DB_PATH = DATA_DIR / "studio.db"
ASSETS_DIR = _env_path("LAVS_ASSETS_DIR", ROOT / "assets")
MODELS_DIR = _env_path("LAVS_MODELS_DIR", ROOT / "models")
FRONTEND_DIST = _env_path("LAVS_FRONTEND_DIST", ROOT / "frontend" / "dist")

MUSIC_DIR = ASSETS_DIR / "music"
SFX_DIR = ASSETS_DIR / "sfx"
FONTS_DIR = ASSETS_DIR / "fonts"


def resolve_ffmpeg() -> str:
    env = os.getenv("FFMPEG_PATH")
    if env and Path(env).exists():
        return env
    bundled = MODELS_DIR.parent / "bin" / "ffmpeg"
    if bundled.exists():
        return str(bundled)
    try:
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).exists():
            return path
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    return found or "ffmpeg"


def resolve_ffprobe() -> str:
    env = os.getenv("FFPROBE_PATH")
    if env and Path(env).exists():
        return env
    ff = resolve_ffmpeg()
    cand = Path(ff).with_name("ffprobe")
    if cand.exists():
        return str(cand)
    found = shutil.which("ffprobe")
    return found or "ffprobe"


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def resolve_whisper_bin() -> str | None:
    env = os.getenv("WHISPER_BIN")
    candidates = [
        env,
        str(MODELS_DIR / "whisper.cpp" / "build" / "bin" / "whisper-cli"),
        str(MODELS_DIR / "whisper.cpp" / "build" / "bin" / "main"),
        shutil.which("whisper-cli"),
        shutil.which("whisper-cpp"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def resolve_whisper_model() -> str | None:
    env = os.getenv("WHISPER_MODEL")
    if env and Path(env).exists():
        return env
    search = [MODELS_DIR / "whisper.cpp" / "models", MODELS_DIR / "whisper"]
    for d in search:
        if d.exists():
            for name in ("ggml-base.en.bin", "ggml-base.bin", "ggml-small.bin", "ggml-tiny.en.bin", "ggml-tiny.bin"):
                p = d / name
                if p.exists():
                    return str(p)
            files = sorted(d.glob("ggml-*.bin"))
            if files:
                return str(files[0])
    return None


def detect_engines() -> dict:
    whisper_bin = resolve_whisper_bin()
    whisper_model = resolve_whisper_model()
    kokoro = _module_available("kokoro_mlx") or _module_available("mlx_audio")
    return {
        "say": bool(shutil.which("say")),
        "kokoro": kokoro,
        "kokoro_hint": None if kokoro else "Install kokoro-mlx or mlx-audio in a Python 3.10-3.12 environment",
        "whisper": bool(whisper_bin and whisper_model),
        "whisper_bin": whisper_bin,
        "whisper_model": Path(whisper_model).name if whisper_model else None,
        "ffmpeg": Path(resolve_ffmpeg()).name,
        "diffusion_video": False,
    }


class Settings(BaseModel):
    ffmpeg: str = resolve_ffmpeg()
    ffprobe: str = resolve_ffprobe()
    db_path: str = str(DB_PATH)
    data_dir: str = str(DATA_DIR)
    projects_dir: str = str(PROJECTS_DIR)
    assets_dir: str = str(ASSETS_DIR)
    models_dir: str = str(MODELS_DIR)
    frontend_dist: str = str(FRONTEND_DIST)
    max_concurrent_jobs: int = 1  # 8GB safety: sequential


settings = Settings()

for p in [DATA_DIR, PROJECTS_DIR, ASSETS_DIR, MODELS_DIR, MUSIC_DIR, SFX_DIR, FONTS_DIR]:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
