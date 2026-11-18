# AI Social Video Studio (Local)

A fully local macOS desktop app and web studio with **two independent engines**:

- **Engine A — AI Video Creator:** turns a topic/prompt into a finished **720p H.264/AAC MP4** (1–5 minutes) with script generation, storyboarded scenes, local narration, timed subtitles, music/SFX mixing, animated-graphic motion visuals, and FFmpeg composition.
- **Engine B — AI Auto-Clip Studio:** turns one long recording (MP4/MOV/MKV/WebM) into short, captioned **720p** clips (9:16 / 16:9 / 1:1) with transcription or SRT/VTT import, transparent highlight scoring, manual/automatic reframing, loudness-normalised audio, and transcript-grounded titles/hooks/hashtags.

- **Local-only:** no cloud inference, no paid APIs, no accounts, no subscriptions. Internet is only needed for optional one-time downloads (models/tooling) — never for generation.
- **Target hardware:** Apple M2, 8 GB unified memory, macOS (Apple Silicon).
- **Honest visuals:** defaults to **animated stills/graphics** (Pillow + FFmpeg motion). Diffusion/generated footage is not assumed feasible on 8 GB and is never silently substituted.

## Deliverables in this repo

- **Packaged desktop app:** `dist-desktop/mac-arm64/AI Social Video Studio.app`, `...-arm64-mac.zip`, and `...-arm64.dmg` (built locally). See [`docs/DESKTOP_APP.md`](docs/DESKTOP_APP.md).
- **Source:** `backend/` (FastAPI, SQLite, sequential pipeline), `frontend/` (React + TypeScript + Vite), `desktop/` (Electron shell), `scripts/` (build/verify/asset generation), `assets/` (bundled CC0 music/SFX).
- **Docs:** [`docs/INSTALL.md`](docs/INSTALL.md), [`docs/DESKTOP_APP.md`](docs/DESKTOP_APP.md), [`docs/ENGINE_B.md`](docs/ENGINE_B.md), [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md), [`docs/HARDWARE_LIMITATIONS.md`](docs/HARDWARE_LIMITATIONS.md), [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md), [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md), [`docs/TEST_REPORT_ENGINE_B.md`](docs/TEST_REPORT_ENGINE_B.md), [`docs/CHANGELOG_ENGINE_B.md`](docs/CHANGELOG_ENGINE_B.md), [`docs/DELIVERABLES.md`](docs/DELIVERABLES.md), [`models/README.md`](models/README.md).
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

All measured renders: H.264 High / yuv420p, AAC 48 kHz stereo, burned subtitles, loudness-normalized mix (~−15.8 LUFS / −3.4 dBTP), **no cloud inference**. Narration engine: macOS `say` (offline). Kokoro MLX is not installed/verified (adapter + fallback in place); whisper.cpp `base.en` is installed and measured for Engine B.

## Engine B verified snapshot (2026-11-17)

Harness `scripts/engine_b_e2e.py` (16 cases, whisper.cpp installed) with a synthetic 67.52 s source (macOS `say` narration + FFmpeg colour video), measured locally:

| Case | Result | Measured |
|---|---|---|
| Upload MP4/MOV/MKV/WebM, original preserved | PASS | SHA-256 of stored file equals uploaded bytes for all four containers |
| Probe metadata | PASS | 67.52 s, 1280×720, 30 fps, H.264/AAC (FFmpeg-fallback probe; no standalone `ffprobe`) |
| Structural analysis | PASS | 676 envelope windows, 14 silence gaps, 0 scene cuts, 0.4 s, 79 MB peak |
| Transcript import (SRT) | PASS | 15 cues, monotonic, `timing=file`, `word_timing=estimated` |
| Local transcription (whisper.cpp base.en) | PASS | 17 segments → 15 sentences, native word timings, monotonic, 1.83 s, 376 MB peak |
| WER on the known fixture script | PASS (clean synthetic TTS) | **1.01 %** (2 substitutions / 199 words; no deletions or insertions) |
| ASR-only clip pipeline | PASS | whisper transcript → 1 highlight → 9:16 render, 9 cues, validation ok |
| Highlight scoring | PASS | 2 non-overlapping clips, per-component weights + reasons, copy grounded in clip text |
| Render 9:16 / 16:9 / 1:1 | PASS | 720×1280 (1.42 MB), 1280×720 (1.24 MB), 720×720 (1.05 MB); H.264/AAC, 28 cues, −16.0 LUFS, A/V delta < 0.1 s |
| Batch export | PASS | 2 requested → 2 exported, per-item manifest with duration/size/validation/loudness/hashtags |
| Cancel live job / restart recovery | PASS | terminal `canceled`, tmp cleaned; in-flight row → `interrupted` |
| Long sources 1 / 5 / 15 / 30 / 60 min | PASS (synthetic) | A1–A5 each 6/6: analysis 0.46 → 18.51 s (77 → 452 MB), highlights 0.02 → 2.88 s, deep-end render 1.56–2.35 s (359–415 MB), all validated |

16 PASS / 0 FAIL / 0 NOT_RUN in acceptance (37.1 s). Long-source harness `scripts/engine_b_longrun.py` measured 68.55 s → 3733.12 s sources with byte-identical upload, exact SRT import and validated 720p renders (`benchmarks/data/engine_b/long_*_{1,5,15,30,60}m.json`). Fixtures are TTS over colour video, so real-footage long-source cost is **not** measured. Engine A regression re-run after the change: **PASS** (`VC-60S`, 16.464 s wall, 69.49 s output, 725.9 MB peak). Full honesty notes: [`docs/TEST_REPORT_ENGINE_B.md`](docs/TEST_REPORT_ENGINE_B.md).

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

### Engine B — AI Auto-Clip Studio

- Upload MP4/MOV/MKV/WebM once; original bytes preserved (SHA-256 recorded), probe metadata, replace-source semantics that explicitly clear stale clips
- Structural analysis: 16 kHz audio, loudness envelope, silence gaps, approximate scene-cut scan
- Transcript: local whisper.cpp when installed (capability-gated, word timings marked `native` only when the build emits token offsets), otherwise SRT/VTT/plain-text import and in-app cue editing
- Highlights: sentence-aligned windows at 15/30/45/60/90 s or custom durations, eight weighted score components shown per clip, greedy non-overlapping selection, explicit shortfall reporting
- Reframing: deterministic cover-crop (centre/edges) or a manual rectangle — **no face or subject tracking is claimed**
- Captions: ASS cues generated from the clip's own sentences, size/position/max-chars/highlight colour, burn-in toggle
- Audio: `loudnorm` to ≈ −16 LUFS, optional local music with sidechain ducking, AAC 48 kHz stereo
- Copy: `transcript-template/v1` titles/hooks/captions/hashtags, each verified as present in the clip transcript (no LLM)
- Export: per-clip render validation and batch export with `manifest.json`
- Jobs: sequential with Engine A, live progress from real stages, cancellation at stage boundaries, `interrupted` recovery, peak RSS recorded

## Limitations (honest)

- **Kokoro TTS:** not installed/verified in this build; macOS `say` and narration-timing subtitles are the working local path (fallbacks recorded). **Whisper.cpp ASR (Engine B):** installed and measured locally — 1.01 % WER on the clean synthetic TTS fixture with native word timings; human-speech accuracy is unmeasured, and Engine A still uses timing-based subtitles.
- **Diffusion image/video generation:** not enabled on 8 GB; visuals are animated graphics/stills unless you add labeled footage.
- **Narration-driven duration:** final length follows synthesized speech/timing (observed 174 wpm for Samantha); a 1-min target typically yields ~70–80 s and a 5-min target ~5.5 min unless narration is shortened.
- **Unsigned app** and no automated in-Electron click-through test in this session.
- **Engine B ASR is verified only on clean synthetic speech:** whisper.cpp `base.en` is installed locally and measured (1.01 % WER, native word timings), but the fixture is macOS TTS with a known script. Human speech, accents, noise, multi-speaker audio and ground-truth human transcripts are **not** measured; no general WER claim is made. SRT/VTT import remains available.
- **Engine B highlight quality is unrated:** scoring is deterministic and inspectable, but there are no human reference ratings and no virality claim.
- **Engine B has no tracking:** crops are static geometry; a moving subject can leave the chosen rectangle.
- **Engine B long-source evidence is synthetic:** 1/5/15/30/60-minute fixtures are TTS over colour video (84.78 MB for the 62-minute case); measured analysis 0.46 → 18.51 s and render cost bound by clip length, but real 720p/1080p footage of the same length is `NOT_RUN`.
- **Engine B in the packaged app:** rebuilt and verified on 2026-11-18 — bundled whisper.cpp ASR is available and a 5-sentence synthetic source went upload → analyze → ASR → highlights → validated 9:16 render through the app's loopback backend (`packaged_a3af06a18580.json`, 11/11 checks PASS). The Electron UI itself was not click-tested.

## Documentation

- [`PLAN_STAGE_A.md`](PLAN_STAGE_A.md) · [`docs/STAGE_B_REVERSE_ENGINEERING.md`](docs/STAGE_B_REVERSE_ENGINEERING.md) · [`docs/RESEARCH_NOTES.md`](docs/RESEARCH_NOTES.md)
- [`docs/INSTALL.md`](docs/INSTALL.md) · [`docs/DESKTOP_APP.md`](docs/DESKTOP_APP.md) · [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md)
- [`docs/HARDWARE_LIMITATIONS.md`](docs/HARDWARE_LIMITATIONS.md) · [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- [`docs/ENGINE_B.md`](docs/ENGINE_B.md) · [`docs/TEST_REPORT_ENGINE_B.md`](docs/TEST_REPORT_ENGINE_B.md) · [`docs/CHANGELOG_ENGINE_B.md`](docs/CHANGELOG_ENGINE_B.md)
- [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) · [`docs/DELIVERABLES.md`](docs/DELIVERABLES.md) · [`models/README.md`](models/README.md)

## License / sources

Open-source components only (FastAPI, React, Electron, FFmpeg via imageio-ffmpeg, Pillow, SQLAlchemy, etc.). Bundled music/SFX are **original procedural audio generated by `scripts/generate_assets.py` (CC0-1.0)** with manifests in `assets/*/licenses.json`. Optional model weights have their own licenses (e.g. Kokoro Apache 2.0, Whisper.cpp MIT). Use only properly licensed assets you add. No proprietary Higgsfield code or models are included.

