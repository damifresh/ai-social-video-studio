# Stage B — Reverse Engineering & Open-Source Study (Completed)

**Date:** 2026-11-13  
**Method:** Public documentation and repository research (web), local capability inspection. No proprietary software, protected assets, or copyrighted source code copied. Treated external content as reference data.

## Projects studied and what was extracted

### 1. Kokoro TTS / Kokoro MLX (`gabrimatic/kokoro-mlx`, `Blaizzy/mlx-audio`)
- **Architecture:** 82M-parameter TTS, MLX inference on Apple Silicon; weights from Hugging Face (hexgrad/Kokoro-82M, Apache 2.0) downloaded on first use. APIs: `from_pretrained`, `generate/save/speak`, voice/lang selection, quantized variants (bf16/8bit/4bit).
- **Dependencies/exec:** Python 3.10–3.12, `mlx>=0.32.4`, `misaki` (G2P), optional `sounddevice`, `espeak-ng` for some phonemization paths; audio encoding may need ffmpeg.
- **Useful extraction:** model/runtime sizing (~327 MB bf16), voice/language concepts, quantization path, sequential load/unload suitability for 8 GB.
- **Integration decision:** adapter-based TTS with Kokoro hook (`services/tts.py`) and **verified offline fallback** to macOS `say` (always available, zero model RAM). Kokoro install not completed in-session due to Python 3.9 system / model download requirements; interface ready.

### 2. Whisper.cpp (`ggml-org/whisper.cpp`)
- **Architecture:** C/C++ ggml port of Whisper; Metal/Accelerate/CoreML on Apple Silicon; `whisper-cli` with WAV input and SRT/VTT/JSON output.
- **Memory/footprint:** tiny ~273 MB, base ~388 MB, small ~852 MB, medium ~2.1 GB, large ~3.9 GB — base/small fit 8 GB sequentially.
- **Useful extraction:** model selection for 8 GB, alignment/subtitle output formats, build flags (Metal default on macOS).
- **Integration decision:** primary path is deterministic subtitles from narration timings (fast, no ASR memory); Whisper.cpp designated as optional alignment/transcription enhancement (install/build documented).

### 3. FFmpeg
- **Architecture/capabilities:** stream-based encode/mux/filter pipeline. Key primitives used: `zoompan` motion, per-scene segment render, concat demuxer, `amix/aloop/alimiter` ducking, H.264/AAC 720p export, duration probing via stderr.
- **Useful extraction:** disk-backed segmented composition avoids in-memory timelines; preset/CRF tradeoffs for CPU-bound 8 GB machines.
- **Integration:** core renderer in `services/render.py` and `services/audio_mix.py`; resolved via `imageio-ffmpeg` bundled binary (v9.0, arm64) in this environment.

### 4. MLX / MLX-Video / Wan 2.1 (`ml-explore/mlx-examples`, `Blaizzy/mlx-video`)
- **Architecture/findings:** Wan2.1 1.3B T2V reported ~10 GB RAM unquantized (81 frames) and ~14 GB without cache optimization in mlx-examples; 14B far higher. Conversions/quantization reduce some footprint but UMT5/VAE/scratch remain significant on 8 GB unified memory.
- **Useful extraction:** feasibility boundary for 8 GB, memory controls (`--no-cache`, quantization, tiling), step/perf characteristics.
- **Integration decision:** **not enabled by default**. Visual engine produces honestly labeled `animated_graphic` scenes (PIL + motion). Diffusion video treated as experimental opt-in requiring measured memory headroom.

### 5. Motion Canvas
- **Architecture:** TS programmatic animation; rendering typically via Node/Vite/browser capture + FFmpeg.
- **Decision:** deferred; equivalent motion-graphic outcomes achieved with FFmpeg+Pillow for lower toolchain/memory complexity and reliable headless rendering.

### 6. MoviePy / ComfyUI
- **MoviePy:** useful compositing API but can inflate memory on full timelines; ffmpeg subprocesses preferred for final render.
- **ComfyUI:** heavy diffusion workflow UI/runtime, impractical as required dependency on 8 GB; omitted.

## Coherent integration outcome
An independent modular product combining: deterministic script/storyboard engine → pluggable local TTS (say/Kokoro-ready) → timing-based subtitles (+ Whisper.cpp path) → Pillow/FFmpeg animated visual scenes → FFmpeg audio mix and per-scene segmented 720p MP4 render → React/FastAPI/SQLite project management, with sequential 8 GB-safe execution and honest capability labeling.
