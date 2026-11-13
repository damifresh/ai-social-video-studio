from __future__ import annotations
import json, traceback, time
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session
from ..db.database import SessionLocal
from ..db.models import Job, Project
from ..core.config import settings
from . import project_store as ps
from .script_engine import generate_script, regenerate_scene
from .tts import synthesize, probe_duration as probe_audio_dur
from .subtitles import timings_to_segments, segments_to_srt, segments_to_vtt
from .visuals import generate_scene_image
from .audio_mix import concat_wavs, mix_narration_music
from .render import render_scene_segment, concat_segments, mux_final, probe_duration as probe_video_dur

def _now():
    return datetime.utcnow()

def _job(db: Session, job_id: str) -> Job | None:
    return db.get(Job, job_id)

def _set(db: Session, job: Job, **kw):
    for k,v in kw.items(): setattr(job, k, v)
    job.updated_at = _now()
    db.commit(); db.refresh(job)

def _log(project_id: str, msg: str):
    d = ps.project_dir(project_id) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pipeline.log").open("a", encoding="utf-8").write(f"[{_now().isoformat()}] {msg}\n")

def run_full_pipeline(job_id: str):
    db = SessionLocal()
    try:
        job = _job(db, job_id)
        if not job: return
        proj = db.get(Project, job.project_id)
        if not proj: return
        pid = proj.id
        _set(db, job, status="running", stage="script", progress=2, message="Generating script...")
        _log(pid, "pipeline start")

        # 1) Script
        script = generate_script(proj.topic, proj.prompt, proj.title, proj.duration_min, proj.style, proj.language)
        ps.save_script(pid, script)
        _set(db, job, stage="storyboard", progress=10, message="Building storyboard...")
        scenes = script.get("scenes", [])
        ps.save_storyboard(pid, scenes)

        # 2) Visual assets per scene
        _set(db, job, stage="visuals", progress=18, message="Generating visual scenes...")
        pdir = ps.project_dir(pid)
        for i, sc in enumerate(scenes):
            img_path = pdir / "images" / f"scene_{i+1:02d}.png"
            generate_scene_image(sc, img_path, aspect=proj.aspect_ratio, style=proj.style, idx=i)
            sc["image_path"] = str(img_path)
            sc["visual_kind"] = "animated_graphic"
            prog = 18 + int(20 * (i+1)/max(1,len(scenes)))
            _set(db, job, progress=prog, message=f"Visuals: scene {i+1}/{len(scenes)}")
        ps.save_storyboard(pid, scenes)

        # 3) Voice per scene (sequential, memory-safe)
        _set(db, job, stage="tts", progress=40, message="Generating narration...")
        wavs = []
        timings = []
        cursor = 0.0
        for i, sc in enumerate(scenes):
            wav_path = pdir / "audio" / f"scene_{i+1:02d}.wav"
            try:
                res = synthesize(sc.get("narration",""), wav_path, voice=proj.voice)
                dur = float(res.get("duration_sec") or probe_audio_dur(wav_path) or sc.get("duration_sec",5))
                sc["tts_engine"] = res.get("engine"); sc["tts_voice"] = res.get("voice")
                if res.get("fallback_from"): sc["tts_fallback"] = res.get("fallback_from")
            except Exception as e:
                # last-resort: generate silence? better to fail clearly
                raise RuntimeError(f"TTS failed for scene {i+1}: {e}")
            sc["audio_path"] = str(wav_path)
            sc["actual_audio_dur"] = dur
            # Use audio duration as source of truth for pacing; keep close to plan
            seg_dur = max(2.0, dur)
            sc["render_dur"] = seg_dur
            timings.append({"scene": i+1, "start": cursor, "end": cursor + seg_dur, "text": sc.get("narration","")})
            cursor += seg_dur
            wavs.append(wav_path)
            prog = 40 + int(20 * (i+1)/max(1,len(scenes)))
            _set(db, job, progress=prog, message=f"Narration: scene {i+1}/{len(scenes)}")
        ps.save_storyboard(pid, scenes)
        ps.write_json(pdir / "timings.json", {"timings": timings, "total_sec": cursor})

        # 4) Subtitles
        _set(db, job, stage="subtitles", progress=62, message="Generating subtitles...")
        segs = timings_to_segments(timings)
        srt_path = pdir / "subs" / "subtitles.srt"
        vtt_path = pdir / "subs" / "subtitles.vtt"
        segments_to_srt(segs, srt_path); segments_to_vtt(segs, vtt_path)

        # 5) Audio mix
        _set(db, job, stage="audio_mix", progress=68, message="Mixing audio...")
        voice_concat = pdir / "audio" / "narration_full.wav"
        concat_wavs(wavs, voice_concat)
        music_path = None  # resolve from assets if selected
        if proj.music_track and proj.music_track != "none":
            cand = (Path(settings.__dict__.get('assets_dir', '')) / "music" / proj.music_track) if False else None
            from ..core.config import ASSETS_DIR
            cand = ASSETS_DIR / "music" / proj.music_track
            if cand.exists(): music_path = cand
        final_audio = pdir / "audio" / "final_mix.wav"
        mix_narration_music(voice_concat, final_audio, music_path)

        # 6) Per-scene video segments
        _set(db, job, stage="render_scenes", progress=72, message="Rendering scene videos...")
        seg_paths = []
        for i, sc in enumerate(scenes):
            seg_out = pdir / "video" / "scenes" / f"scene_{i+1:02d}.mp4"
            render_scene_segment(Path(sc["image_path"]), float(sc.get("render_dur", sc.get("duration_sec",5))), seg_out,
                                 aspect=proj.aspect_ratio, motion=sc.get("camera","slow_zoom_in"), fps=30)
            seg_paths.append(seg_out)
            sc["video_path"] = str(seg_out)
            prog = 72 + int(18 * (i+1)/max(1,len(scenes)))
            _set(db, job, progress=prog, message=f"Rendering: scene {i+1}/{len(scenes)}")
        ps.save_storyboard(pid, scenes)

        # 7) Concat + mux
        _set(db, job, stage="compose", progress=92, message="Composing final video...")
        video_concat = pdir / "video" / "video_concat.mp4"
        concat_segments(seg_paths, video_concat)
        out_name = f"final_{proj.aspect_ratio.replace(':','x')}_720p.mp4"
        final_out = pdir / "renders" / out_name
        mux_final(video_concat, final_audio, final_out, srt_path=srt_path, burn_subs=False)

        # 8) Metadata
        duration = probe_video_dur(final_out)
        result = {
            "final_video": str(final_out),
            "srt": str(srt_path), "vtt": str(vtt_path),
            "duration_sec": duration,
            "aspect_ratio": proj.aspect_ratio, "resolution": "720p",
            "scenes": len(scenes),
            "tts_engine": scenes[0].get("tts_engine") if scenes else None,
        }
        ps.write_json(pdir / "result.json", result)
        proj.status = "completed"; proj.updated_at = _now()
        _set(db, job, status="succeeded", stage="done", progress=100, message="Completed", meta=result)
        db.commit()
        _log(pid, f"pipeline succeeded: {final_out}")
    except Exception as e:
        tb = traceback.format_exc()
        try:
            job = _job(db, job_id)
            if job:
                pid = job.project_id
                _set(db, job, status="failed", stage=job.stage or "error", progress=job.progress, message="Failed", error=str(e)[:2000])
                _log(pid, f"FAILED: {e}\n{tb}")
                proj = db.get(Project, job.project_id)
                if proj: proj.status = "failed"; proj.updated_at = _now(); db.commit()
        except Exception:
            pass
    finally:
        db.close()

def run_scene_regen(project_id: str, scene_index: int, job_id: str):
    db = SessionLocal()
    try:
        job = _job(db, job_id); proj = db.get(Project, project_id)
        if not job or not proj: return
        _set(db, job, status="running", stage="regen_scene", progress=10, message=f"Regenerating scene {scene_index+1}")
        script = ps.load_script(project_id) or {}
        script = regenerate_scene(script, scene_index)
        ps.save_script(project_id, script)
        scenes = script.get("scenes", []); ps.save_storyboard(project_id, scenes)
        sc = scenes[scene_index]
        pdir = ps.project_dir(project_id)
        # visual
        img_path = pdir / "images" / f"scene_{scene_index+1:02d}.png"
        generate_scene_image(sc, img_path, aspect=proj.aspect_ratio, style=proj.style, idx=scene_index)
        sc["image_path"] = str(img_path); sc["visual_kind"] = "animated_graphic"
        _set(db, job, progress=40, message="Regenerating narration...")
        wav_path = pdir / "audio" / f"scene_{scene_index+1:02d}.wav"
        res = synthesize(sc.get("narration",""), wav_path, voice=proj.voice)
        dur = float(res.get("duration_sec") or probe_audio_dur(wav_path) or sc.get("duration_sec",5))
        sc["audio_path"] = str(wav_path); sc["actual_audio_dur"] = dur; sc["render_dur"] = max(2.0,dur)
        sc["tts_engine"] = res.get("engine"); sc["tts_voice"] = res.get("voice")
        ps.save_storyboard(project_id, scenes)
        _set(db, job, progress=70, message="Rendering scene segment...")
        seg_out = pdir / "video" / "scenes" / f"scene_{scene_index+1:02d}.mp4"
        render_scene_segment(Path(sc["image_path"]), float(sc.get("render_dur",5)), seg_out,
                             aspect=proj.aspect_ratio, motion=sc.get("camera","slow_zoom_in"), fps=30)
        sc["video_path"] = str(seg_out); ps.save_storyboard(project_id, scenes)
        _set(db, job, status="succeeded", stage="done", progress=100, message="Scene regenerated. Re-render final to apply.", meta={"scene": scene_index})
    except Exception as e:
        try:
            job = _job(db, job_id)
            if job: _set(db, job, status="failed", error=str(e)[:2000], message="Failed")
        except Exception: pass
    finally:
        db.close()
