# AI Social Video Studio (Local)

A fully local macOS desktop app and web studio that turns a topic/prompt into a finished **720p H.264/AAC MP4** (1–5 minutes) with script generation, storyboarded scenes, local narration, timed subtitles, music/SFX mixing, animated-graphic motion visuals, and FFmpeg composition.

- **Local-only:** no cloud inference, no paid APIs, no accounts, no subscriptions. Internet is only needed for optional one-time downloads (models/tooling) — never for generation.
- **Target hardware:** Apple M2, 8 GB unified memory, macOS (Apple Silicon).
- **Honest visuals:** defaults to **animated stills/graphics** (Pillow + FFmpeg motion). Diffusion/generated footage is not assumed feasible on 8 GB and is never silently substituted.

## Deliverables in this repo

- **Packaged desktop app:** `dist-desktop/mac-arm64/AI Social Video Studio.app`, `...-arm64-mac.zip`, and `...-arm64.dmg` (built locally). See [`docs/DESKTOP_APP.md`](docs/DESKTOP_APP.md).
- **Source:** `backend/` (FastAPI, SQLite, sequential pipeline), `frontend/` (React + TypeScript + Vite), `desktop/` (Electron shell), `scripts/` (build/verify/asset generation), `assets/` (bundled CC0 music/SFX).
- **Docs:** [`docs/INSTALL.md`](docs/INSTALL.md), [`docs/DESKTOP_APP.md`](docs/DESKTOP_APP.md), [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md), [`docs/HARDWARE_LIMITATIONS.md`](docs/HARDWARE_LIMITATIONS.md), [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md), [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md), [`docs/DELIVERABLES.md`](docs/DELIVERABLES.md), [`models/README.md`](models/README.md).
- **Verified outputs & evidence:** `deliverables/` (60 s 16:9 & 9:16, 3-min 16:9 MP4/SRT, `acceptance_extended.json` with 5-min + 1:1 results) and `docs/screenshots/01-dashboard-full.png`.

## Verified capability snapshot (2026-11-14)

| Case | Result | Measured |
|---|---|---|
| 60 s class 16:9 (30 fps) | PASS | 78.52 s, 1280×720, 5.40 MB, 34 cues burned, peak 724–730 MB, render 10–16 s |
| 60 s class 9:16 (24 fps) | PASS | 69.92 s, 720×1280, 3.93 MB, 30 cues burned, peak 659 MB |
| 60 s class 1:1 (30 fps) | PASS | 74.61 s, 720×720, 3.82 MB, 34 cues, peak 490 MB |
| 3 min 16:9 | PASS | 183.55 s, 1280×720, 8.51 MB, 9 scenes |
| 5 min 16:9 | PASS | **329.1 s**, 1280×720 @ 30 fps, **21.44 MB**, 147 cues, 15 scenes, **peak 746 MB**, generate 72.3 s |
| Packaged `.app` render | PASS | 73.66 s, 1280×720, 5.17 MB, 33 cues, peak 728 MB, output in `~/Library/Application Support/AI Social Video Studio/data/...` |

All measured renders: H.264 High / yuv420p, AAC 48 kHz stereo, burned subtitles, loudness-normalized mix (~−15.8 LUFS / −3.4 dBTP), **no cloud inference**. Narration engine: macOS `say` (offline). Kokoro MLX and Whisper.cpp not installed/verified (adapters + fallbacks in place).

## Quick start (dev)

```bash
# Backend
cd local-ai-video-studio
uv venv backend/.venv --python 3.11
uv pip install --python backend/.venv -r backend/requirements.txt
./scripts/start_backend.sh   # http://127.0.0.1:8000

# Frontend
cd frontend && npm install
./scripts/start_frontend.sh  # http://127.0.0.1:5173
```

## Run the packaged app

Open `dist-desktop/AI Social Video Studio-1.0.0-arm64.dmg` and drag to Applications, or open `dist-desktop/mac-arm64/AI Social Video Studio.app`. The app is unsigned: if blocked, use **right-click → Open** or **System Settings → Privacy & Security → Open Anyway**. Data is stored in `~/Library/Application Support/AI Social Video Studio/`.

## Features

- Dashboard, guided new-project flow, templates, recent/drafts, and export center
- Script engine (duration-aware, editable) + scene-by-scene storyboard with camera/transition/overlay/SFX controls and per-scene regeneration
- Local TTS: macOS `say` (verified) with Kokoro MLX adapter + graceful fallback and metadata recording
- Subtitles: SRT/VTT/ASS, timing-based cues, keyword highlighting/style controls, burn-in toggle, custom-cue preservation on re-render
- Audio: narration + bundled/procedural CC0 music and SFX, sidechain ducking, normalization/limiting
- Composition: per-scene animated motion (zoom/pan), concat, 720p H.264/AAC MP4, 9:16/16:9/1:1, 24/30 fps
- Project persistence (SQLite + on-disk artifacts), reopen/edit/duplicate/delete, render history, sequential 8 GB-safe job queue, progress, cancellation, interrupted-job recovery
- System/settings: engine detection, memory/disk, cleanup, voice preview, paths, docs

## Limitations (honest)

- **Kokoro TTS / Whisper.cpp ASR alignment:** not installed/verified in this build; macOS `say` and narration-timing subtitles are the working local path (fallbacks recorded).
- **Diffusion image/video generation:** not enabled on 8 GB; visuals are animated graphics/stills unless you add labeled footage.
- **Narration-driven duration:** final length follows synthesized speech/timing (observed 174 wpm for Samantha); a 1-min target typically yields ~70–80 s and a 5-min target ~5.5 min unless narration is shortened.
- **Unsigned app** and no automated in-Electron click-through test in this session.

## Documentation

- [`PLAN_STAGE_A.md`](PLAN_STAGE_A.md) · [`docs/STAGE_B_REVERSE_ENGINEERING.md`](docs/STAGE_B_REVERSE_ENGINEERING.md) · [`docs/RESEARCH_NOTES.md`](docs/RESEARCH_NOTES.md)
- [`docs/INSTALL.md`](docs/INSTALL.md) · [`docs/DESKTOP_APP.md`](docs/DESKTOP_APP.md) · [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md)
- [`docs/HARDWARE_LIMITATIONS.md`](docs/HARDWARE_LIMITATIONS.md) · [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) · [`docs/DELIVERABLES.md`](docs/DELIVERABLES.md) · [`models/README.md`](models/README.md)

## License / sources

Open-source components only (FastAPI, React, Electron, FFmpeg via imageio-ffmpeg, Pillow, SQLAlchemy, etc.). Bundled music/SFX are **original procedural audio generated by `scripts/generate_assets.py` (CC0-1.0)** with manifests in `assets/*/licenses.json`. Optional model weights have their own licenses (e.g. Kokoro Apache 2.0, Whisper.cpp MIT). Use only properly licensed assets you add. No proprietary Higgsfield code or models are included.

