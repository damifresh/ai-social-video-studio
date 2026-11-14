from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.config import settings

BENCH_DIR = Path(settings.data_dir).parent / "benchmarks"
RUNS_DIR = BENCH_DIR / "data" / "runs"
REPORTS_DIR = BENCH_DIR / "reports"


def ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def run_path(run_id: str) -> Path:
    ensure_dirs()
    return RUNS_DIR / f"{run_id}.json"


def save_run(run: dict[str, Any]) -> Path:
    ensure_dirs()
    run["updated_at"] = now_iso()
    p = run_path(run["id"])
    p.write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")
    # index
    idx = list_runs_index()
    entry = {
        "id": run["id"],
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "status": run.get("status"),
        "suite": run.get("suite"),
        "title": run.get("title"),
        "summary": run.get("summary"),
    }
    idx = [e for e in idx if e.get("id") != run["id"]] + [entry]
    idx.sort(key=lambda e: e.get("updated_at") or "", reverse=True)
    (RUNS_DIR / "index.json").write_text(json.dumps(idx[:200], indent=2), encoding="utf-8")
    return p


def load_run(run_id: str) -> dict[str, Any] | None:
    p = run_path(run_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def list_runs_index() -> list[dict[str, Any]]:
    ensure_dirs()
    p = RUNS_DIR / "index.json"
    if not p.exists():
        # rebuild
        items = []
        for f in sorted(RUNS_DIR.glob("*.json"), reverse=True):
            if f.name == "index.json":
                continue
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
                items.append({"id": r.get("id"), "created_at": r.get("created_at"), "updated_at": r.get("updated_at"), "status": r.get("status"), "suite": r.get("suite"), "title": r.get("title"), "summary": r.get("summary")})
            except Exception:
                pass
        return items
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
