# Local AI Social Video Studio

Localhost-only AI social video studio for Apple Silicon (target: **Apple M2 / 8 GB unified memory**). Produces 720p MP4 videos (1–5 min target) with scripts, storyboards, narration, subtitles, music/SFX mixing, motion-graphic visuals, and FFmpeg rendering — **no paid APIs, no cloud inference, no subscriptions** required for normal production once dependencies/assets are installed.

## Status (verified 2026-11-13)
- **Stage A (Plan):** complete — [`PLAN_STAGE_A.md`](PLAN_STAGE_A.md)
- **Stage B (Reverse engineering/research):** complete — [`docs/STAGE_B_REVERSE_ENGINEERING.md`](docs/STAGE_B_REVERSE_ENGINEERING.md), [`docs/RESEARCH_NOTES.md`](docs/RESEARCH_NOTES.md)
- **Stage C (Build):** functional MVP delivered and tested (see evidence below)

### Verified outputs
- `deliverables/demo_60s_16x9_720p.mp4` — 78.4s, 1280x720, H.264/AAC, narration + subtitles
- `deliverables/demo_60s_9x16_720p.mp4` — 78.8s, 720x1280 (vertical)
- `deliverables/demo_180s_16x9_720p.mp4` — 183.5s (~3 min), 1280x720, 9 scenes
- Sample projects persisted in `data/projects/` and `data/studio.db` (reopenable/editable artifacts)
- Frontend build: **PASS** (`frontend/dist`), Backend API health/projects/voices: **PASS**

Details and honest gaps: [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md), [`docs/DELIVERABLES.md`](docs/DELIVERABLES.md)

## Quick start
```bash
# Backend (Python 3.11+ venv)
cd local-ai-video-studio
uv venv backend/.venv --python 3.11
uv pip install --python backend/.venv -r backend/requirements.txt
./scripts/start_backend.sh   # http://127.0.0.1:8000

# Frontend
cd frontend && npm install
./scripts/start_frontend.sh  # http://127.0.0.1:5173 (proxies to :8000)
```
Full setup: [`docs/INSTALL.md`](docs/INSTALL.md)

## What works now (real, tested)
- Deterministic duration-aware script + scene storyboard generation (editable, per-scene regen endpoint)
- Local narration via macOS `say` (offline) with Kokoro MLX adapter hook/fallback
- SRT/VTT subtitle generation aligned to narration timings
- Programmatic animated-graphic scene visuals (PIL) + FFmpeg zoompan motion, 720p/30fps
- Per-scene disk-backed rendering, concat, final H.264/AAC MP4 mux (16:9, 9:16, 1:1)
- SQLite projects/jobs, sequential 8 GB-safe job queue, real progress/status, persisted artifacts
- React dashboard/editor/export UI (source + production build)

## Honest limitations (8 GB / this session)
- Visuals default to **animated graphics** (labeled). Diffusion video (Wan/MLX-Video) is not assumed feasible on 8 GB and is not enabled.
- Kokoro TTS and Whisper.cpp are **not installed/verified** in-session (adapters/paths ready); macOS `say` and timing-based subtitles provide working local fallbacks.
- 5-minute verified render not executed in-session (3-minute succeeded). Peak memory not formally profiled with `/usr/bin/time -l`.
- See [`docs/HARDWARE_LIMITATIONS.md`](docs/HARDWARE_LIMITATIONS.md) and [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md).

## Documentation
- [PLAN_STAGE_A.md](PLAN_STAGE_A.md) · [Stage B](docs/STAGE_B_REVERSE_ENGINEERING.md) · [Technical](docs/TECHNICAL_DOCUMENTATION.md) · [Install](docs/INSTALL.md) · [Limitations](docs/HARDWARE_LIMITATIONS.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Tests](docs/TEST_REPORT.md) · [Deliverables](docs/DELIVERABLES.md)

## License / sources
Open-source components only (FastAPI, React, FFmpeg, Pillow, SQLAlchemy, etc.). Optional model weights have their own licenses (e.g. Kokoro Apache 2.0, Whisper.cpp MIT). Use only properly licensed audio/visual assets.
