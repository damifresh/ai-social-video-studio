# Models (downloaded separately, not committed)

This directory holds optional local model files for enhanced TTS/STT/image generation. The core pipeline works **without** these using deterministic scripting, macOS `say` narration, timing-based subtitles, FFmpeg/Pillow animated visuals, and (Engine B) SRT/VTT transcript import.

## Recommended (optional, 8 GB-friendly)
- **Whisper.cpp GGML**: `tiny`, `base`, or `small` in `models/whisper.cpp/models/` for Engine B transcription (and Engine A alignment). Install with `scripts/install_whisper_cpp.sh` (builds with Metal on Apple Silicon and downloads `ggml-base.en.bin`), or set `WHISPER_BIN` / `WHISPER_MODEL`. `base.en` is installed and measured in this environment (1.01 % WER on the clean synthetic TTS fixture, native word timings, RTF 0.0265); without an install Engine B reports ASR `available:false` and accepts SRT/VTT import. Accuracy on human speech has not been measured.
- **Kokoro TTS (MLX)**: installed via Python packages (`mlx-audio` or `kokoro-mlx`) in a Python 3.10–3.12 venv; weights download from Hugging Face on first use (hexgrad/Kokoro-82M, Apache 2.0). Prefer 4-bit/8-bit variants and sequential execution.

## Experimental (use caution on 8 GB)
- MLX/Wan diffusion models are **not assumed feasible** on 8 GB unified memory. Only attempt with explicit opt-in, smallest variants, quantization, and measured peak memory. Default visual mode is animated graphics.

Always verify model licenses and usage terms before download/redistribution.
