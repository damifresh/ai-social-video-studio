#!/usr/bin/env python3
"""Extended acceptance runs: a full 5-minute video and a 1:1 square video.

Runs against an already-running backend (dev or packaged). Reports measured
output properties and peak memory; writes a JSON report next to the script.

    PYTHONPATH=backend backend/.venv/bin/python scripts/verify_extended.py [--base URL]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

REPORT = Path(__file__).resolve().parents[1] / "deliverables" / "acceptance_extended.json"


def wait(client: httpx.Client, base: str, job_id: str, label: str) -> tuple[dict, float]:
    t0 = time.time()
    last = ""
    while True:
        job = client.get(f"{base}/api/jobs/{job_id}", timeout=60).json()["job"]
        line = f"[{label}] {job['status']:9s} {job['progress']:3d}% {job['stage']:11s} {job['message'][:64]}"
        if line != last:
            print(line, flush=True)
            last = line
        if job["status"] in ("succeeded", "failed", "canceled", "interrupted"):
            return job, time.time() - t0
        if time.time() - t0 > 2400:
            raise TimeoutError(f"{label} exceeded 40 minutes")
        time.sleep(3)


def run_case(client: httpx.Client, base: str, case: dict) -> dict:
    body = {
        "title": case["title"],
        "topic": case["topic"],
        "prompt": case["prompt"],
        "duration_min": case["minutes"],
        "aspect_ratio": case["aspect"],
        "style": case["style"],
        "voice": "say:Samantha",
        "fps": case.get("fps", 30),
        "music_track": case.get("music", "ambient_upbeat_loop.wav"),
        "music_volume": 0.11,
        "subtitle_enabled": True,
        "burn_subs": True,
        "auto_mode": False,
    }
    project = client.post(f"{base}/api/projects", json=body, timeout=60).json()["project"]
    pid = project["id"]
    print(f"\n=== {case['title']} · project {pid} ===", flush=True)
    job = client.post(f"{base}/api/projects/{pid}/generate", timeout=60).json()["job"]
    final, elapsed = wait(client, base, job["id"], "generate")
    if final["status"] != "succeeded":
        return {"case": case, "project_id": pid, "ok": False, "error": final.get("error")}

    detail = client.get(f"{base}/api/projects/{pid}", timeout=60).json()
    res = detail.get("result") or {}
    cues = detail.get("subtitles") or []
    timings = detail.get("timings") or {}
    out = Path(res.get("final_video") or "")
    row = {
        "case": case,
        "project_id": pid,
        "ok": True,
        "generate_seconds": round(elapsed, 1),
        "duration_sec": res.get("duration_sec"),
        "resolution": res.get("resolution"),
        "fps": res.get("fps"),
        "size_bytes": res.get("size_bytes"),
        "bitrate_kbps": res.get("bitrate_kbps"),
        "peak_memory_mb": res.get("peak_memory_mb"),
        "render_seconds": res.get("render_seconds"),
        "subtitles_burned": res.get("subtitles_burned"),
        "subtitle_cues": res.get("subtitle_cues"),
        "scenes": len(detail.get("scenes") or []),
        "timings_total_sec": timings.get("total_sec"),
        "last_cue_end": max((c.get("end", 0) for c in cues), default=None),
        "video": str(out),
        "video_exists": out.exists(),
        "video_bytes_on_disk": out.stat().st_size if out.exists() else 0,
        "tts_engines": sorted({s.get("tts_engine") for s in (detail.get("scenes") or []) if s.get("tts_engine")}),
        "fallbacks": sorted({s.get("tts_fallback") for s in (detail.get("scenes") or []) if s.get("tts_fallback")}),
    }
    print(json.dumps(row, indent=2), flush=True)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    cases = [
        {
            "title": "Acceptance 5min 16:9",
            "topic": "The quiet revolution in urban farming",
            "prompt": (
                "A five-minute documentary. Open on a rooftop garden at sunrise, explain why cities are "
                "rethinking food production, cover hydroponics and soil-based rooftop farms, discuss water "
                "and energy trade-offs, profile a community project, and close with what the next decade "
                "could look like."
            ),
            "minutes": 5,
            "aspect": "16:9",
            "style": "documentary",
            "music": "ambient_calm_loop.wav",
            "fps": 30,
        },
        {
            "title": "Acceptance 1min 1:1",
            "topic": "Three ways to make a small room feel bigger",
            "prompt": "Fast, practical interior-design tips with one concrete example per tip and a short close.",
            "minutes": 1,
            "aspect": "1:1",
            "style": "faceless",
            "music": "ambient_upbeat_loop.wav",
            "fps": 30,
        },
    ]
    results = []
    with httpx.Client(timeout=120) as client:
        health = client.get(f"{args.base}/health").json()
        print("health:", {k: health.get(k) for k in ("ok", "version", "ffmpeg_ok", "say", "kokoro", "whisper")}, flush=True)
        for case in cases:
            results.append(run_case(client, args.base, case))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({"base": args.base, "results": results}, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport: {REPORT}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
