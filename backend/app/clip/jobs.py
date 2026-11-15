"""Engine B job execution.

Sequential by design (shared with Engine A): one heavyweight job across the
whole app at a time. Progress comes from real stage transitions and FFmpeg
``-progress`` output; there are no timers pretending to be work.
"""

from __future__ import annotations

import json
import re
import time
import traceback
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..db.database import SessionLocal
from ..db.models import Job as EngineAJob
from ..services.memory import MemorySampler, wait_for_memory
from . import audio as clip_audio
from . import highlights as clip_highlights
from . import metadata as clip_metadata
from . import render as clip_render
from . import store, transcribe as clip_transcribe
from .models import ClipCandidate, ClipJob, ClipProject, ClipRender, ClipSource
from .probe import probe_media


class JobCanceled(Exception):
    pass


def _now() -> datetime:
    return datetime.utcnow()


def running_heavy_job(db: Session) -> dict | None:
    """Cross-engine sequential guard. Returns the first active heavy job."""
    a = db.query(EngineAJob).filter(EngineAJob.status.in_(["running", "queued"])).first()
    if a:
        return {"engine": "A", "id": a.id, "status": a.status, "stage": a.stage, "project_id": a.project_id}
    c = db.query(ClipJob).filter(ClipJob.status.in_(["running", "queued"])).first()
    if c:
        return {"engine": "B", "id": c.id, "status": c.status, "stage": c.stage, "project_id": c.clip_project_id}
    return None


class Ctx:
    """Job context: cancellation, throttled progress writes, memory sampling."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.db: Session = SessionLocal()
        self.job: ClipJob | None = self.db.get(ClipJob, job_id)
        if not self.job:
            self.db.close()
            raise RuntimeError("Clip job not found")
        self.project: ClipProject | None = self.db.get(ClipProject, self.job.clip_project_id)
        self._last_check = 0.0
        self._last_write = 0.0
        self._last_progress = -1

    def set(self, progress: int | None = None, message: str | None = None,
            stage: str | None = None, force: bool = False) -> None:
        now = time.time()
        progress = None if progress is None else max(0, min(100, int(progress)))
        changed = (progress is not None and progress != self._last_progress) or message is not None or stage is not None
        if not force and (not changed or now - self._last_write < 0.6):
            return
        if progress is not None:
            self.job.progress = progress
            self._last_progress = progress
        if message is not None:
            self.job.message = message
        if stage is not None:
            self.job.stage = stage
        self.job.updated_at = _now()
        self.db.commit()
        self._last_write = now

    def check(self, force: bool = False) -> None:
        """Raise ``JobCanceled`` when the user requested cancellation.

        Throttled to keep DB reads cheap inside FFmpeg progress loops, but
        stage boundaries pass ``force=True`` so a short job cannot race past a
        pending cancel request.
        """
        now = time.time()
        if not force and now - self._last_check < 0.2:
            return
        self._last_check = now
        self.db.expire(self.job)
        if self.job.canceled:
            raise JobCanceled("Canceled by user")

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass


def _set_status(ctx: Ctx, status: str, message: str | None = None, error: str | None = None) -> None:
    ctx.job.status = status
    if message is not None:
        ctx.job.message = message
    if error is not None:
        ctx.job.error = error[-4000:]
    ctx.job.finished_at = _now() if status in ("succeeded", "failed", "canceled", "interrupted") else ctx.job.finished_at
    ctx.db.commit()


def _latest_source(db: Session, project_id: str) -> ClipSource:
    src = (
        db.query(ClipSource)
        .filter(ClipSource.clip_project_id == project_id)
        .order_by(ClipSource.created_at.desc())
        .first()
    )
    if not src:
        raise RuntimeError("No uploaded source video for this clip project")
    return src


def _analysis_paths(project_id: str) -> dict[str, Path]:
    d = store.clip_paths(project_id)["analysis"]
    return {
        "dir": d,
        "wav": d / "audio16k.wav",
        "structural": d / "structural.json",
        "transcript": d / "transcript.json",
        "whisper_json": d / "whisper_output.json",
    }


# ---------------------------------------------------------------- analyze

def _job_analyze(ctx: Ctx) -> dict:
    db, project = ctx.db, ctx.project
    src = _latest_source(db, project.id)
    paths = _analysis_paths(project.id)
    ctx.set(3, "Preparing analysis", "analyze")
    if not wait_for_memory(threshold_percent=94, timeout=30):
        raise RuntimeError("System memory pressure too high to start analysis; close other apps and retry.")

    ctx.check(force=True)
    ctx.set(10, "Extracting audio (mono 16 kHz)", "audio")
    clip_audio.extract_analysis_audio(Path(src.original_path), paths["wav"])

    ctx.check(force=True)
    ctx.set(25, "Measuring loudness envelope", "audio")
    src_dur = float(src.duration_sec or 0) or float((probe_media(src.original_path) or {}).get("duration") or 0)

    def env_progress(done: float, _total: float) -> None:
        if src_dur:
            ctx.set(25 + int(30 * min(1.0, done / src_dur)), "Measuring loudness envelope", "audio")

    envelope = clip_audio.rms_envelope(paths["wav"], on_progress=env_progress, check=ctx.check)

    ctx.check(force=True)
    ctx.set(60, "Detecting silence gaps", "structure")
    silence = clip_audio.detect_silence(paths["wav"])

    ctx.check(force=True)
    ctx.set(68, "Scanning scene changes (downscaled, approximate)", "structure")
    cuts = clip_audio.detect_scene_cuts(Path(src.original_path))

    ctx.check(force=True)
    ctx.set(92, "Writing analysis artifacts", "structure")
    data = {
        "created_at": _now().isoformat() + "Z",
        "source": {
            "id": src.id, "path": src.original_path, "duration": src.duration_sec,
            "width": src.width, "height": src.height, "fps": src.fps,
            "sha256": src.sha256, "probe_source": (src.probe_json or {}).get("probe_source"),
        },
        "envelope": envelope,
        "silence": silence,
        "scene_cuts": cuts,
    }
    store.write_json(paths["structural"], data)
    project.status = "ready"
    project.error = None
    return {
        "audio": str(paths["wav"]),
        "silence_gaps": len(silence["gaps"]),
        "scene_cuts": len(cuts["cuts"]),
        "envelope_windows": len(envelope["windows"]),
    }


# ------------------------------------------------------------- transcribe

def _job_transcribe(ctx: Ctx) -> dict:
    db, project = ctx.db, ctx.project
    src = _latest_source(db, project.id)
    paths = _analysis_paths(project.id)
    if not paths["wav"].exists():
        ctx.set(5, "Extracting audio for transcription", "audio")
        clip_audio.extract_analysis_audio(Path(src.original_path), paths["wav"])
    cap = clip_transcribe.capability()
    if not cap["available"]:
        raise RuntimeError(
            "Local ASR unavailable: " + "; ".join(cap["reasons"]) + ". "
            "Use Transcript → Import SRT/VTT, or run scripts/install_whisper_cpp.sh."
        )
    ctx.set(10, "Running whisper.cpp", "transcribe")
    result = clip_transcribe.transcribe(
        paths["wav"], paths["whisper_json"], language=project.language or "en",
        on_progress=lambda p, m: ctx.set(10 + int(0.8 * p), m, "transcribe"),
        check=ctx.check,
    )
    clip_transcribe.save_transcript(paths["transcript"], result)
    project.status = "ready"
    project.error = None
    return {
        "backend": result["backend"],
        "model": result.get("model"),
        "segments": len(result["segments"]),
        "sentences": len(result["sentences"]),
        "word_timing": result.get("word_timing"),
        "timing": result.get("timing"),
    }


# --------------------------------------------------------------- highlights

EDIT_DEFAULTS = {
    "crop": None,
    "caption_style": {**clip_render.DEFAULT_CAPTION_STYLE},
    "audio": {**clip_render.DEFAULT_AUDIO},
    "aspect": "9:16",
    "preset": "tiktok",
    "burn_captions": True,
    "fps": 30,
}


def _job_highlights(ctx: Ctx) -> dict:
    db, project = ctx.db, ctx.project
    paths = _analysis_paths(project.id)
    transcript = clip_transcribe.load_transcript(paths["transcript"])
    structural = store.read_json(paths["structural"]) or {}
    if not transcript:
        raise RuntimeError("No transcript yet. Transcribe or import an SRT/VTT first.")
    meta = ctx.job.meta or {}
    durations = [float(d) for d in (meta.get("durations") or [30])][:6]
    count = int(meta.get("count") or 5)
    ctx.set(10, "Scoring transcript windows", "highlights")
    ctx.check()
    result = clip_highlights.generate(transcript, structural, durations=durations, count=count, overlap_tolerance=0.2)

    ctx.set(70, "Saving candidates", "highlights")
    old = db.query(ClipCandidate).filter(ClipCandidate.clip_project_id == project.id).all()
    for c in old:
        for f in (store.clip_paths(project.id)["clips"]).glob(f"{c.id}*"):
            f.unlink(missing_ok=True)
        db.delete(c)
    db.commit()

    for w in result["candidates"]:
        copy = clip_metadata.generate(w["text"], w["category"])
        cand = ClipCandidate(
            clip_project_id=project.id,
            start_sec=w["start"], end_sec=w["end"], duration_sec=w["duration"],
            transcript_text=w["text"], title=copy["title"], hook=copy["hook"],
            category=w["category"], score=w["score"], score_json={
                "components": w["components"], "metrics": w["metrics"],
                "weights": clip_highlights.WEIGHTS, "params": result["params"],
            },
            reason=w["reason"], selected=True, state="new",
            edit_json=json.dumps(EDIT_DEFAULTS),
        )
        db.add(cand)
    db.commit()
    project.status = "ready"
    project.updated_at = _now()
    return {
        "candidates": len(result["candidates"]),
        "shortfall": result["shortfall"],
        "stats": result["stats"],
        "requested_count": count,
        "durations": durations,
    }


# ------------------------------------------------------------------- render

def _source_for(db: Session, project_id: str) -> ClipSource:
    return _latest_source(db, project_id)


def _merge_edit(cand: ClipCandidate, overrides: dict | None) -> dict:
    try:
        base = json.loads(cand.edit_json or "{}")
    except Exception:
        base = {}
    edit = {**EDIT_DEFAULTS, **base, **(overrides or {})}
    if isinstance(edit.get("caption_style"), dict):
        edit["caption_style"] = {**clip_render.DEFAULT_CAPTION_STYLE, **edit["caption_style"]}
    if isinstance(edit.get("audio"), dict):
        edit["audio"] = {**clip_render.DEFAULT_AUDIO, **edit["audio"]}
    return edit


def _render_one(
    ctx: Ctx,
    cand: ClipCandidate,
    src: ClipSource,
    transcript: dict | None,
    out_path: Path,
    progress_base: int,
    progress_span: int,
    overrides: dict | None = None,
) -> dict:
    edit = _merge_edit(cand, overrides)
    aspect = edit.get("aspect") if edit.get("aspect") in clip_render.ASPECTS else "9:16"
    cues = []
    if edit.get("burn_captions", True) and transcript:
        cues = clip_transcribe.caption_segments(
            transcript, cand.start_sec, cand.end_sec,
            max_chars=int((edit.get("caption_style") or {}).get("max_chars") or 32),
        )
    ctx.set(progress_base, f"Rendering {cand.start_sec:.1f}s–{cand.end_sec:.1f}s → {aspect}", "render")

    def prog(p: int, msg: str) -> None:
        ctx.set(progress_base + int(progress_span * p / 100), msg, "render")

    result = clip_render.render_clip(
        source=Path(src.original_path), out_path=out_path,
        start=cand.start_sec, end=cand.end_sec, aspect=aspect,
        crop=edit.get("crop"), cues=cues, caption_style=edit.get("caption_style"),
        audio=edit.get("audio"), fps=int(edit.get("fps") or 30),
        on_progress=prog, check=ctx.check,
    )
    validation = clip_render.validate_render(result, aspect, cand.end_sec - cand.start_sec)
    result["validation"] = validation
    result["edit"] = edit
    result["cues"] = len(cues)
    if not validation["ok"]:
        raise RuntimeError(f"Rendered clip failed validation: {validation}")
    return result


def _job_render(ctx: Ctx) -> dict:
    db, project = ctx.db, ctx.project
    meta = ctx.job.meta or {}
    cand = db.get(ClipCandidate, meta.get("candidate_id") or "")
    if not cand or cand.clip_project_id != project.id:
        raise RuntimeError("Clip candidate not found")
    src = _source_for(db, project.id)
    paths = _analysis_paths(project.id)
    transcript = clip_transcribe.load_transcript(paths["transcript"])

    overrides = meta.get("edit") or {}
    edit = _merge_edit(cand, overrides)
    cand.edit_json = json.dumps(edit)
    db.commit()

    aspect = edit.get("aspect") if edit.get("aspect") in clip_render.ASPECTS else "9:16"
    out = store.clip_paths(project.id)["clips"] / f"{cand.id}_{aspect.replace(':', 'x')}.mp4"
    result = _render_one(ctx, cand, src, transcript, out, 5, 90, overrides)

    row = (
        db.query(ClipRender)
        .filter(ClipRender.candidate_id == cand.id, ClipRender.aspect_ratio == aspect)
        .first()
    )
    if not row:
        row = ClipRender(candidate_id=cand.id, aspect_ratio=aspect)
        db.add(row)
    row.preset = edit.get("preset") or "tiktok"
    row.output_path = str(out)
    row.duration_sec = float(result["probe"].get("duration") or 0)
    row.size_bytes = int(result["probe"].get("size_bytes") or 0)
    row.probe_json = result["probe"]
    row.state = "done"
    cand.state = "rendered"
    db.commit()
    project.status = "completed"
    return {
        "candidate_id": cand.id,
        "output": str(out),
        "duration": row.duration_sec,
        "size_bytes": row.size_bytes,
        "aspect": aspect,
        "validation": result["validation"],
        "probe": result["probe"],
        "cues": result["cues"],
        "loudness": clip_audio.measure_loudness(out),
        "crop": result["crop"],
    }


def _job_batch_export(ctx: Ctx) -> dict:
    db, project = ctx.db, ctx.project
    meta = ctx.job.meta or {}
    ids = meta.get("candidate_ids") or []
    cands = [db.get(ClipCandidate, i) for i in ids]
    cands = [c for c in cands if c and c.clip_project_id == project.id]
    if not cands:
        raise RuntimeError("No clips selected for export")
    src = _source_for(db, project.id)
    paths = _analysis_paths(project.id)
    transcript = clip_transcribe.load_transcript(paths["transcript"])
    out_dir = store.clip_paths(project.id)["exports"]
    out_dir.mkdir(parents=True, exist_ok=True)
    default_aspect = meta.get("aspect")
    manifest: list[dict] = []

    for i, cand in enumerate(cands):
        ctx.check(force=True)
        base = 5 + int(90 * i / len(cands))
        span = max(5, int(90 / len(cands)) - 2)
        overrides = {"aspect": default_aspect} if default_aspect in clip_render.ASPECTS else {}
        edit = _merge_edit(cand, overrides)
        aspect = edit.get("aspect") if edit.get("aspect") in clip_render.ASPECTS else "9:16"
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", (cand.title or cand.category or "clip")).strip("-")[:40] or "clip"
        out = out_dir / f"{i + 1:02d}_{slug}_{aspect.replace(':', 'x')}.mp4"
        try:
            result = _render_one(ctx, cand, src, transcript, out, base, span, overrides)
            cand.state = "rendered"
            manifest.append({
                "candidate_id": cand.id, "file": str(out), "aspect": aspect,
                "duration": result["probe"].get("duration"),
                "size_bytes": result["probe"].get("size_bytes"),
                "validation": result["validation"],
                "loudness": clip_audio.measure_loudness(out),
                "title": cand.title,
                "hook": cand.hook,
                "hashtags": clip_metadata.generate(cand.transcript_text, cand.category)["hashtags"],
                "start": cand.start_sec, "end": cand.end_sec,
                "category": cand.category,
                "error": None,
            })
        except JobCanceled:
            raise
        except Exception as e:  # noqa: BLE001 - one bad clip must not abort the batch
            manifest.append({"candidate_id": cand.id, "file": None, "error": str(e)[:400],
                             "aspect": aspect, "title": cand.title})
        db.commit()

    ok = sum(1 for m in manifest if m.get("file"))
    manifest_path = out_dir / "manifest.json"
    store.write_json(manifest_path, {
        "created_at": _now().isoformat() + "Z",
        "project_id": project.id,
        "source": src.original_path,
        "requested": len(cands),
        "succeeded": ok,
        "failed": len(cands) - ok,
        "items": manifest,
        "note": "Measured from actual rendered files. Failed items are reported individually.",
    })
    if ok == 0:
        raise RuntimeError("All clips failed to export; see manifest.json")
    project.status = "completed"
    return {"requested": len(cands), "succeeded": ok, "failed": len(cands) - ok,
            "manifest": str(manifest_path), "items": manifest}


# ------------------------------------------------------------------ runner

def run_clip_job(job_id: str) -> None:
    sampler = MemorySampler().start()
    ctx: Ctx | None = None
    try:
        ctx = Ctx(job_id)
        ctx.job.status = "running"
        ctx.job.started_at = _now()
        ctx.job.message = "Running"
        ctx.db.commit()
        ctx.set(1, "Starting", ctx.job.type, force=True)
        fn = {
            "analyze": _job_analyze,
            "transcribe": _job_transcribe,
            "highlights": _job_highlights,
            "render": _job_render,
            "batch_export": _job_batch_export,
        }.get(ctx.job.type)
        if not fn:
            raise RuntimeError(f"Unknown clip job type: {ctx.job.type}")
        result = fn(ctx)
        ctx.job.meta = {**(ctx.job.meta or {}), "result": result}
        ctx.set(100, "Completed", "done", force=True)
        _set_status(ctx, "succeeded", "Completed")
    except JobCanceled:
        if ctx:
            _set_status(ctx, "canceled", "Canceled by user")
            if ctx.project:
                ctx.project.status = "ready"
                ctx.db.commit()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if ctx:
            store.log(ctx.job.clip_project_id, f"job {job_id} failed: {msg}\n{traceback.format_exc()[-2500:]}")
            _set_status(ctx, "failed", msg[:400], error=f"{msg}\n{traceback.format_exc()[-2500:]}")
            if ctx.project:
                ctx.project.status = "failed"
                ctx.project.error = msg[:1000]
                ctx.db.commit()
    finally:
        peak = sampler.stop()
        project_id = None
        try:
            if ctx:
                project_id = ctx.job.clip_project_id
                ctx.job.peak_memory_mb = peak
                ctx.db.commit()
                ctx.close()
        except Exception:
            pass
        try:
            if project_id:
                store.cleanup_tmp(project_id)
        except Exception:
            pass


def recover_interrupted_clip_jobs() -> int:
    from sqlalchemy import text

    from ..db.database import engine

    with engine.begin() as conn:
        res = conn.execute(text(
            "UPDATE clip_jobs SET status='interrupted', "
            "message='Interrupted by app restart; artifacts preserved. Re-run to continue.', "
            "finished_at=datetime('now') WHERE status IN ('running','queued')"
        ))
        return res.rowcount or 0
