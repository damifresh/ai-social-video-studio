from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.config import APP_NAME, APP_VERSION, MUSIC_DIR, SFX_DIR, detect_engines, settings
from ..db import Job, Project, get_db
from ..services import project_store as ps
from ..services.memory import system_snapshot
from ..services.render import probe_video_info

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/system")
def system_info(db: Session = Depends(get_db)):
    projects = db.query(Project).count()
    completed = db.query(Project).filter(Project.status == "completed").count()
    running = db.query(Job).filter(Job.status == "running").first()
    data_dir = Path(settings.data_dir)
    try:
        usage = shutil.disk_usage(str(data_dir))
        disk = {
            "total_gb": round(usage.total / 1024**3, 1),
            "free_gb": round(usage.free / 1024**3, 1),
            "used_gb": round((usage.total - usage.free) / 1024**3, 1),
        }
    except Exception:
        disk = {}
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "data_dir": settings.data_dir,
        "projects_dir": settings.projects_dir,
        "assets_dir": settings.assets_dir,
        "models_dir": settings.models_dir,
        "db_path": settings.db_path,
        "ffmpeg": settings.ffmpeg,
        "engines": detect_engines(),
        "memory": system_snapshot(),
        "disk": disk,
        "projects": {"total": projects, "completed": completed},
        "running_job": running.id if running else None,
        "sequential": True,
    }


@router.post("/system/cleanup")
def cleanup_temp():
    """Remove regenerable temporary artifacts (concat lists, previews) but never project sources."""
    removed = 0
    freed = 0
    for p in Path(settings.projects_dir).glob("*"):
        if not p.is_dir():
            continue
        for pattern in ("video/*.concat.txt", "video/tmp/*", "logs/*.log.tmp"):
            for f in p.glob(pattern):
                try:
                    freed += f.stat().st_size
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
    previews = Path(settings.data_dir) / "previews"
    if previews.exists():
        for f in previews.glob("*.wav"):
            try:
                freed += f.stat().st_size
                f.unlink()
                removed += 1
            except Exception:
                pass
    return {"ok": True, "removed": removed, "freed_mb": round(freed / 1048576, 2)}


@router.get("/library")
def library(kind: str | None = None, project_id: str | None = None, db: Session = Depends(get_db)):
    """Aggregate media across projects plus the bundled music/SFX library."""
    sub_map = {
        "images": "image",
        "audio": "audio",
        "assets": "audio",
        "video/scenes": "video",
        "renders": "video",
        "subs": "subtitle",
    }
    items: list[dict] = []
    query = db.query(Project).order_by(Project.updated_at.desc())
    if project_id:
        query = query.filter(Project.id == project_id)
    for p in query.limit(60).all():
        d = ps.project_dir(p.id)
        for sub, k in sub_map.items():
            base = d / sub
            if not base.exists():
                continue
            for f in sorted(base.rglob("*")):
                if not f.is_file() or f.name.startswith("."):
                    continue
                if kind and k != kind:
                    continue
                rel = f.relative_to(d).as_posix()
                items.append({
                    "kind": k,
                    "name": f.name,
                    "rel": rel,
                    "size": f.stat().st_size,
                    "url": f"/api/projects/{p.id}/asset/{rel}",
                    "project_id": p.id,
                    "project_title": p.title,
                    "aspect_ratio": p.aspect_ratio,
                })
    bundled: list[dict] = []
    for base, k in ((MUSIC_DIR, "music"), (SFX_DIR, "sfx")):
        if not base.exists():
            continue
        for f in sorted(base.glob("*")):
            if not f.is_file() or f.suffix.lower() not in (".mp3", ".wav", ".m4a", ".aiff", ".ogg"):
                continue
            if kind and kind != k:
                continue
            bundled.append({
                "kind": k,
                "name": f.name,
                "size": f.stat().st_size,
                "url": f"/media/{k}/{f.name}",
                "project_id": None,
                "project_title": "Bundled library",
            })
    return {"items": items, "bundled": bundled, "count": len(items) + len(bundled)}


@router.get("/projects/{pid}/result-info")
def result_info(pid: str, db: Session = Depends(get_db)):
    project = db.get(Project, pid)
    if not project:
        from fastapi import HTTPException

        raise HTTPException(404, "Project not found")
    d = ps.project_dir(pid)
    result = ps.read_json(d / "result.json") or {}
    video = Path(result.get("final_video") or "")
    info = probe_video_info(video) if video.exists() else {}
    return {"result": result, "probe": info, "exists": video.exists()}
