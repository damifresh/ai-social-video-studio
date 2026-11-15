# Technical Documentation

## Overview
Local AI Social Video Studio is a localhost-only, modular application with two engines on one shared infrastructure: **Engine A** produces 720p social-media videos (1–5 min target) from a topic/prompt, and **Engine B** (AI Auto-Clip Studio) turns an uploaded long recording into short, captioned 720p clips. It runs on Apple Silicon with an 8 GB unified-memory-safe, sequential pipeline.

## Architecture
- **Frontend (`frontend/`)**: React + TypeScript + Vite + Tailwind. Routes: Dashboard, New Project, Project workspace (Script/Storyboard/Render/Export), **Auto-Clip Studio (`/clip`, `/clip/:id`)**, Settings. Polls job status from backend.
- **Backend (`backend/`)**: FastAPI (Python 3.11), SQLite via SQLAlchemy, filesystem project store, single-worker sequential job execution (background task per job, guarded to one running job **across both engines**).
- **Two independent engines:** Engine A (`app/api/*`, `app/services/*`) generates video from a topic; Engine B (`app/clip/*`) turns an uploaded recording into short clips. They share only infrastructure (DB session, FFmpeg resolution, memory guard, job serialisation, UI design system) — never tables, files or job rows.
- **Media engines**: FFmpeg (imageio-ffmpeg bundled binary or system) for probing, audio conversion/mix, per-scene zoompan rendering, concat, mux. Pillow for programmatic scene graphics.
- **AI engines (local, optional/fallback)**: TTS adapter — macOS `say` (default, offline) and Kokoro MLX hooks (best-effort). Subtitles — timing/SRT/VTT generation; whisper.cpp integration path documented. Script — deterministic local generator (editable, pluggable interface). Engine B ASR — whisper.cpp adapter, capability-gated, with SRT/VTT import fallback.

## Data model
- **SQLite `data/studio.db`**: `projects` (topic, prompt, duration, aspect, style, voice, status, etc.), `jobs` (type, stage, status, progress 0–100, message, error, meta JSON).
- **Engine B tables (additive):** `clip_projects`, `clip_sources` (SHA-256, probe JSON), `clip_candidates` (window, score JSON, reason, edit JSON), `clip_renders` (aspect, output path, probe JSON), `clip_jobs` (stage/status/progress/message/error/peak memory/cancel flag). Engine A's `jobs.project_id` stays `NOT NULL`, so Engine B never writes into Engine A's job table.
- **Project directory `data/projects/<id>/`**: `project.json`-equivalent DB state + `script.json/.md`, `scenes.json`, `timings.json`, `result.json`, `audio/` (scene WAVs, narration, mix), `images/` (scene PNGs), `video/scenes/` (per-scene MP4), `video/video_concat.mp4`, `subs/*.srt|vtt`, `renders/final_*.mp4`, `logs/pipeline.log`.
- **Clip directory `data/clip_projects/<id>/`**: `source/` (original upload, never rewritten), `analysis/` (`audio16k.wav`, `structural.json`, `transcript.json`, `whisper_output.json`), `clips/` (per-aspect MP4 + `captions.ass`), `exports/` (numbered MP4s + `manifest.json`), `logs/clip.log`, `tmp/` (upload staging and `.part.mp4`, cleaned after each job).

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

## Engine B pipeline (sequential)
1. **Ingest**: streamed 4 MB chunks + running SHA-256, extension gate, probe, limits (8 GB / 3 h), audio-stream requirement. Stored file is never rewritten.
2. **Analyze**: mono 16 kHz WAV; RMS/peak envelope at 0.1 s windows over an 8 kHz decode; `silencedetect` gaps; 2 fps 320 px scene scan. Artifacts in `analysis/`.
3. **Transcribe** (capability-gated): whisper.cpp with token-offset JSON (word timing `native`), or segment JSON (`estimated`); import path parses SRT/VTT with clamping and monotonic enforcement, then rebuilds sentences; edit path validates and rebuilds.
4. **Highlights**: sentences snapped to nearby silence (≤0.5 s), windows within 80–130 % of each requested duration, eight weighted components, greedy non-overlapping selection, full score table + reason persisted per candidate.
5. **Render**: crop (deterministic centre/edge/manual rect) → scale to target with aspect-preserving increase → exact crop → `setsar=1`/fps/yuv420p; ASS captions from the clip's own sentences; `loudnorm=I=-16:TP=-1.5:LRA=11`; optional sidechain-ducked music; libx264 CRF 21 veryfast + AAC 128 kbit/s 48 kHz stereo + `+faststart`; post-write validation.
6. **Export**: per-clip output into `exports/` with individual results and `manifest.json`.

Sequential guard: a heavy job is either an Engine A `jobs` row or a `clip_jobs` row; the second engine's enqueue returns 409 with the blocking job's type.

## Engine B API
`/api/clip/*`: `capabilities`, `diagnostics`, projects CRUD, `source` upload/stream, `analyze`, `transcribe`, `transcript` (GET/PUT), `transcript/import`, `highlights`, `clips`, clip `PATCH`/`DELETE`, `metadata` regeneration, `render`, clip file download, `export-batch`, `exports`, `jobs/{id}`, `jobs/{id}/cancel`. `/api/system` additionally reports the clip project count, active clip job and ASR capability. Full table: [`ENGINE_B.md`](ENGINE_B.md#4-api-reference).

## Memory & reliability (8 GB)
- One heavy job at a time across both engines; no concurrent heavy models.
- Disk-backed per-scene/per-clip artifacts and FFmpeg streaming/segment workflows.
- Failures record error and preserve intermediates; project DB/files remain intact.
- Real progress derived from pipeline stage updates and FFmpeg `-progress` frames (no fake percentages).
- Engine B measures per-job peak RSS, cleans `tmp/` on success/failure, and marks startup leftovers `interrupted`.

## Extensibility
- TTS backends via `services/tts.py` adapter (`synthesize_*`).
- Visual generators via `services/visuals.py` (swap in image-gen/model output while keeping `visual_kind` labeling).
- Script engine pluggable (`services/script_engine.py`).
- ASR via `app/clip/transcribe.py` capability gate (`WHISPER_BIN`, `WHISPER_MODEL`, or `models/whisper.cpp/...`).
- Highlight weights and metadata templates are data in `app/clip/highlights.py` / `metadata.py`, versioned (`transcript-template/v1`).

## Security & licensing posture
- Localhost only, no auth, no cloud calls in normal flow.
- No paid APIs/subscriptions.
- Bundled/user media must be properly licensed; model licenses (e.g. Kokoro weights Apache 2.0, Whisper.cpp MIT, Wan license terms) must be reviewed before redistribution/use.
