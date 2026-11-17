# Deliverables Summary

## 1. Working macOS desktop application (`.app`) — packaged
- **Location:** `dist-desktop/mac-arm64/AI Social Video Studio.app`
- **Installers/archives:** `dist-desktop/AI Social Video Studio-1.0.0-arm64.dmg` (210 MB), `dist-desktop/AI Social Video Studio-1.0.0-arm64-mac.zip` (188 MB)
- **Contents:** Electron shell + bundled relocatable CPython 3.11 + Python deps + FastAPI backend + built React frontend + FFmpeg (imageio-ffmpeg v7.1) + CC0 assets + docs/models area.
- **Verified:** launches, starts loopback backend, serves UI, and completed a real packaged render (73.66 s 1280×720 MP4, 33 cues, peak 728 MB) writing to `~/Library/Application Support/AI Social Video Studio/data/...`. See `docs/DESKTOP_APP.md` and `docs/TEST_REPORT.md`.

## 2. Full source (web + desktop + pipeline)
- **Backend:** `backend/` — FastAPI, SQLite, sequential 8 GB-safe pipeline (script/storyboard/TTS/subtitles/audio/visuals/FFmpeg compose), engine detection, recovery, SPA/static serving. **Engine B:** `backend/app/clip/` — ingest/probe/analysis/transcription/highlights/render/export with `/api/clip/*`.
- **Frontend:** `frontend/` — React + TypeScript + Vite + Tailwind dashboard/editor (Script, Storyboard, Timeline, Voice, Subtitles, Assets, Export), Auto-Clip Studio (`/clip`, `/clip/:id`), library/exports/settings. Production build verified (`npm run build`).
- **Desktop shell:** `desktop/` — Electron `main.cjs`/`preload.cjs`, app metadata/build config.
- **Scripts:** `scripts/build_desktop.sh`, `scripts/make_dmg.sh`, `scripts/make_icon.py`, `scripts/generate_assets.py` (CC0 music/SFX), `scripts/verify_pipeline.py`, `scripts/verify_extended.py`, `scripts/engine_b_e2e.py` (Engine B acceptance harness), `scripts/engine_b_asr_wer.py` (ASR accuracy harness), `scripts/engine_b_longrun.py` (long-source harness), `scripts/install_whisper_cpp.sh` (local ASR install/build), startup scripts.
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
- `docs/ENGINE_B.md` — Engine B feature specs (goal/engine/behaviour/acceptance/constraints/UI/API/docs), data model, API reference, enabling ASR, limitations
- `docs/TEST_REPORT_ENGINE_B.md` — Engine B harness results, per-case evidence, long-source matrix, render measurements, NOT_RUN list
- `docs/CHANGELOG_ENGINE_B.md` — change record, shared-code touches, verification, rollback
- `docs/M2_HARDWARE_BENCHMARK.md` — M2 8 GB benchmark suite methodology, measured Engine A and Engine B results, reports, and honest NOT_IMPLEMENTED/NOT_RUN gaps (real-footage long sources, WER, highlight quality)
- `models/README.md` — optional model downloads/licensing notes

## 6. Benchmark subsystem & measured evidence (2026-11-14)
- **M2 HARDWARE BENCHMARK dashboard & instrumentation:** backend `app/benchmark/{env,metrics,ffprobe_check,store,runner,report,api}.py`, API `/api/benchmark/*`, frontend page `/benchmark` ("M2 HARDWARE BENCHMARK"), CLI `scripts/benchmark_suite.py`.
- **Measured runs (real, local):**
  - `6a80bee33c89` Engine A baseline VC-60S 16:9 — **PASS** (revalidated): 16.464 s wall, 69.49 s output, ratio 0.237, peak app RSS 708.2 MB, 1280×720 H.264/AAC 4.58 MB valid.
  - `579bf2c90636` format checks — **PASS**: 9:16 720×1280 (15.366 s, peak 743.3 MB) and 1:1 720×720 (12.543 s, peak 460.1 MB), exports valid.
  - `8f20fe6de9f9` cancel-during-generation — **PASS**: canceled, 3.7 s, peak 91.8 MB, no crash.
- **Reports:** `benchmarks/reports/*.json|.html` and `benchmarks/data/runs/*.json` (measured; initial baseline had ffprobe-binary validation bug corrected via ffmpeg-fallback probe).
- **Not implemented/measured (honest):** human-speech WER/alignment and ground-truth human transcripts unavailable (NOT_RUN); no human highlight reference/ratings; GPU/Metal utilization not reliably sampled (privileged powermetrics unavailable); comparative optimization matrix and extended stress matrix not fully executed. Engine B A1–A5 are measured on synthetic long sources by a separate harness (see §6b).

## 6b. Engine B (AI Auto-Clip Studio) — implemented and measured (2026-11-17)
- **Code:** `backend/app/clip/` (models, store, probe, audio, transcribe, highlights, metadata, render, jobs, api), `/api/clip/*`, `frontend/src/pages/ClipStudio.tsx` + `ClipProject.tsx`, `scripts/engine_b_e2e.py`, `scripts/engine_b_asr_wer.py`, `scripts/engine_b_longrun.py`, `scripts/install_whisper_cpp.sh`.
- **Acceptance run:** `benchmarks/data/engine_b/e2e_11d49374a4fb_20261117T081352Z.json` — 16 cases, **16 PASS / 0 FAIL / 0 NOT_RUN**, 37.1 s total (whisper.cpp installed).
  - Upload MP4/MOV/MKV/WebM: SHA-256 of stored file equals uploaded bytes for all four.
  - Probe: 67.52 s, 1280×720, 30 fps, H.264/AAC (FFmpeg-fallback probe).
  - Analyze: 676 envelope windows, 14 silence gaps, 0 scene cuts, 0.4 s, 79 MB peak.
  - ASR: whisper.cpp `base.en` → 17 segments / 15 sentences / 199 words, native word timings, monotonic, 1.83 s, 376 MB peak, **WER 1.01 %** on the fixture's known script.
  - ASR pipeline: recognised transcript alone drives 1 highlight → 9:16 render, 9 caption cues, validation ok.
  - Import: 15 monotonic SRT cues, `timing=file`, `word_timing=estimated`.
  - Highlights: 2 non-overlapping clips, grounded copy, per-component weights and reasons.
  - Render: 9:16 720×1280 (1.42 MB), 16:9 1280×720 (1.24 MB), 1:1 720×720 (1.05 MB); 28 cues; −16.0 LUFS; A/V delta < 0.1 s; peaks 308–388 MB.
  - Batch: 2 requested → 2 exported with per-item manifest, all validations ok.
  - Cancel → `canceled`, tmp cleaned; restart → `interrupted`; source replacement → 409/200 with stale clips/transcript cleared.
- **ASR accuracy (`scripts/engine_b_asr_wer.py`):** `benchmarks/data/engine_b/wer_971ca893acbe.json` — whisper.cpp `whisper-cli` + `ggml-base.en.bin` (147,964,211 B, built locally) on 67.52 s of clean synthetic TTS: ASR 1.79 s, RTF 0.0265, peak 446.2 MB, 15/15 sentences, 14/15 exact normalised text, 14/15 boundaries within 0.75 s (median delta 0.32 s), **1.01 % WER** (2 substitutions `pick→take`, `behaviour→behavior`, 0 deletions, 0 insertions, 199 words). This is a clean-TTS measurement, not a human-speech benchmark.
- **Long-source matrix (`scripts/engine_b_longrun.py`):** 68.55 s / 344.19 s / 965.24 s / 1864.85 s / 3733.12 s synthetic sources — **6/6 PASS in each run**: byte-identical upload, one monotonic SRT segment per sentence, 5 non-overlapping highlights, deep-end 720p render validated.
  - Analysis: 0.46 / 1.81 / 4.97 / 9.79 / 18.51 s (peaks 77 / 174 / 233 / 247 / 452 MB).
  - Highlights: 0.02 / 0.06 / 0.26 / 0.82 / 2.88 s.
  - Deep-end render: 1.56 / 2.30 / 2.03 / 2.23 / 2.35 s (peaks 377 / 359 / 371 / 384 / 415 MB), outputs 28.56–44.77 s, −15.8 to −16.2 LUFS.
  - Reports: `benchmarks/data/engine_b/long_{cc1341298172_1m,46fd0657910e_5m,44d05b39c4b9_15m,49293b9eaf59_30m,b9fc947aaa5d_60m}.json`.
- **Engine A regression after the change:** `benchmarks/data/runs/9bd9e75d5312.json` — **PASS** (16.464 s wall, 69.49 s output, 725.9 MB peak).
- **Honest gaps:** human-speech WER, accents, noise, multi-speaker and independent ground-truth transcripts are `NOT_RUN` (the 1.01 % figure is clean synthetic TTS); word-timestamp fidelity vs a human reference is unmeasured; standalone `ffprobe` absent; no human highlight ratings; long sources are synthetic colour video, so real-footage decode/seek cost is unmeasured; packaged app not rebuilt for Engine B; no automated browser click-through.

## 7. Honest capability notes
- **Local/offline, no paid APIs:** yes (macOS `say`, FFmpeg, Pillow, deterministic script, loopback-only backend). Internet not required for generation.
- **Kokoro/Whisper.cpp:** Kokoro MLX is **not installed/verified** (adapter + fallback implemented); macOS `say` is the proven Engine A narration path. whisper.cpp `base.en` **is** installed, built locally and measured for Engine B (1.01 % WER on clean synthetic TTS, native word timings); SRT/VTT import remains the verified manual path and ASR is never simulated.
- **Engine B reframing:** deterministic geometry only — no face/subject tracking; no virality prediction from highlight scores.
- **Diffusion video:** not enabled on 8 GB; visuals are **animated graphics/stills** (labeled), not AI-generated footage.
- **Narration-driven duration:** outputs may exceed nominal targets (e.g. 5-min target → 329 s at measured speech rate).
- **Unsigned app / UI automation:** Gatekeeper override may be needed; no automated in-Electron click-through test.

