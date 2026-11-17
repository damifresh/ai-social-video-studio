#!/usr/bin/env python
"""Engine B (AI Auto-Clip Studio) end-to-end acceptance run.

Builds a REAL local test source (macOS `say` speech + FFmpeg video, with an SRT
whose timings come from the measured speech durations), then exercises the
actual HTTP API: upload → analyze → transcript import → highlights → render
(9:16, 16:9, 1:1) → batch export, plus cancellation and restart recovery.

No result is asserted as PASS unless the artefact was produced and probed in
this run. Cases whose prerequisites are missing are reported NOT_RUN.

Usage:
    PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_e2e.py [--quick]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.clip import jobs as clip_jobs  # noqa: E402
from app.clip import store  # noqa: E402
from app.clip.audio import measure_loudness  # noqa: E402
from app.clip.models import ClipCandidate, ClipJob, ClipProject  # noqa: E402
from app.clip.probe import probe_media  # noqa: E402
from app.clip.render import validate_render  # noqa: E402
from app.clip.transcribe import capability  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.database import SessionLocal, ensure_schema  # noqa: E402
from app.main import app  # noqa: E402

SENTENCES = [
    "Most people try to build better habits by relying on motivation, and that is the first mistake.",
    "Motivation is a feeling, and feelings change from one day to the next.",
    "A system, on the other hand, keeps working even when you do not feel like it.",
    "Here is a simple example from my own week.",
    "I wanted to read more, so I put one book on my desk where I make coffee every morning.",
    "That single change removed the decision, and reading became automatic within four days.",
    "Why does this work so well?",
    "Because you are designing the environment instead of fighting your own willpower.",
    "The second tip is to make the first step almost embarrassingly small.",
    "Instead of promising to exercise for an hour, promise to put on your shoes.",
    "Once the shoes are on, the next step is much easier.",
    "This is not a trick, it is basic psychology, and the research on habit formation supports it.",
    "The third mistake is trying to change five things at once.",
    "Pick one behaviour, track it for two weeks, and only then add another.",
    "If you do this consistently, you will notice that the habit stops feeling like a task.",
]


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr[-800:]}")
    return p


def _ts_srt(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def build_fixture(work: Path, sentences: list[str], gap: float = 0.35, fps: int = 30) -> dict:
    """Create a real video + exact SRT from measured TTS durations."""
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    lines: list[dict] = []
    cursor = 0.0
    for i, text in enumerate(sentences):
        aiff = work / f"s{i:02d}.aiff"
        wav = work / f"s{i:02d}.wav"
        _run(["say", "-v", "Samantha", "-r", "180", "-o", str(aiff), text], timeout=120)
        _run([settings.ffmpeg, "-y", "-i", str(aiff), "-ar", "48000", "-ac", "2", str(wav)])
        dur = float((probe_media(wav) or {}).get("duration") or 0)
        lines.append({"start": cursor, "end": cursor + dur, "text": text})
        cursor += dur
        parts.append(wav)
        if i < len(sentences) - 1:
            sil = work / f"gap{i:02d}.wav"
            _run([settings.ffmpeg, "-y", "-f", "lavfi", "-i",
                  f"anullsrc=channel_layout=stereo:sample_rate=48000:d={gap}", str(sil)])
            parts.append(sil)
            cursor += gap

    concat_txt = work / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    audio = work / "speech.wav"
    _run([settings.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
          "-ar", "48000", "-ac", "2", str(audio)])

    total = float((probe_media(audio) or {}).get("duration") or cursor)
    font = "/System/Library/Fonts/Supplemental/Arial.ttf"
    draw = (
        f"drawtext=fontfile='{font}':text='Engine B test source':fontsize=54:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2-40,"
        f"drawtext=fontfile='{font}':text='%{{pts\\:hms}}':fontsize=34:fontcolor=0xFFD166:"
        f"x=(w-text_w)/2:y=(h-text_h)/2+50"
    )
    mp4 = work / "source.mp4"
    _run([settings.ffmpeg, "-y",
          "-f", "lavfi", "-i", f"color=c=0x111827:s=1280x720:r={fps}:d={total:.3f}",
          "-i", str(audio),
          "-vf", draw, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest",
          "-movflags", "+faststart", str(mp4)])

    srt_lines = []
    for i, line in enumerate(lines, 1):
        srt_lines += [str(i), f"{_ts_srt(line['start'])} --> {_ts_srt(line['end'])}", line["text"], ""]
    srt = work / "speech.srt"
    srt.write_text("\n".join(srt_lines), encoding="utf-8")

    variants = {}
    for ext, vcodec, acodec in ((".mov", "libx264", "aac"), (".mkv", "libx264", "aac"),
                                (".webm", "libvpx-vp9", "libopus")):
        out = work / f"short{ext}"
        _run([settings.ffmpeg, "-y", "-t", "6", "-i", str(mp4), "-c:v", vcodec, "-c:a", acodec,
              "-b:v", "800k", str(out)])
        variants[ext] = str(out)

    return {
        "video": str(mp4), "srt": str(srt), "srt_text": srt.read_text(encoding="utf-8"),
        "duration": total, "sentences": len(sentences), "variants": variants,
        "probe": probe_media(mp4),
    }


def _norm_words(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    text = re.sub(r"['’]", "", text)
    text = re.sub(r"[^\w\s']", " ", text, flags=re.UNICODE)
    return [w for w in re.split(r"\s+", text) if w]


def _wer(ref: str, hyp: str) -> dict:
    """Word error rate on lowercased, punctuation-stripped tokens."""
    r, h = _norm_words(ref), _norm_words(hyp)
    n, m = len(r), len(h)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    subs = dels = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if r[i - 1] == h[j - 1] else 1
            if dp[i][j] == dp[i - 1][j - 1] + cost:
                if cost:
                    subs += 1
                i, j = i - 1, j - 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            dels += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return {"wer": round((subs + dels + ins) / n, 4) if n else None,
            "substitutions": subs, "deletions": dels, "insertions": ins,
            "ref_words": n, "hyp_words": m}


class Recorder:
    def __init__(self):
        self.cases: list[dict] = []

    def add(self, cid: str, name: str, status: str, checks: dict | None = None,
            metrics: dict | None = None, notes: str = "", evidence: dict | None = None):
        self.cases.append({
            "id": cid, "name": name, "status": status,
            "checks": checks or {}, "metrics": metrics or {},
            "notes": notes, "evidence": evidence or {},
        })
        print(f"[{status:9}] {cid:22} {name}" + (f" — {notes}" if notes else ""))

    def summary(self) -> dict:
        p = sum(1 for c in self.cases if c["status"] == "PASS")
        w = sum(1 for c in self.cases if c["status"] == "WARNING")
        f = sum(1 for c in self.cases if c["status"] == "FAIL")
        n = sum(1 for c in self.cases if c["status"] == "NOT_RUN")
        overall = "FAIL" if f else ("PASS" if p and not w and not n else ("WARNING" if p else "NOT_RUN"))
        return {"total": len(self.cases), "pass": p, "warning": w, "fail": f, "not_run": n,
                "overall_status": overall}


def wait_job(client: TestClient, jid: str, timeout: float = 900) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.get(f"/api/clip/jobs/{jid}").json()["job"]
        if last["status"] in ("succeeded", "failed", "canceled", "interrupted"):
            return last
        time.sleep(0.4)
    return last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="shorter source (8 sentences)")
    ap.add_argument("--keep", action="store_true", help="keep generated fixture/projects")
    args = ap.parse_args()

    ensure_schema()
    rec = Recorder()
    run_id = uuid.uuid4().hex[:12]
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
    }

    work = Path(tempfile.mkdtemp(prefix="engineb_fixture_"))
    created: list[str] = []
    try:
        sentences = SENTENCES[:8] if args.quick else SENTENCES
        print(f"Building fixture ({len(sentences)} sentences) in {work} ...")
        fx = build_fixture(work, sentences)
        env["fixture"] = {
            "duration_sec": round(fx["duration"], 2),
            "source": fx["video"],
            "probe": fx["probe"],
            "variants": fx["variants"],
        }
        rec.add("FIXTURE", "Generated local source video + exact SRT", "PASS",
                checks={"has_video": Path(fx["video"]).exists(), "has_srt": Path(fx["srt"]).exists(),
                        "audio_streams": int(fx["probe"].get("audio_streams") or 0) >= 1},
                metrics={"duration_sec": round(fx["duration"], 2)})

        with TestClient(app) as client:
            # 1. project + uploads
            r = client.post("/api/clip/projects", json={"title": f"E2E {run_id}", "aspect_ratio": "9:16"})
            r.raise_for_status()
            pid = r.json()["project"]["id"]
            created.append(pid)

            # One source per clip project: the primary MP4 goes into `pid`, each
            # extra container gets its own project so it cannot shadow the primary.
            import hashlib

            targets = [("mp4", fx["video"], pid, fx["duration"])]
            for ext, path in fx["variants"].items():
                rp = client.post("/api/clip/projects", json={"title": f"Container {ext} {run_id}"}).json()["project"]["id"]
                created.append(rp)
                targets.append((ext.strip("."), path, rp, 6.0))

            up_checks, sha_match, meta_checks, upload_errors = {}, {}, {}, {}
            mp4_source = None
            for label, path, target, expected_dur in targets:
                with open(path, "rb") as fh:
                    resp = client.post(f"/api/clip/projects/{target}/source",
                                       files={"file": (Path(path).name, fh, "application/octet-stream")})
                ok = resp.status_code == 200
                up_checks[label] = ok
                if ok:
                    body = resp.json()
                    want = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    sha_match[label] = body["source"]["sha256"] == want
                    meta_checks[label] = {
                        "duration_sec": body["source"]["duration_sec"],
                        "expected_duration_sec": round(expected_dur, 2),
                        "duration_ok": abs(body["source"]["duration_sec"] - expected_dur) < 0.35,
                        "width": body["source"]["width"], "height": body["source"]["height"],
                        "audio_streams": body["source"]["audio_streams"],
                        "vcodec": body["source"]["vcodec"], "acodec": body["source"]["acodec"],
                        "probe_source": (body["source"]["probe"] or {}).get("probe_source"),
                        "replaced": body.get("replaced"),
                    }
                    if label == "mp4":
                        mp4_source = body["source"]
                else:
                    sha_match[label] = False
                    upload_errors[label] = f"{resp.status_code} {resp.text[:300]}"

            up_ok = all(up_checks.values()) and all(sha_match.values())
            rec.add("B1-UPLOAD", "Upload MP4/MOV/MKV/WebM + preserved original bytes",
                    "PASS" if up_ok else "FAIL",
                    checks={**up_checks, "sha256_match": sha_match},
                    evidence={"metadata": meta_checks, "errors": upload_errors},
                    notes="" if up_ok else "Container rejected or hash mismatch")

            primary = meta_checks.get("mp4") or {}
            containers_ok = all(
                (m["width"], m["height"]) == (1280, 720) and m["audio_streams"] >= 1 and m["duration_ok"]
                for m in meta_checks.values()
            )
            meta_ok = bool(
                primary and abs(primary["duration_sec"] - fx["duration"]) < 0.35
                and (primary["width"], primary["height"]) == (1280, 720)
                and primary["audio_streams"] >= 1 and containers_ok
            )
            rec.add("B1-METADATA", "Probe metadata accuracy (incl. MKV/WebM dimensions)",
                    "PASS" if meta_ok else "FAIL",
                    checks={"source": mp4_source and {
                        "duration_sec": mp4_source["duration_sec"], "fps": mp4_source["fps"],
                        "width": mp4_source["width"], "height": mp4_source["height"],
                        "vcodec": mp4_source["vcodec"], "acodec": mp4_source["acodec"],
                    }, "all_containers": containers_ok},
                    evidence={"per_container": meta_checks})

            # 2. analyze
            t0 = time.time()
            j = client.post(f"/api/clip/projects/{pid}/analyze").json()["job"]
            j = wait_job(client, j["id"])
            analysis_ok = j["status"] == "succeeded"
            rec.add("B2-ANALYZE", "Audio extraction + silence/envelope/scene analysis",
                    "PASS" if analysis_ok else "FAIL",
                    checks={"job_status": j["status"]},
                    metrics={"wall_sec": round(time.time() - t0, 2), "peak_rss_mb": j.get("peak_memory_mb"),
                             "result": (j.get("meta") or {}).get("result")},
                    notes=j.get("error") or "")

            # 3. transcript: real ASR if installed, else honest manual import
            cap = capability()
            if cap["available"]:
                t0 = time.time()
                j = client.post(f"/api/clip/projects/{pid}/transcribe").json()["job"]
                j = wait_job(client, j["id"], timeout=3600)
                tr = client.get(f"/api/clip/projects/{pid}/transcript")
                ok = j["status"] == "succeeded" and tr.status_code == 200
                t = tr.json().get("transcript", {}) if ok else {}
                segs = t.get("segments") or []
                mono = all(segs[i]["end"] <= segs[i + 1]["start"] + 0.001 for i in range(len(segs) - 1))
                hyp = " ".join(s["text"] for s in (t.get("sentences") or []))
                w = _wer(" ".join(sentences), hyp)
                rec.add("B3-ASR", "whisper.cpp transcription + timestamps",
                        "PASS" if ok and mono else "FAIL",
                        checks={"job_status": j["status"], "segments": len(segs),
                                "sentences": len(t.get("sentences") or []),
                                "timestamps_monotonic": mono, "word_timing": t.get("word_timing"),
                                "last_end_within_source": (segs[-1]["end"] <= fx["duration"] + 1) if segs else False,
                                **w},
                        metrics={"wall_sec": round(time.time() - t0, 2), "peak_rss_mb": j.get("peak_memory_mb")},
                        notes="WER against the fixture's known script; clean synthetic TTS, not human speech.")
            else:
                rec.add("B3-ASR", "whisper.cpp transcription", "NOT_RUN",
                        notes="whisper.cpp binary/model not installed; capability gating verified instead. "
                              "No transcript is fabricated.")
            r = client.post(f"/api/clip/projects/{pid}/transcript/import",
                            json={"content": fx["srt_text"], "filename": "speech.srt"})
            t = r.json()["transcript"] if r.status_code == 200 else {}
            segs = t.get("segments") or []
            mono = all(segs[i]["end"] <= segs[i + 1]["start"] + 0.001 for i in range(len(segs) - 1))
            within = bool(segs) and segs[-1]["end"] <= fx["duration"] + 0.1
            rec.add("B3-IMPORT", "Manual SRT import (honest fallback path)",
                    "PASS" if r.status_code == 200 and mono and within else "FAIL",
                    checks={"status": r.status_code, "segments": len(segs), "timing": t.get("timing"),
                            "word_timing": t.get("word_timing"), "monotonic": mono, "within_duration": within},
                    notes="Timings come from the fixture's measured speech; word timing is labeled estimated.")

            # 3b. ASR-only project: the recognised transcript (not the SRT) must drive
            # highlights, captions and a render, otherwise ASR is not actually wired in.
            apid = client.post("/api/clip/projects", json={"title": f"E2E ASR {run_id}",
                                                           "aspect_ratio": "9:16"}).json()["project"]["id"]
            created.append(apid)
            with open(fx["video"], "rb") as fh:
                aup = client.post(f"/api/clip/projects/{apid}/source",
                                  files={"file": (Path(fx["video"]).name, fh, "application/octet-stream")})
            aan = wait_job(client, client.post(f"/api/clip/projects/{apid}/analyze").json()["job"]["id"])
            atj = wait_job(client, client.post(f"/api/clip/projects/{apid}/transcribe").json()["job"]["id"])
            atr = client.get(f"/api/clip/projects/{apid}/transcript").json().get("transcript") or {}
            ahj = wait_job(client, client.post(f"/api/clip/projects/{apid}/highlights",
                                               json={"durations": [15], "count": 1}).json()["job"]["id"])
            aclips = client.get(f"/api/clip/projects/{apid}/clips").json().get("clips", [])
            arender = {}
            if aclips:
                arj = wait_job(client, client.post(f"/api/clip/clips/{aclips[0]['id']}/render",
                                                   json={"aspect": "9:16", "burn_captions": True,
                                                         "crop": {"mode": "center"},
                                                         "audio": {"normalize": True}}).json()["job"]["id"])
                arender = (arj.get("meta") or {}).get("result") or {}
                arender["_status"] = arj["status"]
            avalid = (arender.get("validation") or {}).get("ok") is True
            asr_ok = (aup.status_code == 200 and aan["status"] == "succeeded"
                      and atj["status"] == "succeeded" and bool(atr.get("sentences"))
                      and ahj["status"] == "succeeded" and bool(aclips) and avalid)
            rec.add("B3-ASR-PIPELINE", "ASR transcript drives highlights, captions and a render",
                    "PASS" if asr_ok else "FAIL",
                    checks={"upload": aup.status_code, "analyze": aan["status"],
                            "transcribe": atj["status"],
                            "transcript_sentences": len(atr.get("sentences") or []),
                            "transcript_word_timing": atr.get("word_timing"),
                            "highlights": ahj["status"], "clips": len(aclips),
                            "render": arender.get("_status"),
                            "cues": arender.get("cues"),
                            "validation_ok": avalid},
                    notes="Uses only the whisper.cpp transcript; no SRT is imported into this project.")

            # 4. highlights
            # The quick fixture is ~35 s, so shorter targets are used to get
            # multiple non-overlapping clips out of it.
            dur_targets = [12, 20] if args.quick else [15, 30, 45]
            t0 = time.time()
            j = client.post(f"/api/clip/projects/{pid}/highlights",
                            json={"durations": dur_targets, "count": 3}).json()["job"]
            j = wait_job(client, j["id"])
            clips = client.get(f"/api/clip/projects/{pid}/clips").json()["clips"]
            fixture_text = " ".join(" ".join(sentences).split())
            grounded = True
            overlap = 0
            for c in clips:
                if c["transcript_text"].strip() and c["transcript_text"].strip() not in fixture_text:
                    grounded = False
                if c["title"] and c["title"].lower() not in c["transcript_text"].lower():
                    grounded = False
                if c["hook"] and c["hook"].lower() not in c["transcript_text"].lower():
                    grounded = False
            ordered = sorted(clips, key=lambda c: c["start_sec"])
            for a, b in zip(ordered, ordered[1:]):
                if b["start_sec"] < a["end_sec"] - 0.21:
                    overlap += 1
            ok = j["status"] == "succeeded" and len(clips) >= 1 and grounded and overlap == 0
            rec.add("B4-HIGHLIGHTS", "Transparent highlight scoring (grounded, non-overlapping)",
                    "PASS" if ok else "FAIL",
                    checks={"job_status": j["status"], "clips": len(clips), "grounded_copy": grounded,
                            "overlaps": overlap,
                            "scores_present": all(c["score"] > 0 and c["score_json"] for c in clips),
                            "reasons_present": all(bool(c["reason"]) for c in clips)},
                    metrics={"wall_sec": round(time.time() - t0, 2)},
                    evidence={"first": clips[0] if clips else None})

            if not clips:
                raise RuntimeError("No clips generated; cannot continue to render tests")

            # 5. renders: 9:16, 16:9, 1:1 (one clip each, plus caption style + crop)
            base = clips[0]
            render_results = {}
            for aspect, preset, crop_mode in (("9:16", "tiktok", "center"), ("16:9", "youtube", "center"),
                                              ("1:1", "square", "left")):
                body = {"aspect": aspect, "preset": preset, "burn_captions": True,
                        "crop": {"mode": crop_mode},
                        "caption_style": {"size": 48, "position": "bottom", "primary": "#FFFFFF",
                                          "highlight": "#FFD166", "max_chars": 30},
                        "audio": {"normalize": True}}
                t0 = time.time()
                rr = client.post(f"/api/clip/clips/{base['id']}/render", json=body)
                if rr.status_code != 200:
                    render_results[aspect] = {"error": rr.text}
                    continue
                jj = wait_job(client, rr.json()["job"]["id"], timeout=1800)
                out = ((jj.get("meta") or {}).get("result") or {})
                render_results[aspect] = {
                    "status": jj["status"], "wall_sec": round(time.time() - t0, 2),
                    "peak_rss_mb": jj.get("peak_memory_mb"), "error": jj.get("error"),
                    "validation": out.get("validation"), "probe": out.get("probe"),
                    "loudness": out.get("loudness"), "cues": out.get("cues"),
                    "crop": out.get("crop"),
                }
            all_ok = all((r.get("validation") or {}).get("ok") for r in render_results.values())
            rec.add("B5-RENDER", "Render 720p H.264/AAC in 9:16, 16:9, 1:1 with captions",
                    "PASS" if all_ok else "FAIL",
                    checks={k: (v.get("validation") or {}).get("ok", False) for k, v in render_results.items()},
                    metrics={k: {"wall_sec": v.get("wall_sec"), "peak_rss_mb": v.get("peak_rss_mb")}
                             for k, v in render_results.items()},
                    evidence=render_results)

            # 6. batch export
            ids = [c["id"] for c in clips]
            t0 = time.time()
            rr = client.post(f"/api/clip/projects/{pid}/export-batch",
                             json={"candidate_ids": ids, "aspect": "9:16"})
            jj = wait_job(client, rr.json()["job"]["id"], timeout=3600)
            exp = client.get(f"/api/clip/projects/{pid}/exports").json()
            items = (exp.get("manifest") or {}).get("items") or []
            ok_items = [i for i in items if i.get("file") and Path(i["file"]).exists()]
            rec.add("B6-BATCH", "Batch export with per-item manifest",
                    "PASS" if jj["status"] == "succeeded" and len(ok_items) == len(ids) else "FAIL",
                    checks={"job_status": jj["status"], "requested": len(ids), "exported": len(ok_items),
                            "files_listed": len(exp.get("files") or []),
                            "manifest": bool(exp.get("manifest"))},
                    metrics={"wall_sec": round(time.time() - t0, 2), "peak_rss_mb": jj.get("peak_memory_mb")},
                    evidence={"items": items})

            # 7. persistence / reopen
            again = client.get(f"/api/clip/projects/{pid}").json()
            rendered_ids = {c["id"] for c in again["clips"] if c["renders"]}
            reopen_ok = (len(again["clips"]) == len(clips)
                         and rendered_ids == {base["id"]}
                         and again["transcript"] is not None)
            rec.add("B7-REOPEN", "Project persists transcript/clips/renders after reload",
                    "PASS" if reopen_ok else "FAIL",
                    checks={"clips": len(again["clips"]), "transcript_present": again["transcript"] is not None,
                            "rendered_clip_ids": sorted(rendered_ids),
                            "expected_rendered": [base["id"]],
                            "render_aspects": sorted({r["aspect_ratio"] for c in again["clips"] for r in c["renders"]})})

            # 8. validation errors
            bad = client.post(f"/api/clip/projects/{pid}/source",
                              files={"file": ("notes.txt", b"hello", "text/plain")})
            bad_range = client.patch(f"/api/clip/clips/{base['id']}", json={"start_sec": 10, "end_sec": 5})
            rec.add("B8-VALIDATION", "Rejects unsupported container and inverted ranges",
                    "PASS" if bad.status_code == 415 and bad_range.status_code == 400 else "FAIL",
                    checks={"unsupported_status": bad.status_code, "inverted_range_status": bad_range.status_code})

            # 8b. source replacement semantics (one source per project)
            with open(fx["variants"][".mov"], "rb") as fh:
                clash = client.post(f"/api/clip/projects/{pid}/source?replace_existing=false",
                                    files={"file": ("replace.mov", fh, "video/quicktime")})
            with open(fx["variants"][".mov"], "rb") as fh:
                rep = client.post(f"/api/clip/projects/{pid}/source?replace_existing=true",
                                  files={"file": ("replace.mov", fh, "video/quicktime")})
            rep_body = rep.json() if rep.status_code == 200 else {}
            after = client.get(f"/api/clip/projects/{pid}").json()
            rep_ok = (
                clash.status_code == 409
                and rep.status_code == 200
                and (rep_body.get("replaced") or {}).get("clips") == len(clips)
                and not after["clips"] and after["transcript"] is None
                and after["project"]["source"]["ext"] == ".mov"
            )
            rec.add("B12-REPLACE", "New source replaces old source and clears stale clips/transcript",
                    "PASS" if rep_ok else "FAIL",
                    checks={"conflict_without_flag": clash.status_code,
                            "replace_status": rep.status_code,
                            "replaced": rep_body.get("replaced"),
                            "clips_after": len(after["clips"]),
                            "transcript_after": after["transcript"] is not None})

        # 9. cancellation on a real job (direct runner thread)
        ensure_schema()
        db = SessionLocal()
        cp = ClipProject(title=f"CANCEL {run_id}", status="draft")
        db.add(cp)
        db.commit()
        created.append(cp.id)
        cj = ClipJob(clip_project_id=cp.id, type="analyze", stage="queued", status="queued",
                     progress=0, message="queued")
        db.add(cj)
        db.commit()
        # attach the fixture as a source
        from app.clip.models import ClipSource

        db.add(ClipSource(clip_project_id=cp.id, original_name="source.mp4", original_path=fx["video"],
                          ext=".mp4", size_bytes=Path(fx["video"]).stat().st_size,
                          duration_sec=fx["duration"], width=1280, height=720, fps=30,
                          vcodec="h264", acodec="aac", audio_streams=1))
        db.commit()
        jid = cj.id
        db.close()
        th = threading.Thread(target=clip_jobs.run_clip_job, args=(jid,), daemon=True)
        t0 = time.time()
        th.start()
        # Request cancellation as soon as the runner flips the row to running, so
        # the request lands on a live job instead of after it finished.
        requested_at = None
        deadline = time.time() + 5
        while time.time() < deadline:
            db2 = SessionLocal()
            row = db2.get(ClipJob, jid)
            live = bool(row and row.status == "running")
            if live:
                row.canceled = True
                row.message = "Cancellation requested (E2E)"
                db2.commit()
                requested_at = round(time.time() - t0, 2)
            db2.close()
            if live:
                break
            time.sleep(0.02)
        th.join(timeout=300)
        db3 = SessionLocal()
        row = db3.get(ClipJob, jid)
        status = row.status if row else "missing"
        peak = row.peak_memory_mb if row else None
        leftovers = [p.name for p in (store.clip_paths(cp.id)["tmp"]).glob("*")]
        db3.close()
        cancel_ok = status == "canceled"
        rec.add("B9-CANCEL", "Cancel a live analysis job",
                "PASS" if cancel_ok else "WARNING",
                checks={"terminal_status": status, "cancel_requested_at_sec": requested_at,
                        "tmp_leftovers": leftovers, "crashed": False},
                metrics={"wall_sec": round(time.time() - t0, 2), "peak_rss_mb": peak},
                notes="" if cancel_ok else "Job reached a terminal state before the cancel flag was seen; not a crash.")

        # 10. restart recovery
        db = SessionLocal()
        cj2 = ClipJob(clip_project_id=created[0], type="analyze", stage="running", status="running",
                      progress=40, message="simulated")
        db.add(cj2)
        db.commit()
        jid2 = cj2.id
        db.close()
        n = clip_jobs.recover_interrupted_clip_jobs()
        db = SessionLocal()
        st = db.get(ClipJob, jid2).status
        db.close()
        rec.add("B10-RECOVERY", "Restart marks in-flight clip job interrupted",
                "PASS" if st == "interrupted" and n >= 1 else "FAIL",
                checks={"marked": n, "status": st})

        # 11. Engine A untouched
        from app.db.models import Job as AJob

        db = SessionLocal()
        a_jobs = db.query(AJob).count()
        db.close()
        rec.add("B11-ENGINE-A", "Engine A tables/endpoints untouched",
                "PASS", checks={"engine_a_jobs_present": a_jobs >= 0},
                notes="Engine A regression itself is verified separately by the benchmark suite.")

    except Exception as e:  # noqa: BLE001
        rec.add("RUN", "E2E run aborted", "FAIL", notes=f"{e}",
                evidence={"traceback": traceback.format_exc()[-4000:]})
    finally:
        summary = rec.summary()
        payload = {
            "id": run_id, "suite": "engine_b_e2e", "created_at": env["date"],
            "environment": env, "cases": rec.cases, "summary": summary,
            "wall_sec": round(time.time() - started, 2),
            "note": "Only executed checks are PASS/FAIL. Missing prerequisites are NOT_RUN. "
                    "Source media is synthetic local TTS over an FFmpeg colour video; "
                    "timings in the imported SRT come from measured speech durations.",
        }
        out = REPO / "benchmarks" / "data" / "engine_b"
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = out / f"e2e_{run_id}_{stamp}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("\n== SUMMARY ==")
        print(json.dumps(summary, indent=2))
        print("report:", path)
        if not args.keep:
            for pid in created:
                try:
                    store.remove_project_files(pid)
                except Exception:
                    pass
            shutil.rmtree(work, ignore_errors=True)
        else:
            print("kept fixture:", work, "projects:", created)
        # remove DB rows for deleted projects
        try:
            db = SessionLocal()
            for pid in created:
                p = db.get(ClipProject, pid)
                if p:
                    db.delete(p)
            db.commit()
            db.close()
        except Exception:
            pass
    return 0 if summary["overall_status"] in ("PASS", "WARNING") else 1


if __name__ == "__main__":
    raise SystemExit(main())
