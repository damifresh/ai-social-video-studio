from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from ..db import get_db, Project, Job
from ..services import project_store as ps
from ..services.pipeline import run_full_pipeline, run_scene_regen
from ..services.script_engine import generate_script, regenerate_scene
from ..services.tts import list_voices
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

router = APIRouter(prefix="/api", tags=["api"])

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

@router.get("/voices")
def voices():
    return {"voices": list_voices()}

@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    items = db.query(Project).order_by(Project.updated_at.desc()).all()
    return {"projects": [proj_to_dict(p) for p in items]}

@router.post("/projects")
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(**body.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    ps.project_dir(p.id)
    return {"project": proj_to_dict(p)}

@router.get("/projects/{pid}")
def get_project(pid: str, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    script = ps.load_script(pid)
    scenes = ps.load_storyboard(pid)
    result = ps.read_json(ps.project_dir(pid)/"result.json")
    return {"project": proj_to_dict(p), "script": script, "scenes": scenes, "result": result}

@router.patch("/projects/{pid}")
def update_project(pid: str, body: ProjectUpdate, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    for k,v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    p.updated_at = datetime.utcnow()
    db.commit(); db.refresh(p)
    return {"project": proj_to_dict(p)}

@router.delete("/projects/{pid}")
def delete_project(pid: str, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    db.delete(p); db.commit()
    # keep files? safer to keep; user can clean manually. But allow optional cleanup later.
    return {"ok": True}

@router.post("/projects/{pid}/duplicate")
def duplicate_project(pid: str, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    data = {c.name: getattr(p,c.name) for c in Project.__table__.columns if c.name not in ("id","created_at","updated_at")}
    data["title"] = (p.title or "Untitled") + " (Copy)"
    data["status"] = "draft"
    n = Project(**data)
    db.add(n); db.commit(); db.refresh(n)
    # copy json artifacts if exist
    import shutil
    src = ps.project_dir(pid); dst = ps.project_dir(n.id)
    for name in ["script.json","script.md","scenes.json","timings.json"]:
        s = src/name
        if s.exists(): shutil.copy2(s, dst/name)
    return {"project": proj_to_dict(n)}

@router.post("/projects/{pid}/generate-script")
def generate_script_only(pid: str, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    script = generate_script(p.topic, p.prompt, p.title, p.duration_min, p.style, p.language)
    ps.save_script(pid, script)
    ps.save_storyboard(pid, script.get("scenes", []))
    return {"script": script, "scenes": script.get("scenes", [])}

@router.put("/projects/{pid}/script")
def save_script(pid: str, body: dict, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    ps.save_script(pid, body)
    if "scenes" in body: ps.save_storyboard(pid, body["scenes"])
    return {"ok": True}

@router.put("/projects/{pid}/scenes")
def save_scenes(pid: str, body: dict, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    scenes = body.get("scenes", body) if isinstance(body, dict) else body
    ps.save_storyboard(pid, scenes)
    return {"ok": True, "count": len(scenes)}

@router.post("/projects/{pid}/scenes/{idx}/regenerate")
def regen_scene(pid: str, idx: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    job = Job(project_id=pid, type="scene", stage="queued", status="queued", progress=0, message="Queued scene regeneration")
    db.add(job); db.commit(); db.refresh(job)
    background.add_task(run_scene_regen, pid, idx, job.id)
    return {"job": job_to_dict(job)}

@router.post("/projects/{pid}/generate")
def generate_full(pid: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p: raise HTTPException(404, "Project not found")
    # sequential safety: reject if running
    running = db.query(Job).filter(Job.status=="running").first()
    if running:
        raise HTTPException(409, "Another job is running. Sequential execution required on 8GB.")
    job = Job(project_id=pid, type="full", stage="queued", status="queued", progress=0, message="Queued")
    p.status = "generating"
    db.add(job); db.commit(); db.refresh(job)
    background.add_task(run_full_pipeline, job.id)
    return {"job": job_to_dict(job)}

@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j: raise HTTPException(404, "Job not found")
    return {"job": job_to_dict(j)}

@router.get("/projects/{pid}/jobs")
def project_jobs(pid: str, db: Session = Depends(get_db)):
    items = db.query(Job).filter(Job.project_id==pid).order_by(Job.created_at.desc()).all()
    return {"jobs": [job_to_dict(j) for j in items]}

@router.get("/projects/{pid}/files/{kind}")
def project_file(pid: str, kind: str):
    # serve key files (video, srt, vtt) - simple implementation
    from fastapi.responses import FileResponse
    d = ps.project_dir(pid)
    mapping = {
        "video": d/"renders"/f"final_16x9_720p.mp4", # will resolve dynamically below
        "srt": d/"subs"/"subtitles.srt",
        "vtt": d/"subs"/"subtitles.vtt",
        "result": d/"result.json",
    }
    if kind == "video":
        r = ps.read_json(d/"result.json") or {}
        fp = r.get("final_video")
        if fp and __import__('pathlib').Path(fp).exists(): return FileResponse(fp, media_type="video/mp4", filename=__import__('pathlib').Path(fp).name)
        # search renders
        renders = list((d/"renders").glob("*.mp4"))
        if renders: return FileResponse(str(renders[-1]), media_type="video/mp4", filename=renders[-1].name)
        raise HTTPException(404, "Video not found")
    path = mapping.get(kind)
    if not path or not path.exists(): raise HTTPException(404, "Not found")
    mt = "application/json" if kind=="result" else "text/plain"
    return FileResponse(str(path), media_type=mt)

def proj_to_dict(p: Project):
    return {c.name: getattr(p,c.name) for c in Project.__table__.columns}

def job_to_dict(j: Job):
    d = {c.name: getattr(j,c.name) for c in Job.__table__.columns}
    return d
