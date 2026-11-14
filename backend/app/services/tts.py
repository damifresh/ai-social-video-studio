from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from ..core.config import DATA_DIR, detect_engines, settings

KOKORO_VOICES = [
    ("af_heart", "Heart (US female)"),
    ("af_bella", "Bella (US female)"),
    ("af_nicole", "Nicole (US female)"),
    ("am_michael", "Michael (US male)"),
    ("am_fenrir", "Fenrir (US male)"),
    ("bf_emma", "Emma (UK female)"),
    ("bm_george", "George (UK male)"),
]

FALLBACK_SAY = ["Samantha", "Alex", "Daniel", "Karen", "Moira", "Tessa", "Rishi", "Veena"]


def _say_voices() -> list[dict]:
    voices: list[dict] = []
    try:
        out = subprocess.check_output(["say", "-v", "?"], text=True, stderr=subprocess.STDOUT, timeout=15)
        for line in out.splitlines():
            parts = line.split()
            if not parts:
                continue
            name = parts[0]
            lang = parts[1] if len(parts) > 1 else ""
            voices.append({"id": f"say:{name}", "name": name, "lang": lang, "engine": "macos-say", "local": True, "available": True})
    except Exception:
        for name in FALLBACK_SAY:
            voices.append({"id": f"say:{name}", "name": name, "lang": "en_US", "engine": "macos-say", "local": True, "available": True})
    return voices


def list_voices() -> list[dict]:
    engines = detect_engines()
    voices = _say_voices()
    for vid, label in KOKORO_VOICES:
        voices.append({
            "id": f"kokoro:{vid}",
            "name": f"Kokoro {label}",
            "lang": "en",
            "engine": "kokoro-mlx",
            "local": True,
            "available": engines["kokoro"],
            "note": None if engines["kokoro"] else engines["kokoro_hint"],
        })
    return voices


def probe_duration(path: Path) -> float:
    try:
        p = subprocess.run([settings.ffmpeg, "-i", str(path)], capture_output=True, text=True, timeout=30)
        import re

        m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    try:
        import contextlib
        import wave

        with contextlib.closing(wave.open(str(path), "r")) as f:
            return f.getnframes() / float(f.getframerate())
    except Exception:
        return 0.0


def synthesize_say(text: str, out_wav: Path, voice: str = "Samantha", rate_wpm: int | None = None) -> dict:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    say_voice = voice.split(":", 1)[1] if voice.startswith("say:") else voice
    with tempfile.TemporaryDirectory(prefix="lavs_say_") as td:
        tmp_aiff = Path(td) / "speech.aiff"
        cmd = ["say", "-v", say_voice]
        if rate_wpm and int(rate_wpm) > 0:
            cmd += ["-r", str(int(rate_wpm))]
        cmd += ["-o", str(tmp_aiff), text]
        subprocess.run(cmd, check=True, timeout=600)
        subprocess.run(
            [settings.ffmpeg, "-y", "-i", str(tmp_aiff), "-ar", "24000", "-ac", "1", str(out_wav)],
            check=True, capture_output=True, timeout=300,
        )
    return {"path": str(out_wav), "duration_sec": probe_duration(out_wav), "engine": "macos-say", "voice": say_voice}


def synthesize_kokoro(text: str, out_wav: Path, voice: str = "af_heart", speed: float = 1.0) -> dict:
    """Best-effort Kokoro via kokoro-mlx or mlx-audio. Raises when unavailable."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    try:
        import kokoro_mlx  # type: ignore

        cls = getattr(kokoro_mlx, "KokoroTTS", None) or getattr(kokoro_mlx, "Kokoro", None)
        if cls is not None:
            tts = cls.from_pretrained() if hasattr(cls, "from_pretrained") else cls()
            if hasattr(tts, "save"):
                tts.save(text, str(out_wav), voice=voice)
            else:
                audio = tts.generate(text, voice=voice, speed=speed)
                _write_audio(audio, out_wav)
            return {"path": str(out_wav), "duration_sec": probe_duration(out_wav), "engine": "kokoro-mlx", "voice": voice}
    except Exception as e:  # noqa: BLE001
        errors.append(f"kokoro_mlx: {e}")

    try:
        from mlx_audio.tts.utils import load_model  # type: ignore

        model = load_model("mlx-community/Kokoro-82M-bf16")
        for result in model.generate(text=text, voice=voice, speed=speed, lang_code="a"):
            _write_audio(getattr(result, "audio", result), out_wav)
            break
        return {"path": str(out_wav), "duration_sec": probe_duration(out_wav), "engine": "mlx-audio-kokoro", "voice": voice}
    except Exception as e:  # noqa: BLE001
        errors.append(f"mlx_audio: {e}")

    raise RuntimeError("; ".join(errors)[:400] or "Kokoro runtime not available")


def _write_audio(audio, out_wav: Path) -> None:
    import numpy as np
    import soundfile as sf  # type: ignore

    arr = np.array(audio)
    sf.write(str(out_wav), arr, 24000)


def synthesize(text: str, out_wav: Path, voice: str = "say:Samantha", speed: int = 0, **kw) -> dict:
    if voice.startswith("kokoro:"):
        try:
            return synthesize_kokoro(text, out_wav, voice=voice.split(":", 1)[1], speed=1.0 + (speed / 100.0 if speed else 0.0))
        except Exception as e:  # noqa: BLE001
            result = synthesize_say(text, out_wav, voice="Samantha", rate_wpm=speed or None)
            result["fallback_from"] = "kokoro"
            result["fallback_reason"] = str(e)[:300]
            return result
    rate = int(speed) if speed and int(speed) > 60 else (int(speed) if speed else None)
    # voice_speed is stored as words-per-minute when > 60, otherwise as extra percentage
    wpm = rate if rate and rate > 60 else (180 + rate if rate else None)
    return synthesize_say(text, out_wav, voice=voice, rate_wpm=wpm)


def preview(voice: str, text: str | None = None) -> Path:
    sample = (text or "This is a preview of the selected narration voice for your social video.").strip()[:220]
    key = hashlib.sha1(f"{voice}|{sample}|{detect_engines()['kokoro']}".encode()).hexdigest()[:16]
    out = DATA_DIR / "previews" / f"{key}.wav"
    if out.exists() and out.stat().st_size > 1000:
        return out
    synthesize(sample, out, voice=voice)
    return out
