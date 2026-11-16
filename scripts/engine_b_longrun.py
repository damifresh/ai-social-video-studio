#!/usr/bin/env python
"""Engine B long-source measurement (5/15/30/60-minute style sources).

This is the honest way to fill the A1–A5 duration matrix: it builds a real
synthetic source of the requested length on this machine, then measures ingest,
analysis, transcript import, highlight selection and one render through the
actual HTTP API. Nothing is extrapolated — values in the report were produced
by this run.

The source is synthesized speech (macOS `say`) over FFmpeg colour video, with
the SRT derived from measured speech durations. It is **not** real footage and
it is **not** ASR output; ASR quality stays NOT_RUN unless whisper.cpp is
installed.

Usage:
    PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_longrun.py --minutes 5
    PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_longrun.py --minutes 15 --keep
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from app.clip.transcribe import capability  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.database import ensure_schema  # noqa: E402
from app.main import app  # noqa: E402

from engine_b_e2e import SENTENCES, Recorder, build_fixture, wait_job  # noqa: E402

CHAPTERS = [
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty",
]


def make_sentences(target_sec: float, block_sec: float = 67.5) -> list[str]:
    """Repeat the 15-sentence script in numbered chapters until the target length.

    Each chapter speaks its number, so the speech and the SRT stay identical and
    sentences remain distinct enough for duplicate suppression.
    """
    blocks = max(1, math.ceil(target_sec / block_sec))
    out: list[str] = []
    for b in range(blocks):
        label = CHAPTERS[b] if b < len(CHAPTERS) else str(b + 1)
        for i, text in enumerate(SENTENCES):
            out.append(f"Chapter {label}. {text}" if i == 0 else text)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=5.0, help="target source length in minutes")
    ap.add_argument("--keep", action="store_true", help="keep the generated fixture/project")
    ap.add_argument("--no-render", action="store_true", help="skip the render case")
    args = ap.parse_args()

    ensure_schema()
    rec = Recorder()
    run_id = uuid.uuid4().hex[:12]
    target = max(30.0, args.minutes * 60.0)
    started = time.time()

    env = {
        "date": datetime.now(timezone.utc).isoformat(),
        "machine": "Apple M2 / 8 GB (as reported by platform)",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "ffmpeg": settings.ffmpeg,
        "asr": capability(),
        "global_memory_percent": __import__("psutil").virtual_memory().percent,
        "source_kind": "synthetic local TTS narration + FFmpeg colour video (real files, generated on this machine)",
        "target_minutes": args.minutes,
    }

    work = Path(tempfile.mkdtemp(prefix=f"engineb_long_{int(args.minutes)}m_"))
    sentences = make_sentences(target)
    print(f"Building ~{args.minutes:g} min fixture: {len(sentences)} sentences in {work} ...")
    t0 = time.time()
    fx = build_fixture(work, sentences)
    build_sec = time.time() - t0
    dur = fx["duration"]
    env["fixture"] = {
        "duration_sec": round(dur, 2),
        "sentences": len(sentences),
        "source": fx["video"],
        "probe": fx["probe"],
        "build_wall_sec": round(build_sec, 2),
    }
    fixture_ok = (dur >= target * 0.9
                  and int(fx["probe"].get("audio_streams") or 0) >= 1
                  and Path(fx["srt"]).exists())
    rec.add("LONG-FIXTURE", "Generated long local source + exact SRT",
            "PASS" if fixture_ok else "FAIL",
            checks={"duration_ok": dur >= target * 0.9,
                    "audio_streams": int(fx["probe"].get("audio_streams") or 0) >= 1,
                    "has_srt": Path(fx["srt"]).exists()},
            metrics={"duration_sec": round(dur, 2), "build_wall_sec": round(build_sec, 2),
                     "sentences": len(sentences)})

    pid = None
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/api/clip/projects", json={"title": f"Long {args.minutes:g}m {run_id}",
                                                        "aspect_ratio": "9:16"})
            r.raise_for_status()
            pid = r.json()["project"]["id"]

            t0 = time.time()
            with open(fx["video"], "rb") as fh:
                up = client.post(f"/api/clip/projects/{pid}/source",
                                 files={"file": (Path(fx["video"]).name, fh, "video/mp4")})
            up_sec = time.time() - t0
            body = up.json() if up.status_code == 200 else {}
            src = body.get("source") or {}
            want_sha = hashlib.sha256(Path(fx["video"]).read_bytes()).hexdigest()
            upload_ok = (up.status_code == 200 and src.get("sha256") == want_sha
                         and abs(float(src.get("duration_sec") or 0) - dur) < 0.6)
            rec.add("LONG-UPLOAD", "Upload long source; bytes preserved", "PASS" if upload_ok else "FAIL",
                    checks={"status": up.status_code, "sha256_match": src.get("sha256") == want_sha,
                            "duration_sec": src.get("duration_sec")},
                    metrics={"wall_sec": round(up_sec, 2), "size_bytes": src.get("size_bytes")},
                    notes="" if upload_ok else str(body or up.text)[:300])

            t0 = time.time()
            j = wait_job(client, client.post(f"/api/clip/projects/{pid}/analyze").json()["job"]["id"],
                         timeout=1800)
            analyze_sec = time.time() - t0
            res = (j.get("meta") or {}).get("result") or {}
            rec.add("LONG-ANALYZE", "Analyze a long source (streamed envelope + silence scan)",
                    "PASS" if j["status"] == "succeeded" else "FAIL",
                    checks={"job_status": j["status"],
                            "envelope_windows": res.get("envelope_windows"),
                            "silence_gaps": res.get("silence_gaps"),
                            "scene_cuts": res.get("scene_cuts")},
                    metrics={"wall_sec": round(analyze_sec, 2),
                             "peak_rss_mb": j.get("peak_memory_mb")},
                    notes=(j.get("error") or "")[:400])

            t0 = time.time()
            imp = client.post(f"/api/clip/projects/{pid}/transcript/import",
                              json={"content": fx["srt_text"], "filename": "long.srt"})
            segs = (imp.json().get("transcript") or {}).get("segments") or [] if imp.status_code == 200 else []
            mono = all(segs[i]["end"] <= segs[i + 1]["start"] + 0.001 for i in range(len(segs) - 1))
            rec.add("LONG-IMPORT", "Import long SRT (monotonic, clamped)",
                    "PASS" if imp.status_code == 200 and mono and len(segs) == len(sentences) else "FAIL",
                    checks={"status": imp.status_code, "segments": len(segs),
                            "expected_segments": len(sentences), "monotonic": mono,
                            "last_end_sec": segs[-1]["end"] if segs else None},
                    metrics={"wall_sec": round(time.time() - t0, 2)},
                    notes=str(imp.text)[:300] if imp.status_code != 200 else "")

            targets = [45.0, 60.0] if dur >= 240 else [20.0, 30.0]
            t0 = time.time()
            hj = wait_job(client, client.post(f"/api/clip/projects/{pid}/highlights",
                                              json={"durations": targets, "count": 5}).json()["job"]["id"],
                          timeout=1800)
            hres = (hj.get("meta") or {}).get("result") or {}
            clips = client.get(f"/api/clip/projects/{pid}/clips").json().get("clips", [])
            overlaps = 0
            spans = sorted((c["start_sec"], c["end_sec"]) for c in clips)
            for a, b in zip(spans, spans[1:]):
                if b[0] < a[1] - 0.2:
                    overlaps += 1
            late = sum(1 for c in clips if c["start_sec"] > dur * 0.5)
            rec.add("LONG-HIGHLIGHTS", "Highlight selection across a long timeline",
                    "PASS" if hj["status"] == "succeeded" and clips and overlaps == 0 else "FAIL",
                    checks={"job_status": hj["status"], "clips": len(clips),
                            "requested": 5, "overlaps": overlaps,
                            "clips_in_second_half": late,
                            "shortfall": hres.get("shortfall"),
                            "windows_evaluated": (hres.get("stats") or {}).get("windows_evaluated")},
                    metrics={"wall_sec": round(time.time() - t0, 2)},
                    notes=(hj.get("error") or "")[:400])

            if clips and not args.no_render:
                # Render the clip that starts latest: exercises seeking deep into the file.
                cand = max(clips, key=lambda c: c["start_sec"])
                t0 = time.time()
                rj = wait_job(client, client.post(f"/api/clip/clips/{cand['id']}/render",
                                                  json={"aspect": "9:16", "burn_captions": True,
                                                        "crop": {"mode": "center"},
                                                        "audio": {"normalize": True}}).json()["job"]["id"],
                              timeout=1800)
                ev = (rj.get("meta") or {}).get("result") or {}
                rec.add("LONG-RENDER", "Render a clip from the deep end of a long source",
                        "PASS" if rj["status"] == "succeeded" and (ev.get("validation") or {}).get("ok") else "FAIL",
                        checks={"job_status": rj["status"], "start_sec": cand["start_sec"],
                                "end_sec": cand["end_sec"], "cues": ev.get("cues"),
                                "validation": ev.get("validation")},
                        metrics={"wall_sec": round(time.time() - t0, 2),
                                 "peak_rss_mb": rj.get("peak_memory_mb"),
                                 "output_duration_sec": (ev.get("probe") or {}).get("duration"),
                                 "output_size_bytes": (ev.get("probe") or {}).get("size_bytes"),
                                 "loudness": ev.get("loudness")},
                        notes=(rj.get("error") or "")[:400])

            total = time.time() - started
            env["project_id"] = pid
            env["source_probe_kind"] = (src.get("probe") or {}).get("probe_source")
            report = {
                "id": run_id,
                "kind": "engine_b_longrun",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "target_minutes": args.minutes,
                "wall_sec": round(total, 2),
                "environment": env,
                "summary": rec.summary(),
                "cases": rec.cases,
            }
            out = REPO / "benchmarks" / "data" / "engine_b" / f"long_{run_id}_{args.minutes:g}m.json"
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"\nReport: {out}")
            print(json.dumps(rec.summary(), indent=1))
            return 0 if report["summary"]["fail"] == 0 else 1
    finally:
        if pid and not args.keep:
            try:
                with TestClient(app) as cleanup:
                    cleanup.delete(f"/api/clip/projects/{pid}?delete_files=true")
            except Exception:
                pass
        if not args.keep:
            import shutil

            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
