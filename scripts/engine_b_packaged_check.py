#!/usr/bin/env python
"""Engine B smoke check against the *packaged* desktop app (real loopback HTTP).

The Electron shell picks a free port for its bundled backend, so this harness
reads the port from the app's own backend log and verifies /health first. If the
app is not running it exits 3 with NOT_RUN — it never starts a service or
pretends a packaged check happened.

Usage:
    open "dist-desktop/mac-arm64/AI Social Video Studio.app"
    PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_packaged_check.py
    # or: ... --base-url http://127.0.0.1:50842 --keep
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

import httpx  # noqa: E402

from engine_b_e2e import SENTENCES, build_fixture  # noqa: E402

LOG = Path.home() / "Library/Application Support/AI Social Video Studio/logs/backend.log"
APP = REPO / "dist-desktop/mac-arm64/AI Social Video Studio.app"


def packaged_port() -> str | None:
    if not LOG.exists():
        return None
    import re

    ports = re.findall(r"starting backend on 127\.0\.0\.1:(\d+)", LOG.read_text(errors="replace"))
    return ports[-1] if ports else None


def wait_job(client: httpx.Client, jid: str, timeout: float = 300) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        last = client.get(f"/api/clip/jobs/{jid}").json()["job"]
        if last["status"] in ("succeeded", "failed", "canceled", "interrupted"):
            return last
        time.sleep(0.4)
    return last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="override the discovered packaged backend URL")
    ap.add_argument("--keep", action="store_true", help="keep generated fixture and clip project")
    args = ap.parse_args()

    base = args.base_url
    port = packaged_port()
    if not base and port:
        base = f"http://127.0.0.1:{port}"
    if not base:
        print("NOT_RUN: packaged app is not running (no backend port in its log). "
              'Launch it with: open "dist-desktop/mac-arm64/AI Social Video Studio.app"')
        return 3

    client = httpx.Client(base_url=base, timeout=120)
    try:
        health = client.get("/health", timeout=5).json()
    except Exception as exc:
        print(f"NOT_RUN: packaged backend unreachable at {base}: {exc}")
        return 3
    if not health.get("ok"):
        print(f"NOT_RUN: packaged /health returned {health}")
        return 3
    caps = client.get("/api/clip/capabilities").json()
    if not caps.get("asr", {}).get("available"):
        print("NOT_RUN: packaged ASR unavailable:", caps.get("asr", {}).get("reasons"))
        return 3

    work = Path(tempfile.mkdtemp(prefix="packaged_clip_"))
    run_id = uuid.uuid4().hex[:12]
    fixture = build_fixture(work, SENTENCES[:5])
    pid = None
    try:
        pid = client.post("/api/clip/projects", json={
            "title": f"Packaged ASR check {run_id}", "aspect_ratio": "9:16",
        }).json()["project"]["id"]
        with open(fixture["video"], "rb") as fh:
            upload = client.post(f"/api/clip/projects/{pid}/source",
                                 files={"file": (Path(fixture["video"]).name, fh,
                                                 "application/octet-stream")})
        t0 = time.time()
        analyze = wait_job(client, client.post(f"/api/clip/projects/{pid}/analyze").json()["job"]["id"])
        transcribe = wait_job(client, client.post(f"/api/clip/projects/{pid}/transcribe").json()["job"]["id"])
        transcript = client.get(f"/api/clip/projects/{pid}/transcript").json().get("transcript") or {}
        highlights = wait_job(client, client.post(f"/api/clip/projects/{pid}/highlights",
                                                  json={"durations": [15], "count": 1}).json()["job"]["id"])
        clips = client.get(f"/api/clip/projects/{pid}/clips").json().get("clips", [])
        render = {}
        if clips:
            rj = wait_job(client, client.post(f"/api/clip/clips/{clips[0]['id']}/render", json={
                "aspect": "9:16", "burn_captions": True,
                "crop": {"mode": "center"}, "audio": {"normalize": True},
            }).json()["job"]["id"])
            render = (rj.get("meta") or {}).get("result") or {}
            render["_status"] = rj["status"]
        validation = render.get("validation") or {}
        checks = {
            "health_ok": health.get("ok") is True,
            "packaged_asr_available": caps["asr"]["available"],
            "upload": upload.status_code == 200,
            "analyze": analyze["status"] == "succeeded",
            "transcribe": transcribe["status"] == "succeeded",
            "transcript_sentences": len(transcript.get("sentences") or []) >= 4,
            "native_word_timing": transcript.get("word_timing") == "native",
            "highlights": highlights["status"] == "succeeded" and bool(clips),
            "render": render.get("_status") == "succeeded",
            "validation_ok": validation.get("ok") is True,
            "cues": int(render.get("cues") or 0) > 0,
        }
        report = {
            "id": run_id,
            "kind": "engine_b_packaged_check",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "PASS" if all(checks.values()) else "FAIL",
            "environment": {
                "app_bundle": str(APP),
                "app_exists": APP.exists(),
                "backend_url": base,
                "data_dir": health.get("data_dir"),
                "ffmpeg": health.get("ffmpeg"),
                "asr": caps["asr"],
                "fixture": {"kind": "synthetic macOS TTS + FFmpeg colour video",
                            "sentences": len(SENTENCES[:5]),
                            "duration_sec": fixture["duration"]},
            },
            "checks": checks,
            "metrics": {
                "wall_sec": round(time.time() - t0, 2),
                "transcribe_peak_rss_mb": transcribe.get("peak_memory_mb"),
                "segments": len(transcript.get("segments") or []),
                "sentences": len(transcript.get("sentences") or []),
                "word_timing": transcript.get("word_timing"),
                "clips": len(clips),
                "cues": render.get("cues"),
                "validation": validation,
            },
            "note": "Real loopback HTTP against the backend embedded in the packaged .app. "
                    "Source is synthetic TTS, so this verifies wiring, not human-speech accuracy.",
        }
        out = REPO / "benchmarks" / "data" / "engine_b" / f"packaged_{run_id}.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"], "checks": checks,
                          "metrics": report["metrics"]}, indent=2))
        print("report:", out)
        return 0 if report["status"] == "PASS" else 1
    finally:
        if pid and not args.keep:
            try:
                client.delete(f"/api/clip/projects/{pid}")
            except Exception:
                pass
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print("kept fixture:", work)


if __name__ == "__main__":
    raise SystemExit(main())
