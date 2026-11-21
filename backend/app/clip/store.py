"""Engine B filesystem layout.

Kept separate from ``services.project_store`` (Engine A layout) so neither
engine's cleanup or migration code can delete the other's artifacts.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..core.config import CLIP_PROJECTS_DIR


def clip_dir(project_id: str) -> Path:
    root = CLIP_PROJECTS_DIR / project_id
    for sub in ("source", "analysis", "clips", "exports", "logs", "tmp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def clip_paths(project_id: str) -> dict[str, Path]:
    d = clip_dir(project_id)
    return {
        "root": d,
        "source": d / "source",
        "analysis": d / "analysis",
        "clips": d / "clips",
        "exports": d / "exports",
        "logs": d / "logs",
        "tmp": d / "tmp",
    }


def source_artifact_dir(project_id: str, source_id: str) -> Path:
    """Per-source analysis artifacts (transcript + audio) for multi-source jobs."""
    d = clip_paths(project_id)["analysis"] / "sources" / str(source_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def source_transcript_path(project_id: str, source_id: str) -> Path:
    return source_artifact_dir(project_id, source_id) / "transcript.json"


def source_whisper_path(project_id: str, source_id: str) -> Path:
    return source_artifact_dir(project_id, source_id) / "whisper_output.json"


def source_audio_path(project_id: str, source_id: str) -> Path:
    return source_artifact_dir(project_id, source_id) / "audio16k.wav"


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(path: Path, default=None):
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def log(project_id: str, message: str) -> None:
    from datetime import datetime

    p = clip_dir(project_id) / "logs" / "clip.log"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(f"[{datetime.utcnow().isoformat()}] {message}\n")


def cleanup_tmp(project_id: str) -> None:
    tmp = clip_dir(project_id) / "tmp"
    for item in tmp.glob("*"):
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except Exception:
            pass


def remove_project_files(project_id: str) -> None:
    shutil.rmtree(CLIP_PROJECTS_DIR / project_id, ignore_errors=True)
