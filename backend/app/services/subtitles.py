from __future__ import annotations
from pathlib import Path

def _fmt_ts(sec: float) -> str:
    if sec < 0: sec = 0
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')

def _fmt_vtt(sec: float) -> str:
    if sec < 0: sec = 0
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

def segments_to_srt(segments: list[dict], out_path: Path) -> Path:
    """segments: [{start,end,text}]"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_fmt_ts(seg['start'])} --> {_fmt_ts(seg['end'])}")
        lines.append(seg.get('text','').strip())
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path

def segments_to_vtt(segments: list[dict], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_fmt_vtt(seg['start'])} --> {_fmt_vtt(seg['end'])}")
        lines.append(seg.get('text','').strip())
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path

def timings_to_segments(scene_timings: list[dict]) -> list[dict]:
    """scene_timings: [{text,start,end}] -> subtitle segments (split long lines)"""
    segs = []
    for t in scene_timings:
        text = (t.get('text') or '').strip()
        start = float(t.get('start', 0)); end = float(t.get('end', start+2))
        # split into chunks ~42 chars
        words = text.split()
        if not words: continue
        chunks, cur = [], ""
        for w in words:
            if len(cur) + len(w) + 1 > 42:
                if cur: chunks.append(cur.strip())
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur: chunks.append(cur.strip())
        dur = max(0.5, end - start)
        step = dur / max(1, len(chunks))
        for j, c in enumerate(chunks):
            segs.append({"start": start + j*step, "end": min(end, start + (j+1)*step), "text": c})
    return segs
