"""Engine B HTTP API (AI Auto-Clip Studio).

All routes live under ``/api/clip``. Engine A routes are untouched; the only
shared piece is the cross-engine sequential job guard.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.config import MUSIC_DIR, settings
from ..db.database import get_db
from ..db.models import Job as EngineAJob
from . import jobs as clip_jobs
from . import render as clip_render
from . import store, transcribe as clip_transcribe
from .models import ClipCandidate, ClipJob, ClipProject, ClipRender, ClipSource
from .probe import probe_media

router = APIRouter(prefix="/api/clip", tags=["auto-clip"])

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm"}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


# ------------------------------------------------------------------ schemas

class ClipProjectCreate(BaseModel):
    title: str = Field(default="Untitled clip project", max_length=200)
    aspect_ratio: str = "9:16"
    preset: str = "tiktok"
    language: str = "en"


class ClipProjectUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    aspect_ratio: Optional[str] = None
    preset: Optional[str] = None
    language: Optional[str] = None
    settings: Optional[dict] = None


class HighlightsBody(BaseModel):
    durations: list[float] = Field(default_factory=lambda: [30])
    count: int = 5


class ClipPatch(BaseModel):
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    title: Optional[str] = None
    hook: Optional[str] = None
    caption: Optional[str] = None
    selected: Optional[bool] = None
    aspect: Optional[str] = None
    preset: Optional[str] = None
    crop: Optional[dict] = None
    caption_style: Optional[dict] = None
    audio: Optional[dict] = None
    burn_captions: Optional[bool] = None
    fps: Optional[int] = None


class RenderBody(BaseModel):
    aspect: Optional[str] = None
    preset: Optional[str] = None
    crop: Optional[dict] = None
    caption_style: Optional[dict] = None
    audio: Optional[dict] = None
    burn_captions: Optional[bool] = None
    fps: Optional[int] = None


class BatchExportBody(BaseModel):
    candidate_ids: Optional[list[str]] = None
    aspect: Optional[str] = None


class TranscriptImportBody(BaseModel):
    content: str
    filename: str = ""


class TranscriptSegmentsBody(BaseModel):
    segments: list[dict]


# -------------------------------------------------------------- serializers

def proj_dict(p: ClipProject, db: Session) -> dict:
    src = (
        db.query(ClipSource).filter(ClipSource.clip_project_id == p.id)
        .order_by(ClipSource.created_at.desc()).first()
    )
    counts = {
        "clips": db.query(ClipCandidate).filter(ClipCandidate.clip_project_id == p.id).count(),
        "rendered": db.query(ClipRender).join(ClipCandidate).filter(ClipCandidate.clip_project_id == p.id).count(),
    }
    paths = store.clip_paths(p.id)
    transcript = clip_transcribe.load_transcript(paths["analysis"] / "transcript.json")
    return {
        "id": p.id,
        "title": p.title,
        "status": p.status,
        "aspect_ratio": p.aspect_ratio,
        "preset": p.preset,
        "language": p.language,
        "settings": json.loads(p.settings_json or "{}"),
        "error": p.error,
        "created_at": _iso(p.created_at),
        "updated_at": _iso(p.updated_at),
        "source": source_dict(src) if src else None,
        "counts": counts,
        "transcript": {
            "present": bool(transcript),
            "backend": (transcript or {}).get("backend"),
            "timing": (transcript or {}).get("timing"),
            "sentences": len((transcript or {}).get("sentences") or []),
        } if transcript else None,
        "analysis_ready": (paths["analysis"] / "structural.json").exists(),
    }


def source_dict(s: ClipSource) -> dict:
    return {
        "id": s.id,
        "original_name": s.original_name,
        "ext": s.ext,
        "sha256": s.sha256,
        "size_bytes": s.size_bytes,
        "duration_sec": s.duration_sec,
        "width": s.width,
        "height": s.height,
        "fps": s.fps,
        "vcodec": s.vcodec,
        "acodec": s.acodec,
        "audio_streams": s.audio_streams,
        "sample_rate": s.sample_rate,
        "channels": s.channels,
        "probe": s.probe_json,
        "created_at": _iso(s.created_at),
        "url": f"/api/clip/sources/{s.id}/file",
    }


def job_dict(j: ClipJob) -> dict:
    return {
        "id": j.id,
        "clip_project_id": j.clip_project_id,
        "type": j.type,
        "stage": j.stage,
        "status": j.status,
        "progress": j.progress,
        "message": j.message,
        "error": j.error,
        "canceled": j.canceled,
        "peak_memory_mb": j.peak_memory_mb,
        "meta": j.meta,
        "created_at": _iso(j.created_at),
        "started_at": _iso(j.started_at),
        "finished_at": _iso(j.finished_at),
    }


def clip_dict(c: ClipCandidate, db: Session) -> dict:
    renders = db.query(ClipRender).filter(ClipRender.candidate_id == c.id).all()
    try:
        edit = json.loads(c.edit_json or "{}")
    except Exception:
        edit = {}
    return {
        "id": c.id,
        "clip_project_id": c.clip_project_id,
        "start_sec": c.start_sec,
        "end_sec": c.end_sec,
        "duration_sec": c.duration_sec,
        "transcript_text": c.transcript_text,
        "title": c.title,
        "hook": c.hook,
        "category": c.category,
        "score": c.score,
        "score_json": c.score_json,
        "reason": c.reason,
        "selected": c.selected,
        "state": c.state,
        "edit": edit,
        "renders": [
            {
                "id": r.id, "aspect_ratio": r.aspect_ratio, "preset": r.preset,
                "duration_sec": r.duration_sec, "size_bytes": r.size_bytes,
                "state": r.state, "probe": r.probe_json,
                "url": f"/api/clip/clips/{c.id}/file?aspect={r.aspect_ratio}",
            } for r in sorted(renders, key=lambda r: r.created_at)
        ],
    }


# ----------------------------------------------------------------- helpers

def _project(db: Session, cid: str) -> ClipProject:
    p = db.get(ClipProject, cid)
    if not p:
        raise HTTPException(404, "Clip project not found")
    return p


def _candidate(db: Session, cid: str, sid: str) -> ClipCandidate:
    c = db.get(ClipCandidate, sid)
    if not c or c.clip_project_id != cid:
        raise HTTPException(404, "Clip not found")
    return c


def _enqueue(db: Session, project: ClipProject, job_type: str, message: str, meta: dict | None = None,
             background: BackgroundTasks | None = None) -> ClipJob:
    active = clip_jobs.running_heavy_job(db)
    if active:
        raise HTTPException(
            409,
            f"Another job is already {active['status']} (engine {active['engine']}, stage {active['stage']}). "
            "Sequential execution is required on 8 GB unified memory.",
        )
    job = ClipJob(clip_project_id=project.id, type=job_type, stage="queued", status="queued",
                  progress=0, message=message, meta=meta)
    project.status = "analyzing" if job_type in ("analyze", "transcribe", "highlights") else "rendering"
    project.updated_at = datetime.utcnow()
    db.add(job)
    db.commit()
    db.refresh(job)
    if background is not None:
        background.add_task(clip_jobs.run_clip_job, job.id)
    return job


# ---------------------------------------------------------------- endpoints

@router.get("/capabilities")
def capabilities():
    cap = clip_transcribe.capability()
    return {
        "asr": cap,
        "manual_transcript": True,
        "aspects": list(clip_render.ASPECTS.keys()),
        "presets": clip_render.PRESETS,
        "crop_modes": clip_render.crop_presets(),
        "durations": [15, 30, 45, 60, 90],
        "diagnostics": {
            "ffmpeg": settings.ffmpeg,
            "ffprobe_standalone": bool(settings.ffprobe and Path(settings.ffprobe).exists()),
            "note": "Reframing is manual/geometric; no face or subject tracking is implemented.",
        },
    }


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    items = db.query(ClipProject).order_by(ClipProject.updated_at.desc()).all()
    return {"projects": [proj_dict(p, db) for p in items]}


@router.post("/projects")
def create_project(body: ClipProjectCreate, db: Session = Depends(get_db)):
    aspect = body.aspect_ratio if body.aspect_ratio in clip_render.ASPECTS else "9:16"
    p = ClipProject(title=body.title, aspect_ratio=aspect, preset=body.preset,
                    language=body.language, settings_json=json.dumps({"aspect": aspect, "preset": body.preset}))
    db.add(p)
    db.commit()
    db.refresh(p)
    store.clip_dir(p.id)
    return {"project": proj_dict(p, db)}


@router.get("/projects/{cid}")
def get_project(cid: str, db: Session = Depends(get_db)):
    p = _project(db, cid)
    paths = store.clip_paths(cid)
    transcript = clip_transcribe.load_transcript(paths["analysis"] / "transcript.json")
    structural = store.read_json(paths["analysis"] / "structural.json")
    jobs = db.query(ClipJob).filter(ClipJob.clip_project_id == cid).order_by(ClipJob.created_at.desc()).limit(20).all()
    caps = clip_transcribe.capability()
    return {
        "project": proj_dict(p, db),
        "transcript": transcript,
        "analysis": {
            "silence_gaps": len(((structural or {}).get("silence") or {}).get("gaps") or []),
            "scene_cuts": len(((structural or {}).get("scene_cuts") or {}).get("cuts") or []),
            "envelope_windows": len(((structural or {}).get("envelope") or {}).get("windows") or []),
            "created_at": (structural or {}).get("created_at"),
        } if structural else None,
        "capabilities": caps,
        "jobs": [job_dict(j) for j in jobs],
        "clips": [clip_dict(c, db) for c in db.query(ClipCandidate)
                  .filter(ClipCandidate.clip_project_id == cid).order_by(ClipCandidate.start_sec).all()],
        "music": _music_tracks(),
    }


@router.patch("/projects/{cid}")
def update_project(cid: str, body: ClipProjectUpdate, db: Session = Depends(get_db)):
    p = _project(db, cid)
    if body.title is not None:
        p.title = body.title
    if body.aspect_ratio is not None:
        if body.aspect_ratio not in clip_render.ASPECTS:
            raise HTTPException(400, "aspect_ratio must be 9:16, 16:9 or 1:1")
        p.aspect_ratio = body.aspect_ratio
    if body.preset is not None:
        p.preset = body.preset
    if body.language is not None:
        p.language = body.language
    if body.settings is not None:
        p.settings_json = json.dumps(body.settings)
    p.updated_at = datetime.utcnow()
    db.commit()
    return {"project": proj_dict(p, db)}


@router.delete("/projects/{cid}")
def delete_project(cid: str, delete_files: bool = False, db: Session = Depends(get_db)):
    p = _project(db, cid)
    db.delete(p)
    db.commit()
    if delete_files:
        store.remove_project_files(cid)
    return {"ok": True, "files_deleted": delete_files}


@router.post("/projects/{cid}/source")
async def upload_source(
    cid: str,
    file: UploadFile = File(...),
    replace_existing: bool = True,
    db: Session = Depends(get_db),
):
    p = _project(db, cid)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(415, f"Unsupported container {suffix or '(none)'}; allowed: MP4, MOV, MKV, WebM")

    paths = store.clip_paths(cid)
    existing = db.query(ClipSource).filter(ClipSource.clip_project_id == cid).count()
    if existing and not replace_existing:
        raise HTTPException(409, "This clip project already has a source video. "
                                 "Pass replace_existing=true to replace it (the previous source, "
                                 "analysis and clips are removed).")
    tmp = paths["tmp"] / f"upload{suffix}"
    digest = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as fh:
            while True:
                chunk = await file.read(settings.clip_chunk_bytes)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.clip_max_upload_bytes:
                    raise HTTPException(413, f"File exceeds {settings.clip_max_upload_bytes / 1024**3:.1f} GB cap")
                digest.update(chunk)
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "Uploaded file is empty")
        info = probe_media(tmp)
        if not info or not info.get("width") or not info.get("duration"):
            raise HTTPException(400, "Could not read video metadata; the file may be corrupt or unsupported")
        dur = float(info.get("duration") or 0)
        if dur > settings.clip_max_duration_sec:
            raise HTTPException(400, f"Source duration {dur:.0f}s exceeds the {settings.clip_max_duration_sec // 60}-minute cap")
        if int(info.get("audio_streams") or 0) == 0:
            raise HTTPException(400, "Source has no audio stream; transcription and timed clips require audio. "
                                     "Add an audio track and re-upload.")
        cleared = _clear_previous_source(db, p, paths) if existing else {"sources": 0, "clips": 0}
        final = paths["source"] / f"{hashlib.sha1((file.filename or 'source').encode()).hexdigest()[:10]}{suffix}"
        tmp.replace(final)
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise HTTPException(500, f"Upload failed: {e}") from e

    src = ClipSource(
        clip_project_id=cid,
        original_name=Path(file.filename or "source").name,
        original_path=str(final),
        ext=suffix,
        sha256=digest.hexdigest(),
        size_bytes=size,
        duration_sec=float(info.get("duration") or 0),
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        fps=float(info.get("fps") or 0),
        vcodec=info.get("video_codec") or "",
        acodec=info.get("audio_codec") or "",
        audio_streams=int(info.get("audio_streams") or 0),
        sample_rate=int(info.get("sample_rate") or 0),
        channels=int(info.get("channels") or 0),
        probe_json=info,
    )
    db.add(src)
    p.status = "draft"
    p.error = None
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(src)
    if cleared["sources"] or cleared["clips"]:
        store.log(cid, f"source replaced: cleared {cleared['sources']} previous source(s), "
                       f"{cleared['clips']} clip candidate(s) and stale analysis artifacts")
    return {"source": source_dict(src), "project": proj_dict(p, db), "replaced": cleared}


@router.get("/sources/{sid}/file")
def source_file(sid: str, db: Session = Depends(get_db)):
    s = db.get(ClipSource, sid)
    if not s:
        raise HTTPException(404, "Source not found")
    fp = Path(s.original_path)
    if not fp.exists():
        raise HTTPException(404, "Source file missing on disk")
    return FileResponse(str(fp), media_type="video/mp4", filename=s.original_name or fp.name)


def _clear_previous_source(db: Session, project: ClipProject, paths: dict) -> dict:
    """Replace semantics: one source per clip project.

    Timings of existing clips refer to the old source, so they are removed
    together with the analysis artifacts. The old media file is deleted from
    disk (the UI states this before uploading a replacement).
    """
    cands = db.query(ClipCandidate).filter(ClipCandidate.clip_project_id == project.id).all()
    for c in cands:
        for f in paths["clips"].glob(f"{c.id}*"):
            f.unlink(missing_ok=True)
        db.delete(c)
    sources = db.query(ClipSource).filter(ClipSource.clip_project_id == project.id).all()
    for s in sources:
        try:
            Path(s.original_path).unlink(missing_ok=True)
        except Exception:
            pass
        db.delete(s)
    db.commit()
    for name in ("structural.json", "transcript.json", "whisper_output.json", "audio16k.wav"):
        (paths["analysis"] / name).unlink(missing_ok=True)
    return {"sources": len(sources), "clips": len(cands)}


@router.get("/projects/{cid}/source/file")
def latest_source_file(cid: str, db: Session = Depends(get_db)):
    _project(db, cid)
    s = db.query(ClipSource).filter(ClipSource.clip_project_id == cid).order_by(ClipSource.created_at.desc()).first()
    if not s:
        raise HTTPException(404, "No source uploaded")
    return FileResponse(s.original_path, filename=s.original_name)


@router.post("/projects/{cid}/analyze")
def analyze(cid: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    p = _project(db, cid)
    if not db.query(ClipSource).filter(ClipSource.clip_project_id == cid).count():
        raise HTTPException(400, "Upload a source video first")
    job = _enqueue(db, p, "analyze", "Queued analysis", background=background)
    return {"job": job_dict(job)}


@router.post("/projects/{cid}/transcribe")
def transcribe(cid: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    p = _project(db, cid)
    cap = clip_transcribe.capability()
    if not cap["available"]:
        raise HTTPException(503, "Local ASR unavailable: " + "; ".join(cap["reasons"]) +
                            ". Use transcript import (SRT/VTT) or install whisper.cpp.")
    if not db.query(ClipSource).filter(ClipSource.clip_project_id == cid).count():
        raise HTTPException(400, "Upload a source video first")
    job = _enqueue(db, p, "transcribe", "Queued transcription", background=background)
    return {"job": job_dict(job)}


@router.get("/projects/{cid}/transcript")
def get_transcript(cid: str, db: Session = Depends(get_db)):
    _project(db, cid)
    paths = store.clip_paths(cid)
    t = clip_transcribe.load_transcript(paths["analysis"] / "transcript.json")
    if not t:
        raise HTTPException(404, "No transcript")
    return {"transcript": t, "capability": clip_transcribe.capability()}


@router.post("/projects/{cid}/transcript/import")
def import_transcript(cid: str, body: TranscriptImportBody, db: Session = Depends(get_db)):
    p = _project(db, cid)
    src = db.query(ClipSource).filter(ClipSource.clip_project_id == cid).order_by(ClipSource.created_at.desc()).first()
    try:
        t = clip_transcribe.import_transcript(body.content, body.filename, duration=float(src.duration_sec if src else 0))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    paths = store.clip_paths(cid)
    clip_transcribe.save_transcript(paths["analysis"] / "transcript.json", t)
    p.status = "ready"
    p.updated_at = datetime.utcnow()
    db.commit()
    return {"transcript": t}


@router.put("/projects/{cid}/transcript")
def update_transcript(cid: str, body: TranscriptSegmentsBody, db: Session = Depends(get_db)):
    _project(db, cid)
    segs = []
    for s in body.segments:
        try:
            start, end = float(s["start"]), float(s["end"])
        except Exception:
            raise HTTPException(400, "Each segment needs numeric start and end")
        text = str(s.get("text") or "").strip()
        if end <= start or not text:
            raise HTTPException(400, "Segments must have text and end > start")
        segs.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    if not segs:
        raise HTTPException(400, "Transcript is empty")
    paths = store.clip_paths(cid)
    old = clip_transcribe.load_transcript(paths["analysis"] / "transcript.json") or {}
    words = clip_transcribe._estimated_words(segs)
    t = {
        "backend": old.get("backend", "manual"),
        "model": old.get("model"),
        "language": old.get("language", "unknown"),
        "timing": "edited",
        "word_timing": "estimated",
        "segments": segs,
        "sentences": clip_transcribe.build_sentences(words),
        "words": words,
        "notes": ["Edited in app; sentence boundaries rebuilt from the edited segments."],
    }
    clip_transcribe.save_transcript(paths["analysis"] / "transcript.json", t)
    return {"transcript": t}


@router.post("/projects/{cid}/highlights")
def generate_highlights(cid: str, body: HighlightsBody, background: BackgroundTasks, db: Session = Depends(get_db)):
    p = _project(db, cid)
    paths = store.clip_paths(cid)
    if not (paths["analysis"] / "transcript.json").exists():
        raise HTTPException(400, "Transcript required before highlight detection")
    durations = [d for d in body.durations if 5 <= d <= 180][:6] or [30]
    count = max(1, min(12, body.count))
    job = _enqueue(db, p, "highlights", "Queued highlight scoring",
                   meta={"durations": durations, "count": count}, background=background)
    return {"job": job_dict(job)}


@router.get("/projects/{cid}/clips")
def list_clips(cid: str, db: Session = Depends(get_db)):
    _project(db, cid)
    clips = db.query(ClipCandidate).filter(ClipCandidate.clip_project_id == cid).order_by(ClipCandidate.start_sec).all()
    return {"clips": [clip_dict(c, db) for c in clips]}


@router.patch("/clips/{sid}")
def patch_clip(sid: str, body: ClipPatch, db: Session = Depends(get_db)):
    c = db.get(ClipCandidate, sid)
    if not c:
        raise HTTPException(404, "Clip not found")
    src = db.query(ClipSource).filter(ClipSource.clip_project_id == c.clip_project_id).order_by(ClipSource.created_at.desc()).first()
    max_dur = float(src.duration_sec) if src else None
    if body.start_sec is not None or body.end_sec is not None:
        start = body.start_sec if body.start_sec is not None else c.start_sec
        end = body.end_sec if body.end_sec is not None else c.end_sec
        if start < 0 or end <= start:
            raise HTTPException(400, "end_sec must be greater than start_sec")
        if max_dur and end > max_dur + 0.05:
            raise HTTPException(400, "Clip extends past the source duration")
        c.start_sec, c.end_sec = round(start, 3), round(end, 3)
        c.duration_sec = round(end - start, 3)
        c.state = "stale"
    if body.title is not None:
        c.title = body.title[:200]
    if body.hook is not None:
        c.hook = body.hook[:400]
    if body.selected is not None:
        c.selected = body.selected

    edit = json.loads(c.edit_json or "{}")
    render_keys = {"aspect", "preset", "crop", "caption_style", "audio", "burn_captions", "fps"}
    changed_render = False
    for key in render_keys:
        val = getattr(body, key)
        if val is not None:
            edit[key] = val
            changed_render = True
    if changed_render:
        if edit.get("aspect") and edit["aspect"] not in clip_render.ASPECTS:
            raise HTTPException(400, "aspect must be 9:16, 16:9 or 1:1")
        c.edit_json = json.dumps(edit)
        c.state = "stale"
    db.commit()
    return {"clip": clip_dict(c, db)}


@router.delete("/clips/{sid}")
def delete_clip(sid: str, db: Session = Depends(get_db)):
    c = db.get(ClipCandidate, sid)
    if not c:
        raise HTTPException(404, "Clip not found")
    for f in store.clip_paths(c.clip_project_id)["clips"].glob(f"{c.id}*"):
        f.unlink(missing_ok=True)
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/clips/{sid}/metadata")
def regenerate_metadata(sid: str, db: Session = Depends(get_db)):
    c = db.get(ClipCandidate, sid)
    if not c:
        raise HTTPException(404, "Clip not found")
    from . import metadata as clip_metadata

    copy = clip_metadata.generate(c.transcript_text, c.category)
    c.title, c.hook = copy["title"], copy["hook"]
    db.commit()
    return {"copy": copy}


@router.post("/clips/{sid}/render")
def render_clip(sid: str, body: RenderBody, background: BackgroundTasks, db: Session = Depends(get_db)):
    c = db.get(ClipCandidate, sid)
    if not c:
        raise HTTPException(404, "Clip not found")
    p = _project(db, c.clip_project_id)
    edit = body.model_dump(exclude_none=True)
    if not edit:
        edit = {}
    job = _enqueue(db, p, "render", "Queued clip render",
                   meta={"candidate_id": c.id, "edit": edit}, background=background)
    return {"job": job_dict(job)}


@router.post("/projects/{cid}/export-batch")
def export_batch(cid: str, body: BatchExportBody, background: BackgroundTasks, db: Session = Depends(get_db)):
    p = _project(db, cid)
    q = db.query(ClipCandidate).filter(ClipCandidate.clip_project_id == cid)
    if body.candidate_ids:
        q = q.filter(ClipCandidate.id.in_(body.candidate_ids))
    else:
        q = q.filter(ClipCandidate.selected.is_(True))
    ids = [c.id for c in q.order_by(ClipCandidate.start_sec).all()]
    if not ids:
        raise HTTPException(400, "No clips selected")
    meta = {"candidate_ids": ids, "aspect": body.aspect or p.aspect_ratio}
    job = _enqueue(db, p, "batch_export", "Queued batch export", meta=meta, background=background)
    return {"job": job_dict(job), "requested": len(ids)}


@router.get("/clips/{sid}/file")
def clip_file(sid: str, aspect: Optional[str] = None, db: Session = Depends(get_db)):
    c = db.get(ClipCandidate, sid)
    if not c:
        raise HTTPException(404, "Clip not found")
    q = db.query(ClipRender).filter(ClipRender.candidate_id == sid)
    if aspect:
        q = q.filter(ClipRender.aspect_ratio == aspect)
    row = q.order_by(ClipRender.created_at.desc()).first()
    if not row or not Path(row.output_path).exists():
        raise HTTPException(404, "No rendered file for this clip yet")
    return FileResponse(row.output_path, media_type="video/mp4", filename=Path(row.output_path).name)


@router.get("/projects/{cid}/exports")
def list_exports(cid: str, db: Session = Depends(get_db)):
    _project(db, cid)
    ex = store.clip_paths(cid)["exports"]
    manifest = store.read_json(ex / "manifest.json")
    files = [{
        "name": f.name, "size_bytes": f.stat().st_size,
        "url": f"/api/clip/exports/{cid}/{f.name}",
    } for f in sorted(ex.glob("*.mp4"))]
    return {"files": files, "manifest": manifest}


@router.get("/exports/{cid}/{name}")
def export_file(cid: str, name: str, db: Session = Depends(get_db)):
    _project(db, cid)
    ex = store.clip_paths(cid)["exports"].resolve()
    target = (ex / Path(name).name).resolve()
    if not str(target).startswith(str(ex)) or not target.exists():
        raise HTTPException(404, "Export not found")
    return FileResponse(str(target), media_type="video/mp4", filename=target.name)


@router.get("/projects/{cid}/jobs")
def project_jobs(cid: str, db: Session = Depends(get_db)):
    _project(db, cid)
    jobs = db.query(ClipJob).filter(ClipJob.clip_project_id == cid).order_by(ClipJob.created_at.desc()).limit(30).all()
    return {"jobs": [job_dict(j) for j in jobs]}


@router.get("/jobs/{jid}")
def get_job(jid: str, db: Session = Depends(get_db)):
    j = db.get(ClipJob, jid)
    if not j:
        raise HTTPException(404, "Job not found")
    return {"job": job_dict(j)}


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: str, db: Session = Depends(get_db)):
    j = db.get(ClipJob, jid)
    if not j:
        raise HTTPException(404, "Job not found")
    if j.status in ("succeeded", "failed", "canceled", "interrupted"):
        return {"job": job_dict(j), "note": "Job already finished"}
    j.canceled = True
    j.message = "Cancellation requested"
    db.commit()
    return {"job": job_dict(j)}


@router.get("/diagnostics")
def diagnostics():
    from .probe import _ffprobe_bin

    return {
        "ffmpeg": settings.ffmpeg,
        "ffmpeg_exists": Path(settings.ffmpeg).exists(),
        "ffprobe": _ffprobe_bin(),
        "probe_fallback": "ffmpeg stderr parsing when no standalone ffprobe",
        "whisper": clip_transcribe.capability(),
        "note": "Engine B is local-only; no cloud calls are made.",
    }


def _music_tracks() -> list[dict]:
    out = []
    if MUSIC_DIR.exists():
        for f in sorted(MUSIC_DIR.glob("*")):
            if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".aiff", ".ogg"):
                out.append({"name": f.name, "path": str(f), "url": f"/media/music/{f.name}"})
    return out
