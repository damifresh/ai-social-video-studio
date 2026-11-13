from __future__ import annotations
import os, subprocess, shutil, uuid
from pathlib import Path
from ..core.config import settings

# Available macOS voices (common); actual availability checked at runtime
SAY_VOICES = ["Samantha", "Alex", "Daniel", "Karen", "Moira", "Tessa", "Rishi", "Veena"]

def list_voices() -> list[dict]:
    voices = []
    # Try macOS say -v ?
    try:
        out = subprocess.check_output(["say", "-v", "?"], text=True, stderr=subprocess.STDOUT, timeout=10)
        for line in out.splitlines():
            # format: Name  lang  # sample
            parts = line.split()
            if parts:
                name = parts[0]
                lang = parts[1] if len(parts) > 1 else ""
                voices.append({"id": f"say:{name}", "name": name, "lang": lang, "engine": "macos-say", "local": True})
    except Exception:
        for v in SAY_VOICES:
            voices.append({"id": f"say:{v}", "name": v, "lang": "en_US", "engine": "macos-say", "local": True})
    # Kokoro placeholder (detected if installed) - real integration attempted separately
    voices.append({"id": "kokoro:af_heart", "name": "Kokoro af_heart (MLX, if installed)", "lang": "en", "engine": "kokoro-mlx", "local": True, "available": False, "note": "Requires kokoro-mlx/mlx-audio install; falls back to macOS say"})
    return voices


def synthesize_say(text: str, out_wav: Path, voice: str = "Samantha", rate_wpm: int | None = None) -> dict:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp_aiff = out_wav.with_suffix(".aiff")
    say_voice = voice.replace("say:", "") if voice.startswith("say:") else voice
    cmd = ["say", "-v", say_voice]
    if rate_wpm:
        cmd += ["-r", str(int(rate_wpm))]
    cmd += ["-o", str(tmp_aiff), text]
    subprocess.run(cmd, check=True, timeout=300)
    # convert to wav 16k mono for whisper/compat
    subprocess.run([settings.ffmpeg, "-y", "-i", str(tmp_aiff), "-ar", "24000", "-ac", "1", str(out_wav)],
                   check=True, capture_output=True, timeout=120)
    try: tmp_aiff.unlink()
    except Exception: pass
    dur = probe_duration(out_wav)
    return {"path": str(out_wav), "duration_sec": dur, "engine": "macos-say", "voice": say_voice}


def synthesize(text: str, out_wav: Path, voice: str = "say:Samantha", **kw) -> dict:
    # Route: kokoro if explicitly requested and available, else macOS say
    if voice.startswith("kokoro:"):
        # attempt kokoro; fall back gracefully
        try:
            return synthesize_kokoro(text, out_wav, voice=voice.split(":",1)[1], **kw)
        except Exception as e:
            # fallback
            res = synthesize_say(text, out_wav, voice="Samantha", **kw)
            res["fallback_from"] = "kokoro"
            res["fallback_reason"] = str(e)[:200]
            return res
    return synthesize_say(text, out_wav, voice=voice, **kw)


def synthesize_kokoro(text: str, out_wav: Path, voice: str = "af_heart", **kw) -> dict:
    """Best-effort Kokoro via mlx-audio or kokoro-mlx if installed in an accessible env.
    Raises on failure so caller can fall back."""
    # Try kokoro-mlx API
    try:
        from kokoro_mlx import KokoroTTS  # type: ignore
        tts = KokoroTTS.from_pretrained()
        tts.save(text, str(out_wav))
        dur = probe_duration(out_wav)
        return {"path": str(out_wav), "duration_sec": dur, "engine": "kokoro-mlx", "voice": voice}
    except Exception:
        pass
    # Try mlx_audio CLI-style via python module
    try:
        import mlx_audio.tts.utils as mau  # type: ignore
        model = mau.load_model("mlx-community/Kokoro-82M-bf16")
        for result in model.generate(text=text, voice=voice, speed=kw.get("speed",1.0), lang_code=kw.get("lang_code","a")):
            # result.audio is mx array; save via soundfile if available
            import numpy as np, soundfile as sf  # type: ignore
            audio = np.array(result.audio)
            out_wav.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(out_wav), audio, 24000)
            dur = probe_duration(out_wav)
            return {"path": str(out_wav), "duration_sec": dur, "engine": "mlx-audio-kokoro", "voice": voice}
    except Exception as e:
        raise RuntimeError(f"Kokoro not available: {e}")


def probe_duration(path: Path) -> float:
    # Use ffmpeg stderr parsing (ffprobe may be absent)
    try:
        p = subprocess.run([settings.ffmpeg, "-i", str(path)], capture_output=True, text=True, timeout=30)
        # Duration: 00:00:05.12
        import re
        m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h)*3600 + int(mi)*60 + float(s)
    except Exception:
        pass
    # wav fallback
    try:
        import wave, contextlib
        with contextlib.closing(wave.open(str(path),'r')) as f:
            frames = f.getnframes(); rate = f.getframerate(); return frames/float(rate)
    except Exception:
        return 0.0
