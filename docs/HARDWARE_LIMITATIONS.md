# Hardware Limitations & Optimization Guide (Apple M2 / 8 GB)

## Target constraints
- **Unified memory:** 8 GB shared by CPU/GPU/ANE. Memory pressure causes swap thrash, slowdowns, or OOM kills.
- **No 16/24/48 GB workflows.** All defaults must function (or degrade gracefully) within 8 GB.

## Implemented optimizations
- **Sequential execution:** single heavy job at a time across both engines (`409` if a job is running, whichever engine owns it). Engine A stages run in order: script → storyboard → visuals → TTS → subtitles → audio mix → per-scene render → compose.
- **Disk-backed intermediates:** per-scene images, WAVs, MP4 segments, concat lists, SRT/VTT, and final render are written to `data/projects/<id>/` (never held as a full in-memory timeline).
- **Per-scene rendering:** each scene is rendered to its own MP4 segment via FFmpeg, then concatenated and muxed with audio.
- **Lazy/subprocess media work:** FFmpeg and `say` run as subprocesses; memory is reclaimed by the OS on exit.
- **Conservative defaults:** 720p, 30 fps, deterministic script, macOS `say` narration fallback, animated-graphic visuals (PIL + zoompan), SRT-from-timings.
- **Cleanup/resilience:** intermediates are preserved on failure for recovery/debugging; projects/assets are not deleted by failed renders.
- **Engine B specifics:** streamed 4 MB uploads with running SHA-256 (no full-file buffering), 16 kHz mono audio extraction, 8 kHz envelope decode, 2 fps 320 px scene scan, per-render FFmpeg subprocess with `-progress` parsing, and `tmp/` cleaned on success and failure.

## Model-specific guidance
| Component | 8 GB guidance |
|---|---|
| Kokoro TTS (82M, MLX) | Feasible *if installed* (prefer 4-bit/8-bit), but run alone and unload before other heavy stages. Not auto-assumed; fallback is macOS `say`. |
| Whisper.cpp | Installed and measured here as `base.en` (English-only). Prefer `tiny`/`base`/`small` ggml models on 8 GB; avoid `medium`/`large`. Measured 67.52 s of clean TTS in 1.79 s at 446 MB peak. |
| Image generation (diffusion) | Use low resolutions, one image at a time, unload model after batch; expect swap on larger models. Default is programmatic graphics. |
| Video diffusion (Wan 2.1 1.3B etc.) | **Not assumed feasible** (~10+ GB reported). Default OFF; if experimented, use shortest clips, quantization, cache controls, and measure peak memory. |
| FFmpeg encode | Memory-safe/streaming; CPU time is the main cost. `veryfast` preset and per-scene segments reduce peak pressure. |

## Monitoring & failure handling
- Job `stage/progress/message/error` persisted in SQLite and shown in UI (real state, not fake percentages).
- Pipeline logs: `data/projects/<id>/logs/pipeline.log`.
- Measure with Activity Monitor / `vm_stat` / `/usr/bin/time -l` during acceptance tests; record peak RSS/unified memory pressure.
- On OOM or crash: re-run generation or use Re-render; completed per-scene artifacts remain on disk. `backend/app/services/resume.py` records input signatures in `resume.json`, and Re-render skips only stages whose signature still matches and whose artifacts are present. Startup still marks interrupted jobs rather than auto-starting them, so the user remains in control of re-triggering work.

## Verified measurements (Apple M2 / 8 GB, macOS 27.0.1)

- **1-min class renders (16:9/9:16/1:1, 24–30 fps):** ~70–79 s output, ~4–5.4 MB, **peak 490–730 MB** sampled, ~10–17 s generate time.
- **3-min 16:9:** 183.55 s output, 8.51 MB (earlier verified demo).
- **5-min 16:9 (narration-driven 329.1 s, 15 scenes, 147 cues):** 21.44 MB, **peak 746 MB** sampled, generate 72.3 s — completed without OOM under memory pressure (~1.4 GB free / swap in use).
- **Packaged desktop render:** 73.66 s output, 5.17 MB, peak 728 MB, successful through bundled Python/FFmpeg inside the `.app`.
- **Engine B short source (67.52 s synthetic, separate harness):** analysis 0.4 s / 79 MB peak; 44.14 s clip renders 2.41 s (9:16, 402 MB), 2.17 s (16:9, 376 MB), 1.85 s (1:1, 348 MB); batch of 2 in 2.84 s / 377 MB. Global memory was ~83.6 % during the run; no OOM.
- **Engine B long sources (synthetic, separate harness):** 1/5/15/30/60-minute fixtures measured end to end. Analyze 0.46 → 18.51 s (peaks 77 → 452 MB), highlights 0.02 → 2.88 s, deep-end render 1.56–2.35 s (359–415 MB). All uploads byte-identical, all renders validated; no OOM.
- **Engine B ASR (whisper.cpp `base.en`, separate harness):** 67.52 s of clean synthetic TTS → 17 segments / 15 sentences / 199 words in **1.79 s** (RTF 0.0265), **446.2 MB** peak, native word timings, monotonic. WER **1.01 %** on the fixture's known script (2 substitutions / 199 words). Whisper runs as a subprocess, so its memory is released on exit; the sequential-job guard also covers clip jobs, so ASR and Engine A renders never overlap.

## Current limitations (honest)

- **Kokoro MLX:** not installed or runtime-verified in this build. Narration uses macOS `say` (offline) and subtitles use narration-timing segmentation (accurate to synthesized boundaries, no ASR correction). Fallbacks are recorded in metadata. whisper.cpp is a separate Engine B path (below) and is installed.
- **Diffusion image/video generation:** not enabled/assumed feasible on 8 GB. Visuals are animated graphics/stills (labeled), not AI-generated footage.
- **Narration-driven duration:** final length follows synthesized speech (measured ~174 wpm for Samantha), so 1-min/5-min targets can overshoot (e.g. ~74–79 s, 329 s) unless script/narration is shortened.
- **Memory metric:** jobs report sampled process RSS peak; not a formal `/usr/bin/time -l` max-RSS measurement.
- **Music/SFX:** bundled tracks are original procedural CC0 audio (`scripts/generate_assets.py`); add your own properly licensed files as needed.
- **Desktop app:** unsigned (Gatekeeper override on first launch). Rebuilt 2026-11-18 with Engine B and bundled whisper.cpp; its loopback backend was smoke-checked, but automated in-Electron UI click-through was not captured in this session.
- **Engine B ASR is measured only on clean synthetic speech:** whisper.cpp `base.en` is installed (cmake installed into the backend venv was the prerequisite on this machine) and produces native word timings, but the only ground truth is the TTS script that generated the fixture. Accents, background noise, multi-speaker audio, fast speech and human ground-truth transcripts are **NOT_RUN**; the 1.01 % WER must not be generalised. The model is English-only. SRT/VTT import remains available and is never simulated.
- **Engine B long sources are measured on synthetic media:** 1/5/15/30/60-minute fixtures are TTS over `testsrc2` colour video (1.56 MB → 84.78 MB). Latency/memory are real for those files, but a real 720p/1080p recording of the same length decodes far more data; real-footage cost is unmeasured. Deep seeks (up to ~41 min into the 62-min file) were not a bottleneck on this material.
- **Engine B tracking:** none. Crops are static geometry (centre/edges/manual rect), so a moving subject can leave frame.
