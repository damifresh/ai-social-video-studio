from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .db.database import Base, engine
from .api.projects import router as projects_router
from .core.config import settings, PROJECTS_DIR

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Local AI Social Video Studio", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)

# serve project data files (dev convenience)
try:
    app.mount("/data", StaticFiles(directory=str(PROJECTS_DIR.parent)), name="data")
except Exception:
    pass

@app.get("/health")
def health():
    import shutil
    return {
        "ok": True,
        "service": "local-ai-video-studio",
        "ffmpeg": settings.ffmpeg,
        "ffmpeg_ok": bool(shutil.which(settings.ffmpeg) or __import__('pathlib').Path(settings.ffmpeg).exists()),
        "db": settings.db_path,
        "sequential_jobs": True,
    }
