# Troubleshooting Guide

## FFmpeg not found / render fails
- Check `GET /health` → `ffmpeg` path and `ffmpeg_ok`.
- Install: `uv pip install --python backend/.venv imageio-ffmpeg` or `brew install ffmpeg`, or set `FFMPEG_PATH`.
- `subtitles` burn-in requires libass-enabled ffmpeg; if unavailable the app muxes video+audio and provides `.srt/.vtt` sidecars.

## `409 Another job is running`
- By design on 8 GB: only one heavy job runs at a time. Wait for completion or check `/api/jobs/<id>`.

## TTS / voice issues
- Default `say:*` voices use macOS built-in `say` (offline). Ensure the selected voice exists (`say -v ?`).
- `kokoro:*` voices require Kokoro MLX packages + model download + Python 3.10+; on failure the pipeline falls back to `say` and records `tts_fallback` in scene metadata.
- Very long narration increases render time (per-scene segments). Edit script to shorten if needed.

## Out of memory / system slowdown
- Close other apps. Keep generation sequential.
- Avoid running Whisper/Kokoro/diffusion models simultaneously.
- Prefer tiny/base Whisper models; keep diffusion/video models off on 8 GB.
- Renders are disk-backed; if a crash occurs, intermediates remain in `data/projects/<id>/` for inspection.

## Video duration differs from target
- Final duration follows actual narration audio (source of truth) to keep A/V in sync. The script engine expands text to target duration, but `say` speaking rate and edits affect final length. Regenerate or edit narration for tighter control.

## Subtitles out of sync
- Timing-based subtitles are aligned to synthesized scene audio boundaries. For ASR-refined alignment, install and run Whisper.cpp on narration audio, then regenerate SRT.

## Frontend cannot reach API
- Start backend on `:8000` and frontend dev server on `:5173` (Vite proxies `/api`). For production, build frontend and serve with a static host/proxy to backend.
- CORS allows localhost origins in dev.

## Interrupted job / recovery
- Job state and artifacts persist in SQLite/filesystem. Failed jobs do not delete prior assets. Re-run full generation or regenerate specific scenes; per-file outputs are overwritten safely.

## Project not found after delete
- Project DB row removed; filesystem artifacts may remain under `data/projects/<id>/` for safety. Remove manually if desired.
