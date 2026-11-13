# Deliverables Summary

## 1. Working application (local)
- **Backend:** `backend/` (FastAPI, SQLite, sequential pipeline, FFmpeg/Pillow/TTS/subtitles/render services)
- **Frontend:** `frontend/` (React + TypeScript + Vite + Tailwind), production build verified (`npm run build`)
- **Startup:** `scripts/start_backend.sh`, `scripts/start_frontend.sh`, `scripts/start_all.sh`

## 2. Verified demo outputs (720p MP4, H.264/AAC)
- `deliverables/demo_60s_16x9_720p.mp4` — ~78s, 1280x720 (landscape), narration + subtitles + animated scenes
- `deliverables/demo_60s_9x16_720p.mp4` — ~79s, 720x1280 (vertical)
- `deliverables/demo_180s_16x9_720p.mp4` — ~183.5s (3 min), 1280x720, 9 scenes
- Sidecars: `.srt` files and `demo_60s_result.json`

## 3. Sample video projects (reopenable/editable artifacts)
Stored in `data/projects/<id>/` with DB entries in `data/studio.db`:
- `80308e58-8b19-4b8f-a15a-e57bb0f08b29` — Demo 60s 16:9 (succeeded)
- `9eccd854-5556-4933-9113-2091b58b94fe` — Demo 60s 9:16 (succeeded)
- `4d82a38f-fa77-4357-bdd2-77347b25f5ca` — Demo 3min 16:9 (succeeded)

## 4. Documentation
- `PLAN_STAGE_A.md` — Stage A plan (env, architecture, phases, acceptance criteria)
- `docs/STAGE_B_REVERSE_ENGINEERING.md` — open-source study and integration decisions
- `docs/RESEARCH_NOTES.md` — component research notes
- `docs/TECHNICAL_DOCUMENTATION.md` — architecture, pipeline, API, data model
- `docs/INSTALL.md` — installation and setup
- `docs/HARDWARE_LIMITATIONS.md` — 8 GB constraints and optimizations
- `docs/TROUBLESHOOTING.md` — common issues and recovery
- `docs/TEST_REPORT.md` — acceptance test results, measurements, honest gaps
- `models/README.md` — optional model downloads

## 5. Honest capability notes
- **Local/offline, no paid APIs:** yes (macOS `say` TTS, FFmpeg, Pillow, deterministic script, localhost).
- **Kokoro/Whisper.cpp/diffusion video:** adapters/paths documented; not fully installed/executed in this session. Fallbacks produce real outputs.
- **5-minute verified render:** not executed in this session (3-minute succeeded; pipeline is disk-backed and designed for 1–5 min).
