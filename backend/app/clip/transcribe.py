"""Transcription for Engine B.

Design rule: never invent speech. A transcript exists only if (a) a verified
local whisper.cpp build produced it, or (b) the user supplied it. When neither
is true the capability is reported as unavailable and the clip pipeline refuses
to pretend it has text.

Word timings are marked ``native`` when the ASR build emits token offsets and
``estimated`` when they are derived proportionally inside a real segment (that
is a display approximation, recorded as such, not ASR output).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..core.config import resolve_whisper_bin, resolve_whisper_model
from ..services.subtitles import parse_srt, split_chunks

LANGUAGES = {"auto", "en", "es", "fr", "de", "it", "pt", "nl", "hi", "ja", "ko", "zh"}
TERMINAL = re.compile(r"(?:[.!?。！？]['\")\]]?)$")


class TranscriptionUnavailable(RuntimeError):
    pass


def _bin_works(path: str) -> tuple[bool, str]:
    try:
        p = subprocess.run([path, "--help"], capture_output=True, text=True, timeout=20)
        text = (p.stdout or "") + (p.stderr or "")
        ok = ("usage:" in text.lower()) or ("whisper" in text.lower() and p.returncode in (0, 1))
        return ok, text[:400]
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def capability() -> dict:
    bin_path = resolve_whisper_bin()
    model_path = resolve_whisper_model()
    reasons = []
    runs = False
    if not bin_path:
        reasons.append("whisper.cpp binary not found (set WHISPER_BIN or build into models/whisper.cpp/build/bin)")
    else:
        runs, _ = _bin_works(bin_path)
        if not runs:
            reasons.append("whisper.cpp binary found but did not run (--help failed)")
    if not model_path:
        reasons.append("no GGML model found (set WHISPER_MODEL or place ggml-base.en.bin in models/whisper.cpp/models)")
    available = bool(bin_path and model_path and runs)
    return {
        "backend": "whisper_cpp" if available else "unavailable",
        "available": available,
        "bin": Path(bin_path).name if bin_path else None,
        "bin_path": bin_path,
        "model": Path(model_path).name if model_path else None,
        "model_path": model_path,
        "reasons": reasons,
        "manual_import": True,
        "note": "Manual SRT/VTT/plain-text import always available. ASR is never simulated.",
    }


def _estimated_words(segments: list[dict]) -> list[dict]:
    words: list[dict] = []
    for seg in segments:
        toks = (seg.get("text") or "").split()
        if not toks:
            continue
        start, end = float(seg.get("start", 0)), float(seg.get("end", 0))
        dur = max(0.05, end - start)
        weights = [len(t) + 1 for t in toks]
        total = sum(weights)
        cursor = start
        for tok, w in zip(toks, weights):
            span = dur * w / total
            words.append({"start": round(cursor, 3), "end": round(cursor + span, 3), "text": tok})
            cursor += span
    return words


SPECIAL_TOKEN = re.compile(r"^(?:\[_.*\]|<\|.*\|>)$")
NO_SPACE_LANGS = {"ja", "ko", "zh"}


def _clean_text(text: str) -> str:
    text = SPECIAL_TOKEN.sub(" ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _merge_tokens(items: list[dict], language: str) -> list[dict]:
    """Turn whisper tokens into words, honouring leading-space word boundaries.

    whisper.cpp emits subword tokens without a leading space (``Mot`` + ``ivation``)
    and a leading space at the start of each new word (``" people"``). Joining every
    token with a space corrupts the transcript, so tokens are concatenated until a
    token that starts with whitespace begins the next word. Control tokens
    (``[_BEG_]``, ``[_TT_123]``, ``<|...|>``) are dropped rather than displayed.
    """
    words: list[dict] = []
    no_space = language in NO_SPACE_LANGS
    for tok in items:
        raw = tok.get("text") or ""
        if not raw or SPECIAL_TOKEN.match(raw.strip()):
            continue
        off = tok.get("offsets") or {}
        if "from" not in off or "to" not in off:
            continue
        text = raw.strip()
        if not text:
            continue
        start, end = round(off["from"] / 1000.0, 3), round(off["to"] / 1000.0, 3)
        starts_word = no_space or not words or raw[:1].isspace()
        if starts_word:
            words.append({"start": start, "end": end, "text": text})
        else:
            words[-1]["text"] += text
            words[-1]["end"] = max(words[-1]["end"], end)
    return words


def build_sentences(words: list[dict], max_gap: float = 0.8, max_chars: int = 240,
                    join_with: str | None = None) -> list[dict]:
    """Group words into sentence units using punctuation, pauses and length."""
    sep = join_with
    if sep is None:
        # CJK text is conventionally unspaced; everything else uses spaces.
        sep = " "
    sentences: list[dict] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 999
        text = sep.join(x["text"] for x in cur)
        if TERMINAL.search(w["text"]) or gap > max_gap or len(text) >= max_chars or nxt is None:
            sentences.append({
                "start": round(cur[0]["start"], 3),
                "end": round(cur[-1]["end"], 3),
                "text": re.sub(r"\s+", " ", text).strip(),
            })
            cur = []
    return sentences


def _parse_whisper_json(data: dict, language: str = "en") -> tuple[list[dict], list[dict]]:
    items = data.get("transcription") or data.get("segments") or []
    segments: list[dict] = []
    words: list[dict] = []
    for it in items:
        offsets = it.get("offsets") or {}
        if "from" in offsets and "to" in offsets:
            start, end = offsets["from"] / 1000.0, offsets["to"] / 1000.0
        elif it.get("start") is not None:
            start, end = float(it["start"]), float(it["end"])
        else:
            continue
        text = _clean_text(it.get("text") or "")
        if not text:
            continue
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        words.extend(_merge_tokens(it.get("tokens") or [], language))
    return segments, words


def transcribe(
    audio_wav: Path,
    out_json: Path,
    language: str = "en",
    on_progress: Callable[[int, str], None] | None = None,
    check: Callable[[], None] | None = None,
) -> dict:
    cap = capability()
    if not cap["available"]:
        raise TranscriptionUnavailable("; ".join(cap["reasons"]) or "whisper.cpp unavailable")

    prefix = out_json.with_suffix("")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    lang = language if language in LANGUAGES else "en"
    arg_sets = [
        ["-ojf"],
        ["-oj"],
    ]
    last_err = ""
    for extra in arg_sets:
        if check:
            check()
        cmd = [cap["bin_path"], "-m", cap["model_path"], "-f", str(audio_wav),
               "-of", str(prefix), "-l", lang, "--print-progress"] + extra
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        progress_line = ""
        assert proc.stderr is not None
        for line in proc.stderr:
            progress_line = line.strip()
            m = re.search(r"progress\s*=\s*(\d+)%", progress_line)
            if m and on_progress:
                on_progress(min(99, int(m.group(1))), "Transcribing audio")
            if check:
                try:
                    check()
                except Exception:
                    proc.kill()
                    raise
        proc.wait()
        produced = prefix.with_suffix(".json")
        if proc.returncode == 0 and produced.exists():
            data = json.loads(produced.read_text(encoding="utf-8", errors="replace"))
            segments, words = _parse_whisper_json(data, lang)
            if not segments:
                raise RuntimeError("whisper.cpp produced JSON without segments")
            native_words = bool(words)
            if not words:
                words = _estimated_words(segments)
            sentences = build_sentences(words, join_with="" if lang in NO_SPACE_LANGS else " ")
            return {
                "backend": "whisper_cpp",
                "model": cap["model"],
                "language": lang,
                "timing": "native",
                "word_timing": "native" if native_words else "estimated",
                "segments": segments,
                "sentences": sentences,
                "words": words,
                "notes": [] if native_words else [
                    "Word timings estimated proportionally within ASR segments (segment timings are native)."
                ],
            }
        last_err = (proc.stderr.read() if proc.stderr else "") or f"exit {proc.returncode}"
        if "unknown argument" not in last_err.lower() and "invalid option" not in last_err.lower():
            break
    raise RuntimeError(f"whisper.cpp failed: {last_err[-500:]}")


def _vtt_to_segments(content: str) -> list[dict]:
    body = re.sub(r"^WEBVTT[^\n]*\n", "", content.replace("\r\n", "\n"))
    return parse_srt(body)


def import_transcript(content: str, filename: str = "", duration: float = 0.0) -> dict:
    """Parse a user-supplied transcript. Never fabricates text or timings."""
    name = (filename or "").lower()
    text = content.replace("\r\n", "\n")
    segments: list[dict] = []
    timing = "none"
    if name.endswith(".vtt") or text.lstrip().startswith("WEBVTT"):
        segments = _vtt_to_segments(text)
        timing = "file"
    elif name.endswith(".srt") or "-->" in text:
        segments = parse_srt(text)
        timing = "file"
    if segments:
        segments = [
            {"start": round(float(s["start"]), 3), "end": round(float(s["end"]), 3),
             "text": re.sub(r"\s+", " ", s["text"]).strip()}
            for s in segments if (s.get("text") or "").strip()
        ]
        segments.sort(key=lambda s: (s["start"], s["end"]))
        if duration > 0:
            for s in segments:
                s["start"] = max(0.0, min(s["start"], duration))
                s["end"] = max(s["start"] + 0.05, min(s["end"], duration))
        # Subtitles from real tools occasionally overlap; keep the timeline
        # monotonic so downstream clip maths never sees reversed spans.
        for i in range(1, len(segments)):
            if segments[i]["start"] < segments[i - 1]["end"]:
                segments[i]["start"] = segments[i - 1]["end"]
            if segments[i]["end"] <= segments[i]["start"]:
                segments[i]["end"] = round(segments[i]["start"] + 0.05, 3)
        words = _estimated_words(segments)
        return {
            "backend": "manual",
            "model": None,
            "language": "unknown",
            "timing": timing,
            "word_timing": "estimated",
            "segments": segments,
            "sentences": build_sentences(words),
            "words": words,
            "notes": ["Timings taken from the supplied subtitle file; word timings estimated inside each cue."],
        }
    plain = re.sub(r"\s+", " ", text).strip()
    if not plain:
        raise ValueError("Transcript is empty")
    sentences = [{"start": 0.0, "end": 0.0, "text": s.strip()} for s in re.split(r"(?<=[.!?])\s+", plain) if s.strip()]
    return {
        "backend": "manual",
        "model": None,
        "language": "unknown",
        "timing": "none",
        "word_timing": None,
        "segments": [],
        "sentences": sentences,
        "words": [],
        "notes": [
            "Plain text import has no timings. Highlight text and clip copy can use it, "
            "but timed clips/captions require an SRT/VTT or ASR transcript.",
        ],
    }


def caption_segments(transcript: dict, start: float, end: float, max_chars: int = 42) -> list[dict]:
    """Clip-relative caption cues built from the clip's own transcript text."""
    if not transcript or transcript.get("timing") == "none":
        return []
    sentences = transcript.get("sentences") or []
    cues: list[dict] = []
    for s in sentences:
        s0, s1 = float(s["start"]), float(s["end"])
        if s1 <= start or s0 >= end:
            continue
        text = s["text"]
        cs, ce = max(s0, start), min(s1, end)
        chunks = split_chunks(text, max_chars)
        if not chunks:
            continue
        dur = max(0.2, ce - cs)
        total_chars = sum(len(c) for c in chunks) or 1
        cursor = cs
        for c in chunks:
            span = dur * len(c) / total_chars
            cues.append({
                "start": round(cursor - start, 3),
                "end": round(min(end, cursor + span) - start, 3),
                "text": c,
            })
            cursor += span
    return [c for c in cues if c["end"] > c["start"]]


def save_transcript(path: Path, transcript: dict) -> Path:
    data = dict(transcript)
    data["created_at"] = datetime.utcnow().isoformat() + "Z"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_transcript(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def whisper_install_hint() -> str:
    return (
        "Install whisper.cpp locally: run scripts/install_whisper_cpp.sh "
        "(requires cmake + network once), or set WHISPER_BIN/WHISPER_MODEL. "
        "Until then use Transcript → Import SRT/VTT."
    )
