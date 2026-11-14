#!/usr/bin/env python3
"""Run the M2 hardware benchmark suite (Engine A baseline) and generate reports.

Usage:
  cd local-ai-video-studio
  PYTHONPATH=backend backend/.venv/bin/python scripts/benchmark_suite.py [--quick] [--full]

By default runs a quick baseline (30s-target-ish + 60s target). Use --full to add 3-min.
Results are saved to benchmarks/data/runs/*.json and benchmarks/reports/*.html|.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.benchmark.runner import run_engine_a_baseline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="Run 1-min target cases only (default)")
    ap.add_argument("--full", action="store_true", help="Include 3-minute case")
    ap.add_argument("--json", action="store_true", help="Print JSON summary to stdout")
    args = ap.parse_args()

    cases = [
        {"id": "VC-60S", "name": "Video Creator 60s target 16:9", "duration_min": 1, "aspect_ratio": "16:9", "fps": 30, "voice": "say:Samantha", "music_track": "ambient_calm_loop.wav", "music_volume": 0.1, "burn_subs": True, "topic": "How to plan your day in five simple steps", "prompt": "Practical, structured narration."},
    ]
    if args.full:
        cases.append({"id": "VC-3M", "name": "Video Creator 3-minute target 16:9", "duration_min": 3, "aspect_ratio": "16:9", "fps": 30, "voice": "say:Samantha", "music_track": "ambient_calm_loop.wav", "music_volume": 0.1, "burn_subs": True, "topic": "The basics of personal budgeting", "prompt": "Educational, step-by-step."})
    if not args.full and not args.quick:
        # default quick
        pass

    title = "Engine A Baseline (CLI full)" if args.full else "Engine A Baseline (CLI quick)"
    print(f"Starting {title} with {len(cases)} case(s)...", flush=True)
    run = run_engine_a_baseline(cases=cases, title=title)
    summary = {
        "id": run.get("id"),
        "status": run.get("status"),
        "summary": run.get("summary"),
        "reports": run.get("reports"),
        "tests": [{"id": t.get("id"), "status": t.get("status"), "wall_time_sec": t.get("wall_time_sec"), "output_duration_sec": t.get("output_duration_sec"), "peak_app_rss_mb": t.get("peak_app_rss_mb"), "processing_speed_ratio": t.get("processing_speed_ratio")} for t in run.get("tests", [])],
    }
    print(json.dumps(summary, indent=2))
    if args.json:
        print(json.dumps(run))
    return 0 if run.get("status") in ("completed",) and run.get("summary", {}).get("fail", 1) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
