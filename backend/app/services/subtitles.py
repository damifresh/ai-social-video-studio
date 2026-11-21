from __future__ import annotations

import re
from pathlib import Path

DEFAULT_STYLE = {
    "font": "Arial",
    "size": 46,
    "position": "bottom",
    "primary": "#FFFFFF",
    "highlight": "#FFD166",
    "outline": "#000000",
    "bold": True,
    "keyword_highlight": True,
    "max_chars": 42,
}

STOPWORDS = {
    "the", "and", "that", "this", "with", "from", "your", "have", "will", "they", "them", "there",
    "what", "when", "where", "which", "while", "into", "about", "because", "these", "those", "their",
    "just", "very", "more", "most", "than", "then", "also", "such", "each", "some", "make", "made",
    "does", "doing", "been", "being", "were", "was", "are", "for", "not", "but", "you", "our", "can",
    "how", "why", "all", "any", "its", "it's", "a", "an", "of", "to", "in", "on", "is", "as", "at",
}


def _fmt_ts(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _fmt_vtt(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _fmt_ass(sec: float) -> str:
    """Format seconds as an ASS timestamp: H:MM:SS.cc (centiseconds).

    libass silently drops Dialogue lines whose timestamps use 3 decimal
    places (SRT/VTT style). ASS requires exactly two centisecond digits.
    """
    sec = max(0.0, float(sec))
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def parse_ts(raw: str) -> float:
    raw = raw.strip().replace(",", ".")
    parts = raw.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(raw)
    except Exception:
        return 0.0


def split_chunks(text: str, max_chars: int = 42) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    chunks, cur = [], ""
    for w in words:
        candidate = (cur + " " + w).strip()
        if len(candidate) > max_chars and cur:
            chunks.append(cur)
            cur = w
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return chunks


def timings_to_segments(scene_timings: list[dict], max_chars: int = 42) -> list[dict]:
    segs: list[dict] = []
    for t in scene_timings:
        text = (t.get("text") or "").strip()
        start = float(t.get("start", 0))
        end = float(t.get("end", start + 2))
        chunks = split_chunks(text, max_chars)
        if not chunks:
            continue
        dur = max(0.5, end - start)
        step = dur / len(chunks)
        for j, c in enumerate(chunks):
            segs.append({
                "start": round(start + j * step, 3),
                "end": round(min(end, start + (j + 1) * step), 3),
                "text": c,
                "scene": t.get("scene"),
            })
    return segs


def segments_to_srt(segments: list[dict], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        lines += [str(i), f"{_fmt_ts(seg['start'])} --> {_fmt_ts(seg['end'])}", (seg.get("text") or "").strip(), ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def segments_to_vtt(segments: list[dict], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines += [f"{_fmt_vtt(seg['start'])} --> {_fmt_vtt(seg['end'])}", (seg.get("text") or "").strip(), ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def parse_srt(content: str) -> list[dict]:
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip())
    out: list[dict] = []
    for block in blocks:
        lines = [l for l in block.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        idx = 0
        if re.fullmatch(r"\d+", lines[0].strip()):
            idx = 1
        if idx >= len(lines) or "-->" not in lines[idx]:
            continue
        a, b = [p.strip() for p in lines[idx].split("-->")]
        text = " ".join(lines[idx + 1:]).strip()
        if not text:
            continue
        out.append({"start": parse_ts(a), "end": parse_ts(b), "text": text})
    return out


def load_srt(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return parse_srt(path.read_text(encoding="utf-8", errors="replace"))


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except Exception:
        r = g = b = 255
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def keywords(text: str, limit: int = 3) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", text or "")
    ranked = sorted(
        {w.lower() for w in words if len(w) >= 5 and w.lower() not in STOPWORDS},
        key=lambda w: (-len(w), w),
    )
    return set(ranked[:limit])


def _ass_text(line: str, style: dict) -> str:
    if not style.get("keyword_highlight", True):
        return line
    hl = _ass_color(style.get("highlight", "#FFD166"))
    primary = _ass_color(style.get("primary", "#FFFFFF"))
    keys = keywords(line)
    parts = []
    for word in line.split():
        clean = re.sub(r"[^A-Za-z'\-]", "", word).lower()
        if clean in keys:
            parts.append(rf"{{\c{hl}}}{word}{{\c{primary}}}")
        else:
            parts.append(word)
    return " ".join(parts)


def build_ass(
    segments: list[dict],
    out_path: Path,
    style: dict | None = None,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """Build a styled ASS file with optional keyword highlighting for FFmpeg libass burn-in."""
    st = {**DEFAULT_STYLE, **(style or {})}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    size = int(st.get("size") or 46)
    # scale font relative to 1280-wide design space
    size = max(18, round(size * width / 1280))
    position = st.get("position", "bottom")
    alignment = {"bottom": 2, "center": 5, "top": 8}.get(position, 2)
    margin_v = max(24, round(height * 0.06))
    margin_h = max(24, round(width * 0.06))
    bold = -1 if st.get("bold", True) else 0
    primary = _ass_color(st.get("primary", "#FFFFFF"))
    outline_col = _ass_color(st.get("outline", "#000000"))
    font = st.get("font") or "Arial"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{primary},&H000000FF,{outline_col},&H80000000,{bold},0,0,0,100,100,0,0,1,3,1,{alignment},{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for seg in segments:
        text = (seg.get("text") or "").replace("\n", " ").strip()
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_fmt_ass(seg['start'])},{_fmt_ass(seg['end'])},Default,,0,0,0,,{_ass_text(text, st)}\n"
        )
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def write_subtitles(
    segments: list[dict],
    subs_dir: Path,
    style: dict | None = None,
    width: int = 1280,
    height: int = 720,
) -> dict:
    subs_dir.mkdir(parents=True, exist_ok=True)
    srt = segments_to_srt(segments, subs_dir / "subtitles.srt")
    vtt = segments_to_vtt(segments, subs_dir / "subtitles.vtt")
    ass = build_ass(segments, subs_dir / "subtitles.ass", style=style, width=width, height=height)
    return {"srt": str(srt), "vtt": str(vtt), "ass": str(ass), "count": len(segments)}
