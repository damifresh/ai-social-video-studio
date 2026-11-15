"""Transcript-grounded clip copy.

Deterministic template extraction, not an LLM. Every generated field is
validated to be a substring of the clip's own transcript text (hashtags are
tokens from that text), so the app can never invent a claim or a topic.
"""

from __future__ import annotations

import re
from collections import Counter

from .highlights import EMOTION_CUES, HOOK_CUES, INSIGHT_CUES, STOP, _hits, _tokens


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _trim(text: str, limit: int) -> str:
    """Trim at a word boundary; result is always a prefix of the input."""
    text = _clean(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", _clean(text)) if s.strip()]


def _title(text: str) -> str:
    sents = _sentences(text)
    best = max(sents, key=lambda s: (_hits(s, HOOK_CUES) * 2 + _hits(s, INSIGHT_CUES)
                                    + (2 if re.search(r"\?|^\d", s) else 0)
                                    - (0.02 * abs(len(s) - 48))), default="")
    if not best:
        return ""
    return _trim(best, 64)


def _hook(text: str) -> str:
    sents = _sentences(text)
    if not sents:
        return ""
    question = next((s for s in sents if s.endswith("?")), None)
    cue = max(sents, key=lambda s: _hits(s, HOOK_CUES) + _hits(s, EMOTION_CUES))
    pick = question or (cue if _hits(cue, HOOK_CUES) else sents[0])
    return _trim(pick, 90)


def _caption(text: str) -> str:
    sents = _sentences(text)
    joined = ""
    for s in sents[:2]:
        candidate = (joined + " " + s).strip()
        if len(candidate) > 220:
            break
        joined = candidate
    return _trim(joined or text, 220)


def _hashtags(text: str, limit: int = 5) -> list[str]:
    counts = Counter(w for w in _tokens(text) if len(w) >= 4 and w not in STOP and not w.isdigit())
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    out: list[str] = []
    for word, _ in ordered:
        tag = "#" + re.sub(r"[^a-z0-9]", "", word.lower())
        if len(tag) > 3 and tag not in out:
            out.append(tag)
        if len(out) >= limit:
            break
    return out


def generate(text: str, category: str) -> dict:
    text = _clean(text)
    payload = {
        "title": _title(text),
        "hook": _hook(text),
        "caption": _caption(text),
        "hashtags": _hashtags(text),
        "category": category,
        "generator": "transcript-template/v1 (deterministic, no LLM)",
    }
    payload["grounding"] = verify(text, payload)
    return payload


def verify(text: str, payload: dict) -> dict:
    """Report per-field whether the output is literally supported by the text."""
    norm = _clean(text).lower()
    out = {}
    for field in ("title", "hook", "caption"):
        value = _clean(payload.get(field) or "")
        out[field] = bool(value) and value.lower() in norm
    tags = payload.get("hashtags") or []
    out["hashtags"] = all(t.lstrip("#").lower() in norm for t in tags)
    out["all_grounded"] = all(out.values())
    return out
