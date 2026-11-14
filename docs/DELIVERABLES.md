# Deliverables Summary

## 1. Working macOS desktop application (`.app`) — packaged
- **Location:** `dist-desktop/mac-arm64/AI Social Video Studio.app`
- **Installers/archives:** `dist-desktop/AI Social Video Studio-1.0.0-arm64.dmg` (210 MB), `dist-desktop/AI Social Video Studio-1.0.0-arm64-mac.zip` (188 MB)
- **Contents:** Electron shell + bundled relocatable CPython 3.11 + Python deps + FastAPI backend + built React frontend + FFmpeg (imageio-ffmpeg v7.1) + CC0 assets + docs/models area.
- **Verified:** launches, starts loopback backend, serves UI, and completed a real packaged render (73.66 s 1280×720 MP4, 33 cues, peak 728 MB) writing to `~/Library/Application Support/AI Social Video Studio/data/...`. See `docs/DESKTOP_APP.md` and `docs/TEST_REPORT.md`.

## 2. Full source (web + desktop + pipeline)
- **Backend:** `backend/` — FastAPI, SQLite, sequential 8 GB-safe pipeline (script/storyboard/TTS/subtitles/audio/visuals/FFmpeg compose), engine detection, recovery, SPA/static serving.
- **Frontend:** `frontend/` — React + TypeScript + Vite + Tailwind dashboard/editor (Script, Storyboard, Timeline, Voice, Subtitles, Assets, Export), library/exports/settings. Production build verified (`npm run build`).
- **Desktop shell:** `desktop/` — Electron `main.cjs`/`preload.cjs`, app metadata/build config.
- **Scripts:** `scripts/build_desktop.sh`, `scripts/make_dmg.sh`, `scripts/make_icon.py`, `scripts/generate_assets.py` (CC0 music/SFX), `scripts/verify_pipeline.py`, `scripts/verify_extended.py`, startup scripts.
- **Bundled assets:** `assets/music/*`, `assets/sfx/*` with `licenses.json` (original procedural CC0-1.0).

## 3. Verified demo outputs (720p MP4, H.264/AAC) & evidence
- `deliverables/demo_60s_16x9_720p.mp4` (~78.4 s, 1280×720) + `demo_60s_16x9_720p.srt`, `demo_60s_result.json`
- `deliverables/demo_60s_9x16_720p.mp4` (~78.8 s, 720×1280 vertical)
- `deliverables/demo_180s_16x9_720p.mp4` (~183.55 s, 1280×720, 3 min) + `.srt`
- `deliverables/demo_329s_16x9_720p.mp4` (~329.1 s, 1280×720, 5-min target) + `.srt`, `demo_329s_16x9_result.json`
- `deliverables/demo_75s_1x1_720p.mp4` (~74.6 s, 720×720, 1:1) + `.srt`
- `deliverables/demo_packaged_app_74s_16x9_720p.mp4` (~73.7 s, 1280×720, rendered via packaged `.app`) + `.srt`
- `deliverables/acceptance_extended.json` — measured extended acceptance runs (5-min 16:9, 1-min 1:1)
- `docs/screenshots/01-dashboard-full.png` — packaged app running (full desktop capture)

## 4. Sample projects (reopenable/editable artifacts)
Dev DB: `data/studio.db`; project folders under `data/projects/<id>/` (script/scenes/timings/results/subs and, when retained locally, media/renders). Verified IDs include `81451eb3` (1-min 16:9 sync-fixed), `50c68f25` (1-min 9:16 24 fps, custom-subtitle preservation/cancel), `4d82a38f` (3-min), `f6c75e7b` (5-min), `1dd46376` (1:1), and packaged-app project `2b9a01ed` in user Application Support. Note: large media artifacts are gitignored by policy; metadata/JSON where present and deliverable MP4/SRT/JSON are kept.

## 5. Documentation
- `README.md` — overview, capabilities, quick start, limitations
- `PLAN_STAGE_A.md` — Stage A plan
- `docs/STAGE_B_REVERSE_ENGINEERING.md`, `docs/RESEARCH_NOTES.md` — research/integration notes
- `docs/INSTALL.md` — packaged install, source/dev setup, desktop build, optional engines
- `docs/DESKTOP_APP.md` — bundling, runtime, data paths, build outputs, packaged verification
- `docs/TECHNICAL_DOCUMENTATION.md` — architecture, pipeline, API, data model
- `docs/HARDWARE_LIMITATIONS.md` — 8 GB constraints and optimizations
- `docs/TROUBLESHOOTING.md` — common issues and recovery
- `docs/TEST_REPORT.md` — acceptance matrix, measurements, packaged-app evidence, honest gaps
- `models/README.md` — optional model downloads/licensing notes

## 6. Honest capability notes
- **Local/offline, no paid APIs:** yes (macOS `say`, FFmpeg, Pillow, deterministic script, loopback-only backend). Internet not required for generation.
- **Kokoro/Whisper.cpp:** adapters and fallbacks implemented; **not installed/verified** in this build. Timing-based subtitles and macOS `say` are the proven path.
- **Diffusion video:** not enabled on 8 GB; visuals are **animated graphics/stills** (labeled), not AI-generated footage.
- **Narration-driven duration:** outputs may exceed nominal targets (e.g. 5-min target → 329 s at measured speech rate).
- **Unsigned app / UI automation:** Gatekeeper override may be needed; no automated in-Electron click-through test.

