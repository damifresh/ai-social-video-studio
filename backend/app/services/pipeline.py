from __future__ import annotations

import json
import time
import traceback
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..core.config import MUSIC_DIR, SFX_DIR, settings
from ..db.database import SessionLocal
from ..db.models import Job, Project
from . import project_store as ps
from .audio_mix import concat_wavs, mix_narration_music, pad_audio_to
from .memory import MemorySampler, wait_for_memory
from .render import concat_segments, mux_final, probe_video_info, render_scene_segment
from .script_engine import generate_script, regenerate_scene
from .subtitles import DEFAULT_STYLE, load_srt, timings_to_segments, write_subtitles
from .tts import probe_duration as probe_audio_dur
from .tts import synthesize
from .visuals import generate_scene_image

TRANSITION_SECONDS = 0.35


class JobCanceled(Exception):
    pass


def _now() -> datetime:
    return datetime.utcnow()


def _log(project_id: str, msg: str) -> None:
    d = ps.project_dir(project_id) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "pipeline.log").open("a", encoding="utf-8") as fh:
        fh.write(f"[{_now().isoformat()}] {msg}\n")


def _set(db: Session, job: Job, **kw) -> None:
    for k, v in kw.items():
        setattr(job, k, v)
    job.updated_at = _now()
    db.commit()
    db.refresh(job)


def _check_cancel(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise JobCanceled("job removed")
    if job.canceled:
        raise JobCanceled("canceled by user")
    return job


def _style(project: Project) -> dict:
    try:
        data = json.loads(project.subtitle_style or "{}")
        return {**DEFAULT_STYLE, **(data if isinstance(data, dict) else {})}
    except Exception:
        return dict(DEFAULT_STYLE)


def _resolve_music(track: str, pdir: Path | None = None) -> Path | None:
    if not track or track == "none":
        return None
    p = Path(track)
    if p.is_absolute() and p.exists():
        return p
    bases = [MUSIC_DIR, Path(settings.assets_dir) / "music", Path(settings.data_dir) / "music"]
    if pdir is not None:
        bases.insert(0, pdir / "assets" / "music")
    for base in bases:
        cand = base / track
        if cand.exists():
            return cand
    return None


def _resolve_sfx(name: str | None, pdir: Path | None = None) -> Path | None:
    if not name or name == "none":
        return None
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    bases = [SFX_DIR, Path(settings.assets_dir) / "sfx"]
    if pdir is not None:
        bases.insert(0, pdir / "assets" / "sfx")
    for base in bases:
        for ext in ("", ".wav", ".mp3", ".aiff", ".m4a"):
            cand = base / (name if ext == "" else f"{name}{ext}")
            if cand.exists():
                return cand
    return None


def _scene_duration(scene: dict) -> float:
    return float(scene.get("render_dur") or scene.get("actual_audio_dur") or scene.get("duration_sec") or 5.0)


def _visual_kind(scene: dict) -> str:
    return scene.get("visual_kind") or ("generated_footage" if scene.get("video_path") else "animated_graphic")


def _build_scene_assets(db, job, project, scenes, pdir, fps: int, regenerate_audio: bool = True):
    """Synthesize narration per scene (sequential) and compute timings."""
    timings = []
    cursor = 0.0
    for i, sc in enumerate(scenes):
        _check_cancel(db, job.id)
        wav_path = pdir / "audio" / f"scene_{i + 1:02d}.wav"
        narration = sc.get("narration", "")
        need_audio = regenerate_audio or not wav_path.exists() or sc.get("tts_text") != narration
        if need_audio:
            if not wait_for_memory(threshold_percent=94, timeout=30):
                _log(project.id, "memory pressure high before TTS; continuing sequentially")
            res = synthesize(narration, wav_path, voice=project.voice, speed=int(project.voice_speed or 0))
            sc["tts_engine"] = res.get("engine")
            sc["tts_voice"] = res.get("voice")
            sc["tts_text"] = narration
            if res.get("fallback_from"):
                sc["tts_fallback"] = res.get("fallback_from")
                sc["tts_fallback_reason"] = res.get("fallback_reason")
            speech_dur = probe_audio_dur(wav_path)
        else:
            sc.setdefault("tts_engine", "cached")
            speech_dur = float(sc.get("actual_audio_dur") or 0.0)
            if speech_dur <= 0:
                speech_dur = probe_audio_dur(wav_path) or max(2.0, _scene_duration(sc))

        if speech_dur <= 0:
            speech_dur = max(2.0, _scene_duration(sc))

        # Scene video lasts speech + a short breathing gap. Pad the narration clip by
        # the same gap so video and audio timelines match exactly (subtitles stay in sync).
        target = round(speech_dur + 0.25, 3)
        current = probe_audio_dur(wav_path)
        if abs(current - target) > 0.05:
            pad_audio_to(wav_path, target)
        sc["audio_path"] = str(wav_path)
        sc["actual_audio_dur"] = round(speech_dur, 3)
        sc["speech_dur"] = round(speech_dur, 3)
        sc["render_dur"] = target
        timings.append({
            "scene": i + 1,
            "start": round(cursor, 3),
            "end": round(cursor + speech_dur, 3),
            "text": narration,
        })
        cursor += target
        prog = 40 + int(18 * (i + 1) / max(1, len(scenes)))
        _set(db, job, progress=prog, message=f"Narration: scene {i + 1}/{len(scenes)}")
    return timings, cursor


def _render_scenes(db, job, project, scenes, pdir, fps: int, start_progress: int = 72) -> list[Path]:
    seg_paths: list[Path] = []
    for i, sc in enumerate(scenes):
        _check_cancel(db, job.id)
        img = Path(sc.get("image_path") or "")
        if not img.exists():
            img = pdir / "images" / f"scene_{i + 1:02d}.png"
            generate_scene_image(sc, img, aspect=project.aspect_ratio, style=project.style, idx=i)
            sc["image_path"] = str(img)
            sc["visual_kind"] = "animated_graphic"
        seg_out = pdir / "video" / "scenes" / f"scene_{i + 1:02d}.mp4"
        render_scene_segment(
            img,
            _scene_duration(sc),
            seg_out,
            aspect=project.aspect_ratio,
            motion=sc.get("camera", "slow_zoom_in"),
            fps=fps,
            transition=sc.get("transition", "cut"),
        )
        sc["video_path"] = str(seg_out)
        seg_paths.append(seg_out)
        prog = start_progress + int(16 * (i + 1) / max(1, len(scenes)))
        _set(db, job, progress=prog, message=f"Rendering scene {i + 1}/{len(scenes)}")
    ps.save_storyboard(project.id, scenes)
    return seg_paths


def _compose(db, job, project, scenes, timings, pdir, fps: int, style: dict, preserve_custom: bool = True) -> dict:
    _check_cancel(db, job.id)
    _set(db, job, stage="audio_mix", progress=88, message="Mixing audio...")
    wavs = [Path(sc["audio_path"]) for sc in scenes if sc.get("audio_path")]
    if len(wavs) != len(scenes):
        raise RuntimeError("Narration audio missing for one or more scenes; regenerate narration and retry.")
    voice_concat = pdir / "audio" / "narration_full.wav"
    concat_wavs(wavs, voice_concat)

    sfx_events = []
    cursor = 0.0
    for sc in scenes:
        sfx = _resolve_sfx(sc.get("sfx"), pdir)
        if sfx:
            sfx_events.append({"path": str(sfx), "start": cursor, "volume": 0.5})
        cursor += _scene_duration(sc)

    final_audio = pdir / "audio" / "final_mix.wav"
    mix_narration_music(
        voice_concat,
        final_audio,
        music_path=_resolve_music(project.music_track, pdir),
        music_volume=float(project.music_volume or 0.10),
        sfx_events=sfx_events,
    )

    subs_dir = pdir / "subs"
    if project.subtitle_enabled:
        existing = load_srt(subs_dir / "subtitles.srt")
        if preserve_custom and style.get("customized") and existing:
            subs = existing  # preserve user-edited cues/timings
        else:
            subs = timings_to_segments(timings, max_chars=int(style.get("max_chars", 42)))
        sub_info = write_subtitles(
            subs,
            subs_dir,
            style=style,
            width=1280 if project.aspect_ratio == "16:9" else 720,
            height=1280 if project.aspect_ratio == "9:16" else 720,
        )
    else:
        sub_info = {"srt": None, "vtt": None, "ass": None, "count": 0}

    _check_cancel(db, job.id)
    _set(db, job, stage="compose", progress=93, message="Composing final video...")
    seg_paths = [Path(sc["video_path"]) for sc in scenes if sc.get("video_path")]
    video_concat = pdir / "video" / "video_concat.mp4"
    concat_segments(seg_paths, video_concat)
    out_name = f"final_{project.aspect_ratio.replace(':', 'x')}_720p.mp4"
    final_out = pdir / "renders" / out_name
    mux = mux_final(
        video_concat,
        final_audio,
        final_out,
        ass_path=Path(sub_info["ass"]) if sub_info.get("ass") else None,
        burn_subs=bool(project.burn_subs and project.subtitle_enabled),
    )
    info = probe_video_info(final_out)
    return {
        "final_video": str(final_out),
        "srt": sub_info.get("srt"),
        "vtt": sub_info.get("vtt"),
        "ass": sub_info.get("ass"),
        "duration_sec": info.get("duration"),
        "aspect_ratio": project.aspect_ratio,
        "resolution": f"{info.get('width', 1280)}x{info.get('height', 720)}",
        "fps": info.get("fps", fps),
        "size_bytes": info.get("size_bytes"),
        "bitrate_kbps": info.get("bitrate_kbps"),
        "scenes": len(scenes),
        "subtitles_burned": mux.get("burned_subtitles", False),
        "subtitle_cues": sub_info.get("count", 0),
    }


def _finalize(db, job, project, result, t0, peak_mb):
    result = {
        **result,
        "peak_memory_mb": peak_mb,
        "render_seconds": round(time.time() - t0, 2),
        "completed_at": _now().isoformat() + "Z",
    }
    pdir = ps.project_dir(project.id)
    ps.write_json(pdir / "result.json", result)
    hist_path = pdir / "renders" / "history.json"
    history = ps.read_json(hist_path, []) or []
    history.append({
        "at": result["completed_at"],
        "video": result.get("final_video"),
        "duration_sec": result.get("duration_sec"),
        "size_bytes": result.get("size_bytes"),
        "peak_memory_mb": peak_mb,
        "fps": result.get("fps"),
        "job_id": job.id,
    })
    ps.write_json(hist_path, history[-20:])
    thumb = pdir / "images" / "scene_01.png"
    project.status = "completed"
    project.thumbnail = str(thumb) if thumb.exists() else ""
    project.updated_at = _now()
    _set(
        db, job,
        status="succeeded", stage="done", progress=100, message="Completed",
        meta=result, peak_memory_mb=peak_mb, finished_at=_now(),
    )
    db.commit()


def _fail(db, job_id: str, exc: Exception) -> None:
    tb = traceback.format_exc()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        project = db.get(Project, job.project_id)
        canceled = isinstance(exc, JobCanceled)
        _set(
            db, job,
            status="canceled" if canceled else "failed",
            message="Canceled" if canceled else "Failed",
            error=None if canceled else str(exc)[:2000],
            finished_at=_now(),
        )
        if project:
            project.status = "draft" if canceled else "failed"
            project.updated_at = _now()
            db.commit()
        _log(job.project_id, f"{'CANCELED' if canceled else 'FAILED'}: {exc}\n{tb}")
    except Exception:
        pass


def run_full_pipeline(job_id: str) -> None:
    db = SessionLocal()
    sampler = MemorySampler().start()
    t0 = time.time()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        project = db.get(Project, job.project_id)
        if not project:
            return
        pid = project.id
        fps = int(project.fps or 30)
        _set(db, job, status="running", stage="script", progress=2, message="Generating script...", started_at=_now())
        _log(pid, f"pipeline start (fps={fps}, aspect={project.aspect_ratio})")

        script = generate_script(project.topic, project.prompt, project.title, project.duration_min, project.style, project.language)
        ps.save_script(pid, script)
        scenes = script.get("scenes", [])
        ps.save_storyboard(pid, scenes)
        _check_cancel(db, job_id)

        _set(db, job, stage="visuals", progress=8, message="Generating visual scenes...")
        pdir = ps.project_dir(pid)
        for i, sc in enumerate(scenes):
            _check_cancel(db, job_id)
            img_path = pdir / "images" / f"scene_{i + 1:02d}.png"
            generate_scene_image(sc, img_path, aspect=project.aspect_ratio, style=project.style, idx=i)
            sc["image_path"] = str(img_path)
            sc["visual_kind"] = "animated_graphic"
            _set(db, job, progress=8 + int(22 * (i + 1) / max(1, len(scenes))), message=f"Visuals: scene {i + 1}/{len(scenes)}")
        ps.save_storyboard(pid, scenes)

        _set(db, job, stage="tts", progress=38, message="Generating narration...")
        timings, total = _build_scene_assets(db, job, project, scenes, pdir, fps)
        ps.save_storyboard(pid, scenes)
        ps.write_json(pdir / "timings.json", {"timings": timings, "total_sec": round(total, 3)})

        _set(db, job, stage="subtitles", progress=60, message="Generating subtitles...")
        style = _style(project)

        _render_scenes(db, job, project, scenes, pdir, fps)
        result = _compose(db, job, project, scenes, timings, pdir, fps, style, preserve_custom=False)
        peak = sampler.stop()
        _finalize(db, job, project, result, t0, peak)
        _log(pid, f"pipeline succeeded: {result['final_video']} ({result.get('duration_sec')}s, peak {peak}MB)")
    except Exception as exc:  # noqa: BLE001
        sampler.stop()
        _fail(db, job_id, exc)
    finally:
        db.close()


def run_rerender(project_id: str, job_id: str, burn_subs: bool | None = None) -> None:
    """Re-render from stored scenes/assets (re-synthesizes narration only when text changed)."""
    db = SessionLocal()
    sampler = MemorySampler().start()
    t0 = time.time()
    try:
        job = db.get(Job, job_id)
        project = db.get(Project, project_id)
        if not job or not project:
            return
        fps = int(project.fps or 30)
        scenes = ps.load_storyboard(project_id)
        if not scenes:
            raise RuntimeError("No storyboard found. Generate a script first.")
        pdir = ps.project_dir(project_id)
        _set(db, job, status="running", stage="prepare", progress=3, message="Preparing re-render...", started_at=_now())
        if burn_subs is not None:
            project.burn_subs = bool(burn_subs)
            db.commit()

        # Ensure images exist
        for i, sc in enumerate(scenes):
            _check_cancel(db, job_id)
            img = Path(sc.get("image_path") or pdir / "images" / f"scene_{i + 1:02d}.png")
            if not img.exists():
                generate_scene_image(sc, img, aspect=project.aspect_ratio, style=project.style, idx=i)
                sc["image_path"] = str(img)
                sc["visual_kind"] = "animated_graphic"
            else:
                sc["image_path"] = str(img)
        ps.save_storyboard(project_id, scenes)

        _set(db, job, stage="tts", progress=20, message="Verifying narration...")
        timings, total = _build_scene_assets(db, job, project, scenes, pdir, fps, regenerate_audio=False)
        ps.save_storyboard(project_id, scenes)
        ps.write_json(pdir / "timings.json", {"timings": timings, "total_sec": round(total, 3)})

        style = _style(project)

        _render_scenes(db, job, project, scenes, pdir, fps, start_progress=45)
        result = _compose(db, job, project, scenes, timings, pdir, fps, style)
        peak = sampler.stop()
        _finalize(db, job, project, result, t0, peak)
        _log(project_id, f"rerender succeeded: {result['final_video']}")
    except Exception as exc:  # noqa: BLE001
        sampler.stop()
        _fail(db, job_id, exc)
    finally:
        db.close()


def run_scene_regen(project_id: str, scene_index: int, job_id: str) -> None:
    db = SessionLocal()
    sampler = MemorySampler().start()
    t0 = time.time()
    try:
        job = db.get(Job, job_id)
        project = db.get(Project, project_id)
        if not job or not project:
            return
        _set(db, job, status="running", stage="regen_scene", progress=10,
             message=f"Regenerating scene {scene_index + 1}", started_at=_now())
        script = ps.load_script(project_id) or {}
        scenes = script.get("scenes") or ps.load_storyboard(project_id)
        if scene_index < 0 or scene_index >= len(scenes):
            raise RuntimeError(f"Scene {scene_index + 1} does not exist")
        script = regenerate_scene(script, scene_index)
        scenes = script.get("scenes", scenes)
        ps.save_script(project_id, script)
        ps.save_storyboard(project_id, scenes)
        sc = scenes[scene_index]
        pdir = ps.project_dir(project_id)

        img_path = pdir / "images" / f"scene_{scene_index + 1:02d}.png"
        generate_scene_image(sc, img_path, aspect=project.aspect_ratio, style=project.style, idx=scene_index)
        sc["image_path"] = str(img_path)
        sc["visual_kind"] = "animated_graphic"
        _set(db, job, progress=40, message="Regenerating narration...")
        wav_path = pdir / "audio" / f"scene_{scene_index + 1:02d}.wav"
        res = synthesize(sc.get("narration", ""), wav_path, voice=project.voice, speed=int(project.voice_speed or 0))
        dur = probe_audio_dur(wav_path) or _scene_duration(sc)
        pad_audio_to(wav_path, dur + 0.25)
        sc.update({
            "audio_path": str(wav_path),
            "actual_audio_dur": round(dur, 3),
            "speech_dur": round(dur, 3),
            "render_dur": round(dur + 0.25, 3),
            "tts_engine": res.get("engine"),
            "tts_voice": res.get("voice"),
            "tts_text": sc.get("narration", ""),
        })
        ps.save_storyboard(project_id, scenes)
        _set(db, job, progress=70, message="Rendering scene segment...")
        seg_out = pdir / "video" / "scenes" / f"scene_{scene_index + 1:02d}.mp4"
        render_scene_segment(
            Path(sc["image_path"]), _scene_duration(sc), seg_out,
            aspect=project.aspect_ratio, motion=sc.get("camera", "slow_zoom_in"),
            fps=int(project.fps or 30), transition=sc.get("transition", "cut"),
        )
        sc["video_path"] = str(seg_out)
        ps.save_storyboard(project_id, scenes)
        peak = sampler.stop()
        project.updated_at = _now()
        _set(db, job, status="succeeded", stage="done", progress=100,
             message=f"Scene {scene_index + 1} regenerated. Run Re-render to apply to the final video.",
             meta={"scene": scene_index, "peak_memory_mb": peak, "render_seconds": round(time.time() - t0, 2)},
             peak_memory_mb=peak, finished_at=_now())
    except Exception as exc:  # noqa: BLE001
        sampler.stop()
        _fail(db, job_id, exc)
    finally:
        db.close()


def load_subtitle_segments(project_id: str) -> list[dict]:
    return load_srt(ps.project_dir(project_id) / "subs" / "subtitles.srt")
