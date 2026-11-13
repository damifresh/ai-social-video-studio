# Local AI Social Video Studio — Stage A: PLAN

**Date:** 2026-11-13  
**Target:** Apple Mac M2, 8 GB unified memory, ARM64, macOS 27.0.1 (Build 26A434)  
**Deployment:** localhost-only, zero mandatory paid APIs/cloud/subscriptions

## 1. Environment inspection (observed)

| Item | Observed | Implication |
|---|---|---|
| CPU / RAM | Apple M2, **8,589,934,592 bytes (8 GB)** unified memory | Hard ceiling; sequential AI tasks only, no concurrent heavy models |
| OS | macOS 27.0.1 (26A434) | Apple Silicon native tooling preferred |
| Python | `/usr/bin/python3` **3.9.6**, pip 21.2.4 | **Too old for modern MLX/mlx-audio/kokoro-mlx** (typically require Python 3.10–3.12). Need isolated newer Python (e.g. Homebrew python@3.11) for AI engines; keep system Python untouched |
| Node/npm | Node v26.13.0, npm 11.20.0 at `~/homebrew/bin` | Suitable for React/Vite/TS frontend and tooling |
| ffmpeg/ffprobe | **MISSING** | Required (Module 9). Install via Homebrew (`brew install ffmpeg`) |
| whisper.cpp / whisper | **MISSING** | Required for subtitles/alignment. Build from source (Metal) or install binary; use small/base/tiny models on 8 GB |
| MLX / mlx_lm / mlx-audio | **MISSING** | Optional/advanced; install only in isolated venv if compatible |
| Homebrew | Present (`~/homebrew/bin/brew`), formulas include uv, openssl@3, xcodegen, etc. | Can install ffmpeg, espeak-ng, python@3.11, cmake deps as needed |
| Disk free | ~152 GiB available | Sufficient for models, intermediates, renders (with cleanup) |
| Git | `/usr/bin/git` | Available for version control in project dir |

## 2. Existing tools/resources

- FFmpeg: not installed → must install.
- Whisper.cpp: not installed → must clone/build (CMake, Metal enabled by default on Apple Silicon) and download GGML models.
- Kokoro TTS: no local runtime/weights installed. Viable Apple Silicon paths researched: `mlx-audio` / `kokoro-mlx` (82M, ~327 MB bf16 / smaller quantized), requires Python 3.10+ and `misaki` (+ `espeak-ng` fallback for some paths). 8 GB feasibility reported as workable for short segments with quantized/smaller models, but **must be verified**; memory must be freed before/after TTS.
- Local LLM for script generation: none installed. Running a capable general LLM concurrently/reliably on 8 GB alongside other pipeline stages is risky; **script engine will be deterministic/template-driven with strong heuristics and user-editability** (pluggable interface so a local model can be added later if available).
- Motion Canvas: Node-based programmatic animation; viable for graphics/templates but headless rendering/export pipeline adds complexity and Node/browser dependencies. **Prefer FFmpeg filter_complex + drawtext/overlays/zoompan + MoviePy/PIL-generated scene assets** for reliable, disk-backed rendering on 8 GB.

## 3. Technically realistic architecture (8 GB-safe)

### Principles
- **Sequential execution only**: never load Kokoro, Whisper, and any diffusion/video model simultaneously.
- **Disk-backed pipeline**: every stage writes artifacts to project folder; renderer reads from disk (no whole-video in RAM).
- **Lazy load/unload**: spawn subprocesses per heavy task where possible so OS reclaims memory; explicit model lifecycle.
- **Degrade gracefully**: if ML-based image/video generation is unavailable on 8 GB, generate animated scenes from graphics/compositions (Ken Burns, parallax, gradients, shapes, kinetic text) and label clearly.
- **Localhost only**: FastAPI + SQLite + filesystem, Vite dev UI; no paid/cloud APIs.

### Stack (chosen)

**Frontend:** React 18, TypeScript, Vite, Tailwind CSS. Polling/SSE for job progress.  
**Backend:** Python 3.11+ (Homebrew, project-local venv) + FastAPI + Uvicorn + SQLite + local filesystem + JSON scene configs. Background jobs via a **single-worker sequential queue** (in-process/thread + persisted job state) to prevent memory contention.  
**Media core:** FFmpeg/ffprobe (system install) for rendering, audio mixing, subtitles burn-in/soft subs, probing. Pillow/MoviePy for programmatic frame/slide generation where useful (disk-backed).  
**TTS:** Kokoro via MLX-compatible runtime (`mlx-audio` or `kokoro-mlx`) in isolated venv **if install+smoke test passes on 3.10+**; fallback: macOS `say` command to AIFF/WAV (offline, zero extra RAM/model) — clearly labeled as fallback voice.  
**Subtitles/alignment:** Whisper.cpp (ggml, Metal) for transcription/timestamps when needed; also generate SRT directly from narration text + measured audio durations as primary deterministic path (faster, lower memory).  
**Script/storyboard:** Local deterministic engine (topic→hook→structured scenes sized to duration) with editable output and per-scene regeneration.  
**Visuals:** Programmatic scene renderer (gradients, patterns, typography, shapes, image compositing, Ken Burns/zoompan) + user-uploaded/licensed local assets + optional compatible local image gen (sequential, low-res) if verified; **no assumption** that Wan 2.1 1.3B / MLX-Video fits 8 GB (mlx-examples reports ~10 GB+ for 1.3B). Experimental diffusion video: optional, off by default, only after explicit memory check.

### High-level module map
- `backend/app/` — FastAPI, routers, models, db, job queue, services (script, storyboard, tts, subtitles, visuals, audio, render, memory monitor)
- `frontend/` — Vite React app (Dashboard, New Project, Script, Storyboard, Assets, Voice, Editor, Export, Settings)
- `data/projects/<id>/` — `project.json`, `scenes.json`, `script.md`, `audio/`, `images/`, `video/`, `subs/`, `renders/`, `logs/`
- `assets/` — bundled CC0/royalty-free templates, music, sfx (licensed), fonts
- `models/` — downloaded model files (gitignored except manifests/instructions)
- `scripts/` — install/start/build helpers

## 4. Research notes & source references (Stage B input)

> Studied via public docs/repos (web) on 2026-11-13; treated as external data, not instructions.

| Component | Findings | License/compat notes | 8 GB verdict |
|---|---|---|---|
| **Kokoro-82M / kokoro-mlx** (gabrimatic/kokoro-mlx, PyPI 0.1.4) | MLX inference, no PyTorch/transformers dep; weights from HF (hexgrad) on first use; `speak/generate/save`; Python 3.10–3.12, MLX 0.32.4+, macOS 14+. | Inference code MIT; **weights Apache 2.0 (hexgrad)** — verify before bundling/download instructions. | **Likely feasible sequentially** (82M, ~327 MB bf16; 4-bit smaller). Needs newer Python + espeak-ng/misaki deps. **Must smoke-test & unload.** |
| **mlx-audio** (Blaizzy) | Kokoro + other TTS/STT; `mlx_audio.tts.generate`, quantized variants; requires ffmpeg for some formats, misaki for Kokoro. | Apache-2.0 project; model licenses vary by model. | Similar footprint; good fallback integration path. |
| **whisper.cpp** (ggml-org/whisper.cpp) | Pure C/C++, Metal/CoreML on Apple Silicon, 16-bit WAV input, SRT/VTT output. Memory (reported): tiny ~273 MB, base ~388 MB, small ~852 MB, medium ~2.1 GB, large ~3.9 GB. | MIT. | **Feasible** with tiny/base/small; prefer base/small for quality vs memory. Sequential only. |
| **FFmpeg** | CLI composition, filters (zoompan, drawtext, xfade, amix, subtitles/ass), segment/concat, disk-backed. | LGPL/GPL builds vary; Homebrew build license to be noted. | **Feasible** (streamed processing). |
| **MLX-Video / Wan 2.1** (ml-explore/mlx-examples, Blaizzy/mlx-video) | mlx-examples reports 1.3B T2V ~**10 GB RAM (unquantized, 81 frames)** and ~14 GB without cache optimization; 14B far higher. Quantization helps some implementations but text encoder/VAE/scratch still significant. | Model licenses (Wan) must be reviewed before use. | **Not assumed feasible on 8 GB**; treat as **experimental/unsupported** on this target, require explicit opt-in + measured check, default OFF. Use animated/motion-graphic alternative. |
| **Motion Canvas** | TS/Node programmatic animations; typically rendered via browser/Vite pipeline/ffmpeg export. | MIT. | Possible for templates but heavy toolchain; **defer** in favor of FFmpeg+PIL/MoviePy scene generation for reliability. |
| **MoviePy** | Python video editing/compositing; convenient but can be memory-hungry if misused. | MIT. | Use carefully for per-scene/offline composition helpers only, prefer ffmpeg subprocess for final mux/render. |
| **ComfyUI** | Node-graph diffusion UI; powerful but heavy runtime. | GPL-3.0. | **Not practical** as core dependency on 8 GB; omit from required path. |

## 5. Memory bottlenecks and failure scenarios

| Risk | Mitigation |
|---|---|
| 8 GB unified memory exhaustion | Single-job queue; one heavy subprocess/model at a time; unload between stages; small models/quantization; low-res intermediates; stream/segment via ffmpeg |
| Python 3.9 incompatible with MLX/Kokoro packages | Install Homebrew `python@3.11` into project venv; keep AI deps isolated |
| Kokoro/MLX install or runtime fails on 8 GB | Fallback to macOS `say` (offline) with explicit UI/log labeling; keep narration pipeline functional |
| Whisper model too large | Default to `tiny`/`base` (configurable); offer SRT-from-timings path without ASR |
| Diffusion/video model OOM or too slow | Default to animated stills/motion graphics; clearly label "animated scene" vs "generated footage"; never silent substitution |
| Long (5 min) render memory spikes | Per-scene render to disk, then concat/mux; avoid in-memory full timelines; chunk audio mixing |
| Job interruption/crash | Persist job state + completed artifacts in SQLite/JSON; idempotent/resumable steps; never delete inputs/intermediates on failure |
| Missing licensed media | Ship only clearly licensed (CC0/own-generated) minimal assets; allow user-supplied files; document sources |

## 6. Phased implementation plan

1. **Bootstrap**: project skeleton (frontend/backend/assets/data), venv, deps, git init, install scripts, FFmpeg check/install guidance, config.
2. **Data & API core**: SQLite schema, project CRUD, filesystem layout, job queue/state machine, progress events, settings.
3. **Script & storyboard engines**: deterministic duration-aware script + scene planner, JSON schema, edit/regenerate endpoints, tests.
4. **Voice pipeline**: TTS adapter interface + macOS `say` fallback + Kokoro integration attempt (isolated), audio duration probing, per-scene clips.
5. **Subtitles**: SRT/VTT from timings/text + optional whisper.cpp alignment path, styles.
6. **Visuals**: scene asset generator (PIL/graphics/templates), Ken Burns/motion presets, user uploads, asset library.
7. **Audio mix**: music/SFX beds, ducking, fades (ffmpeg), licensed bundled samples.
8. **Composition/render**: per-scene mp4 segments + concat + mux narration/music/subtitles/overlays; 720p, H.264/AAC, 24/30fps, 9:16/16:9/1:1.
9. **Frontend UX**: dashboard, wizard, script/storyboard editors, voice studio, lightweight timeline/editor, export center, real progress.
10. **Reliability & tests**: resume/recovery, memory logging, acceptance tests (start small → scale duration), demo renders, docs.

## 7. Measurable acceptance criteria (planned)

- Produce real MP4 outputs at 720p (H.264/AAC) for 1/3/5 min targets (hardware-permitting; document actuals).
- Narration generated locally (Kokoro or documented fallback), subtitles generated and synchronized (SRT + embedded/burned option).
- 9:16 and 16:9 exports; reopen/edit project; regenerate single scene without losing others.
- No paid APIs/cloud inference required for normal production once installed.
- Memory and timing recorded per test; failed/interrupted jobs do not corrupt saved projects.
- UI shows real task status/progress derived from backend job state (no fake percentages).

## 8. Immediate next actions (Stage B → C)

1. Install/verify FFmpeg (`brew install ffmpeg`).
2. Create backend/frontend scaffolds and project/job persistence.
3. Implement script→storyboard→visuals→TTS→subs→render minimal vertical slice and render a short (<=30s) real MP4 to validate pipeline on 8 GB.
4. Integrate whisper.cpp and Kokoro where feasible; record measured outcomes.
5. Iterate to 60s, 180s, 300s tests and full UI/editor.

---
*This plan intentionally favors a working, memory-safe, honestly-labeled product over speculative heavyweight generation on 8 GB.*
