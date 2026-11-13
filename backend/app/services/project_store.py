from __future__ import annotations
import json, shutil
from pathlib import Path
from ..core.config import PROJECTS_DIR

def project_dir(project_id: str) -> Path:
    p = PROJECTS_DIR / project_id
    for sub in ["audio","images","video","video/scenes","subs","renders","logs","assets"]:
        (p / sub).mkdir(parents=True, exist_ok=True)
    return p

def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def save_script(project_id: str, script: dict):
    d = project_dir(project_id)
    write_json(d / "script.json", script)
    # human-readable
    lines = [f"# {script.get('title','')}\n", script.get("full_text",""), "\n"]
    (d / "script.md").write_text("\n".join(lines), encoding="utf-8")

def save_storyboard(project_id: str, scenes: list[dict]):
    write_json(project_dir(project_id) / "scenes.json", {"scenes": scenes})

def load_storyboard(project_id: str) -> list[dict]:
    data = read_json(project_dir(project_id) / "scenes.json", {"scenes": []})
    return data.get("scenes", [])

def load_script(project_id: str) -> dict | None:
    return read_json(project_dir(project_id) / "script.json")

def project_paths(project_id: str) -> dict:
    d = project_dir(project_id)
    return {k: str(d / k) for k in ["","audio","images","video","subs","renders","logs"]} | {"root": str(d)}
