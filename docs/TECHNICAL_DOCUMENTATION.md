# Technical Documentation

## Overview
Local AI Social Video Studio is a localhost-only, modular application that produces 720p social-media videos (1–5 min target) from a topic/prompt. It runs on Apple Silicon with an 8 GB unified-memory-safe, sequential pipeline.

## Architecture
- **Frontend (`frontend/`)**: React + TypeScript + Vite + Tailwind. Routes: Dashboard, New Project, Project workspace (Script/Storyboard/Render/Export), Settings. Polls job status from backend.
- **Backend (`backend/`)**: FastAPI (Python 3.11), SQLite via SQLAlchemy, filesystem project store, single-worker sequential job execution (background task per job, guarded to one running job).
- **Media engines**: FFmpeg (imageio-ffmpeg bundled binary or system) for probing, audio conversion/mix, per-scene zoompan rendering, concat, mux. Pillow for programmatic scene graphics.
- **AI engines (local, optional/fallback)**: TTS adapter — macOS `say` (default, offline) and Kokoro MLX hooks (best-effort). Subtitles — timing/SRT/VTT generation; whisper.cpp integration path documented. Script — deterministic local generator (editable, pluggable interface).

## Data model
- **SQLite `data/studio.db`**: `projects` (topic, prompt, duration, aspect, style, voice, status, etc.), `jobs` (type, stage, status, progress 0–100, message, error, meta JSON).
- **Project directory `data/projects/<id>/`**: `project.json`-equivalent DB state + `script.json/.md`, `scenes.json`, `timings.json`, `result.json`, `audio/` (scene WAVs, narration, mix), `images/` (scene PNGs), `video/scenes/` (per-scene MP4), `video/video_concat.mp4`, `subs/*.srt|vtt`, `renders/final_*.mp4`, `logs/pipeline.log`.

## Pipeline (sequential)
1. **Script**: duration-aware deterministic generation (`script_engine.py`), ~140 WPM planning, expanded narration per scene.
2. **Storyboard**: scenes with narration, visual description, camera motion, transition, SFX/text overlay, `visual_kind=animated_graphic`.
3. **Visuals**: Pillow-generated scene images (style palettes, typography, shapes), labeled honestly.
4. **TTS**: per-scene narration (macOS `say` → AIFF → WAV via FFmpeg) or Kokoro if available; audio duration is source of truth for pacing.
5. **Subtitles**: segment timings → SRT/VTT.
6. **Audio mix**: concat narration; optional looped background music + ducking/limiter via FFmpeg (if licensed asset provided).
7. **Render**: per-scene MP4 via FFmpeg `zoompan` (720p, 30 fps, H.264 yuv420p) using disk images; concat segments.
8. **Compose**: mux final audio (AAC 48 kHz stereo) + video; sidecar subtitles. Result metadata persisted.

## API (key endpoints)
- `GET /health` — runtime/ffmpeg status
- `GET /api/voices` — available voices
- `GET/POST /api/projects`, `GET/PATCH/DELETE /api/projects/{id}`, `POST /api/projects/{id}/duplicate`
- `POST /api/projects/{id}/generate-script`, `PUT /api/projects/{id}/script`, `PUT /api/projects/{id}/scenes`
- `POST /api/projects/{id}/generate` — enqueue full pipeline (409 if another running)
- `POST /api/projects/{id}/scenes/{idx}/regenerate` — regenerate single scene assets
- `GET /api/jobs/{id}`, `GET /api/projects/{id}/jobs`
- `GET /api/projects/{id}/files/{video|srt|vtt|result}`

## Memory & reliability (8 GB)
- One job at a time; no concurrent heavy models.
- Disk-backed per-scene artifacts and FFmpeg streaming/segment workflow.
- Failures record error and preserve intermediates; project DB/files remain intact.
- Real progress derived from pipeline stage updates (no fake percentages).

## Extensibility
- TTS backends via `services/tts.py` adapter (`synthesize_*`).
- Visual generators via `services/visuals.py` (swap in image-gen/model output while keeping `visual_kind` labeling).
- Script engine pluggable (`services/script_engine.py`).
- Optional engines (Kokoro, Whisper.cpp, MLX image/video) can be added behind capability checks and sequential execution.

## Security & licensing posture
- Localhost only, no auth, no cloud calls in normal flow.
- No paid APIs/subscriptions.
- Bundled/user media must be properly licensed; model licenses (e.g. Kokoro weights Apache 2.0, Whisper.cpp MIT, Wan license terms) must be reviewed before redistribution/use.
