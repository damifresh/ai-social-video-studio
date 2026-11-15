"""Transparent, deterministic highlight scoring.

No LLM is involved and nothing is invented: candidate text is always an exact
concatenation of transcript sentences, and every score component is stored with
its raw value, normalised value, weight and contribution so a user can audit
why a clip was suggested.

This is a *clip-worthiness heuristic*, not a virality predictor.
"""

from __future__ import annotations

import math
import re

CATEGORIES = ("educational", "funny", "controversial", "motivational", "informative", "opinion", "question")

WEIGHTS = {
    "hook": 0.20,
    "insight": 0.14,
    "emotion": 0.12,
    "density": 0.10,
    "audio": 0.12,
    "boundary": 0.12,
    "completeness": 0.10,
    "novelty": 0.10,
}

HOOK_CUES = (
    "how", "why", "what", "never", "nobody", "everyone", "most", "biggest", "secret",
    "mistake", "truth", "stop", "here's", "heres", "the one", "you need", "you should",
)
INSIGHT_CUES = (
    "learn", "tip", "strategy", "because", "reason", "result", "improve", "avoid",
    "mistake", "recommend", "actually", "research", "study", "data", "example",
    "step", "framework", "principle", "habit", "system", "practice",
)
EMOTION_CUES = (
    "amazing", "crazy", "love", "hate", "honestly", "believe", "shocking", "funny",
    "ridiculous", "terrible", "incredible", "insane", "wild", "scary", "surprised",
)
CONTROVERSIAL_CUES = (
    "controversial", "disagree", "myth", "wrong", "overrated", "underrated", "never",
    "everyone believes", "unpopular", "debate", "actually",
)
MOTIVATIONAL_CUES = (
    "succeed", "success", "discipline", "goal", "dream", "start", "keep going",
    "habit", "focus", "motivation", "change your", "you can",
)
DANGLING_START = {"and", "but", "so", "because", "which", "that", "or", "also", "then", "plus"}
DANGLING_END = {"and", "but", "so", "because", "the", "a", "an", "to", "of", "with", "for", "in", "on", "that", "which"}

STOP = {
    "the", "and", "that", "this", "with", "from", "your", "have", "will", "they", "them", "there",
    "what", "when", "where", "which", "while", "into", "about", "because", "these", "those", "their",
    "just", "very", "more", "most", "than", "then", "also", "such", "each", "some", "make", "made",
    "does", "doing", "been", "being", "were", "was", "are", "for", "not", "but", "you", "our", "can",
    "how", "why", "all", "any", "its", "it's", "a", "an", "of", "to", "in", "on", "is", "as", "at",
    "we", "i", "it", "he", "she", "his", "her", "they", "if", "or", "my", "me", "be", "do", "get",
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", (text or "").lower())


def _hits(text: str, cues: tuple[str, ...]) -> int:
    t = (text or "").lower()
    return sum(1 for c in cues if c in t)


def _norm(v: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return round(max(0.0, min(1.0, (v - lo) / (hi - lo))), 4)


def _jaccard(a: str, b: str) -> float:
    sa = {w for w in _tokens(a) if w not in STOP and len(w) > 3}
    sb = {w for w in _tokens(b) if w not in STOP and len(w) > 3}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _gap_before(gaps: list[dict], t: float, window: float = 0.6) -> float:
    best = 0.0
    for g in gaps:
        if 0 <= t - g["end"] <= window:
            best = max(best, t - g["end"])
    return best


def _gap_after(gaps: list[dict], t: float, window: float = 0.6) -> float:
    best = 0.0
    for g in gaps:
        if 0 <= g["start"] - t <= window:
            best = max(best, g["start"] - t)
    return best


def snap_to_pauses(sentences: list[dict], gaps: list[dict]) -> list[dict]:
    """Extend sentence boundaries into nearby silence without overlapping neighbours."""
    out: list[dict] = []
    for i, s in enumerate(sentences):
        start, end = float(s["start"]), float(s["end"])
        for g in gaps:
            if g["end"] <= start and start - g["end"] <= 0.5:
                start = g["end"]
            if g["start"] >= end and g["start"] - end <= 0.5:
                end = g["start"]
        out.append({**s, "start": round(start, 3), "end": round(end, 3)})
    for i in range(len(out) - 1):
        out[i]["end"] = round(min(out[i]["end"], out[i + 1]["start"]), 3)
    return out


def build_windows(sentences: list[dict], durations: list[float], max_overrun: float = 1.3) -> list[dict]:
    """Sentence-aligned windows close to each requested duration."""
    windows: list[dict] = []
    n = len(sentences)
    for target in durations:
        lo, hi = target * 0.8, target * max_overrun
        for i in range(n):
            start = sentences[i]["start"]
            best = None
            for j in range(i, n):
                end = sentences[j]["end"]
                dur = end - start
                if dur > hi:
                    break
                if dur >= lo:
                    score = abs(dur - target)
                    if best is None or score < best[0]:
                        best = (score, i, j, dur)
            if best:
                _, i2, j2, dur = best
                windows.append({
                    "start": round(start, 3),
                    "end": round(sentences[j2]["end"], 3),
                    "duration": round(dur, 3),
                    "target": target,
                    "sentence_start": i2,
                    "sentence_end": j2,
                    "text": " ".join(s["text"] for s in sentences[i2:j2 + 1]),
                })
    # de-duplicate identical spans
    seen: set[tuple[float, float]] = set()
    unique = []
    for w in windows:
        key = (round(w["start"], 1), round(w["end"], 1))
        if key in seen:
            continue
        seen.add(key)
        unique.append(w)
    return unique


def score_window(
    w: dict,
    envelope: dict,
    gaps: list[dict],
    mean_db_fn,
    silence_ratio_fn,
    novelty: float = 1.0,
) -> dict:
    text = w["text"]
    first = text.split(".")[0][:160] if text else ""
    dur = max(0.5, float(w["duration"]))
    toks = _tokens(text)
    wps = len(toks) / dur
    mean_db = mean_db_fn(envelope, w["start"], w["end"])
    sil = silence_ratio_fn(envelope, w["start"], w["end"])

    raws = {
        "hook": min(1.0, (_hits(first, HOOK_CUES) + (0.4 if re.search(r"\?|^\d", first) else 0)
                          + (0.3 if re.search(r"\byou\b|\byour\b", first, re.I) else 0)) / 4),
        "insight": min(1.0, _hits(text, INSIGHT_CUES) / 6),
        "emotion": min(1.0, _hits(text, EMOTION_CUES) / 4),
        "density": min(1.0, wps / 3.0) * (0.75 if wps > 5.5 else 1.0),
        "audio": max(0.0, min(1.0, ((mean_db if mean_db is not None else -40) + 45) / 33 - sil * 0.6)),
        "boundary": min(1.0,
                        0.45
                        + (0.2 if _gap_before(gaps, w["start"]) else 0)
                        + (0.2 if _gap_after(gaps, w["end"]) else 0)
                        + (0.15 if re.search(r"[.!?]['\")\]]?$", text.strip()) else 0)),
        "completeness": max(0.0, min(1.0, 1.0
                                    - (0.45 if (toks[0] in DANGLING_START if toks else False) else 0)
                                    - (0.45 if (toks[-1] in DANGLING_END if toks else False) else 0))),
        "novelty": max(0.0, min(1.0, novelty)),
    }
    components = {}
    total = 0.0
    for name, weight in WEIGHTS.items():
        raw = round(raws[name], 4)
        total += weight * raw
        components[name] = {"raw": raw, "weight": weight, "contribution": round(weight * raw, 4)}
    return {
        "score": round(100 * total, 2),
        "components": components,
        "metrics": {
            "words": len(toks),
            "words_per_sec": round(wps, 2),
            "mean_dbfs": mean_db,
            "silence_ratio": sil,
        },
    }


def classify(text: str) -> str:
    t = (text or "").lower()
    if "?" in t:
        return "question"
    if _hits(t, ("funny", "laugh", "joke", "hilarious", "ridiculous")):
        return "funny"
    if _hits(t, CONTROVERSIAL_CUES) >= 2:
        return "controversial"
    if _hits(t, MOTIVATIONAL_CUES) >= 2:
        return "motivational"
    if _hits(t, INSIGHT_CUES) >= 2:
        return "educational"
    if re.search(r"\bi (think|believe|feel)\b|in my opinion|honestly", t):
        return "opinion"
    return "informative"


def build_reason(scored: dict) -> str:
    comp = scored["components"]
    ordered = sorted(comp.items(), key=lambda kv: kv[1]["contribution"], reverse=True)
    label = {
        "hook": "strong opening hook",
        "insight": "educational/insight cues",
        "emotion": "emotional or opinionated language",
        "density": "steady speech density",
        "audio": "clean, audible delivery",
        "boundary": "clean start/end at a pause",
        "completeness": "complete sentence boundaries",
        "novelty": "distinct from other selected clips",
    }
    top = [f"{label[k]} ({v['raw']:.2f})" for k, v in ordered[:2]]
    m = scored["metrics"]
    return f"Scored {scored['score']:.0f}/100 for " + " and ".join(top) + \
           f"; {m['words_per_sec']} words/s, {int((m['silence_ratio'] or 0) * 100)}% silence."


def generate(
    transcript: dict,
    structural: dict,
    durations: list[float],
    count: int = 5,
    overlap_tolerance: float = 0.2,
) -> dict:
    if not transcript or transcript.get("timing") == "none" or not transcript.get("sentences"):
        raise ValueError(
            "Timed transcript required. Import an SRT/VTT or install whisper.cpp; "
            "plain text has no usable timings for clip boundaries."
        )
    sentences = transcript["sentences"]
    gaps = (structural or {}).get("silence", {}).get("gaps", [])
    envelope = (structural or {}).get("envelope", {})
    snaps = snap_to_pauses(sentences, gaps)
    windows = build_windows(snaps, durations)
    if not windows:
        raise ValueError("Source is too short for the requested clip durations")

    from .audio import mean_db, silence_ratio

    scored: list[dict] = []
    for w in windows:
        s = score_window(w, envelope, gaps, mean_db, silence_ratio)
        scored.append({**w, **s})

    scored.sort(key=lambda x: x["score"], reverse=True)
    selected: list[dict] = []
    for w in scored:
        if len(selected) >= count:
            break
        if any(min(w["end"], s["end"]) - max(w["start"], s["start"]) > overlap_tolerance for s in selected):
            continue
        if any(_jaccard(w["text"], s["text"]) > 0.85 for s in selected):
            continue
        novelty = 1.0
        if selected:
            novelty = 1.0 - max(_jaccard(w["text"], s["text"]) for s in selected)
        s2 = score_window(w, envelope, gaps, mean_db, silence_ratio, novelty=novelty)
        item = {**w, **s2}
        item["category"] = classify(w["text"])
        item["reason"] = build_reason(s2)
        selected.append(item)

    selected.sort(key=lambda x: x["start"])
    return {
        "candidates": selected,
        "params": {
            "durations": durations,
            "count": count,
            "overlap_tolerance_sec": overlap_tolerance,
            "weights": WEIGHTS,
            "window_rule": "sentence-aligned, 80%-130% of requested duration, nearest to target",
        },
        "stats": {
            "sentences": len(sentences),
            "windows_evaluated": len(windows),
            "selected": len(selected),
        },
        "shortfall": None if len(selected) >= count else (
            f"Only {len(selected)} non-overlapping clip(s) of the requested durations fit this source; "
            f"requested {count}."
        ),
    }
