"""Deterministic prompter for Auto-Clip Studio.

The prompter is a rule-based intent parser, not an LLM. It converts a natural
language brief into transparent scoring modifiers, keywords to look for, and
topics to avoid. Every parsed rule is returned so the UI and the job record can
show exactly what changed.
"""

from __future__ import annotations

import re

MAX_PROMPT = 500
DEFAULT_DIRECTOR_PRESET = "tiktok"

DIRECTOR_PRESETS = {
    "tiktok": {
        "label": "TikTok · fast hook",
        "instruction": "Favor a strong opening, tight pacing, clean sentence boundaries and a 15–30 s target.",
        "default_prompt": "Funny 15s TikTok clips about habits; avoid jargon",
    },
    "reels": {
        "label": "Reels · visual rhythm",
        "instruction": "Favor visual, upbeat moments with quick hooks and a 15–30 s target.",
        "default_prompt": "Educational Reels for beginners; clear audio and complete thoughts",
    },
    "linkedin": {
        "label": "LinkedIn · insight first",
        "instruction": "Favor insight, complete thoughts, clear audio and a 30–60 s target; avoid hype.",
        "default_prompt": "Motivational LinkedIn clips about discipline; no controversial claims",
    },
    "educational": {
        "label": "Educational · teach one thing",
        "instruction": "Favor one complete lesson with an explanation and a 30–60 s target.",
        "default_prompt": "Educational clips for beginners; clear audio and complete thoughts",
    },
    "motivational": {
        "label": "Motivational · emotional arc",
        "instruction": "Favor emotional, disciplined arcs with an inspiring complete thought.",
        "default_prompt": "Motivational clips about discipline; no controversial claims",
    },
}


def director_preset(preset_id: str | None) -> dict:
    return DIRECTOR_PRESETS.get((preset_id or "").lower(), DIRECTOR_PRESETS[DEFAULT_DIRECTOR_PRESET])

TONE_CUES = {
    "funny": ("funny", "humor", "humorous", "comedy", "laugh", "meme", "ridiculous"),
    "controversial": ("controversial", "debate", "unpopular", "bold take", "disagree"),
    "motivational": ("motivational", "inspiring", "inspire", "motivate", "discipline", "keep going"),
    "educational": ("educational", "teach", "learning", "learn", "explain", "tutorial", "tip", "lesson"),
    "informative": ("informative", "facts", "news", "summary", "overview"),
    "question": ("question", "questions", "ask", "answer"),
    "opinion": ("opinion", "perspective", "honest take", "i think", "i believe"),
    "emotional": ("emotional", "dramatic", "heartfelt", "personal story", "feel"),
}

PLATFORMS = {
    "tiktok": "tiktok",
    "reels": "reels",
    "instagram reels": "reels",
    "shorts": "shorts",
    "youtube shorts": "shorts",
    "youtube": "youtube",
    "linkedin": "linkedin",
}

AUDIENCE_RE = re.compile(
    r"\bfor\s+(beginners?|students?|founders?|creators?|kids?|teens?|adults?|"
    r"professionals?|marketers?|developers?|viewers?|followers?)\b",
    re.I,
)
KEYWORD_RE = re.compile(r"\b(?:about|focus(?:ing)? on|featuring|include|mention|keywords?)\s+([^.;!?]+)", re.I)
AVOID_RE = re.compile(r"\b(?:avoid|exclude|skip|without|no|don't include|do not include)\s+([^.;!?]+)", re.I)
LENGTH_RE = re.compile(r"\b(\d{1,3})\s*(?:s|sec|secs|second|seconds)\b", re.I)

PREFERENCE_RULES = (
    (("hook", "attention", "grabbing", "opening", "scroll stopping", "scroll-stopping"), "hook", 1.50),
    (("insight", "educational", "teach", "tip", "lesson", "learn", "useful"), "insight", 1.40),
    (("funny", "humor", "entertaining", "emotion", "emotional", "dramatic", "inspiring"), "emotion", 1.35),
    (("clear audio", "clean audio", "crisp voice", "audible"), "audio", 1.40),
    (("complete", "full thought", "not cut off", "whole point"), "completeness", 1.35),
    (("fast", "punchy", "dense", "quick", "short"), "density", 1.25),
    (("clean cuts", "pause", "natural break", "smooth"), "boundary", 1.25),
    (("varied", "unique", "fresh", "non repetitive", "non-repetitive"), "novelty", 1.30),
)


def _phrases(raw: str, limit: int = 6) -> list[str]:
    out: list[str] = []
    for part in re.split(r",|;|/|\band\b|\bor\b|\bplus\b", raw, flags=re.I):
        value = re.sub(r"[^A-Za-z0-9' -]", " ", part).strip().lower()
        value = re.sub(r"^(?:the|a|an|some|any|my|our)\s+", "", value)
        value = re.sub(r"\s+", " ", value).strip(" -")
        if 2 <= len(value) <= 40 and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return out


def _summary_bits(tone, platform, audience, keywords, avoid, length_hint) -> list[str]:
    bits: list[str] = []
    if tone:
        bits.append(f"{tone} tone")
    if platform:
        bits.append(f"for {platform.upper()}")
    if audience:
        bits.append(f"for {audience}")
    if keywords:
        bits.append("focus: " + ", ".join(keywords[:3]))
    if avoid:
        bits.append("avoid: " + ", ".join(avoid[:3]))
    if length_hint:
        bits.append(f"around {length_hint['label']}")
    if not bits:
        bits.append("balanced default scoring")
    return bits


def parse(prompt: str | None) -> dict:
    """Parse a free-text brief into audit-friendly scoring instructions."""
    text = re.sub(r"\s+", " ", (prompt or "").strip())[:MAX_PROMPT]
    if not text:
        return {}

    low = text.lower()
    tone = next((name for name, cues in TONE_CUES.items() if any(cue in low for cue in cues)), None)
    platform = next((name for phrase, name in PLATFORMS.items() if phrase in low), None)
    audience_match = AUDIENCE_RE.search(low)
    audience = audience_match.group(1).lower() if audience_match else None

    keywords: list[str] = []
    for match in KEYWORD_RE.finditer(text):
        for phrase in _phrases(match.group(1)):
            if phrase not in keywords:
                keywords.append(phrase)

    avoid: list[str] = []
    for match in AVOID_RE.finditer(text):
        for phrase in _phrases(match.group(1)):
            if phrase not in avoid:
                avoid.append(phrase)

    length_match = LENGTH_RE.search(low)
    if length_match:
        seconds = int(length_match.group(1))
        length_hint = {"seconds": min(180, max(5, seconds)), "label": f"{seconds}s"}
    elif re.search(r"\bshort\b", low):
        length_hint = {"seconds": 15, "label": "short"}
    elif re.search(r"\blong(?:er)?\b|in depth\b|in-depth\b", low):
        length_hint = {"seconds": 60, "label": "long"}
    else:
        length_hint = None

    multipliers: dict[str, float] = {}
    rules: list[str] = []
    for phrases, component, factor in PREFERENCE_RULES:
        if any(phrase in low for phrase in phrases):
            multipliers[component] = max(multipliers.get(component, 1.0), factor)
            rules.append(f"{component} ×{factor:g} ({phrases[0]})")

    if platform in ("tiktok", "reels", "shorts"):
        for component, factor in (("hook", 1.30), ("density", 1.15), ("boundary", 1.10)):
            multipliers[component] = max(multipliers.get(component, 1.0), factor)
        rules.append(f"{platform}: stronger hooks, tighter pacing, clean cuts")
    elif platform in ("youtube", "linkedin"):
        for component, factor in (("insight", 1.25), ("completeness", 1.25), ("audio", 1.10)):
            multipliers[component] = max(multipliers.get(component, 1.0), factor)
        rules.append(f"{platform}: insight, complete thoughts, clear audio")

    if avoid:
        rules.append("penalize windows containing avoided topics")

    summary_bits = _summary_bits(tone, platform, audience, keywords, avoid, length_hint)

    return {
        "text": text,
        "tone": tone,
        "platform": platform,
        "audience": audience,
        "keywords": keywords[:6],
        "avoid": avoid[:6],
        "length_hint": length_hint,
        "weight_multipliers": multipliers,
        "rules": rules,
        "summary": "; ".join(summary_bits),
        "engine": "prompter-rules/v1 (deterministic)",
    }
