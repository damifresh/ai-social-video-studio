#!/usr/bin/env python
"""Engine B — local ASR accuracy measurement (WER) on a known-text fixture.

This measures the installed whisper.cpp backend against the *known* narration
text of the synthetic fixture. That is a real measurement of this build on this
machine, but it is **not** a human-speech benchmark: the audio is clean macOS
TTS, one speaker, no noise, no accents. Report it as such.

Usage:
    PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_asr_wer.py
    PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_asr_wer.py --model small.en --keep
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

import psutil  # noqa: E402

from app.clip.audio import extract_analysis_audio  # noqa: E402
from app.clip.probe import probe_media  # noqa: E402
from app.clip.transcribe import capability, transcribe  # noqa: E402
from app.core.config import settings  # noqa: E402

from engine_b_e2e import SENTENCES, build_fixture  # noqa: E402


PUNCT = re.compile(r"[^\w\s']", re.UNICODE)
APOSTROPHE = re.compile(r"['’]")
SPACE = re.compile(r"\s+")


def normalize_words(text: str) -> list[str]:
    """Case/punctuation-insensitive tokenisation used by both sides of WER."""
    text = text.lower().replace("’", "'")
    text = APOSTROPHE.sub("", text)
    text = PUNCT.sub(" ", text)
    return [w for w in SPACE.split(text) if w]


def edit_counts(ref: list[str], hyp: list[str]) -> dict:
    """Levenshtein alignment with substitution/deletion/insertion counts."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)

    subs = dels = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
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
    return {
        "substitutions": subs,
        "deletions": dels,
        "insertions": ins,
        "ref_words": n,
        "hyp_words": m,
        "errors": subs + dels + ins,
        "wer": round((subs + dels + ins) / n, 4) if n else None,
    }


class RssMonitor:
    """Sample this process plus its whisper child; report the peak RSS in MB."""

    def __init__(self, interval: float = 0.15):
        self.interval = interval
        self.samples: list[float] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        me = psutil.Process()
        while not self._stop.is_set():
            try:
                procs = [me] + me.children(recursive=True)
                rss = sum(p.memory_info().rss for p in procs if p.is_running())
                self.samples.append(rss / (1024 * 1024))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)

    @property
    def peak_mb(self) -> float | None:
        return round(max(self.samples), 1) if self.samples else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", help="reuse an existing fixture directory (source.mp4 + speech.srt)")
    ap.add_argument("--model", help="informational only; the active model comes from resolve_whisper_model()")
    ap.add_argument("--keep", action="store_true", help="keep a generated fixture")
    args = ap.parse_args()

    cap = capability()
    if not cap["available"]:
        print("ASR unavailable:", "; ".join(cap["reasons"]))
        return 3
    if args.model and args.model not in (cap.get("model") or ""):
        print(f"note: requested model {args.model}, active model is {cap.get('model')} "
              f"(set WHISPER_MODEL to change it)")

    work = Path(args.fixture) if args.fixture else Path(tempfile.mkdtemp(prefix="engineb_wer_"))
    run_id = uuid.uuid4().hex[:12]
    if args.fixture:
        fx = {
            "video": str(work / "source.mp4"),
            "srt_text": (work / "speech.srt").read_text(encoding="utf-8"),
        }
        if not Path(fx["video"]).exists():
            print(f"fixture missing {fx['video']}")
            return 2
        probe = probe_media(Path(fx["video"]))
        fx["duration"] = probe.get("duration") or probe.get("duration_sec")
    else:
        print(f"Building fixture in {work} ...")
        fx = build_fixture(work, SENTENCES)

    audio = work / f"wer_audio_{run_id}.wav"
    t0 = time.time()
    extract_analysis_audio(Path(fx["video"]), audio)
    audio_sec = time.time() - t0

    t0 = time.time()
    with RssMonitor() as mon:
        tr = transcribe(audio, work / f"wer_{run_id}.json", language="en")
    asr_sec = time.time() - t0

    ref_text = " ".join(SENTENCES)
    hyp_text = " ".join(s["text"] for s in tr["sentences"]) or " ".join(s["text"] for s in tr["segments"])
    ref_words = normalize_words(ref_text)
    hyp_words = normalize_words(hyp_text)
    counts = edit_counts(ref_words, hyp_words)

    # Sentence boundaries: compare the app's sentence units to the fixture SRT
    # (whose timings come from the measured duration of each spoken sentence).
    from app.services.subtitles import parse_srt  # local import keeps startup cheap

    ref_segments = parse_srt(fx["srt_text"])
    hyp_sentences = tr["sentences"]
    pairs = min(len(ref_segments), len(hyp_sentences))
    boundary_hits = 0
    exact_text_hits = 0
    boundary_deltas: list[float] = []
    for i in range(pairs):
        rs, hs = ref_segments[i], hyp_sentences[i]
        ds = abs(float(rs["start"]) - float(hs["start"]))
        de = abs(float(rs["end"]) - float(hs["end"]))
        boundary_deltas += [ds, de]
        if ds <= 0.75 and de <= 0.75:
            boundary_hits += 1
        if normalize_words(rs["text"]) == normalize_words(hs["text"]):
            exact_text_hits += 1

    words = tr.get("words") or []
    monotonic = all(words[i]["end"] <= words[i + 1]["start"] + 0.001 for i in range(len(words) - 1))
    last_word_inside = bool(words) and (words[-1]["end"] <= float(fx.get("duration") or 300.0) + 1.0)
    report = {
        "id": run_id,
        "kind": "engine_b_asr_wer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_kind": "clean synthetic macOS-TTS narration, single speaker, no noise/accent",
        "not_a_human_benchmark": True,
        "environment": {
            "machine": "Apple M2 / 8 GB (as reported by platform)",
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "ffmpeg": settings.ffmpeg,
            "asr": cap,
            "global_memory_percent": psutil.virtual_memory().percent,
            "fixture": {
                "source": fx["video"],
                "sentences": len(SENTENCES),
                "duration_sec": fx.get("duration"),
            },
        },
        "metrics": {
            "audio_extract_sec": round(audio_sec, 2),
            "asr_wall_sec": round(asr_sec, 2),
            "asr_peak_rss_mb": mon.peak_mb,
            "rtf": round(asr_sec / fx.get("duration", 1) or 1, 4) if fx.get("duration") else None,
            **counts,
            "sentence_count_reference": len(ref_segments),
            "sentence_count_hypothesis": len(hyp_sentences),
            "sentence_text_exact_matches": exact_text_hits,
            "sentence_boundaries_within_0_75s": boundary_hits,
            "median_boundary_delta_sec": round(statistics.median(boundary_deltas), 3) if boundary_deltas else None,
            "word_count": len(words),
            "word_timing": tr.get("word_timing"),
            "word_timings_monotonic": monotonic,
            "last_word_inside_fixture": last_word_inside,
        },
        "reference_text": ref_text,
        "hypothesis_text": hyp_text,
        "reference_words": ref_words,
        "hypothesis_words": hyp_words,
        "notes": [
            "WER uses lowercased, punctuation-stripped whitespace tokens.",
            "The source is synthetic TTS with a known script, so this is an upper-bound "
            "convenience measurement on clean audio, not a human-speech WER result.",
            "The hypothesis is the app's sentence text after whisper.cpp token merging.",
        ],
    }
    out = REPO / "benchmarks" / "data" / "engine_b" / f"wer_{run_id}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report["metrics"][k] for k in
                      ("asr_wall_sec", "asr_peak_rss_mb", "rtf", "substitutions",
                       "deletions", "insertions", "ref_words", "wer",
                       "sentence_count_reference", "sentence_count_hypothesis",
                       "sentence_boundaries_within_0_75s", "word_timing")}, indent=1))
    print(f"report: {out}")

    if not args.fixture and not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
