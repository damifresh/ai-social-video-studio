# Troubleshooting Guide

## FFmpeg not found / render fails
- Check `GET /health` → `ffmpeg` path and `ffmpeg_ok`.
- Install: `uv pip install --python backend/.venv imageio-ffmpeg` or `brew install ffmpeg`, or set `FFMPEG_PATH`.
- `subtitles` burn-in requires libass-enabled ffmpeg; if unavailable the app muxes video+audio and provides `.srt/.vtt` sidecars.

## `409 Another job is running`
- By design on 8 GB: only one heavy job runs at a time **across both engines**. Engine A jobs are at `/api/jobs/<id>`, Engine B jobs at `/api/clip/jobs/<id>`. The 409 detail names the blocking job type.

## Engine B (Auto-Clip Studio) issues

### "Speech recognition unavailable" / Transcribe disabled
- Expected when no local ASR is installed. `GET /api/clip/capabilities` lists the exact reasons.
- Either import an existing `.srt`/`.vtt` (Transcript → Import), or install whisper.cpp:
  ```bash
  scripts/install_whisper_cpp.sh --check   # reports missing prerequisites
  brew install cmake                       # if missing
  scripts/install_whisper_cpp.sh           # clone + build + ggml-base.en.bin
  ```
- Restart the backend and confirm `"available": true`. The app never fabricates a transcript.

### Upload rejected
- `415`: container not in MP4/MOV/MKV/WebM. Remux first (`ffmpeg -i in.<ext> -c copy out.mp4`).
- `400` no audio stream: clip timing needs audio; add a track and re-upload.
- `413`: file exceeds the 8 GB cap (or duration exceeds 3 h).

### Uploading a second video
- One source per project. The UI replaces the source and **clears the old transcript/clips** because their timings refer to the old file; the API returns `409` unless `replace_existing=true`.

### Captions/subtitles missing in a clip
- Check the render's `validation` and the clip's transcript. Burn-in requires libass-enabled FFmpeg (`subtitles` filter); the capability/diagnostics endpoint reports the resolved binary.

### Clip count lower than requested
- Non-overlapping windows that fit the source are limited; the job reports a `shortfall` string instead of duplicating/overlapping spans. Shorten the target durations or use a longer source.

### Crop cuts off the subject
- Crops are deterministic geometry, not tracking. Choose a manual rectangle (`crop.mode=custom`, fractions of the source frame) and re-render.

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
- Start backend on `:8000` and frontend dev server on `:5173` (Vite proxies `/api`, `/health`, `/data`, `/media`). For production, build the frontend (`frontend/dist`) — the backend serves it with an SPA fallback.
- CORS allows localhost/127.0.0.1 origins in dev.

## Desktop app issues (packaged `.app`)
- **macOS blocks the app (unsigned):** right-click the app → **Open** → **Open**, or **System Settings → Privacy & Security → Open Anyway**.
- **“Local engine could not start”:** check `~/Library/Application Support/AI Social Video Studio/logs/backend.log`. Ensure the app bundle contains `Contents/Resources/runtime/{python,py-packages,backend,frontend-dist}`.
- **Where are my projects?** `~/Library/Application Support/AI Social Video Studio/data/projects/`. Use the menu **Open Data Folder**. Reinstalling/updating the app does not delete user data.
- **Bundled music not listed:** confirm `assets/music/*.wav` and `licenses.json` exist inside the app’s runtime and `/media/music/...` responds (dev: backend serves `/media`).

## Interrupted job / recovery
- Job state and artifacts persist in SQLite/filesystem. On backend startup, stale `running/queued` jobs are marked **interrupted** (artifacts preserved). Failed/interrupted/canceled jobs do not delete prior assets — re-run generation or re-render safely.
- Use the job **Cancel** action to stop at the next safe stage boundary.

## Project not found after delete
- Project DB row removed; filesystem artifacts may remain under the project data folder for safety. Remove manually if desired.
