from __future__ import annotations
import os
from pathlib import Path
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]  # local-ai-video-studio/
BACKEND_DIR = ROOT / "backend"
DATA_DIR = ROOT / "data"
PROJECTS_DIR = DATA_DIR / "projects"
ASSETS_DIR = ROOT / "assets"
MODELS_DIR = ROOT / "models"
DB_PATH = DATA_DIR / "studio.db"


def resolve_ffmpeg() -> str:
    env = os.getenv("FFMPEG_PATH")
    if env and Path(env).exists():
        return env
    # Prefer bundled imageio-ffmpeg binary (portable on this machine)
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return "ffmpeg"


def resolve_ffprobe() -> str:
    env = os.getenv("FFPROBE_PATH")
    if env and Path(env).exists():
        return env
    # imageio-ffmpeg doesn't ship ffprobe; try sibling or PATH
    ff = resolve_ffmpeg()
    cand = Path(ff).with_name("ffprobe")
    if cand.exists():
        return str(cand)
    return "ffprobe"


class Settings(BaseModel):
    ffmpeg: str = resolve_ffmpeg()
    ffprobe: str = resolve_ffprobe()
    db_path: str = str(DB_PATH)
    max_concurrent_jobs: int = 1  # 8GB safety: sequential


settings = Settings()

for p in [DATA_DIR, PROJECTS_DIR, ASSETS_DIR, MODELS_DIR]:
    p.mkdir(parents=True, exist_ok=True)
