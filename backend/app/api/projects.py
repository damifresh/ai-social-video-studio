from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.config import MUSIC_DIR, SFX_DIR, settings
from ..db import Job, Project, get_db
from ..services import project_store as ps
from ..services.pipeline import (
    load_subtitle_segments,
    run_full_pipeline,
    run_rerender,
    run_scene_regen,
)
from ..services.render import probe_video_info
from ..services.script_engine import generate_script
from ..services.subtitles import DEFAULT_STYLE, write_subtitles
from ..services.tts import list_voices, preview

router = APIRouter(prefix="/api", tags=["api"])

SUBTITLE_DEFAULT = DEFAULT_STYLE


def _u(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def proj_to_dict(p: Project) -> dict:
    try:
        style = json.loads(p.subtitle_style or "{}")
    except Exception:
        style = {}
    return {
        "id": p.id,
        "title": p.title,
        "topic": p.topic,
        "prompt": p.prompt,
        "duration_min": p.duration_min,
        "aspect_ratio": p.aspect_ratio,
        "resolution": p.resolution,
        "style": p.style,
        "language": p.language,
        "voice": p.voice,
        "subtitle_enabled": p.subtitle_enabled,
        "music_track": p.music_track,
        "status": p.status,
        "fps": p.fps,
        "burn_subs": p.burn_subs,
        "subtitle_style": {**SUBTITLE_DEFAULT, **style},
        "music_volume": p.music_volume,
        "voice_speed": p.voice_speed,
        "auto_mode": p.auto_mode,
        "thumbnail": p.thumbnail,
        "created_at": _u(p.created_at),
        "updated_at": _u(p.updated_at),
    }


def job_to_dict(j: Job) -> dict:
    elapsed = None
    eta = None
    if j.started_at:
        end = j.finished_at or datetime.utcnow()
        elapsed = max(0.0, (end - j.started_at).total_seconds())
        if j.status == "running" and 2 < (j.progress or 0) < 100 and elapsed > 1:
            eta = round(elapsed * (100 - (j.progress or 0)) / max(1, (j.progress or 0)), 1)
    return {
        "id": j.id,
        "project_id": j.project_id,
        "type": j.type,
        "stage": j.stage,
        "status": j.status,
        "progress": j.progress,
        "message": j.message,
        "error": j.error,
        "meta": j.meta,
        "peak_memory_mb": j.peak_memory_mb,
        "canceled": j.canceled,
        "elapsed_sec": round(elapsed, 1) if elapsed is not None else None,
        "eta_sec": eta,
        "created_at": _u(j.created_at),
        "updated_at": _u(j.updated_at),
        "started_at": _u(j.started_at),
        "finished_at": _u(j.finished_at),
    }


class ProjectCreate(BaseModel):
    title: str = "Untitled"
    topic: str = ""
    prompt: str = ""
    duration_min: int = 1
    aspect_ratio: str = "16:9"
    style: str = "cinematic"
    language: str = "en"
    voice: str = "say:Samantha"
    subtitle_enabled: bool = True
    music_track: str = "none"
    fps: int = 30
    burn_subs: bool = True
    subtitle_style: Optional[dict] = None
    music_volume: float = 0.10
    voice_speed: int = 0
    auto_mode: bool = False


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    topic: Optional[str] = None
    prompt: Optional[str] = None
    duration_min: Optional[int] = None
    aspect_ratio: Optional[str] = None
    style: Optional[str] = None
    language: Optional[str] = None
    voice: Optional[str] = None
    subtitle_enabled: Optional[bool] = None
    music_track: Optional[str] = None
    status: Optional[str] = None
    fps: Optional[int] = None
    burn_subs: Optional[bool] = None
    subtitle_style: Optional[dict] = None
    music_volume: Optional[float] = None
    voice_speed: Optional[int] = None
    auto_mode: Optional[bool] = None


class ReorderBody(BaseModel):
    order: list[int]


class SubtitlesBody(BaseModel):
    segments: list[dict]
    style: Optional[dict] = None


class VoicePreviewBody(BaseModel):
    voice: str = "say:Samantha"
    text: Optional[str] = None


def _apply_updates(p: Project, body: ProjectUpdate) -> None:
    data = body.model_dump(exclude_unset=True)
    if "subtitle_style" in data and isinstance(data["subtitle_style"], dict):
        data["subtitle_style"] = json.dumps(data["subtitle_style"])
    for k, v in data.items():
        setattr(p, k, v)
    p.updated_at = datetime.utcnow()


def _require_project(db: Session, pid: str) -> Project:
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _running_job(db: Session) -> Job | None:
    return db.query(Job).filter(Job.status.in_(["running", "queued"])).first()


def _enqueue(db: Session, project: Project, job_type: str, message: str) -> Job:
    running = _running_job(db)
    if running:
        raise HTTPException(
            409,
            f"Another job is already {running.status} ({running.stage}). "
            "Sequential execution is required on 8 GB unified memory.",
        )
    job = Job(project_id=project.id, type=job_type, stage="queued", status="queued", progress=0, message=message)
    if job_type == "full":
        project.status = "generating"
    project.updated_at = datetime.utcnow()
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/voices")
def voices():
    return {"voices": list_voices()}


@router.post("/voices/preview")
def voice_preview(body: VoicePreviewBody):
    try:
        path = preview(body.voice, body.text)
        if not path.exists():
            raise RuntimeError("preview was not created")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Voice preview failed: {e}") from e
    return FileResponse(str(path), media_type="audio/wav", filename=path.name)


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    items = db.query(Project).order_by(Project.updated_at.desc()).all()
    out = []
    for p in items:
        d = proj_to_dict(p)
        result = ps.read_json(ps.project_dir(p.id) / "result.json")
        d["duration_sec"] = (result or {}).get("duration_sec")
        out.append(d)
    return {"projects": out}


@router.post("/projects")
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    data = body.model_dump()
    style = data.pop("subtitle_style", None)
    p = Project(**data)
    if style:
        p.subtitle_style = json.dumps(style)
    db.add(p)
    db.commit()
    db.refresh(p)
    ps.project_dir(p.id)
    return {"project": proj_to_dict(p)}


@router.get("/projects/{pid}")
def get_project(pid: str, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    script = ps.load_script(pid)
    scenes = ps.load_storyboard(pid)
    result = ps.read_json(ps.project_dir(pid) / "result.json")
    timings = ps.read_json(ps.project_dir(pid) / "timings.json", {})
    subs = load_subtitle_segments(pid)
    history = ps.read_json(ps.project_dir(pid) / "renders" / "history.json", []) or []
    return {
        "project": proj_to_dict(p),
        "script": script,
        "scenes": scenes,
        "result": result,
        "timings": timings,
        "subtitles": subs,
        "history": history,
    }


@router.patch("/projects/{pid}")
def update_project(pid: str, body: ProjectUpdate, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    _apply_updates(p, body)
    db.commit()
    db.refresh(p)
    return {"project": proj_to_dict(p)}


@router.delete("/projects/{pid}")
def delete_project(pid: str, delete_files: bool = False, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    db.delete(p)
    db.commit()
    if delete_files:
        shutil.rmtree(ps.project_dir(pid), ignore_errors=True)
    return {"ok": True, "deleted_files": delete_files}


@router.post("/projects/{pid}/duplicate")
def duplicate_project(pid: str, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    data = {c.name: getattr(p, c.name) for c in Project.__table__.columns if c.name not in ("id", "created_at", "updated_at")}
    data["title"] = (p.title or "Untitled") + " (Copy)"
    data["status"] = "draft"
    data["thumbnail"] = ""
    n = Project(**data)
    db.add(n)
    db.commit()
    db.refresh(n)
    src, dst = ps.project_dir(pid), ps.project_dir(n.id)
    for name in ("script.json", "script.md", "scenes.json", "timings.json"):
        s = src / name
        if s.exists():
            shutil.copy2(s, dst / name)
    for sub in ("images", "audio", "subs"):
        if (src / sub).exists():
            shutil.copytree(src / sub, dst / sub, dirs_exist_ok=True)
    return {"project": proj_to_dict(n)}


@router.post("/projects/{pid}/generate-script")
def generate_script_only(pid: str, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    script = generate_script(p.topic, p.prompt, p.title, p.duration_min, p.style, p.language)
    ps.save_script(pid, script)
    ps.save_storyboard(pid, script.get("scenes", []))
    return {"script": script, "scenes": script.get("scenes", [])}


@router.put("/projects/{pid}/script")
def save_script(pid: str, body: dict, db: Session = Depends(get_db)):
    _require_project(db, pid)
    ps.save_script(pid, body)
    if "scenes" in body:
        ps.save_storyboard(pid, body["scenes"])
    return {"ok": True}


@router.put("/projects/{pid}/scenes")
def save_scenes(pid: str, body: dict, db: Session = Depends(get_db)):
    _require_project(db, pid)
    scenes = body.get("scenes", body) if isinstance(body, dict) else body
    ps.save_storyboard(pid, scenes)
    return {"ok": True, "count": len(scenes)}


@router.post("/projects/{pid}/scenes/reorder")
def reorder_scenes(pid: str, body: ReorderBody, db: Session = Depends(get_db)):
    _require_project(db, pid)
    scenes = ps.load_storyboard(pid)
    order = body.order
    if sorted(order) != list(range(len(scenes))):
        raise HTTPException(400, "order must be a permutation of existing scene indices")
    new_scenes = []
    for new_idx, old_idx in enumerate(order):
        sc = dict(scenes[old_idx])
        sc["index"] = new_idx
        if sc.get("title") and sc["title"].startswith("Scene "):
            sc["title"] = f"Scene {new_idx + 1}"
        new_scenes.append(sc)
    ps.save_storyboard(pid, new_scenes)
    return {"ok": True, "scenes": new_scenes}


@router.post("/projects/{pid}/scenes/{idx}/regenerate")
def regen_scene(pid: str, idx: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    scenes = ps.load_storyboard(pid)
    if idx < 0 or idx >= len(scenes):
        raise HTTPException(400, f"Scene index {idx} out of range")
    job = _enqueue(db, p, "scene", f"Queued scene {idx + 1} regeneration")
    background.add_task(run_scene_regen, pid, idx, job.id)
    return {"job": job_to_dict(job)}


@router.post("/projects/{pid}/scenes/{idx}/image")
async def upload_scene_image(pid: str, idx: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _require_project(db, pid)
    scenes = ps.load_storyboard(pid)
    if idx < 0 or idx >= len(scenes):
        raise HTTPException(400, f"Scene index {idx} out of range")
    suffix = Path(file.filename or "image.png").suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "Image must be PNG, JPG or WEBP")
    d = ps.project_dir(pid) / "images"
    out = d / f"scene_{idx + 1:02d}{suffix}"
    out.write_bytes(await file.read())
    scenes[idx]["image_path"] = str(out)
    scenes[idx]["visual_kind"] = "user_uploaded"
    ps.save_storyboard(pid, scenes)
    return {"ok": True, "image_path": str(out), "scenes": scenes}


@router.get("/projects/{pid}/subtitles")
def get_subtitles(pid: str, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    return {"segments": load_subtitle_segments(pid), "style": proj_to_dict(p)["subtitle_style"]}


@router.put("/projects/{pid}/subtitles")
def put_subtitles(pid: str, body: SubtitlesBody, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    segs = [s for s in body.segments if (s.get("text") or "").strip()]
    for s in segs:
        s["start"] = float(s.get("start", 0))
        s["end"] = max(float(s.get("end", 0)), s["start"] + 0.2)
    style = {**SUBTITLE_DEFAULT, **(body.style or {}), "customized": True}
    p.subtitle_style = json.dumps(style)
    p.updated_at = datetime.utcnow()
    db.commit()
    write_subtitles(segs, ps.project_dir(pid) / "subs", style=style,
                    width=1280 if p.aspect_ratio == "16:9" else 720,
                    height=1280 if p.aspect_ratio == "9:16" else 720)
    return {"ok": True, "count": len(segs), "style": style}


@router.post("/projects/{pid}/generate")
def generate_full(pid: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    job = _enqueue(db, p, "full", "Queued full generation")
    background.add_task(run_full_pipeline, job.id)
    return {"job": job_to_dict(job)}


@router.post("/projects/{pid}/rerender")
def rerender(pid: str, background: BackgroundTasks, burn_subs: bool | None = None, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    job = _enqueue(db, p, "rerender", "Queued re-render")
    background.add_task(run_rerender, pid, job.id, burn_subs)
    return {"job": job_to_dict(job)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return {"job": job_to_dict(j)}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    if j.status not in ("queued", "running"):
        return {"job": job_to_dict(j), "already_finished": True}
    j.canceled = True
    j.message = "Cancellation requested..."
    j.updated_at = datetime.utcnow()
    db.commit()
    return {"job": job_to_dict(j)}


@router.get("/projects/{pid}/jobs")
def project_jobs(pid: str, db: Session = Depends(get_db)):
    _require_project(db, pid)
    items = db.query(Job).filter(Job.project_id == pid).order_by(Job.created_at.desc()).limit(40).all()
    return {"jobs": [job_to_dict(j) for j in items]}


@router.get("/projects/{pid}/timeline")
def timeline(pid: str, db: Session = Depends(get_db)):
    p = _require_project(db, pid)
    return {
        "project": proj_to_dict(p),
        "scenes": ps.load_storyboard(pid),
        "timings": ps.read_json(ps.project_dir(pid) / "timings.json", {}),
        "subtitles": load_subtitle_segments(pid),
        "result": ps.read_json(ps.project_dir(pid) / "result.json"),
    }


@router.get("/projects/{pid}/assets")
def project_assets(pid: str, db: Session = Depends(get_db)):
    _require_project(db, pid)
    d = ps.project_dir(pid)
    out = {"images": [], "audio": [], "other": []}
    for sub in ("images", "audio", "assets/music", "assets/sfx", "video/scenes", "renders", "subs"):
        base = d / sub
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            rel = f.relative_to(d).as_posix()
            item = {"name": f.name, "rel": rel, "size": f.stat().st_size, "url": f"/api/projects/{pid}/asset/{rel}"}
            if sub == "images":
                out["images"].append(item)
            elif sub in ("audio", "assets/music", "assets/sfx"):
                out["audio"].append(item)
            else:
                out["other"].append(item)
    return out


@router.get("/projects/{pid}/asset/{rel:path}")
def project_asset_file(pid: str, rel: str, db: Session = Depends(get_db)):
    _require_project(db, pid)
    d = ps.project_dir(pid).resolve()
    target = (d / rel).resolve()
    if not str(target).startswith(str(d)) or not target.is_file():
        raise HTTPException(404, "Asset not found")
    return FileResponse(str(target))


@router.post("/projects/{pid}/assets/upload")
async def upload_asset(pid: str, kind: str = "images", file: UploadFile = File(...), db: Session = Depends(get_db)):
    _require_project(db, pid)
    if kind not in ("images", "audio", "music", "sfx"):
        raise HTTPException(400, "kind must be images, audio, music or sfx")
    suffix = Path(file.filename or "upload").suffix.lower()
    allowed = {
        "images": (".png", ".jpg", ".jpeg", ".webp"),
        "audio": (".wav", ".mp3", ".m4a", ".aiff", ".ogg"),
        "music": (".wav", ".mp3", ".m4a", ".aiff", ".ogg"),
        "sfx": (".wav", ".mp3", ".m4a", ".aiff", ".ogg"),
    }[kind]
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported file type for {kind}")
    target_dir = ps.project_dir(pid) / ("images" if kind == "images" else "assets" / kind)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or f"upload{suffix}").name
    out = target_dir / safe_name
    out.write_bytes(await file.read())
    return {"ok": True, "path": str(out), "rel": out.relative_to(ps.project_dir(pid)).as_posix()}


@router.get("/projects/{pid}/files/{kind}")
def project_file(pid: str, kind: str, db: Session = Depends(get_db)):
    _require_project(db, pid)
    d = ps.project_dir(pid)
    if kind in ("video", "mp4"):
        r = ps.read_json(d / "result.json") or {}
        fp = Path(r.get("final_video") or "")
        if not fp.exists():
            renders = sorted((d / "renders").glob("*.mp4"))
            fp = renders[-1] if renders else None
        if not fp or not Path(fp).exists():
            raise HTTPException(404, "Video not found")
        return FileResponse(str(fp), media_type="video/mp4", filename=Path(fp).name)
    mapping = {
        "srt": (d / "subs" / "subtitles.srt", "application/x-subrip"),
        "vtt": (d / "subs" / "subtitles.vtt", "text/vtt"),
        "ass": (d / "subs" / "subtitles.ass", "text/plain"),
        "result": (d / "result.json", "application/json"),
        "thumbnail": (d / "images" / "scene_01.png", "image/png"),
        "audio": (d / "audio" / "final_mix.wav", "audio/wav"),
        "narration": (d / "audio" / "narration_full.wav", "audio/wav"),
        "script": (d / "script.json", "application/json"),
        "scenes": (d / "scenes.json", "application/json"),
        "timings": (d / "timings.json", "application/json"),
        "history": (d / "renders" / "history.json", "application/json"),
        "log": (d / "logs" / "pipeline.log", "text/plain"),
    }
    item = mapping.get(kind)
    if not item or not item[0].exists():
        raise HTTPException(404, f"{kind} not found")
    return FileResponse(str(item[0]), media_type=item[1], filename=item[0].name)


@router.get("/music")
def music_library():
    entries = []
    for base, kind in ((MUSIC_DIR, "music"), (SFX_DIR, "sfx")):
        if not base.exists():
            continue
        licenses: dict = {}
        lic_path = base / "licenses.json"
        if lic_path.exists():
            try:
                licenses = json.loads(lic_path.read_text(encoding="utf-8"))
            except Exception:
                licenses = {}
        for f in sorted(base.glob("*")):
            if not f.is_file() or f.suffix.lower() not in (".mp3", ".wav", ".m4a", ".aiff", ".ogg"):
                continue
            meta = licenses.get(f.name, {}) if isinstance(licenses, dict) else {}
            entries.append({
                "name": f.name,
                "kind": kind,
                "size": f.stat().st_size,
                "license": meta.get("license", "User-supplied / verify license"),
                "source": meta.get("source", ""),
            })
    return {"tracks": entries}


@router.get("/exports")
def exports(db: Session = Depends(get_db)):
    items = []
    for p in db.query(Project).order_by(Project.updated_at.desc()).all():
        d = ps.project_dir(p.id)
        history = ps.read_json(d / "renders" / "history.json", []) or []
        result = ps.read_json(d / "result.json") or {}
        renders = sorted((d / "renders").glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not renders and not result:
            continue
        latest = renders[0] if renders else None
        info = probe_video_info(latest) if latest else {}
        items.append({
            "project_id": p.id,
            "title": p.title,
            "aspect_ratio": p.aspect_ratio,
            "status": p.status,
            "updated_at": _u(p.updated_at),
            "video_url": f"/api/projects/{p.id}/files/video" if latest else None,
            "srt_url": f"/api/projects/{p.id}/files/srt" if (d / "subs" / "subtitles.srt").exists() else None,
            "duration_sec": (result or {}).get("duration_sec") or info.get("duration"),
            "size_bytes": info.get("size_bytes") or (result or {}).get("size_bytes"),
            "peak_memory_mb": (result or {}).get("peak_memory_mb"),
            "renders": len(renders),
            "history": history[-5:],
        })
    return {"exports": items}
