from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from .env import capture_environment
from .metrics import sample_once
from .report import generate_reports
from .runner import REPO_ROOT, run_engine_a_baseline
from .store import list_runs_index, load_run, save_run

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

_active: dict[str, Any] = {"running": False, "run_id": None, "message": ""}


@router.get("/environment")
def environment():
    return capture_environment(REPO_ROOT)


@router.get("/sample")
def sample():
    from ..core.config import settings
    return sample_once(Path(settings.data_dir))


@router.get("/runs")
def runs():
    return {"runs": list_runs_index(), "active": _active}


@router.get("/runs/{run_id}")
def run_detail(run_id: str):
    r = load_run(run_id)
    if not r:
        raise HTTPException(404, "Benchmark run not found")
    return r


@router.post("/runs/{run_id}/report")
def regenerate_report(run_id: str):
    r = load_run(run_id)
    if not r:
        raise HTTPException(404, "Benchmark run not found")
    paths = generate_reports(r)
    r["reports"] = paths
    save_run(r)
    return {"ok": True, "reports": paths}


def _run_bg(cases, title: str):
    global _active
    _active = {"running": True, "run_id": None, "message": "Starting baseline suite"}
    try:
        run = run_engine_a_baseline(cases=cases, title=title)
        _active = {"running": False, "run_id": run.get("id"), "message": run.get("status", "done")}
    except Exception as e:
        _active = {"running": False, "run_id": _active.get("run_id"), "message": f"failed: {e}"}


@router.post("/run/baseline")
def run_baseline(body: dict[str, Any] | None = None, background: BackgroundTasks = None):  # type: ignore[assignment]
    if _active.get("running"):
        raise HTTPException(409, "A benchmark run is already in progress")
    body = body or {}
    cases = body.get("cases")
    title = body.get("title") or "Engine A Baseline"
    # run in background thread to avoid blocking if BackgroundTasks behaves differently
    t = threading.Thread(target=_run_bg, args=(cases, title), daemon=True)
    t.start()
    return {"ok": True, "started": True, "active": _active, "note": "Benchmark running; poll /api/benchmark/runs for progress/results."}
