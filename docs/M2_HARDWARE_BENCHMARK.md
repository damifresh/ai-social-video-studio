# M2 Hardware Benchmark — AI Video Production Engine

**Suite:** M2 HARDWARE BENCHMARK (local, measured)  
**Target hardware:** Apple Mac M2, 8 GB unified memory, macOS  
**Constraints:** local processing, 720p output, zero paid APIs, zero mandatory cloud processing  
**Date of baseline execution:** 2026-11-14 (UTC timestamps in reports)  
**Git:** `26d60b2` (dirty working tree during runs; see per-run environment capture)  
**App:** 1.0.0

> **Policy:** This document contains only **measured or directly observed** results from executed runs, plus explicitly labeled `NOT_IMPLEMENTED` / `NOT_RUN` items where capability or required prerequisites are unavailable. No fabricated benchmark numbers.

---

## 1. Hardware configuration (captured)

| Field | Value |
|---|---|
| Processor | Apple M2 (arm64, 8 logical CPUs reported) |
| Unified memory | 8.00 GB |
| macOS | macOS 27.0.1 (Darwin 27.0.0, as captured) |
| Disk (at capture) | ~233.47 GB total, ~53–57 GB free during runs (varies; sampled per run) |
| Background workload | Not strictly isolated/controlled; noted per methodology (best-effort local machine) |

Source: `benchmarks/data/runs/*` and generated reports (`environment.hardware`, `environment.disk`, `environment.software`).

## 2. Software and model versions (captured)

| Component | Value / status |
|---|---|
| App version | 1.0.0 |
| Python | 3.11.18 (project venv) |
| FFmpeg | imageio-ffmpeg v7.1 (`ffmpeg-macos-aarch64-v7.1`, bundled binary) |
| ffprobe binary | **Not present as standalone binary**; export validation uses ffprobe JSON when available, else **ffmpeg-based probe fallback** (`app.services.render.probe_video_info`) — recorded per probe (`source: ffmpeg_fallback`) |
| TTS engine (verified/used) | macOS `say` (e.g. Samantha). Kokoro MLX: **not installed/verified** (`engines.kokoro=false`) |
| ASR/transcription engine | Engine B: whisper.cpp `whisper-cli` + `ggml-base.en.bin`, **built locally and measured** (1.01 % WER on clean synthetic TTS, native word timings). Engine A subtitles remain narration/timing-based. Human-speech WER **NOT_RUN** |
| Visual generation | Animated graphics/stills (Pillow) + FFmpeg motion (labeled). Diffusion video **not enabled** |
| Hardware acceleration (GPU/Metal) | Not enabled as a separate encode path in pipeline; **GPU/Metal utilization not reliably sampled** without privileged `powermetrics` (reported unavailable, not fabricated) |
| Processing model | Sequential jobs, disk-backed intermediates, 720p target, per-scene rendering |

## 3. Test methodology

- **Instrumentation:** `backend/app/benchmark/{env,metrics,ffprobe_check,store,runner,report,api}.py`, frontend `M2 Benchmark` dashboard (`/benchmark`), CLI `scripts/benchmark_suite.py`, API `/api/benchmark/*`.
- **Sampling:** `MetricSampler` during runs (default 1.0 s; stability/cancel used 0.5 s). Samples include CPU (`psutil.cpu_percent`), **application memory as process-tree RSS** (`psutil`), **system memory/swap** (`psutil.virtual_memory/swap_memory`, host-wide), memory pressure (best-effort `memory_pressure`), disk (`shutil.disk_usage`), and GPU note (unavailable without privileged counters).
- **Important distinction:** **Application memory (RSS)** is not total system memory. System memory/swap are host-wide snapshots and can be influenced by other processes/background workload.
- **Export validation:** container/streams/codecs/resolution/aspect/duration/size checked via ffprobe or ffmpeg-fallback probe. H.264 video + AAC audio + 720p target + expected aspect validated for measured Engine A exports.
- **Repeatability:** per-case configs recorded in run JSON; environment captured per run; multiple variables not intentionally changed within a single comparison case. Background workload not forcibly isolated.
- **Execution:** real Engine A pipeline jobs (script/narration/render/export) run sequentially via existing app services.

## 4. AI Auto-Clip results (Engine B)

Engine B (AI Auto-Clip Studio) **is implemented** in this codebase and is measured by its own
harnesses — `scripts/engine_b_e2e.py` (acceptance) and `scripts/engine_b_longrun.py`
(duration matrix) — see [`TEST_REPORT_ENGINE_B.md`](TEST_REPORT_ENGINE_B.md) and
`benchmarks/data/engine_b/`. The A1–A5 cases below were executed on **synthetic** local
sources (TTS narration + FFmpeg colour video with an exact SRT); no number is extrapolated.
They are not part of this benchmark suite's JSON.

| Test | Target | Actual source | Status | Analyze | Highlights | Deep-end render |
|---|---:|---:|---|---:|---:|---:|
| A1 | 1 min | 68.55 s | **PASS** (synthetic) | 0.46 s / 77 MB | 0.02 s, 2 clips | 1.56 s / 377 MB, 28.56 s out |
| A2 | 5 min | 344.19 s | **PASS** (synthetic) | 1.81 s / 174 MB | 0.06 s, 5 clips | 2.30 s / 359 MB, 44.39 s out |
| A3 | 15 min | 965.24 s | **PASS** (synthetic) | 4.97 s / 233 MB | 0.26 s, 5 clips | 2.03 s / 371 MB, 38.59 s out |
| A4 | 30 min | 1864.85 s | **PASS** (synthetic) | 9.79 s / 247 MB | 0.82 s, 5 clips | 2.23 s / 384 MB, 38.59 s out |
| A5 | 60 min | 3733.12 s | **PASS** (synthetic) | 18.51 s / 452 MB | 2.88 s, 5 clips | 2.35 s / 415 MB, 44.77 s out |

Every A1–A5 run also verified byte-identical upload (SHA-256), exact SRT import (one monotonic
segment per sentence), 5 non-overlapping highlights, and a fully validated 720p H.264/AAC
render (`av_sync_ok`, loudness −15.8 to −16.2 LUFS). Reports:
`benchmarks/data/engine_b/long_*_{1,5,15,30,60}m.json`.

**Honest limits:** analysis is roughly linear (18.51 s for 62 minutes) and render cost follows
clip length, not source length. But the fixtures are colour video that decodes cheaply
(84.78 MB for the hour), so these are lower bounds for real footage. Real 720p/1080p
long recordings are **NOT_RUN**. Engine B's short-source acceptance run measured a 67.52 s
source with renders 2.41 s / 2.17 s / 1.85 s wall and 402 / 376 / 348 MB peak RSS for
9:16 / 16:9 / 1:1 at 44.14 s output.

## 5. Transcription accuracy

Local whisper.cpp `whisper-cli` + `ggml-base.en.bin` was built and measured by
`scripts/engine_b_asr_wer.py` (see `benchmarks/data/engine_b/wer_971ca893acbe.json`).

| Item | Status | Notes |
|---|---|---|
| whisper.cpp Tiny / Base | **PASS** (`base.en`) | 67.52 s clean synthetic TTS at 16 kHz: ASR 1.79 s wall, RTF 0.0265, peak 446.2 MB |
| WER / missing-incorrect words | **PASS (clean synthetic TTS only)** | **1.01 %** = 2 substitutions / 199 words, 0 deletions, 0 insertions (`pick→take`, `behaviour→behavior`) |
| Sentence boundaries | **PARTIAL** | 15/15 sentence count, 14/15 exact normalised text, 14/15 start+end within 0.75 s, median delta 0.32 s |
| Human speech / accents / noise / multi-speaker / fast-speech | **NOT_RUN** | No human-speech corpus or independent ground-truth transcripts; do not generalise the TTS WER |
| Word-timestamp fidelity vs human reference | **NOT_RUN** | Native token offsets are monotonic and within the source, but no independent alignment exists to score them |

**WER formula:** `WER = (S + D + I) / N`. This measurement verifies the adapter and
timestamps; it is not evidence about real-world recording accuracy.

## 6. AI highlight quality

| Item | Status | Notes |
|---|---|---|
| Reference highlight set / detection rate / precision / recall | **NOT_RUN** | No AI highlight extraction engine and no human-reviewed reference set in this app |
| Sentence completion / context completeness / duplicates-overlaps / false positives / silence | **NOT_RUN** | Not measurable without Engine B and reference annotations |
| Human ratings (1–5: context, coherence, opening, standalone usefulness, ending) | **NOT_RUN** | No human reviewer study conducted |

## 7. Export quality (measured for Engine A)

Validation checks executed on real outputs (ffmpeg-fallback probe; ffprobe binary unavailable): file exists, probe valid, video/audio streams present, H.264/AAC, 720p target, aspect ratio, duration > 0, size > 0, MP4 container.

| Run / case | Aspect | Status | Resolution | Duration (s) | Size (MB) | Notes |
|---|---|---|---|---:|---:|---|
| `6a80bee33c89` VC-60S | 16:9 | **PASS** (revalidated) | 1280×720 | 69.49 | 4.58 | Valid H.264/AAC MP4, 30 fps; initial report showed FAIL due to ffprobe-binary validation bug, corrected by ffmpeg-fallback probe and report regeneration |
| `579bf2c90636` VC-60S-9x16 | 9:16 | **PASS** | 720×1280 | 67.43 | 3.54 | Valid export, aspect check passed |
| `579bf2c90636` VC-60S-1x1 | 1:1 | **PASS** | 720×720 | 65.96 | 3.26 | Valid export, aspect check passed |

**A/V sync (spot-check from prior verified acceptance renders):** stream durations matched in ffprobe-based acceptance evidence (e.g. 78.52 s 16:9, 329.1 s 5-min). Current benchmark probe reports container/stream presence and duration; deep A/V drift analysis beyond probe not separately instrumented. **Engine B clip exports (from uploaded sources):** all 5 long-source renders and 3 aspect renders validated `av_sync_ok` (stream-duration delta < 0.1 s); per-frame drift not instrumented.

## 8. AI Video Creator results (Engine A, measured baseline)

| Test ID | Case | Status | Wall time (s) | Output duration (s) | Processing ratio (wall/output) | Peak app RSS (MB) | CPU avg / peak (%) | Sys mem peak (%) | Swap peak (MB) | Export |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| VC-60S (`6a80bee33c89`) | 1-min target, 16:9, 30 fps, music, burn subs | **PASS** | 16.464 | 69.49 | 0.237 | 708.2 | 42.21 / 92.9 | 83.4 | 4073.9 | 4.58 MB, 1280×720, valid |
| VC-60S-9x16 (`579bf2c90636`) | 1-min target, 9:16, 30 fps | **PASS** | 15.366 | 67.43 | 0.228 | 743.3 | 40.52 / 84.9 | 84.0 | 4349.6 | 3.54 MB, 720×1280, valid |
| VC-60S-1x1 (`579bf2c90636`) | 1-min target, 1:1, 30 fps | **PASS** | 12.543 | 65.96 | 0.190 | 460.1 | 35.56 / 65.4 | 83.4 | 4349.6 | 3.26 MB, 720×720, valid |

**Notes:** Processing ratio < 1 here means wall-clock generation finished faster than narrated output length (not realtime playback encoding ratio). Output durations are narration-driven (macOS `say`) and exceeded nominal 60 s targets in these cases. 30-second, 3-minute, and 5-minute *benchmark-suite* cases were **not re-run** in this session’s automated benchmark runs (prior acceptance evidence exists separately in `docs/TEST_REPORT.md`: 3-min 183.55 s pass, 5-min 329.1 s pass, peak 746 MB; not duplicated as benchmark-run JSON except as historical evidence).

## 9. Memory and stability stress test

| Test | Status | Measured/observed result |
|---|---|---|
| 5 consecutive 1-minute videos | **NOT_RUN** (this benchmark session) | Prior ad-hoc acceptance runs completed without OOM; no automated 5x loop benchmark recorded here |
| 3 consecutive 5-minute videos | **NOT_RUN** | High time/memory cost on 8 GB; not executed in this session |
| Multiple clips from one 30-minute source (Engine B) | **PASS** (selection; 1 of 5 rendered) | `long_49293b9eaf59_30m.json`: 5 non-overlapping clips selected in 0.82 s; one deep-end clip rendered in 2.23 s / 384 MB and validated |
| Cancel job during transcription | **NOT_RUN** | No transcription pipeline/Whisper job in Engine A |
| Cancel job during rendering/generation | **PASS** (`8f20fe6de9f9`, STAB-CANCEL) | `job.canceled=True` set ~2.5 s into real run; terminal `job_status=canceled`, wall 3.7 s, peak app RSS 91.8 MB, **no crash observed** |
| Restart app during recoverable workflow | **NOT_RUN** (automated) | Startup recovery logic exists and previously verified (`interrupted` marking); automated restart benchmark not executed here |
| Reopen previously saved project | **NOT_RUN** (automated benchmark) | Verified in prior acceptance/API checks; not executed as timed benchmark case |
| Process after a failed job | **NOT_RUN** (automated) | Not executed in this benchmark session |

**Memory/pressure observations (Engine A runs):** peak app RSS 460–743 MB in short measured cases; host system memory percent peaked ~83–84% and swap used peaked ~4.07–4.35 GB (host-wide, influenced by environment). **No crashes or OOM observed** in executed benchmark cases.

## 10. Benchmark pass/fail criteria (applied)

| Criterion | Result |
|---|---|
| No cloud/API dependency | **PASS** (local pipeline, macOS `say`, FFmpeg/Pillow) |
| No paid API requirement | **PASS** |
| No application crash during standard 1–5-minute workloads (measured in available runs) | **PASS** for executed benchmark cases; 3/5-min suite reruns not executed this session (prior acceptance passes documented) |
| Valid 720p MP4 exports (measured cases) | **PASS** |
| Correct A/V sync | **PASS** by prior verified acceptance probes; benchmark probe confirms valid streams/duration (detailed drift not separately instrumented) |
| Correct timestamp handling | **NOT FULLY BENCHMARKED** (Engine B timestamps N/A; Engine A subtitle timing is narration-derived) |
| Saved projects reopen successfully | **PASS** in prior acceptance/API evidence (not re-timed here) |
| No silent loss of uploaded source files | **PASS for Engine B uploads (separate harness)** | SHA-256 of stored file equals uploaded bytes for MP4/MOV/MKV/WebM |
| Processing errors reported accurately | **PASS** (job statuses/errors recorded; initial ffprobe-binary validation issue identified and corrected in reporting/tooling) |
| Memory released after jobs (settling) | **PARTIAL** (post-run samples captured; long-interval settling not formally profiled) |

## 11. Performance optimization experiments

| Experiment | Status | Notes |
|---|---|---|
| A. Whisper Tiny vs Base | **PARTIAL** | `base.en` measured (RTF 0.0265, 446 MB peak, 1.01 % WER on clean TTS); `tiny.en` not built/measured, so no A/B comparison |
| B. CPU vs Apple Silicon acceleration | **NOT_RUN** (comparative) | No controlled A/B measured |
| C. Low-res proxy vs original-resolution analysis | **NOT_RUN** | Proxy path not implemented; current analysis uses 16 kHz audio + 2 fps 320 px scan |
| D. FFmpeg encoding presets | **NOT_RUN** (comparative) | No controlled comparison executed |
| E. Sequential vs concurrent pipeline | **NOT_RUN** (comparative) | Sequential enforced by design for 8 GB safety |
| F. Processing chunk sizes | **NOT_RUN** | Not varied/measured comparatively |
| G. Optional local LLM enabled vs disabled | **N/A** | The app is deterministic-only; no LLM path exists to compare |

**Baseline configuration chosen (current):** sequential, disk-backed, 720p, per-scene composition, macOS `say` — consistent with observed stability on 8 GB in measured runs.

## 12. Automated testing

- **Benchmark command:** `PYTHONPATH=backend backend/.venv/bin/python scripts/benchmark_suite.py [--quick|--full]` (real Engine A runs + reports under `benchmarks/`).
- **API/UI:** `/api/benchmark/*` endpoints and `M2 Benchmark` dashboard for live samples, run history, and report paths.
- **Unit/integration test suite (requested breadth):** Engine B has an acceptance harness (`scripts/engine_b_e2e.py`, 16 cases), an ASR accuracy harness (`scripts/engine_b_asr_wer.py`) and a long-source harness (`scripts/engine_b_longrun.py`), but there is still **no comprehensive pytest suite** for the full transcription/highlight/FFmpeg export matrix, and no benchmark-suite integration for Engine B.

## 13. Benchmark reports (generated artifacts)

| Run | JSON | HTML |
|---|---|---|
| `6a80bee33c89` (corrected validation/report) | `benchmarks/reports/benchmark_6a80bee33c89_20261114T181946Z.json` | `benchmarks/reports/benchmark_6a80bee33c89_20261114T181946Z.html` |
| `579bf2c90636` format checks | `benchmarks/reports/benchmark_579bf2c90636_20261114T182101Z.json` | `benchmarks/reports/benchmark_579bf2c90636_20261114T182101Z.html` |
| `8f20fe6de9f9` cancel stability | `benchmarks/reports/benchmark_8f20fe6de9f9_20261114T182514Z.json` | `benchmarks/reports/benchmark_8f20fe6de9f9_20261114T182514Z.html` |

Raw run records: `benchmarks/data/runs/*.json` (include samples excerpts, configs, environment, sections, statuses).

Engine B reports (separate harnesses): `benchmarks/data/engine_b/e2e_11d49374a4fb_20261117T081352Z.json`
(acceptance, 16 cases), `benchmarks/data/engine_b/wer_971ca893acbe.json` (ASR WER) and
`benchmarks/data/engine_b/long_*_{1,5,15,30,60}m.json` (duration matrix).

## 14. Final hardware capability classification

| Engine | Workload | Classification | Notes |
|---|---|---|---|
| AI Video Creator (Engine A) | 1-min target 720p (16:9/9:16/1:1) animated-graphics generation | **FULLY_SUPPORTED** (measured PASS in executed cases) | Valid 720p H.264/AAC exports; narration-driven duration ~66–69 s; peaks ~460–743 MB app RSS in these runs |
| AI Video Creator (Engine A) | 3-minute 720p generation | **SUPPORTED_WITH_OPTIMIZATION** (prior acceptance evidence) | 183.55 s output measured previously (see `docs/TEST_REPORT.md`); not rerun in this automated benchmark session |
| AI Video Creator (Engine A) | 5-minute 720p generation | **SUPPORTED_WITH_OPTIMIZATION** (prior acceptance evidence) | 329.1 s, peak 746 MB measured previously; narration exceeded 300 s target |
| AI Video Creator (Engine A) | Cancel during generation (basic) | **SUPPORTED_WITH_OPTIMIZATION** | Measured PASS (canceled, no crash); checkpoint-dependent responsiveness |
| AI Auto-Clip Studio (Engine B) | Auto-clip on short sources (≤ ~1–2 min tested) | **SUPPORTED_WITH_OPTIMIZATION** (measured separately) | 67.52 s synthetic source: 3 aspects validated, 1.83–2.30 s per render, 362–379 MB peak (latest run); ASR-only path additionally produced 1 highlight → 9:16 render (9 cues, validated). |
| AI Auto-Clip Studio (Engine B) | Auto-clip on long sources (1–60 min, synthetic) | **SUPPORTED_WITH_OPTIMIZATION** (measured separately) | 68.55 s → 3733.12 s sources: analysis 0.46 → 18.51 s (77 → 452 MB), highlights 0.02 → 2.88 s, deep-end render 1.56–2.35 s (359–415 MB), all validated. Real-footage cost **NOT_RUN**. |
| AI Auto-Clip Studio (Engine B) | Local ASR (whisper.cpp base.en) | **SUPPORTED** (clean synthetic TTS) | 67.52 s audio in 1.79 s (RTF 0.0265), 446.2 MB peak, native word timings, **1.01 % WER** on the known TTS script; human speech **NOT_RUN**. |

## 15. Bottleneck analysis, recommendations, failures, limitations

**Bottlenecks (measured/observed):** Engine A — narration synthesis + per-scene FFmpeg composition dominate wall time; narration-driven output length affects processing ratio/targets; host memory pressure/swap can be high system-wide during runs on 8 GB. Engine B — envelope analysis scales with source duration (18.51 s for 62 min) and render cost with clip length (2.0–2.4 s per 30–45 s clip); deep seeking is not a bottleneck on the synthetic source, but real long-GOP footage was not measured.

**Optimization recommendations (evidence-aligned):** keep sequential, disk-backed, per-scene processing; tighten scripts for target duration; add more cancel checkpoints in long operations; benchmark other Whisper sizes only with ground-truth datasets (only `base.en` was measured here); do not enable concurrent heavy workloads (diffusion+transcription) on 8 GB.

**Failed tests (executed benchmark suite):** none in final corrected results. (Initial `6a80bee33c89` report marked FAIL due to missing `ffprobe` binary in validator — **measurement/reporting defect corrected**, export itself was valid and revalidated PASS.)

**Known limitations:** Engine B A1–A5 are measured only on synthetic sources; real-footage long-source cost is **NOT_RUN**; ASR is measured only on clean synthetic TTS (human speech/accents/noise are **NOT_RUN**); no human WER corpus or independently aligned word reference; no highlight reference/human ratings; GPU/Metal utilization not reliably sampled; background workload not isolated; `/usr/bin/time -l` max-RSS not captured; some Engine A stress/recovery matrix items not rerun this session (documented as NOT_RUN where applicable).

**Final assessment:** Engine A is **measurably capable** of local 720p animated-graphics video generation on M2 8 GB for tested cases with valid exports and no observed crashes, within the constraints above. Engine B is implemented and measured for short- and long-source clipping by its own harnesses (acceptance 16 PASS / 0 FAIL / 0 NOT_RUN; A1–A5 6/6 PASS each), with linear-time analysis, clip-length-bound render cost and validated 720p exports up to a 62-minute synthetic source. Local ASR runs at RTF 0.0265 with 1.01 % WER on the known clean-TTS script and native word timings; accuracy on human recordings and highlight quality against human judgement remain unverified. All results above are based on actual runs and captured reports.
