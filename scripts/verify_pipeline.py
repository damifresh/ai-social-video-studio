#!/usr/bin/env python3
"""End-to-end verification against a running backend.

Creates a real project, runs the full pipeline, waits for completion, then
re-renders from the stored storyboard and reports measured output metrics.

Usage:
    PYTHONPATH=backend backend/.venv/bin/python scripts/verify_pipeline.py [--minutes 1] [--aspect 16:9]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
TIMEOUT = 60


def _wait(client: httpx.Client, job_id: str, label: str, limit_sec: float = 1800) -> dict:
    t0 = time.time()
    last = ""
    while time.time() - t0 < limit_sec:
        job = client.get(f"{BASE}/api/jobs/{job_id}", timeout=TIMEOUT).json()["job"]
        line = f"[{label}] {job['status']:9s} {job['progress']:3d}% {job['stage']:12s} {job['message'][:70]}"
        if line != last:
            print(line, flush=True)
            last = line
        if job["status"] in ("succeeded", "failed", "canceled", "interrupted"):
            return job
        time.sleep(2)
    raise TimeoutError(f"{label} exceeded {limit_sec}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=1)
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--music", default="ambient_calm_loop.wav")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--keep", action="store_true", help="keep the created project (default: keep for inspection)")
    args = ap.parse_args()

    with httpx.Client(timeout=TIMEOUT) as c:
        health = c.get(f"{BASE}/health").json()
        print("health:", json.dumps({k: health[k] for k in ("ok", "version", "ffmpeg_ok", "say", "kokoro", "whisper")}))
        body = {
            "title": f"Verification {args.minutes}min {args.aspect}",
            "topic": "How coastal cities are adapting to rising sea levels",
            "prompt": "Explain the problem, three adaptation strategies, a real-world example, and close with a hopeful call to action.",
            "duration_min": args.minutes,
            "aspect_ratio": args.aspect,
            "style": "documentary",
            "voice": "say:Samantha",
            "subtitle_enabled": True,
            "burn_subs": True,
            "music_track": args.music,
            "music_volume": 0.12,
            "fps": args.fps,
            "auto_mode": False,
        }
        proj = c.post(f"{BASE}/api/projects", json=body).json()["project"]
        pid = proj["id"]
        print(f"project {pid} created: {proj['title']}")

        t0 = time.time()
        job = c.post(f"{BASE}/api/projects/{pid}/generate").json()["job"]
        final = _wait(c, job["id"], "generate")
        elapsed = time.time() - t0
        if final["status"] != "succeeded":
            print("FAILED:", final.get("error"), file=sys.stderr)
            print(f"project id {pid}", file=sys.stderr)
            return 1
        meta = final.get("meta") or {}
        print(json.dumps({
            "phase": "generate",
            "seconds": round(elapsed, 1),
            "peak_memory_mb": final.get("peak_memory_mb"),
            "duration_sec": meta.get("duration_sec"),
            "resolution": meta.get("resolution"),
            "fps": meta.get("fps"),
            "size_bytes": meta.get("size_bytes"),
            "bitrate_kbps": meta.get("bitrate_kbps"),
            "subtitles_burned": meta.get("subtitles_burned"),
            "subtitle_cues": meta.get("subtitle_cues"),
            "scenes": meta.get("scenes"),
            "video": meta.get("final_video"),
        }, indent=2))

        # Re-render path (no narration regeneration needed if text unchanged)
        t1 = time.time()
        job2 = c.post(f"{BASE}/api/projects/{pid}/rerender?burn_subs=true").json()["job"]
        final2 = _wait(c, job2["id"], "rerender")
        if final2["status"] != "succeeded":
            print("RERENDER FAILED:", final2.get("error"), file=sys.stderr)
            return 1
        meta2 = final2.get("meta") or {}
        print(json.dumps({
            "phase": "rerender",
            "seconds": round(time.time() - t1, 1),
            "peak_memory_mb": final2.get("peak_memory_mb"),
            "duration_sec": meta2.get("duration_sec"),
            "size_bytes": meta2.get("size_bytes"),
            "subtitles_burned": meta2.get("subtitles_burned"),
        }, indent=2))

        detail = c.get(f"{BASE}/api/projects/{pid}").json()
        print("timings:", json.dumps({
            "total_sec": (detail.get("timings") or {}).get("total_sec"),
            "scenes": len(detail.get("scenes") or []),
            "cues": len(detail.get("subtitles") or []),
        }))
        video = Path(meta2.get("final_video") or meta.get("final_video") or "")
        print("project id:", pid)
        print("video path:", video)
        print("video exists:", video.exists(), video.stat().st_size if video.exists() else 0)
        print("subs:", sorted(str(p) for p in (video.parent.parent / "subs").glob("*")))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
