#!/usr/bin/env python3
"""Generate the studio's bundled royalty-free music beds and SFX.

All audio here is synthesized from scratch by this script using only the Python
standard library: no samples, loops or recordings from third parties. The output
is dedicated to the public domain (CC0-1.0) so it can ship and be redistributed
with the app. Regenerate with:

    backend/.venv/bin/python scripts/generate_assets.py

Files are written to assets/music and assets/sfx with a licenses.json manifest.
"""
from __future__ import annotations

import json
import math
import random
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUSIC = ROOT / "assets" / "music"
SFX = ROOT / "assets" / "sfx"
RATE = 24000


def _write(path: Path, samples: list[float], rate: int = RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    peak = max(1e-6, max(abs(s) for s in samples))
    gain = 0.82 / peak
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for s in samples:
            v = int(max(-1.0, min(1.0, s * gain)) * 32767)
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _env(i: int, n: int, attack: float = 0.08, release: float = 0.12) -> float:
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    if i < a:
        return i / a
    if i > n - r:
        return max(0.0, (n - i) / r)
    return 1.0


def pad(path: Path, seconds: float, root: float, partials: tuple[float, ...], bpm: float = 60.0) -> None:
    """Slow evolving chord pad with gentle movement; loops by construction."""
    n = int(seconds * RATE)
    rng = random.Random(int(root * 1000) + len(partials))
    beat = 60.0 / bpm
    samples: list[float] = []
    # A simple four-chord progression (root-relative semitone offsets)
    chords = [0, -3, 5, -5]
    for i in range(n):
        t = i / RATE
        chord_idx = int(t / (beat * 8)) % len(chords)
        base = root * (2 ** (chords[chord_idx] / 12.0))
        v = 0.0
        for k, mult in enumerate(partials):
            freq = base * mult
            v += math.sin(2 * math.pi * freq * t + k * 1.7) / (k + 1.6)
            # slow detune shimmer
            v += 0.16 * math.sin(2 * math.pi * (freq * 1.003) * t + k)
        swell = 0.55 + 0.45 * math.sin(2 * math.pi * t / (beat * 16))
        trem = 0.9 + 0.1 * math.sin(2 * math.pi * t / 7.3)
        samples.append(v * swell * trem * _env(i, n, 0.02, 0.02) * 0.32)
    # crossfade the seam so the loop is click-free
    seam = int(RATE * 0.35)
    for i in range(seam):
        g = i / seam
        samples[i] = samples[i] * g + samples[n - seam + i] * (1 - g)
    _write(path, samples)


def whoosh(path: Path, seconds: float = 0.7, rising: bool = True) -> None:
    n = int(seconds * RATE)
    rng = random.Random(7 if rising else 11)
    samples: list[float] = []
    lp = 0.0
    for i in range(n):
        p = i / n
        cutoff = 0.02 + (0.30 * p if rising else 0.30 * (1 - p))
        lp += cutoff * ((rng.random() * 2 - 1) - lp)
        amp = math.sin(math.pi * p) ** 2.2
        tone = math.sin(2 * math.pi * (180 + 900 * p) * i / RATE) * 0.18
        samples.append((lp * 1.6 + tone) * amp)
    _write(path, samples)


def riser(path: Path, seconds: float = 1.6) -> None:
    n = int(seconds * RATE)
    rng = random.Random(23)
    samples = []
    lp = 0.0
    for i in range(n):
        p = i / n
        lp += (0.01 + 0.2 * p) * ((rng.random() * 2 - 1) - lp)
        tone = math.sin(2 * math.pi * (120 + 700 * p * p) * i / RATE) * 0.25
        samples.append((lp * 1.4 + tone) * (p ** 1.5))
    _write(path, samples)


def click(path: Path) -> None:
    n = int(0.09 * RATE)
    samples = []
    for i in range(n):
        p = i / n
        samples.append(math.sin(2 * math.pi * 1400 * i / RATE) * (1 - p) ** 4 * 0.9)
    _write(path, samples)


def main() -> None:
    pad(MUSIC / "ambient_calm_loop.wav", 40.0, 110.0, (1, 1.5, 2, 2.5, 3))
    pad(MUSIC / "ambient_upbeat_loop.wav", 40.0, 146.83, (1, 1.25, 1.5, 2, 3), bpm=88)
    whoosh(SFX / "whoosh_soft.wav", 0.7, rising=True)
    whoosh(SFX / "whoosh_down.wav", 0.7, rising=False)
    riser(SFX / "riser_short.wav", 1.6)
    click(SFX / "click_soft.wav")

    manifest = {
        "ambient_calm_loop.wav": {
            "license": "CC0-1.0 (public domain dedication)",
            "source": "Original procedural synthesis by scripts/generate_assets.py; no third-party samples",
            "artist": "AI Social Video Studio",
        },
        "ambient_upbeat_loop.wav": {
            "license": "CC0-1.0 (public domain dedication)",
            "source": "Original procedural synthesis by scripts/generate_assets.py; no third-party samples",
            "artist": "AI Social Video Studio",
        },
    }
    (MUSIC / "licenses.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    sfx_manifest = {
        name: {
            "license": "CC0-1.0 (public domain dedication)",
            "source": "Original procedural synthesis by scripts/generate_assets.py",
        }
        for name in ("whoosh_soft.wav", "whoosh_down.wav", "riser_short.wav", "click_soft.wav")
    }
    (SFX / "licenses.json").write_text(json.dumps(sfx_manifest, indent=2) + "\n", encoding="utf-8")
    for p in sorted(list(MUSIC.glob("*.wav")) + list(SFX.glob("*.wav"))):
        print(f"{p.relative_to(ROOT)}  {p.stat().st_size / 1048576:.2f} MB")


if __name__ == "__main__":
    main()
