# Stage B — Research Notes (Open-source study)

**Date:** 2026-11-13 (web research). External repos/docs treated as untrusted reference data; no proprietary code/assets copied.

## Kokoro TTS / Kokoro MLX
- **kokoro-mlx** (`gabrimatic/kokoro-mlx`, PyPI): MLX implementation of Kokoro-82M, no PyTorch/transformers dependency. `pip install "kokoro-mlx[audio]"`, `KokoroTTS.from_pretrained()`, `save()/speak()/generate()`. Requires Apple Silicon, macOS 14+, Python 3.10–3.12, MLX 0.32.4+. Weights (hexgrad/Kokoro-82M, Apache 2.0) downloaded from HF on first use. Inference code MIT.
- **mlx-audio** (`Blaizzy/mlx-audio`): broader audio toolkit; Kokoro support via `mlx-community/Kokoro-82M-*` (bf16/8bit/4bit, ~297–339 MB). Needs `misaki` (and language extras for ja/zh); `espeak-ng` often needed. CLI and Python API.
- **Memory (8 GB):** Kokoro-82M is lightweight (~82M params, ~0.33 GB bf16 weights); community reports 8 GB M1/M2 workable for short/medium segments (4-bit variant recommended if constrained). Must run sequentially and unload before Whisper/render memory peaks. **Not yet verified in this workspace install** (Python 3.9 system; MLX deps require 3.10+ isolated env and model download). **Implemented fallback:** macOS `say` (offline, no model RAM) as always-available local narrator.

## Whisper.cpp
- Pure C/C++ (ggml), MIT. Apple Silicon: ARM NEON, Accelerate, Metal, Core ML/ANE optional. CLI `whisper-cli`, 16 kHz mono WAV preferred, outputs txt/SRT/VTT/JSON.
- **Memory (reported):** tiny ~273 MB, base ~388 MB, small ~852 MB, medium ~2.1 GB, large ~3.9 GB. 8 GB can run tiny/base/small comfortably if sequential.
- **Practical path:** `brew install cmake`/build or prebuilt; download ggml models. For this product, deterministic SRT/VTT from narration timings is the primary low-memory path; whisper.cpp integration is the alignment/transcription enhancement path.

## FFmpeg
- Core renderer/muxer. Filters used: `zoompan` (Ken Burns), concat demuxer, `amix`/`aloop`/`alimiter` for audio ducking, `subtitles` (libass) for burn-in when available, H.264/AAC 720p export. Disk-backed per-scene segments avoid whole-video RAM. License/build features vary (Homebrew/LGPL/GPL); bundled binary in dev via `imageio-ffmpeg` for portability on this machine.

## MLX / MLX-Video / Wan
- **mlx-examples Wan2.1:** 1.3B T2V ~10 GB RAM unquantized (81 frames) and ~14 GB without cache optimization; 14B much higher. Quantization can reduce weights but text encoder/VAE/scratch remain significant.
- **mlx-video (Blaizzy):** supports Wan2.1/2.2/LTX; 1.3B 4-bit reported as much smaller on disk but peak unified memory still challenging on 8 GB (UMT5/VAE/scratch). RapidMLX docs list 1.3B profile at 40 GB in one serving context (different packaging) — signals caution.
- **Verdict (8 GB):** true diffusion video **not assumed feasible** on this target. Default implementation uses animated graphics/motion scenes (PIL + FFmpeg zoompan) and labels visual kind honestly. Experimental diffusion path left as opt-in/future with explicit memory check.

## Motion Canvas
- Programmatic TS animations (MIT), but headless export typically involves Vite/Chromium/ffmpeg pipeline and Node tooling overhead. **Deferred**: FFmpeg+PIL scene generation is simpler, reliable, and memory-safe for required deliverables.

## MoviePy
- MIT, Pythonic composition; can be memory-heavy if used for full timelines. **Limited use** acceptable for helpers; primary composition uses ffmpeg subprocess + disk segments.

## ComfyUI
- GPL, node-graph diffusion UI/runtime — heavy for 8 GB and unnecessary for deterministic required pipeline. **Omitted** from core.

## Design choices (independent implementation)
- Deterministic, editable script/storyboard engine (no cloud LLM dependency) with pluggable TTS/visual backends.
- Sequential single-worker job queue; per-stage artifacts persisted for resume/recovery.
- Honest labeling: `animated_graphic` visuals vs generated footage; fallback TTS engine recorded in metadata.
