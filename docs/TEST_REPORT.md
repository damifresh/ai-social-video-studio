# Test & Acceptance Report

**Date:** 2026-11-14 (updated from 2026-11-13)  
**Machine:** Apple M2, 8 GB unified memory, macOS 27.0.1 (arm64)  
**App version:** 1.0.0  
**Python:** 3.11.18 (uv/venv; packaged app bundles relocatable CPython 3.11.18)  
**FFmpeg:** imageio-ffmpeg bundled **v7.1** arm64 (`ffmpeg-macos-aarch64-v7.1`), libass/sidechain/loudnorm available  
**TTS (verified):** macOS `say` (e.g. Samantha), fully local/offline, ~174 wpm measured  
**Kokoro MLX:** **not installed/verified** (adapter + fallback + metadata recording present)  
**Whisper.cpp:** **not installed/verified** (timing-based SRT/VTT/ASS used)  
**Visuals:** animated graphics/stills (Pillow) + FFmpeg zoom/pan motion (**labeled**); diffusion/generated footage not enabled

## Acceptance criteria (1–12)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Create a 60-second social-media video | **PASS** (1-min target; narration-driven ~70–79 s) | 16:9 30fps: 78.52 s, 1280×720, 5.40 MB, 34 cues, peak 724–730 MB, render 10.1–16.1 s (`81451eb3`). 9:16 24fps: 69.92 s, 720×1280, 3.93 MB, 30 cues, peak 659 MB (`50c68f25`). 1:1 30fps: 74.61 s, 720×720, 3.82 MB, 34 cues, peak 490 MB (`1dd46376`, `acceptance_extended.json`). Earlier verified demo: `deliverables/demo_60s_16x9_720p.mp4` (78.4 s). |
| 2 | Create a 180-second video | **PASS** | 183.55 s, 1280×720 @ 30 fps, 8.51 MB, 9 scenes, H.264/AAC — `deliverables/demo_180s_16x9_720p.mp4` / project `4d82a38f`. |
| 3 | Create a 300-second video | **PASS** | **329.1 s** (5 min 29 s), 1280×720 @ 30 fps, **21.44 MB**, 147 subtitle cues, 15 scenes, H.264 High + AAC, **peak 746 MB**, generate 72.3 s, render 69.6 s — project `f6c75e7b` (`deliverables/acceptance_extended.json`). Duration is narration-driven (longer than 300 s target). |
| 4 | Generate narration using Kokoro locally | **PARTIAL / FALLBACK VERIFIED** | `say=true`, `kokoro=false`, `whisper=false` in `/health` (dev and packaged). All verified renders used `tts_engines=["macos-say"]`, no fallbacks recorded for these runs. Kokoro MLX adapter and graceful fallback/metadata (`tts_fallback`, `tts_fallback_reason`) are implemented but Kokoro packages/weights not installed/verified on this machine. |
| 5 | Generate and synchronize subtitles | **PASS** | SRT/VTT/ASS generated per project and burned when enabled. Timing-based cues aligned to narration (speech end per scene; audio padded to scene render duration for A/V sync). Re-render preserves user-customized cues (`style.customized`), full regeneration rebuilds cues — verified on `50c68f25`. Subtitle sidecars present for all renders. |
| 6 | Render an MP4 at 720p | **PASS** | 1280×720 (16:9), 720×1280 (9:16), 720×720 (1:1). H.264 High, yuv420p, AAC 48 kHz stereo, 24/30 fps. Audio/video durations match (e.g. 78.52 s streams, 329.1 s for 5-min). Loudness ≈ −15.8 LUFS integrated / −3.4 dBTP. |
| 7 | Create both vertical and landscape videos | **PASS** (+ square) | Landscape 16:9: multiple passes (78.52 s, 183.55 s, 329.1 s). Vertical 9:16 @ 24 fps: 69.92 s (`50c68f25`, `deliverables/demo_60s_9x16_720p.mp4`). Square 1:1: 74.61 s (`1dd46376`). |
| 8 | Reopen an existing project and edit a scene | **PASS (API/persistence) / UI build PASS** | Projects/scenes/scripts/timings/results persist in SQLite + `data/projects/<id>/...`; API supports reopen (`GET /api/projects/:id`), script/scene edits (`PUT`), duplicate, subtitles/assets. Frontend workspace (Script/Storyboard/Timeline/Voice/Subtitles/Assets/Export) builds successfully (`vite build`, 262 kB JS). Automated in-browser click-through not executed. |
| 9 | Regenerate an individual scene without losing the rest | **PASS (wired, targeted verification)** | `POST /api/projects/{id}/scenes/{idx}/regenerate` and rerender path reuse unchanged narration when text unchanged; per-scene assets stored independently. Custom subtitle preservation across re-render and sequential job behavior verified. Full UI-click E2E for single-scene regen with before/after frame diff not separately captured. |
| 10 | No paid APIs or cloud inference | **PASS** | Local macOS `say` TTS, local FFmpeg/Pillow/SQLite, deterministic script engine, bundled/procedural CC0 audio. No cloud calls in pipeline; packaged app runs loopback-only backend. |
| 11 | Monitor memory usage throughout workflow | **PASS (instrumented sampling, no OOM observed)** | Job records `peak_memory_mb` (process RSS sampling). Observed peaks: ~490–730 MB for 1-min renders, **746 MB** for 5-min (329 s) render on 8 GB M2 under memory pressure; no OOM/swap-failure observed. Sequential single-job execution enforced. Not a formal `/usr/bin/time -l` max-RSS profile. |
| 12 | Interrupted jobs recover without corrupting saved projects | **PASS (by design, startup recovery verified)** | Stale `running/queued` jobs are marked `interrupted` on startup (`recover_interrupted_jobs`); artifacts remain on disk and projects are re-runnable. Job cancellation sets `canceled` and aborts at stage boundaries (verified: cancel requested → `canceled`, “Canceled by user”). |

## Packaged desktop app verification (2026-11-14)

| Check | Result | Evidence |
|---|---|---|
| `.app` build & launch | **PASS** | `dist-desktop/mac-arm64/AI Social Video Studio.app` (Electron 45.3.2, arm64), backend spawned on loopback, `/health` ok, FFmpeg bundled, UI routes served |
| Bundled media/assets | **PASS** | `/media/music/ambient_calm_loop.wav` HTTP 200 (1.92 MB); library reports bundled tracks |
| Real render inside packaged app | **PASS** | 73.66 s, 1280×720 @ 30 fps, 5.17 MB, 33 cues, peak 728 MB, 17.04 s render; output in `~/Library/Application Support/AI Social Video Studio/data/projects/2b9a01ed-8393-4a87-81c9-0f3beaa2c806/renders/final_16x9_720p.mp4` (SRT/VTT/ASS present) |
| Clean shutdown | **PASS** | Quit stopped backend process (log shows shutdown/SIGKILL termination) |
| DMG/ZIP artifacts | **PASS** | `AI Social Video Studio-1.0.0-arm64.dmg` (210 MB), `-arm64-mac.zip` (188 MB) |
| GUI screenshot | **PARTIAL** | Full-screen capture while app running: `docs/screenshots/01-dashboard-full.png` (2880×1800). Automated Electron window/content assertion not run (browser tool not connected). |

## Additional verified behaviors

- **Sequential guard:** second `/generate` while running returns HTTP 409.
- **A/V sync fix:** narration padded to `speech_dur + 0.25 s` gap so audio matches video timeline/subtitles (verified 78.52 s end-to-end).
- **Audio mix:** narration+music mixed, ducked, loudness-normalized (≈ −15.8 LUFS / −3.4 dBTP, no clipping above limiter target).
- **Subtitle customization:** edited cues/style saved and preserved on re-render; cleared on full regeneration (verified SRT/ASS content).
- **Question-style hook fix:** topics starting with how/what/why… produce natural openings (verified in 9:16 project).
- **Bundled CC0 assets:** procedural music/SFX generated by `scripts/generate_assets.py` with `licenses.json`.
- **Frontend build:** `npm run build` PASS (TypeScript + Vite).

## Artifacts & references

- `deliverables/demo_60s_16x9_720p.mp4`, `demo_60s_9x16_720p.mp4`, `demo_180s_16x9_720p.mp4` (+ sidecars)
- `deliverables/acceptance_extended.json` (5-min 16:9 and 1-min 1:1 results)
- `docs/screenshots/01-dashboard-full.png`
- `dist-desktop/AI Social Video Studio.app`, `.zip`, `.dmg`

## M2 Hardware Benchmark (measured, 2026-11-14)

Dedicated benchmark instrumentation and dashboard added (`backend/app/benchmark/*`, `/api/benchmark/*`, `frontend/src/pages/Benchmark.tsx`, `scripts/benchmark_suite.py`). Reports: `benchmarks/reports/*.json|.html`, run data `benchmarks/data/runs/*.json`. Full details: `docs/M2_HARDWARE_BENCHMARK.md`.

| Run | Case(s) | Status | Key measured results |
|---|---|---|---|
| `6a80bee33c89` (corrected) | VC-60S 16:9, 30 fps | **PASS** | wall 16.464 s, output 69.49 s, ratio 0.237, peak app RSS 708.2 MB, CPU avg/peak 42.2/92.9%, sys mem peak 83.4%, swap peak 4073.9 MB, export 1280×720 4.58 MB H.264/AAC valid (ffmpeg-fallback probe; no standalone ffprobe) |
| `579bf2c90636` | VC-60S-9x16, VC-60S-1x1 | **PASS** | 9:16: 15.366 s, 67.43 s, peak 743.3 MB, 720×1280 valid. 1:1: 12.543 s, 65.96 s, peak 460.1 MB, 720×720 valid |
| `8f20fe6de9f9` | STAB-CANCEL | **PASS** | cancel requested ~2.5 s into real run → `job_status=canceled`, wall 3.7 s, peak 91.8 MB, no crash |

**Engine B (AI Auto-Clip Studio):** NOT_IMPLEMENTED (A1–A5, transcription WER/alignment, highlight quality/human ratings all NOT_RUN — no fabricated data). **GPU/Metal utilization:** not reliably sampled without privileged `powermetrics` (reported unavailable). **Max RSS (`/usr/bin/time -l`):** not captured (sampled process-tree RSS peaks used).

## Known gaps / limitations (honest)

- **Kokoro MLX / Whisper.cpp** not installed or runtime-verified; macOS `say` + timing subtitles are the proven local path.
- **Diffusion/generated footage** not enabled on 8 GB; visuals are animated graphics (labeled), not AI-generated video frames.
- **Narration-driven duration:** output can exceed the nominal minute target (measured ~174 wpm). 5-min target produced 329 s.
- **Memory metric:** sampled process peak RSS reported by jobs/benchmarks, not `/usr/bin/time -l` high-water mark.
- **UI automation:** no automated click-through in a live browser/Electron session; API/pipeline, packaged health, and renders verified.
- **App signing/notarization:** unsigned build (`identity: null`) — Gatekeeper override needed on first open.
- **Auto-resume:** interrupted jobs are recoverable/re-runnable but not automatically resumed from the exact failed stage. Scene-regeneration recompose is implemented but not separately frame-diff validated in this report.
- **Benchmark scope:** Engine B, Whisper WER/ground-truth, highlight reference/human evaluation, comparative optimization matrix (A–G), and extended stress matrix (5x1-min, 3x5-min, restart/reopen/after-fail timed runs) not fully executed — reported as NOT_IMPLEMENTED/NOT_RUN in benchmark docs/reports. Initial baseline run had a validation bug (missing `ffprobe` binary) corrected with ffmpeg-fallback probing and regenerated report.

