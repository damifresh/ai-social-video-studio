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
    """Last source in the project's explicit order (or upload order)."""
    project = db.get(ClipProject, project_id)
    order: list[str] = []
    if project:
        try:
            order = [str(i) for i in (json.loads(project.settings_json or "{}").get("source_order") or [])]
        except Exception:
            order = []
    rows = db.query(ClipSource).filter(ClipSource.clip_project_id == project_id).all()
    by_id = {s.id: s for s in rows}
    ordered = [by_id[i] for i in order if i in by_id]
    seen = set(order)
    ordered.extend(s for s in sorted(rows, key=lambda s: (s.created_at, s.id)) if s.id not in seen)
    if not ordered:
        raise RuntimeError("No uploaded source video for this clip project")
    return ordered[-1]


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
    source_id = str((ctx.job.meta or {}).get("source_id") or "")
    scoped_source = db.get(ClipSource, source_id) if source_id else None
    if scoped_source and scoped_source.clip_project_id != project.id:
        raise RuntimeError("Transcription source does not belong to this project")
    if source_id and not scoped_source:
        raise RuntimeError("Transcription source no longer exists")
    src = scoped_source or _latest_source(db, project.id)
    if source_id:
        paths = {
            "wav": store.source_audio_path(project.id, source_id),
            "whisper_json": store.source_whisper_path(project.id, source_id),
            "transcript": store.source_transcript_path(project.id, source_id),
        }
    else:
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
    if source_id:
        for candidate in db.query(ClipCandidate).filter(
            ClipCandidate.clip_project_id == project.id
        ).all():
            candidate.state = "stale"
    project.status = "ready"
    project.error = None
    return {
        "backend": result["backend"],
        "model": result.get("model"),
        "segments": len(result["segments"]),
        "sentences": len(result["sentences"]),
        "word_timing": result.get("word_timing"),
        "timing": result.get("timing"),
        "source_id": source_id or None,
        "scope": "source" if source_id else "project",
    }


# --------------------------------------------------------------- highlights

def _score_json(cand: ClipCandidate) -> dict:
    """Read a candidate's audit metadata regardless of how the column was stored."""
    value = cand.score_json
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _combine_candidate(c: ClipCandidate) -> bool:
    assembly = _score_json(c).get("assembly")
    return isinstance(assembly, dict) and assembly.get("kind") == "source_combine"


def _combine_sources(score_json: dict, assembly: dict, segments: list[dict]) -> list[dict]:
    """Rebuild the ordered whole-file source list stored on a combine candidate.

    A combine's segments are *per source* full ranges (0 → duration), not ranges
    inside one transcript source. Their stored order and source_ids are the
    authoritative release order; missing files are a hard error so an export can
    never silently substitute the latest single source.
    """
    rows = [s for s in (segments or []) if isinstance(s, dict)]
    ids = [str(i) for i in (assembly.get("source_ids") or [])]
    if ids:
        by_id = {str(s.get("source_id")): s for s in rows if s.get("source_id") is not None}
        ordered = [by_id[i] for i in ids if i in by_id]
        if len(ordered) == len(ids):
            rows = ordered
    sources: list[dict] = []
    for item in rows:
        path = str(item.get("path") or "")
        if not path or not Path(path).is_file():
            continue
        entry = {
            key: item[key] for key in ("source_id", "name", "path", "start", "end", "duration")
            if key in item
        }
        entry["path"] = path
        sources.append(entry)
    if len(sources) < 2:
        raise RuntimeError(
            "Combined-video source files are missing on disk; restore them or combine the videos again"
        )
    return sources


def _combine_options(score_json: dict, assembly: dict) -> tuple[bool, float]:
    params = score_json.get("params") or {}
    transitions = assembly.get("transitions")
    if transitions is None:
        transitions = params.get("transitions", True)
    seconds = (
        assembly.get("transition_seconds")
        or params.get("transition_seconds")
        or clip_render.DEFAULT_TRANSITION_SECONDS
    )
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        seconds = clip_render.DEFAULT_TRANSITION_SECONDS
    return bool(transitions), seconds


def _combine_target(score_json: dict, assembly: dict) -> float | None:
    """Requested final timeframe recorded on a source_combine candidate."""
    params = score_json.get("params") or {}
    value = assembly.get("target_duration")
    if value is None:
        value = params.get("target_duration")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _assembly_cues(transcript: dict | None, segments: list[dict], max_chars: int) -> list[dict]:
    """Remap each source segment's caption cues to the assembled timeline."""
    if not transcript:
        return []
    cues: list[dict] = []
    offset = 0.0
    for segment in segments:
        part = clip_transcribe.caption_segments(
            transcript, float(segment["start"]), float(segment["end"]), max_chars=max_chars,
        )
        cues.extend({
            **cue,
            "start": round(float(cue["start"]) + offset, 3),
            "end": round(float(cue["end"]) + offset, 3),
        } for cue in part)
        offset += float(segment["duration"])
    return [cue for cue in cues if cue["end"] > cue["start"]]


EDIT_DEFAULTS = {
    "crop": None,
    "caption_style": {**clip_render.DEFAULT_CAPTION_STYLE},
    "audio": {**clip_render.DEFAULT_AUDIO},
    "aspect": "9:16",
    "preset": "tiktok",
    "burn_captions": True,
    "fps": 30,
}


def _captions_enabled(project) -> bool:
    """Project-level default for newly generated transcript candidates."""
    try:
        settings = json.loads(getattr(project, "settings_json", None) or "{}")
    except (TypeError, ValueError):
        settings = {}
    return bool(settings.get("burn_captions", True))


def _highlight_edit_defaults(project, meta: dict | None = None) -> dict:
    value = (meta or {}).get("burn_captions")
    if value is None:
        value = _captions_enabled(project)
    return {**EDIT_DEFAULTS, "burn_captions": bool(value)}


def _combine_source_cues(
    ctx: Ctx,
    segments: list[dict],
    max_chars: int,
    on_progress=None,
) -> tuple[list[list[dict]], list[str]]:
    """Build subtitle cues for each ordered combine source.

    Transcripts are cached per source. Missing transcripts are generated with
    the local ASR when available; sources without speech/audio simply contribute
    no cues and are reported in the notice list. No copy is invented.
    """
    project = ctx.project
    cues_by_source: list[list[dict]] = []
    notices: list[str] = []
    for index, segment in enumerate(segments):
        source_id = str(segment.get("source_id") or "")
        name = str(segment.get("name") or source_id or f"source {index + 1}")
        transcript = clip_transcribe.load_transcript(
            store.source_transcript_path(project.id, source_id)
        ) if source_id else None
        missing_notice = False
        if transcript is None and source_id:
            source = ctx.db.get(ClipSource, source_id)
            cap = clip_transcribe.capability()
            if source and source.audio_streams and cap.get("available"):
                wav = store.source_audio_path(project.id, source_id)
                whisper = store.source_whisper_path(project.id, source_id)
                if not wav.exists():
                    clip_audio.extract_analysis_audio(Path(source.original_path), wav)
                ctx.check()
                result = clip_transcribe.transcribe(
                    wav, whisper, language=project.language or "en",
                    on_progress=(
                        (lambda pct, msg: on_progress(index, pct, msg))
                        if on_progress else None
                    ),
                    check=ctx.check,
                )
                clip_transcribe.save_transcript(
                    store.source_transcript_path(project.id, source_id), result,
                )
                transcript = result
            else:
                reason = "ASR unavailable" if not cap.get("available") else "no audio stream"
                notices.append(f"{name}: {reason}; no captions generated")
                missing_notice = True
        if transcript and not (transcript.get("segments") or transcript.get("sentences")):
            # A successful ASR run on silent/non-speech audio returns an empty
            # transcript. Report it instead of failing the whole combine.
            notices.append(f"{name}: no speech detected; no captions generated")
        if not transcript:
            if source_id and not missing_notice:
                notices.append(f"{name}: no transcript; no captions generated")
            cues_by_source.append([])
            continue
        try:
            start, end = float(segment.get("start", 0)), float(segment.get("end", 0))
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        cues_by_source.append(
            clip_transcribe.caption_segments(transcript, start, end, max_chars=max_chars)
        )
    return cues_by_source, notices


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
    brief = meta.get("brief") or None
    plan = meta.get("direction") or {}
    single_clip = bool(meta.get("single_clip") or plan.get("single_clip"))
    edit_defaults = _highlight_edit_defaults(project, meta)
    burn_captions = bool(edit_defaults["burn_captions"])
    source_duration: float | None = None
    if single_clip:
        try:
            source_duration = float(_latest_source(db, project.id).duration_sec or 0) or None
        except RuntimeError:
            # Transcript-only projects keep the previous behavior; the render
            # step still reports a missing source clearly.
            source_duration = None
    ctx.set(10, "Scoring transcript windows", "highlights")
    ctx.check()
    result = clip_highlights.generate(
        transcript, structural, durations=durations, count=count,
        overlap_tolerance=0.2, brief=brief, single_clip=single_clip,
        source_duration=source_duration,
    )

    ctx.set(70, "Saving candidates", "highlights")
    old = db.query(ClipCandidate).filter(ClipCandidate.clip_project_id == project.id).all()
    for c in old:
        if _combine_candidate(c):
            continue  # a source combine is independent of transcript highlights
        for f in (store.clip_paths(project.id)["clips"]).glob(f"{c.id}*"):
            f.unlink(missing_ok=True)
        db.delete(c)
    db.commit()

    for w in result["candidates"]:
        assembly = w.get("assembly")
        copy = clip_metadata.generate(w["text"], w["category"])
        cand = ClipCandidate(
            clip_project_id=project.id,
            start_sec=w["start"], end_sec=w["end"], duration_sec=w["duration"],
            transcript_text=w["text"], title=copy["title"], hook=copy["hook"],
            category=w["category"], score=w["score"], score_json={
                "components": w["components"], "metrics": w["metrics"],
                "weights": clip_highlights.WEIGHTS, "params": result["params"],
                "copy": copy,
                "plan_order": w.get("plan_order"),
                "engine": plan.get("engine"),
                "assembly": assembly,
                "segments": w.get("segments") or [],
            },
            reason=w["reason"], selected=True, state="new",
            edit_json=json.dumps(edit_defaults),
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
        "single_clip": single_clip,
        "burn_captions": burn_captions,
        "brief": brief,
        "direction": {
            "engine": plan.get("engine"),
            "notice": plan.get("notice"),
            "focus_indices": plan.get("focus_indices") or [],
            "moments": len(plan.get("focus_windows") or []),
            "segments": len(plan.get("segments") or []),
            "assembly": plan.get("assembly"),
        },
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
    score_json = _score_json(cand)
    assembly = score_json.get("assembly")
    assembly = assembly if isinstance(assembly, dict) else {}
    is_combine = _combine_candidate(cand)
    segments = score_json.get("segments") or []
    if not segments and assembly:
        segments = (assembly.get("segments") or (score_json.get("params") or {}).get("assembly") or {}).get("segments") or []
    if assembly and segments and not is_combine:
        # Older candidates may carry transcript ranges from a longer source.
        # Keep them renderable by clamping to the uploaded file instead of
        # failing with "Assembly segment extends outside the source duration".
        source_len = float(src.duration_sec or 0) if src else 0.0
        if source_len > 0:
            kept: list[dict] = []
            for segment in segments:
                start = max(0.0, min(float(segment.get("start") or 0), source_len))
                end = max(start, min(float(segment.get("end") or start), source_len))
                if end - start < 0.05:
                    continue
                kept.append({
                    **segment,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "duration": round(end - start, 3),
                })
            if kept:
                segments = kept
    max_chars = int((edit.get("caption_style") or {}).get("max_chars") or 32)
    if is_combine:
        # Combine segments are per-source ranges. Rebuild subtitle cues from
        # each source's own cached transcript/ASR so Export uses the same
        # multi-source caption timeline as the original combine render.
        sources = _combine_sources(score_json, assembly, segments)
        transitions, seconds = _combine_options(score_json, assembly)
        target = _combine_target(score_json, assembly)
        cues: list[dict] = []
        source_cues: list[list[dict]] = []
        caption_notices: list[str] = []
        if edit.get("burn_captions", True):
            source_cues, caption_notices = _combine_source_cues(ctx, segments, max_chars)
        else:
            caption_notices.append("On-screen captions are off for this candidate.")
        label = f"Rendering {len(sources)} uploaded sources → {aspect}"
    elif assembly and segments:
        cues = _assembly_cues(transcript, segments, max_chars) if edit.get("burn_captions", True) else []
        label = f"Rendering {len(segments)} assembled scenes → {aspect}"
    else:
        cues = clip_transcribe.caption_segments(
            transcript, cand.start_sec, cand.end_sec, max_chars=max_chars,
        ) if edit.get("burn_captions", True) and transcript else []
        label = f"Rendering {cand.start_sec:.1f}s–{cand.end_sec:.1f}s → {aspect}"
    ctx.set(progress_base, label, "render")

    def prog(p: int, msg: str) -> None:
        ctx.set(progress_base + int(progress_span * p / 100), msg, "render")

    if is_combine:
        result = clip_render.render_combine(
            sources=sources, out_path=out_path, aspect=aspect,
            crop=edit.get("crop"), cues=cues, source_cues=source_cues,
            caption_style=edit.get("caption_style"), audio=edit.get("audio"),
            fps=int(edit.get("fps") or 30),
            transitions=transitions, transition_seconds=seconds,
            target_duration=target,
            on_progress=prog, check=ctx.check,
        )
        result["assembly"] = assembly
    elif assembly and segments:
        result = clip_render.render_assembly(
            source=Path(src.original_path), out_path=out_path, segments=segments,
            aspect=aspect, crop=edit.get("crop"), cues=cues,
            caption_style=edit.get("caption_style"), audio=edit.get("audio"),
            fps=int(edit.get("fps") or 30), on_progress=prog, check=ctx.check,
        )
    else:
        result = clip_render.render_clip(
            source=Path(src.original_path), out_path=out_path,
            start=cand.start_sec, end=cand.end_sec, aspect=aspect,
            crop=edit.get("crop"), cues=cues, caption_style=edit.get("caption_style"),
            audio=edit.get("audio"), fps=int(edit.get("fps") or 30),
            on_progress=prog, check=ctx.check,
        )
    validation = clip_render.validate_render(
        result, aspect, float(result.get("requested_duration") or cand.end_sec - cand.start_sec)
    )
    result["validation"] = validation
    result["edit"] = edit
    if is_combine:
        assembly_captions = assembly.setdefault("captions", {})
        assembly_captions.update({
            "enabled": bool(edit.get("burn_captions", True)),
            "source": "per-source transcript/ASR",
            "cue_count": int(result.get("cue_count") or 0),
            "notices": caption_notices,
        })
        result["assembly"] = assembly
        result["caption_notices"] = caption_notices
        result["cues"] = int(result.get("cue_count") or 0)
    else:
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
            is_combine = _combine_candidate(cand)
            score_json = _score_json(cand)
            copy = score_json.get("copy") or {}
            extra: dict = {}
            if is_combine:
                # A combine has no transcript copy: record the audit metadata
                # produced by the multi-source render instead of generating copy.
                extra = {
                    "combine": result.get("combine"),
                    "transition": result.get("transition"),
                    "resolution": result.get("resolution"),
                    "source_resolution": result.get("source_resolution"),
                    "resolution_mode": result.get("resolution_mode"),
                    "source_paths": [
                        s.get("path") for s in (score_json.get("segments") or []) if isinstance(s, dict)
                    ],
                }
            manifest.append({
                "candidate_id": cand.id, "file": str(out), "aspect": aspect,
                "duration": result["probe"].get("duration"),
                "size_bytes": result["probe"].get("size_bytes"),
                "validation": result["validation"],
                "loudness": clip_audio.measure_loudness(out),
                "title": cand.title,
                "hook": cand.hook,
                "hashtags": (copy.get("hashtags") or []) if is_combine
                            else clip_metadata.generate(cand.transcript_text, cand.category)["hashtags"],
                "start": cand.start_sec, "end": cand.end_sec,
                "category": cand.category,
                "assembly": result.get("assembly"),
                "error": None,
                **extra,
            })
        except JobCanceled:
            raise
        except Exception as e:  # noqa: BLE001 - one bad clip must not abort the batch
            manifest.append({"candidate_id": cand.id, "file": None, "error": str(e)[:400],
                             "aspect": aspect, "title": cand.title})
        db.commit()

    ok = sum(1 for m in manifest if m.get("file"))
    combine_candidates = [c for c in cands if _combine_candidate(c)]
    combine_sources = [
        {key: s.get(key) for key in ("source_id", "name", "path")}
        for c in combine_candidates
        for s in (_score_json(c).get("segments") or []) if isinstance(s, dict)
    ]
    manifest_path = out_dir / "manifest.json"
    store.write_json(manifest_path, {
        "created_at": _now().isoformat() + "Z",
        "project_id": project.id,
        "source": src.original_path,
        "source_combine": bool(combine_candidates),
        "combine_sources": combine_sources,
        "requested": len(cands),
        "succeeded": ok,
        "failed": len(cands) - ok,
        "items": manifest,
        "note": (
            "Measured from actual rendered files. Failed items are reported individually. "
            "For source_combine items, combine_sources and each item's combine metadata "
            "are authoritative; 'source' is only the project's latest single source."
            if combine_candidates else
            "Measured from actual rendered files. Failed items are reported individually."
        ),
    })
    if ok == 0:
        raise RuntimeError("All clips failed to export; see manifest.json")
    project.status = "completed"
    return {"requested": len(cands), "succeeded": ok, "failed": len(cands) - ok,
            "manifest": str(manifest_path), "items": manifest}


# ------------------------------------------------------------------ combine


def _job_combine(ctx: Ctx) -> dict:
    """Join ordered uploaded videos into one auditable render-ready candidate."""
    db, project = ctx.db, ctx.project
    meta = ctx.job.meta or {}
    ids = [str(i) for i in (meta.get("source_ids") or [])]
    rows = [db.get(ClipSource, i) for i in ids]
    sources = [s for s in rows if s and s.clip_project_id == project.id]
    if len(sources) < 2:
        raise RuntimeError("At least two uploaded videos are required for a combine")
    transitions = bool(meta.get("transitions", True))
    seconds = float(meta.get("transition_seconds") or clip_render.DEFAULT_TRANSITION_SECONDS)
    target = meta.get("target_duration")
    try:
        target = float(target) if target is not None else None
    except (TypeError, ValueError):
        raise RuntimeError("target_duration must be a number")
    aspect = meta.get("aspect") if meta.get("aspect") in clip_render.ASPECTS else project.aspect_ratio

    # One combine candidate per project. Re-combining replaces the old file.
    for old in db.query(ClipCandidate).filter(ClipCandidate.clip_project_id == project.id).all():
        if _combine_candidate(old):
            for f in store.clip_paths(project.id)["clips"].glob(f"{old.id}*"):
                f.unlink(missing_ok=True)
            db.delete(old)
    db.commit()

    raw_segments: list[dict] = []
    for source in sources:
        duration = round(float(source.duration_sec or 0), 3)
        raw_segments.append({
            "source_id": source.id,
            "name": source.original_name,
            "path": source.original_path,
            "start": 0.0,
            "end": duration,
            "duration": duration,
        })
    if target is not None:
        try:
            segments = clip_render.fit_combine_segments(
                raw_segments, target, transitions, seconds,
            )
        except ValueError as exc:
            raise RuntimeError(str(exc))
        total = target
        ctx.set(8, f"Fitting {len(segments)} source videos to {target:g}s", "combine")
    else:
        segments = raw_segments
        durations = [float(s["duration"]) for s in segments]
        total = clip_render.max_combine_duration(durations, transitions, seconds)
        ctx.set(8, f"Combining {len(segments)} source videos", "combine")
    ctx.check(force=True)

    burn_captions = bool(meta.get("burn_captions", _captions_enabled(project)))
    edit = {**EDIT_DEFAULTS, "aspect": aspect, "burn_captions": burn_captions}
    assembly = {
        "kind": "source_combine",
        "segment_count": len(segments),
        "source_ids": [s.id for s in sources],
        "transitions": transitions,
        "transition_mode": "fade" if transitions else "cut",
        "transition_seconds": seconds,
        "boundary_authority": "uploaded source order",
        "target_duration": target,
        "duration_mode": "target" if target is not None else "whole_sources",
        "captions": {
            "enabled": burn_captions,
            "source": "per-source transcript/ASR",
            "cue_count": 0,
            "notices": [],
        },
        "timeline": {"start": 0.0, "end": total},
        "note": (
            "One output video; ordered sources are trimmed proportionally to the selected target duration."
            if target is not None else
            "One output video; every source is a whole uploaded video in user order."
        ),
    }
    candidate = ClipCandidate(
        clip_project_id=project.id,
        start_sec=0.0, end_sec=total, duration_sec=total,
        transcript_text="", title="Combined video", hook="", category="combine",
        score=0.0, selected=True, state="new",
        reason=(
            f"Combined {len(segments)} ordered source videos ({assembly['transition_mode']}) to {target:g}s."
            if target is not None else
            f"Combined {len(segments)} ordered source videos ({assembly['transition_mode']})."
        ),
        edit_json=json.dumps(edit),
        score_json={
            "components": {},
            "metrics": {"source_count": len(segments)},
            "weights": {},
            "params": {
                "kind": "source_combine", "single_clip": True,
                "source_count": len(segments), "transitions": transitions,
                "transition_seconds": seconds, "target_duration": target,
                "burn_captions": burn_captions,
            },
            "copy": {
                "title": "Combined video", "hook": "", "caption": "", "hashtags": [],
                "grounding": {
                    "all_grounded": True,
                    "note": "No transcript copy is invented for a source combine.",
                },
            },
            "plan_order": None,
            "engine": "source-combine/v1",
            "assembly": assembly,
            "segments": segments,
        },
    )
    db.add(candidate)
    db.flush()

    out = store.clip_paths(project.id)["clips"] / f"{candidate.id}_{aspect.replace(':', 'x')}.mp4"
    source_cues: list[list[dict]] = []
    caption_notices: list[str] = []
    if burn_captions:
        max_chars = int((edit.get("caption_style") or {}).get("max_chars") or 32)

        def cue_progress(source_index: int, percent: int, message: str) -> None:
            share = (source_index + percent / 100.0) / max(1, len(segments))
            ctx.set(8 + min(2, int(2 * share)), f"Preparing captions: {message}", "transcribe")

        source_cues, caption_notices = _combine_source_cues(
            ctx, segments, max_chars, cue_progress,
        )
    else:
        caption_notices.append("On-screen captions are off for this project.")

    def prog(p: int, message: str) -> None:
        ctx.set(10 + int(85 * p / 100), message, "combine")

    result = clip_render.render_combine(
        sources=segments, out_path=out, aspect=aspect,
        crop=edit.get("crop"), cues=[], source_cues=source_cues,
        caption_style=edit.get("caption_style"),
        audio=edit.get("audio"), fps=int(edit.get("fps") or 30),
        transitions=transitions, transition_seconds=seconds,
        target_duration=target,
        on_progress=prog, check=ctx.check,
    )
    total = float(result.get("requested_duration") or total)
    candidate.start_sec, candidate.end_sec, candidate.duration_sec = 0.0, round(total, 3), round(total, 3)
    assembly["timeline"] = {"start": 0.0, "end": round(total, 3)}
    assembly["source_timeline_duration"] = float(
        (result.get("combine") or {}).get("source_timeline_duration") or total
    )
    # Record the real output canvas. The Final preview and the downloaded file
    # share this render, so both keep the first source's native dimensions.
    assembly["resolution_mode"] = result.get("resolution_mode") or "source-native"
    assembly["resolution"] = result.get("resolution")
    assembly["source_resolution"] = result.get("source_resolution") or result.get("resolution")
    assembly["note"] = (
        (assembly.get("note") or "")
        + f" Output keeps the first source's native {assembly['resolution']} resolution; "
        "mismatched sources are fitted and padded, never cropped."
    )
    assembly["captions"]["cue_count"] = int(result.get("cue_count") or 0)
    assembly["captions"]["notices"] = caption_notices
    score_json_out = dict(candidate.score_json)
    score_json_out["params"] = dict(score_json_out.get("params") or {})
    score_json_out["params"]["cue_count"] = assembly["captions"]["cue_count"]
    score_json_out["params"]["caption_notices"] = caption_notices
    score_json_out["assembly"] = assembly
    candidate.score_json = score_json_out
    validation = clip_render.validate_render(result, aspect, total)
    result["validation"] = validation
    if not validation["ok"]:
        raise RuntimeError(f"Combined video failed validation: {validation}")

    row = (
        db.query(ClipRender)
        .filter(ClipRender.candidate_id == candidate.id, ClipRender.aspect_ratio == aspect)
        .first()
    )
    if not row:
        row = ClipRender(candidate_id=candidate.id, aspect_ratio=aspect)
        db.add(row)
    row.preset = edit.get("preset") or "tiktok"
    row.output_path = str(out)
    row.duration_sec = float((result.get("probe") or {}).get("duration") or total)
    row.size_bytes = int((result.get("probe") or {}).get("size_bytes") or 0)
    row.probe_json = result.get("probe")
    row.state = "done"
    candidate.state = "rendered"
    db.commit()
    project.status = "completed"
    return {
        "candidate_id": candidate.id,
        "output": str(out),
        "source_count": len(segments),
        "source_ids": [s.id for s in sources],
        "transition_mode": assembly["transition_mode"],
        "transitions": transitions,
        "transition_seconds": seconds,
        "target_duration": target,
        "duration": row.duration_sec,
        "size_bytes": row.size_bytes,
        "aspect": aspect,
        "validation": validation,
        "probe": result.get("probe"),
        "transition": result.get("transition"),
        "captions": assembly["captions"],
        "cue_count": int(result.get("cue_count") or 0),
    }


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
            "combine": _job_combine,
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
