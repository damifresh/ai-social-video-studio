"""Deterministic director/producer plans for Auto-Clip Studio.

The local rules are the only planner. They turn the creator brief and the
built-in presets into a transparent, auditable plan: a parsed brief, target
durations, and — in one-clip mode — the assembly metadata that scoring records.
No model is consulted and no copy is invented here; `metadata.py` generates
transcript-grounded copy and `highlights.py` scores and assembles the result.
"""

from __future__ import annotations

import re

from . import highlights as clip_highlights
from . import prompt as clip_prompt

PLAN_VERSION = "director-plan/v1"
ENGINE = "prompter-rules/v1 (deterministic)"


def presets() -> dict:
    """Built-in set prompts exposed to the prompter UI."""
    items = []
    for preset_id, data in clip_prompt.DIRECTOR_PRESETS.items():
        items.append({
            "id": preset_id,
            "label": data["label"],
            "instruction": data["instruction"],
            "default_prompt": data["default_prompt"],
        })
    return {"default": clip_prompt.DEFAULT_DIRECTOR_PRESET, "presets": items}


def effective_prompt(prompt: str | None, preset_id: str | None = None) -> str:
    """Free text wins; an empty brief falls back to the preset's set prompt."""
    text = re.sub(r"\s+", " ", (prompt or "").strip())[:2000]
    return text or clip_prompt.director_preset(preset_id)["default_prompt"]


def _preset_id(preset_id: str | None) -> str:
    value = (preset_id or "").lower()
    return value if value in clip_prompt.DIRECTOR_PRESETS else clip_prompt.DEFAULT_DIRECTOR_PRESET


def _effective_durations(fallback_durations: list[float] | None, brief: dict | None) -> list[float]:
    """Explicit UI durations win; the prompt's length hint is only a last resort."""
    chosen = []
    for value in (fallback_durations or []):
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if 5 <= seconds <= 180:
            chosen.append(seconds)
    if chosen:
        return chosen[:6]
    seconds = ((brief or {}).get("length_hint") or {}).get("seconds")
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and 5 <= seconds <= 180:
        return [float(seconds)]
    return [30.0]


def deterministic_plan(
    prompt: str,
    preset_id: str | None,
    fallback_durations: list[float] | None = None,
    notice: str | None = None,
    single_clip: bool = False,
    structural: dict | None = None,
) -> dict:
    """Build the local plan that scoring and assembly consume."""
    text = effective_prompt(prompt, preset_id)
    brief = clip_prompt.parse(text)
    durations = _effective_durations(fallback_durations, brief)
    gaps, cuts = clip_highlights.structural_boundaries(structural)
    assembly = None
    if single_clip:
        assembly = {
            "mode": "single-final-video",
            "enabled": True,
            "segment_count": 0,
            "roles": [],
            "target_seconds": durations[0],
            "boundary_authority": "transcript sentence ranges; silence gaps and scene cuts are support evidence",
            "pause_gaps_considered": len(gaps),
            "scene_cuts_considered": len(cuts),
            "engine": ENGINE,
            "notice": notice or "Local rules will assemble one final video from ordered transcript moments.",
        }
        brief["assembly"] = assembly
        brief["single_clip"] = True
    return {
        "version": PLAN_VERSION,
        "engine": ENGINE,
        "preset": _preset_id(preset_id),
        "prompt": text,
        "brief": brief,
        "focus_indices": [],
        "focus_windows": [],
        "segments": [],
        "assembly": assembly,
        "durations": durations[:6],
        "single_clip": bool(single_clip),
        "notice": notice or (
            "Local rules will assemble one final video from ordered transcript moments."
            if single_clip else "Local director rules parsed the brief."
        ),
        "validation": {"moments": 0, "segments": 0, "rejected_fields": []},
    }
