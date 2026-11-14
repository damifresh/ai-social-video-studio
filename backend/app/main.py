from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.projects import router as projects_router
from .api.system import router as system_router
from .benchmark.api import router as benchmark_router
from .core.config import APP_NAME, APP_VERSION, FRONTEND_DIST, PROJECTS_DIR, detect_engines, settings
from .db.database import ensure_schema, recover_interrupted_jobs
from .services.memory import system_snapshot


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_schema()
    interrupted = recover_interrupted_jobs()
    if interrupted:
        print(f"[startup] marked {interrupted} interrupted job(s); artifacts preserved")
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
        "http://localhost:3000",
    ],
    allow_origin_regex=r"^http://127\.0\.0\.1:\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)
app.include_router(system_router)
app.include_router(benchmark_router)


@app.get("/health")
def health():
    ffmpeg_ok = bool(shutil.which(settings.ffmpeg) or Path(settings.ffmpeg).exists())
    engines = detect_engines()
    return {
        "ok": True,
        "service": "local-ai-video-studio",
        "app": APP_NAME,
        "version": APP_VERSION,
        "ffmpeg": settings.ffmpeg,
        "ffmpeg_ok": ffmpeg_ok,
        "say": engines["say"],
        "kokoro": engines["kokoro"],
        "whisper": engines["whisper"],
        "db": settings.db_path,
        "data_dir": settings.data_dir,
        "sequential_jobs": True,
        "memory_percent": system_snapshot().get("percent"),
    }


# Project data (dev convenience; also used by the desktop shell for opening assets)
if Path(PROJECTS_DIR).parent.exists():
    app.mount("/data", StaticFiles(directory=str(Path(PROJECTS_DIR).parent)), name="data")

# Bundled licensed assets (music, sfx, fonts)
_assets_dir = Path(settings.assets_dir)
if _assets_dir.exists():
    app.mount("/media", StaticFiles(directory=str(_assets_dir)), name="media")


# Serve the built web app (production / desktop). API routes are registered above.
_index = Path(FRONTEND_DIST) / "index.html"
if _index.exists():
    _assets = Path(FRONTEND_DIST) / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "health", "data/")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = Path(FRONTEND_DIST) / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_index))
