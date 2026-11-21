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

MAX_ASSEMBLY_SEGMENTS = 6
ASSEMBLY_ROLES = ("hook", "context", "payoff", "proof", "close", "moment")
DEFAULT_ASSEMBLY_ROLES = ("hook", "context", "payoff", "close", "proof", "moment")

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

TONE_CUE_MAP = {
    "funny": ("funny", "laugh", "joke", "hilarious", "ridiculous"),
    "controversial": CONTROVERSIAL_CUES,
    "motivational": MOTIVATIONAL_CUES,
    "educational": INSIGHT_CUES,
    "question": ("?", "how", "why", "what"),
    "informative": ("data", "research", "study", "fact", "example"),
    "opinion": ("i think", "i believe", "in my opinion", "honestly"),
    "emotional": EMOTION_CUES,
}
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


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def structural_boundaries(structural: dict | None) -> tuple[list[dict], list[float]]:
    """Normalise silence gaps and approximate scene cuts from analysis output."""
    data = structural or {}
    gaps: list[dict] = []
    raw_gaps = (data.get("silence") or {}).get("gaps") or []
    for gap in raw_gaps:
        if not isinstance(gap, dict):
            continue
        start = _finite(gap.get("start", gap.get("start_sec")))
        end = _finite(gap.get("end", gap.get("end_sec")))
        if start is None or end is None or end <= start:
            continue
        gaps.append({"start": round(start, 3), "end": round(end, 3),
                     "duration": round(end - start, 3)})

    cuts: list[float] = []
    raw_cuts = (data.get("scene_cuts") or {}).get("cuts") or []
    for item in raw_cuts:
        value = _finite(item.get("time", item.get("start", item.get("start_sec")))) \
            if isinstance(item, dict) else _finite(item)
        if value is not None and value >= 0:
            cuts.append(round(value, 3))
    return gaps, sorted(set(cuts))


def boundary_evidence(
    snaps: list[dict],
    gaps: list[dict],
    cuts: list[float],
    start_index: int,
    end_index: int,
    raw_sentences: list[dict] | None = None,
) -> dict:
    """Audit trail for one sentence range; transcript remains the authority."""
    if start_index < 0 or end_index < start_index or end_index >= len(snaps):
        return {}
    start = float(snaps[start_index]["start"])
    end = float(snaps[end_index]["end"])
    raw = raw_sentences if raw_sentences and len(raw_sentences) > end_index else snaps
    raw_start = float(raw[start_index]["start"])
    raw_end = float(raw[end_index]["end"])
    before_lo = float(raw[start_index - 1]["end"]) if start_index > 0 else raw_start - 0.75
    after_hi = float(raw[end_index + 1]["start"]) if end_index + 1 < len(raw) else raw_end + 0.75

    def gap_overlap(gap: dict, lo: float, hi: float) -> float:
        return max(0.0, min(gap["end"], hi) - max(gap["start"], lo))

    before = max((gap_overlap(g, before_lo, raw_start) for g in gaps), default=0.0)
    after = max((gap_overlap(g, raw_end, after_hi) for g in gaps), default=0.0)
    inside = [c for c in cuts if raw_start - 0.05 <= c <= raw_end + 0.05]
    at_edge = [c for c in cuts if abs(c - raw_start) <= 0.75 or abs(c - raw_end) <= 0.75]
    support: list[str] = []
    if before >= 0.1:
        support.append(f"pause before sentence ({before:.2f}s)")
    if after >= 0.1:
        support.append(f"pause after sentence ({after:.2f}s)")
    if inside:
        support.append(f"{len(inside)} scene cut(s) inside range")
    if at_edge:
        support.append(f"scene cut near boundary ({len(at_edge)})")
    if re.search(r"[.!?]['\")\]]?$", str(snaps[end_index].get("text") or "").strip()):
        support.append("complete sentence end")
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "raw_start": round(raw_start, 3),
        "raw_end": round(raw_end, 3),
        "pause_before_sec": round(before, 3),
        "pause_after_sec": round(after, 3),
        "scene_cuts_inside": inside[:10],
        "scene_cuts_near_boundary": at_edge[:10],
        "support": support,
        "authority": "transcript sentence range",
    }


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


def _brief_fit(
    text: str,
    brief: dict | None,
    duration: float | None = None,
    sentence_start: int | None = None,
    sentence_end: int | None = None,
    directed: bool = False,
) -> float:
    """How well a window follows the parsed prompter brief (0..1)."""
    if not brief:
        return 0.0
    low = (text or "").lower()
    raw = 0.35
    keywords = brief.get("keywords") or []
    if keywords:
        hits = sum(1 for k in keywords if k.lower() in low)
        raw += 0.40 * min(1.0, hits / max(1, len(keywords)))
    tone = brief.get("tone")
    if tone:
        raw += 0.25 * min(1.0, _hits(low, TONE_CUE_MAP.get(tone, ())) / 2)
    avoid = brief.get("avoid") or []
    if any(term.lower() in low for term in avoid):
        raw -= 0.60
    seconds = (brief.get("length_hint") or {}).get("seconds")
    if seconds and duration:
        delta = abs(float(duration) - float(seconds)) / max(1.0, float(seconds))
        raw += 0.15 * max(0.0, 1.0 - delta) - 0.15 * min(1.0, delta)
    focus = brief.get("focus_indices") or []
    if focus and sentence_start is not None and sentence_end is not None:
        if any(sentence_start <= int(idx) <= sentence_end for idx in focus if isinstance(idx, (int, float))):
            raw += 0.35
    if directed:
        raw += 0.25
    return max(0.0, min(1.0, raw))


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
    weights: dict[str, float] | None = None,
    brief: dict | None = None,
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
    active = dict(weights or WEIGHTS)
    if brief:
        raws["brief_fit"] = _brief_fit(
            text, brief, dur,
            sentence_start=w.get("sentence_start"),
            sentence_end=w.get("sentence_end"),
            directed=bool(w.get("directed")),
        )
        active.setdefault("brief_fit", 0.12)
    weight_sum = sum(active.values()) or 1.0
    components = {}
    total = 0.0
    for name, weight in active.items():
        raw = round(raws.get(name, 0.0), 4)
        normalized = weight / weight_sum
        total += normalized * raw
        components[name] = {
            "raw": raw,
            "weight": round(normalized, 4),
            "contribution": round(normalized * raw, 4),
        }
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
        "brief_fit": "fit to your clipping brief",
    }
    top = [f"{label[k]} ({v['raw']:.2f})" for k, v in ordered[:2]]
    m = scored["metrics"]
    return f"Scored {scored['score']:.0f}/100 for " + " and ".join(top) + \
           f"; {m['words_per_sec']} words/s, {int((m['silence_ratio'] or 0) * 100)}% silence."


def _assembly_target_count(target_seconds: float, sentence_count: int) -> int:
    if sentence_count <= 0:
        return 0
    target = max(5.0, min(180.0, float(target_seconds or 30)))
    desired = max(2, min(4, math.ceil(target / 10)))
    return min(MAX_ASSEMBLY_SEGMENTS, max(1, desired), sentence_count)


def _assembly_category(text: str, brief: dict | None) -> str:
    category = classify(text)
    tone = (brief or {}).get("tone")
    if tone in CATEGORIES and tone != category and _hits(text, TONE_CUE_MAP.get(tone, ())) >= 1:
        return tone
    return category


def _assembly_window(
    snaps: list[dict],
    gaps: list[dict],
    cuts: list[float],
    start_index: int,
    end_index: int,
    target_seconds: float,
    role: str,
    directed: bool,
    copy: dict | None = None,
    order: int = 0,
    raw_sentences: list[dict] | None = None,
) -> dict:
    start = round(float(snaps[start_index]["start"]), 3)
    end = round(float(snaps[end_index]["end"]), 3)
    return {
        "start": start,
        "end": end,
        "duration": round(end - start, 3),
        "target": float(target_seconds),
        "sentence_start": start_index,
        "sentence_end": end_index,
        "text": " ".join(str(s.get("text") or "") for s in snaps[start_index:end_index + 1]),
        "role": role,
        "directed": bool(directed),
        "plan_order": order,
        "copy": copy or {},
        "boundary_evidence": boundary_evidence(
            snaps, gaps, cuts, start_index, end_index, raw_sentences,
        ),
    }


def _score_assembly_window(
    window: dict,
    envelope: dict,
    gaps: list[dict],
    mean_db_fn,
    silence_ratio_fn,
    weights: dict,
    brief: dict | None,
) -> dict:
    scored = score_window(
        window, envelope, gaps, mean_db_fn, silence_ratio_fn,
        novelty=1.0, weights=weights, brief=brief,
    )
    result = {**window, **scored}
    result["category"] = _assembly_category(window["text"], brief)
    result["reason"] = build_reason(scored)
    if window.get("directed"):
        result["reason"] = "Director-selected scene. " + result["reason"]
    return result


def _directed_assembly_windows(
    brief: dict | None,
    snaps: list[dict],
    raw_sentences: list[dict],
    gaps: list[dict],
    cuts: list[float],
    target_seconds: float,
    envelope: dict,
    mean_db_fn,
    silence_ratio_fn,
    weights: dict,
) -> tuple[list[dict], int]:
    data = brief or {}
    raw_segments = data.get("assembly_segments")
    if not isinstance(raw_segments, list):
        raw_segments = data.get("focus_windows")
    if not isinstance(raw_segments, list):
        return [], 0
    windows: list[dict] = []
    occupied: list[tuple[int, int]] = []
    rejected = 0
    for order, raw in enumerate(raw_segments[:MAX_ASSEMBLY_SEGMENTS]):
        if not isinstance(raw, dict):
            rejected += 1
            continue
        start, end = raw.get("start_index"), raw.get("end_index")
        if not (isinstance(start, int) and isinstance(end, int)) or isinstance(start, bool) \
                or isinstance(end, bool) or start < 0 or end < start or end >= len(snaps):
            rejected += 1
            continue
        if _assembly_overlaps(start, end, occupied):
            rejected += 1
            continue
        occupied.append((start, end))
        role = raw.get("role")
        if role not in ASSEMBLY_ROLES:
            role = DEFAULT_ASSEMBLY_ROLES[len(windows) % len(DEFAULT_ASSEMBLY_ROLES)]
        target = _finite(raw.get("target_seconds")) or target_seconds
        window = _assembly_window(
            snaps, gaps, cuts, start, end, target, role, True,
            raw.get("copy") or {}, len(windows), raw_sentences,
        )
        proposed_evidence = raw.get("boundary_evidence")
        if isinstance(proposed_evidence, dict):
            window["boundary_evidence"]["proposed_by_director"] = proposed_evidence
        windows.append(_score_assembly_window(
            window, envelope, gaps, mean_db_fn, silence_ratio_fn, weights, brief,
        ))
    return windows, rejected


def _assembly_overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= other_end and end >= other_start for other_start, other_end in spans)


def _deterministic_assembly_windows(
    snaps: list[dict],
    raw_sentences: list[dict],
    gaps: list[dict],
    cuts: list[float],
    target_seconds: float,
    count: int,
    envelope: dict,
    mean_db_fn,
    silence_ratio_fn,
    weights: dict,
    brief: dict | None,
    exclude: set[int] | None = None,
) -> list[dict]:
    n = len(snaps)
    count = min(max(1, int(count)), n, MAX_ASSEMBLY_SEGMENTS)
    if count <= 0:
        return []
    block_size = math.ceil(n / count)
    per_target = max(3.0, float(target_seconds) / count)
    chosen: list[dict] = []
    for block_start in range(0, n, block_size):
        block_end = min(n, block_start + block_size)
        best: tuple[float, dict] | None = None
        for start in range(block_start, block_end):
            for span in range(1, min(3, block_end - start) + 1):
                end = start + span - 1
                if exclude and any(i in exclude for i in range(start, end + 1)):
                    continue
                window = _assembly_window(
                    snaps, gaps, cuts, start, end, per_target,
                    DEFAULT_ASSEMBLY_ROLES[0], False, {}, len(chosen), raw_sentences,
                )
                scored = score_window(
                    window, envelope, gaps, mean_db_fn, silence_ratio_fn,
                    novelty=1.0, weights=weights, brief=brief,
                )
                evidence = window["boundary_evidence"]
                fit = 1.0 - min(1.0, abs(window["duration"] - per_target) / per_target)
                value = scored["score"] + 12.0 * fit + 3.0 * len(evidence["support"]) \
                    + 2.0 * len(evidence["scene_cuts_inside"])
                if best is None or value > best[0]:
                    best = (value, {**window, **scored})
        if best is not None:
            chosen.append(best[1])
    for index, window in enumerate(chosen):
        window["role"] = DEFAULT_ASSEMBLY_ROLES[index % len(DEFAULT_ASSEMBLY_ROLES)]
        window["plan_order"] = index
        window["category"] = _assembly_category(window["text"], brief)
        window["reason"] = build_reason({k: window[k] for k in ("score", "components", "metrics")})
    return chosen


def _complete_assembly_windows(
    directed: list[dict],
    snaps: list[dict],
    raw_sentences: list[dict],
    gaps: list[dict],
    cuts: list[float],
    target_seconds: float,
    envelope: dict,
    mean_db_fn,
    silence_ratio_fn,
    weights: dict,
    brief: dict | None,
) -> list[dict]:
    """Add local scenes when the director returned none or only one."""
    desired = _assembly_target_count(target_seconds, len(snaps))
    if len(directed) >= max(2, min(desired, len(snaps))) or len(snaps) < 2:
        return directed
    covered: set[int] = set()
    for window in directed:
        covered.update(range(window["sentence_start"], window["sentence_end"] + 1))
    fill = _deterministic_assembly_windows(
        snaps, raw_sentences, gaps, cuts, target_seconds, max(1, desired - len(directed)),
        envelope, mean_db_fn, silence_ratio_fn, weights, brief, exclude=covered,
    )
    combined = list(directed)
    for window in sorted(fill, key=lambda w: w["sentence_start"]):
        position = len(combined)
        for index, existing in enumerate(combined):
            if window["sentence_start"] < existing["sentence_start"]:
                position = index
                break
        combined.insert(position, window)
    for index, window in enumerate(combined):
        if not window.get("directed"):
            window["role"] = DEFAULT_ASSEMBLY_ROLES[index % len(DEFAULT_ASSEMBLY_ROLES)]
        window["plan_order"] = index
    return combined


def _assembly_copy(proposed, segments: list[dict], combined_text: str, category: str) -> dict:
    from . import metadata as clip_metadata

    fallback = clip_metadata.generate(combined_text, category)
    fields = ("title", "hook", "caption", "hashtags")

    def accept(value: dict | None) -> dict | None:
        candidate = {k: v for k, v in (value or {}).items() if k in fields}
        if not candidate:
            return None
        checked = clip_metadata.verify(combined_text, candidate)
        if not checked.get("all_grounded"):
            return None
        return {**fallback, **candidate, "grounding": checked}

    accepted = accept(proposed)
    if accepted:
        return accepted

    titles: list[str] = []
    hooks: list[str] = []
    captions: list[str] = []
    tags: list[str] = []
    for segment in segments:
        copy = segment.get("copy") or {}
        for key, sink in (("title", titles), ("hook", hooks), ("caption", captions)):
            value = copy.get(key)
            if isinstance(value, str) and value.strip() and value not in sink:
                sink.append(value)
        for tag in copy.get("hashtags") or []:
            if isinstance(tag, str) and tag not in tags:
                tags.append(tag)
        if len(titles) >= 2 and len(hooks) >= 2 and len(captions) >= 2:
            break
    aggregated = {
        "title": titles[0] if titles else None,
        "hook": (hooks[1] if len(hooks) > 1 else (hooks[0] if hooks else None)),
        "caption": " ".join(captions[:2]) or None,
        "hashtags": tags[:5],
    }
    aggregated = {k: v for k, v in aggregated.items() if v}
    return accept(aggregated) or fallback


def _aggregate_assembly_scores(segments: list[dict]) -> dict:
    total = max(0.001, sum(float(s["duration"]) for s in segments))
    template = segments[0].get("components") or {}
    weights = {name: float(data.get("weight") or 0) for name, data in template.items()}
    components: dict[str, dict] = {}
    for name, weight in weights.items():
        raw = sum(float(s.get("components", {}).get(name, {}).get("raw") or 0) * float(s["duration"])
                  for s in segments) / total
        components[name] = {
            "raw": round(raw, 4),
            "weight": round(weight, 4),
            "contribution": round(weight * raw, 4),
        }
    metrics = {
        "words": sum(int(s.get("metrics", {}).get("words") or 0) for s in segments),
        "words_per_sec": round(sum(float(s.get("metrics", {}).get("words_per_sec") or 0)
                                   for s in segments) / max(1, len(segments)), 2),
        "mean_dbfs": round(sum(float(s.get("metrics", {}).get("mean_dbfs") or 0)
                               for s in segments) / max(1, len(segments)), 2),
        "silence_ratio": round(sum(float(s.get("metrics", {}).get("silence_ratio") or 0)
                                   for s in segments) / max(1, len(segments)), 4),
    }
    return {"score": round(100 * sum(c["contribution"] for c in components.values()), 2),
            "components": components, "metrics": metrics}


def _limit_assembly_to_source(
    transcript: dict,
    structural: dict,
    source_duration: float | None,
) -> tuple[dict, dict, float | None]:
    """Keep every transcript boundary inside the uploaded source video.

    A timed transcript can outlive the uploaded file (a different cut, an SRT
    from the full recording, or a short test source). Clamping here keeps the
    one-clip plan grounded in transcript text while guaranteeing the renderer
    never sees a segment past the end of the actual media.
    """
    limit = float(source_duration or 0)
    if limit <= 0:
        return transcript, structural, None

    sentences: list[dict] = []
    for sentence in transcript.get("sentences") or []:
        start = float(sentence.get("start") or 0)
        end = float(sentence.get("end") or start)
        if start >= limit:
            continue
        end = min(end, limit)
        if end <= start:
            continue
        item = {**sentence, "start": round(start, 3), "end": round(end, 3)}
        words = item.get("words")
        if isinstance(words, list):
            kept: list[dict] = []
            for word in words:
                ws = float(word.get("start") or 0)
                we = float(word.get("end") or ws)
                if ws >= limit:
                    continue
                we = min(we, limit)
                if we <= ws:
                    continue
                kept.append({**word, "start": round(ws, 3), "end": round(we, 3)})
            item["words"] = kept
        sentences.append(item)

    limited = {**transcript, "sentences": sentences}
    if isinstance(transcript.get("segments"), list):
        limited["segments"] = [
            {**cue, "start": round(min(float(cue.get("start") or 0), limit), 3),
             "end": round(min(float(cue.get("end") or 0), limit), 3)}
            for cue in transcript["segments"]
            if float(cue.get("start") or 0) < limit
        ]

    gaps, cuts = structural_boundaries(structural)
    limited_gaps: list[dict] = []
    for gap in gaps:
        gs = float(gap.get("start") or 0)
        ge = float(gap.get("end") or gs)
        if gs >= limit:
            continue
        limited_gaps.append({**gap, "start": round(gs, 3), "end": round(min(ge, limit), 3)})
    limited_cuts = [float(cut) for cut in cuts if 0 < float(cut) < limit]
    limited_structural = {**(structural or {}), "silence": {**(structural or {}).get("silence", {}), "gaps": limited_gaps}}
    return limited, limited_structural, limit


def _generate_assembly(
    transcript: dict,
    structural: dict,
    durations: list[float],
    brief: dict | None,
    source_duration: float | None = None,
) -> dict:
    """Compose exactly one render-ready candidate from ordered transcript scenes."""
    from .audio import mean_db, silence_ratio

    transcript, structural, source_limit = _limit_assembly_to_source(
        transcript, structural, source_duration,
    )
    sentences = transcript["sentences"]
    gaps, cuts = structural_boundaries(structural)
    snaps = snap_to_pauses(sentences, gaps)
    if source_limit is not None:
        snaps = [
            {
                **snap,
                "start": round(max(0.0, min(float(snap["start"]), source_limit)), 3),
                "end": round(max(0.0, min(float(snap["end"]), source_limit)), 3),
            }
            for snap in snaps
            if float(snap["end"]) > 0 and float(snap["start"]) < source_limit
        ]
        snaps = [snap for snap in snaps if snap["end"] > snap["start"]]
    envelope = (structural or {}).get("envelope", {})
    hint = ((brief or {}).get("length_hint") or {}).get("seconds")
    target_candidates = [float(d) for d in (durations or []) if 5 <= float(d) <= 180]
    target = target_candidates[0] if target_candidates else \
        float(hint) if isinstance(hint, (int, float)) and 5 <= hint <= 180 else 30.0
    if source_limit is not None and source_limit > 0:
        target = min(target, source_limit)

    weights = dict(WEIGHTS)
    for component, multiplier in ((brief or {}).get("weight_multipliers") or {}).items():
        if component in weights:
            try:
                weights[component] = round(weights[component] * float(multiplier), 6)
            except (TypeError, ValueError):
                continue
    weights["brief_fit"] = 0.12

    directed, rejected = _directed_assembly_windows(
        brief, snaps, sentences, gaps, cuts, target, envelope, mean_db, silence_ratio, weights,
    )
    segments = _complete_assembly_windows(
        directed, snaps, sentences, gaps, cuts, target, envelope, mean_db, silence_ratio,
        weights, brief,
    )
    short_source_notice = ""
    if not segments and snaps:
        # A very short or single-sentence source cannot supply 2+ sentence
        # ranges. Keep one grounded scene instead of failing the whole job.
        window = _assembly_window(
            snaps, gaps, cuts, 0, len(snaps) - 1, target,
            DEFAULT_ASSEMBLY_ROLES[0], False, {}, 0, sentences,
        )
        segments = [_score_assembly_window(
            window, envelope, gaps, mean_db, silence_ratio, weights, brief,
        )]
        short_source_notice = (
            "Source is shorter than the requested assembly; used one "
            "transcript-grounded scene."
        )
    if not segments:
        raise ValueError("Source is too short for transcript-grounded assembly")

    combined_text = " ".join(segment["text"] for segment in segments)
    category = _assembly_category(combined_text, brief)
    assembly_source = (brief or {}).get("assembly") or {}
    copy = _assembly_copy(assembly_source.get("copy"), segments, combined_text, category)
    scores = _aggregate_assembly_scores(segments)
    directed_count = sum(1 for segment in segments if segment.get("directed"))
    pause_boundaries = sum(1 for segment in segments
                           if segment.get("boundary_evidence", {}).get("pause_before_sec")
                           or segment.get("boundary_evidence", {}).get("pause_after_sec"))
    cut_boundaries = sum(1 for segment in segments
                         if segment.get("boundary_evidence", {}).get("scene_cuts_inside")
                         or segment.get("boundary_evidence", {}).get("scene_cuts_near_boundary"))
    assembly_meta = (brief or {}).get("assembly") or {}
    notice = assembly_meta.get("notice")
    if short_source_notice:
        notice = f"{notice} {short_source_notice}".strip() if notice else short_source_notice
    roles = [segment["role"] for segment in segments]
    total_duration = round(sum(float(segment["duration"]) for segment in segments), 3)
    arc = " → ".join(roles)
    reason = (
        f"Director-assembled {len(segments)} ordered transcript scene(s) ({arc}). "
        + " | ".join(segment["reason"] for segment in segments[:2])
    )
    assembly = {
        "mode": "single-final-video",
        "enabled": True,
        "target_seconds": target,
        "final_duration_sec": total_duration,
        "timeline": {"start": 0.0, "end": total_duration},
        "segment_count": len(segments),
        "roles": roles,
        "narrative_arc": arc,
        "boundary_authority": "transcript sentence ranges; silence gaps and scene cuts are support evidence",
        "pause_boundaries": pause_boundaries,
        "scene_cut_boundaries": cut_boundaries,
        "directed_segments": directed_count,
        "fallback_segments": len(segments) - directed_count,
        "rejected_plan_segments": rejected,
        "engine": assembly_meta.get("engine"),
        "notice": notice,
        "clamped_to_source_duration": bool(source_limit is not None),
        "segments": segments,
        "copy": copy,
    }
    candidate = {
        "start": 0.0,
        "end": total_duration,
        "duration": total_duration,
        "target": target,
        "text": combined_text,
        "sentence_start": segments[0]["sentence_start"],
        "sentence_end": segments[-1]["sentence_end"],
        "segments": segments,
        "assembly": assembly,
        "copy": copy,
        "category": category,
        "reason": reason,
        "directed": directed_count > 0,
        "plan_order": 0,
        **scores,
    }
    return {
        "candidates": [candidate],
        "params": {
            "durations": durations,
            "count": 1,
            "single_clip": True,
            "overlap_tolerance_sec": 0.2,
            "weights": weights,
            "brief": brief,
            "assembly": assembly,
            "focus_indices": (brief or {}).get("focus_indices") or [],
            "focus_windows": (brief or {}).get("focus_windows") or [],
            "window_rule": (
                "single-clip assembly: validated ordered transcript sentence ranges first; "
                "local rules fill missing scenes; pauses and scene cuts are boundary support"
            ),
        },
        "stats": {
            "sentences": len(sentences),
            "windows_evaluated": len(segments),
            "assembly_segments": len(segments),
            "directed_segments": directed_count,
            "fallback_segments": len(segments) - directed_count,
            "rejected_plan_segments": rejected,
            "pause_boundaries": pause_boundaries,
            "scene_cut_boundaries": cut_boundaries,
            "selected": 1,
        },
        "shortfall": None if len(segments) >= 2 else (
            "Only one complete transcript sentence was available; produced a one-scene final video."
        ),
    }


def generate(
    transcript: dict,
    structural: dict,
    durations: list[float],
    count: int = 5,
    overlap_tolerance: float = 0.2,
    brief: dict | None = None,
    single_clip: bool = False,
    source_duration: float | None = None,
) -> dict:
    if not transcript or transcript.get("timing") == "none" or not transcript.get("sentences"):
        raise ValueError(
            "Timed transcript required. Import an SRT/VTT or install whisper.cpp; "
            "plain text has no usable timings for clip boundaries."
        )
    if single_clip:
        return _generate_assembly(transcript, structural, durations, brief, source_duration)
    sentences = transcript["sentences"]
    gaps = (structural or {}).get("silence", {}).get("gaps", [])
    envelope = (structural or {}).get("envelope", {})
    snaps = snap_to_pauses(sentences, gaps)

    focus_windows = (brief or {}).get("focus_windows") or []
    directed: list[dict] = []
    for order, fw in enumerate(focus_windows):
        if not isinstance(fw, dict):
            continue
        si, ei = fw.get("start_index"), fw.get("end_index")
        if not (isinstance(si, int) and isinstance(ei, int)):
            continue
        if isinstance(si, bool) or isinstance(ei, bool) or si < 0 or ei < si or ei >= len(snaps):
            continue
        target = fw.get("target_seconds") or (durations[0] if durations else 30)
        try:
            target = float(target)
        except (TypeError, ValueError):
            target = 30.0
        start, end = round(float(snaps[si]["start"]), 3), round(float(snaps[ei]["end"]), 3)
        if end <= start:
            continue
        directed.append({
            "start": start,
            "end": end,
            "duration": round(end - start, 3),
            "target": target,
            "sentence_start": si,
            "sentence_end": ei,
            "text": " ".join(str(s.get("text") or "") for s in snaps[si:ei + 1]),
            "directed": True,
            "plan_order": fw.get("order", order),
            "copy": fw.get("copy") or {},
        })

    deduped: list[dict] = []
    seen: set[tuple[float, float]] = set()
    for w in directed + build_windows(snaps, durations):
        key = (round(w["start"], 1), round(w["end"], 1))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(w)
    windows = deduped
    if not windows:
        raise ValueError("Source is too short for the requested clip durations")

    from .audio import mean_db, silence_ratio

    effective_weights = dict(WEIGHTS)
    if brief:
        for component, multiplier in (brief.get("weight_multipliers") or {}).items():
            if component in effective_weights:
                effective_weights[component] = round(effective_weights[component] * float(multiplier), 6)
        effective_weights["brief_fit"] = 0.12

    def preferred_category(text: str) -> str:
        category = classify(text)
        tone = brief.get("tone") if brief else None
        if tone in CATEGORIES and tone != category and _hits(text, TONE_CUE_MAP.get(tone, ())) >= 1:
            return tone
        return category

    scored: list[dict] = []
    for w in windows:
        s = score_window(w, envelope, gaps, mean_db, silence_ratio,
                         weights=effective_weights, brief=brief)
        scored.append({**w, **s})

    scored.sort(key=lambda x: (not x.get("directed", False), -x["score"], x["start"]))
    selected: list[dict] = []

    def fits_selection(w: dict) -> bool:
        if len(selected) >= count:
            return False
        if any(min(w["end"], s["end"]) - max(w["start"], s["start"]) > overlap_tolerance for s in selected):
            return False
        return not any(_jaccard(w["text"], s["text"]) > 0.85 for s in selected)

    def add(w: dict) -> bool:
        if not fits_selection(w):
            return False
        novelty = 1.0 - max((_jaccard(w["text"], s["text"]) for s in selected), default=0.0)
        s2 = score_window(w, envelope, gaps, mean_db, silence_ratio,
                          novelty=novelty, weights=effective_weights, brief=brief)
        item = {**w, **s2}
        item["category"] = preferred_category(w["text"])
        item["reason"] = build_reason(s2)
        if w.get("directed"):
            item["reason"] = "Director-selected moment. " + item["reason"]
        selected.append(item)
        return True

    for w in scored:
        if not w.get("directed"):
            continue
        add(w)
    for w in scored:
        if len(selected) >= count:
            break
        if not w.get("directed"):
            add(w)

    if any(w.get("directed") for w in selected):
        selected.sort(key=lambda x: (x.get("plan_order", 999), x["start"]))
    else:
        selected.sort(key=lambda x: x["start"])
    return {
        "candidates": selected,
        "params": {
            "durations": durations,
            "count": count,
            "single_clip": bool(single_clip),
            "overlap_tolerance_sec": overlap_tolerance,
            "weights": effective_weights,
            "brief": brief,
            "focus_indices": (brief or {}).get("focus_indices") or [],
            "focus_windows": focus_windows,
            "window_rule": (
                "director-plan windows first, then sentence-aligned 80%-130% of requested duration, "
                "nearest to target"
            ),
        },
        "stats": {
            "sentences": len(sentences),
            "windows_evaluated": len(windows),
            "directed_windows": len(directed),
            "selected": len(selected),
        },
        "shortfall": None if len(selected) >= count else (
            f"Only {len(selected)} non-overlapping clip(s) of the requested durations fit this source; "
            f"requested {count}."
        ),
    }
