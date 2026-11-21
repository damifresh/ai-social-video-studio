"""Manifest-based, exact-stage resume for Engine A renders.

A stage is skipped only when all three conditions hold:

1. the manifest records the same input signature for that stage,
2. every artifact the stage produces still exists and is non-empty, and
3. the current input signature still matches what was recorded.

Signatures include the input files' size and mtime, so replacing an image,
audio file, subtitle file or scene segment invalidates the affected stages.
No stage is skipped on artifact existence alone.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import project_store as ps

MANIFEST = "resume.json"
VERSION = 1
STAGES = ("script", "visuals", "tts", "scenes", "audio_mix", "subtitles", "compose")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fmeta(path: Path) -> dict[str, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _scenes_meta(scenes: Iterable[dict], pdir: Path) -> list[dict[str, Any]]:
    out = []
    for i, sc in enumerate(scenes):
        n = i + 1
        image = Path(sc.get("image_path") or pdir / "images" / f"scene_{n:02d}.png")
        audio = pdir / "audio" / f"scene_{n:02d}.wav"
        segment = pdir / "video" / "scenes" / f"scene_{n:02d}.mp4"
        out.append({
            "index": n,
            "narration": sc.get("narration", ""),
            "tts_text": sc.get("tts_text", ""),
            "tts_engine": sc.get("tts_engine", ""),
            "render_dur": sc.get("render_dur"),
            "camera": sc.get("camera", "slow_zoom_in"),
            "transition": sc.get("transition", "cut"),
            "sfx": sc.get("sfx"),
            "image": str(image),
            "image_meta": _fmeta(image),
            "audio_meta": _fmeta(audio),
            "segment_meta": _fmeta(segment),
        })
    return out


def artifact_paths(project_id: str, stage: str, project: Any, scenes: list[dict], pdir: Path | None = None) -> list[Path]:
    """Files a stage is responsible for producing."""
    pdir = pdir or ps.project_dir(project_id)
    n = len(scenes)
    if stage == "script":
        return [pdir / "script.json", pdir / "scenes.json"]
    if stage == "visuals":
        return [Path(sc.get("image_path") or pdir / "images" / f"scene_{i + 1:02d}.png") for i, sc in enumerate(scenes)]
    if stage == "tts":
        return [pdir / "audio" / f"scene_{i + 1:02d}.wav" for i in range(n)] + [pdir / "timings.json"]
    if stage == "scenes":
        return [pdir / "video" / "scenes" / f"scene_{i + 1:02d}.mp4" for i in range(n)]
    if stage == "audio_mix":
        return [pdir / "audio" / "final_mix.wav", pdir / "audio" / "narration_full.wav"]
    if stage == "subtitles":
        return [] if not getattr(project, "subtitle_enabled", True) else [
            pdir / "subs" / "subtitles.srt",
            pdir / "subs" / "subtitles.vtt",
            pdir / "subs" / "subtitles.ass",
        ]
    if stage == "compose":
        aspect = str(getattr(project, "aspect_ratio", "16:9")).replace(":", "x")
        return [pdir / "renders" / f"final_{aspect}_720p.mp4", pdir / "result.json"]
    return []


def stage_signature(project_id: str, stage: str, project: Any, scenes: list[dict], pdir: Path | None = None) -> str:
    """Hash all inputs that affect this stage plus its produced file metadata."""
    pdir = pdir or ps.project_dir(project_id)
    common = {
        "project_id": project_id,
        "aspect_ratio": getattr(project, "aspect_ratio", "16:9"),
        "fps": getattr(project, "fps", 30),
        "style": getattr(project, "style", "cinematic"),
        "version": VERSION,
    }
    meta = _scenes_meta(scenes, pdir)

    if stage == "script":
        payload = {**common, "topic": getattr(project, "topic", ""), "prompt": getattr(project, "prompt", ""),
                   "title": getattr(project, "title", ""), "duration_min": getattr(project, "duration_min", 1),
                   "language": getattr(project, "language", "en"),
                   "scenes": [{"index": s["index"], "narration": s["narration"]} for s in meta]}
    elif stage == "visuals":
        payload = {**common, "scenes": [{"index": s["index"], "narration": s["narration"], "camera": s["camera"]} for s in meta]}
    elif stage == "tts":
        payload = {**common, "voice": getattr(project, "voice", ""),
                   "voice_speed": getattr(project, "voice_speed", 0),
                   "scenes": [{"index": s["index"], "narration": s["narration"], "tts_text": s["tts_text"],
                               "audio_meta": s["audio_meta"]} for s in meta]}
    elif stage == "scenes":
        payload = {**common, "scenes": [{k: s[k] for k in ("index", "image", "image_meta", "audio_meta", "render_dur", "camera", "transition")} for s in meta]}
    elif stage == "audio_mix":
        payload = {**common,
                   "music_track": getattr(project, "music_track", "none"),
                   "music_volume": getattr(project, "music_volume", 0.10),
                   "scenes": [{"index": s["index"], "audio_meta": s["audio_meta"], "sfx": s["sfx"], "render_dur": s["render_dur"]} for s in meta]}
    elif stage == "subtitles":
        payload = {**common,
                   "subtitle_enabled": getattr(project, "subtitle_enabled", True),
                   "subtitle_style": getattr(project, "subtitle_style", "{}"),
                   "timings_meta": _fmeta(pdir / "timings.json"),
                   "cues_meta": _fmeta(pdir / "subs" / "subtitles.srt")}
    elif stage == "compose":
        payload = {**common,
                   "subtitle_enabled": getattr(project, "subtitle_enabled", True),
                   "burn_subs": getattr(project, "burn_subs", True),
                   "subtitle_style": getattr(project, "subtitle_style", "{}"),
                   "music_track": getattr(project, "music_track", "none"),
                   "music_volume": getattr(project, "music_volume", 0.10),
                   "scenes": [{"index": s["index"], "audio_meta": s["audio_meta"], "segment_meta": s["segment_meta"], "sfx": s["sfx"]} for s in meta],
                   "subtitles_meta": _fmeta(pdir / "subs" / "subtitles.srt")}
    else:
        raise ValueError(f"unknown stage: {stage}")
    return _digest(payload)


def load_manifest(project_id: str, pdir: Path | None = None) -> dict[str, Any]:
    pdir = pdir or ps.project_dir(project_id)
    data = ps.read_json(pdir / MANIFEST, {}) or {}
    if data.get("version") != VERSION or not isinstance(data.get("stages"), dict):
        return {"version": VERSION, "updated_at": None, "stages": {}}
    return data


def mark_stage(project_id: str, stage: str, signature: str, pdir: Path | None = None) -> None:
    pdir = pdir or ps.project_dir(project_id)
    manifest = load_manifest(project_id, pdir)
    manifest["stages"][stage] = {"signature": signature, "at": _now()}
    manifest["updated_at"] = _now()
    ps.write_json(pdir / MANIFEST, manifest)


def can_skip(project_id: str, stage: str, signature: str, artifacts: list[Path], pdir: Path | None = None) -> bool:
    pdir = pdir or ps.project_dir(project_id)
    record = load_manifest(project_id, pdir)["stages"].get(stage) or {}
    if record.get("signature") != signature:
        return False
    return all(p.exists() and p.stat().st_size > 0 for p in artifacts)


def build_plan(project_id: str, project: Any, scenes: list[dict], pdir: Path | None = None) -> dict[str, dict[str, Any]]:
    pdir = pdir or ps.project_dir(project_id)
    plan: dict[str, dict[str, Any]] = {}
    for stage in STAGES:
        artifacts = artifact_paths(project_id, stage, project, scenes, pdir)
        signature = stage_signature(project_id, stage, project, scenes, pdir)
        plan[stage] = {
            "signature": signature,
            "artifacts": [str(p) for p in artifacts],
            "skip": can_skip(project_id, stage, signature, artifacts, pdir),
        }
    return plan
