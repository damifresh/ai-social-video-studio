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
| Whisper.cpp | Prefer `tiny`/`base`/`small` ggml models; avoid `medium/large` during other work. Optional (timing-based subs available). |
| Image generation (diffusion) | Use low resolutions, one image at a time, unload model after batch; expect swap on larger models. Default is programmatic graphics. |
| Video diffusion (Wan 2.1 1.3B etc.) | **Not assumed feasible** (~10+ GB reported). Default OFF; if experimented, use shortest clips, quantization, cache controls, and measure peak memory. |
| FFmpeg encode | Memory-safe/streaming; CPU time is the main cost. `veryfast` preset and per-scene segments reduce peak pressure. |

## Monitoring & failure handling
- Job `stage/progress/message/error` persisted in SQLite and shown in UI (real state, not fake percentages).
- Pipeline logs: `data/projects/<id>/logs/pipeline.log`.
- Measure with Activity Monitor / `vm_stat` / `/usr/bin/time -l` during acceptance tests; record peak RSS/unified memory pressure.
- On OOM or crash: re-run generation; completed per-scene artifacts remain on disk. (Full automatic resume-from-stage is incremental; current behavior is safe/idempotent per output file.)

## Verified measurements (Apple M2 / 8 GB, macOS 27.0.1)

- **1-min class renders (16:9/9:16/1:1, 24–30 fps):** ~70–79 s output, ~4–5.4 MB, **peak 490–730 MB** sampled, ~10–17 s generate time.
- **3-min 16:9:** 183.55 s output, 8.51 MB (earlier verified demo).
- **5-min 16:9 (narration-driven 329.1 s, 15 scenes, 147 cues):** 21.44 MB, **peak 746 MB** sampled, generate 72.3 s — completed without OOM under memory pressure (~1.4 GB free / swap in use).
- **Packaged desktop render:** 73.66 s output, 5.17 MB, peak 728 MB, successful through bundled Python/FFmpeg inside the `.app`.
- **Engine B (67.52 s synthetic source, separate harness):** analysis 0.4 s / 79 MB peak; 44.14 s clip renders 2.41 s (9:16, 402 MB), 2.17 s (16:9, 376 MB), 1.85 s (1:1, 348 MB); batch of 2 in 2.84 s / 377 MB. Global memory was ~83.6 % during the run; no OOM.

## Current limitations (honest)

- **Kokoro MLX / Whisper.cpp:** not installed or runtime-verified in this build. Narration uses macOS `say` (offline) and subtitles use narration-timing segmentation (accurate to synthesized boundaries, no ASR correction). Fallbacks are recorded in metadata.
- **Diffusion image/video generation:** not enabled/assumed feasible on 8 GB. Visuals are animated graphics/stills (labeled), not AI-generated footage.
- **Narration-driven duration:** final length follows synthesized speech (measured ~174 wpm for Samantha), so 1-min/5-min targets can overshoot (e.g. ~74–79 s, 329 s) unless script/narration is shortened.
- **Memory metric:** jobs report sampled process RSS peak; not a formal `/usr/bin/time -l` max-RSS measurement.
- **Music/SFX:** bundled tracks are original procedural CC0 audio (`scripts/generate_assets.py`); add your own properly licensed files as needed.
- **Desktop app:** unsigned (Gatekeeper override on first launch). Automated in-Electron UI click-through was not captured in this session.
- **Engine B ASR:** whisper.cpp binary/model absent → transcription `NOT_RUN`; use SRT/VTT import or run `scripts/install_whisper_cpp.sh` (needs cmake + network once). No WER claim.
- **Engine B long sources:** 5/15/30/60-minute sources and real-footage behaviour are untested; the measured source is 67.5 s. Analysis is linear-time and disk-backed, but memory/latency on hour-long files is unmeasured.
- **Engine B tracking:** none. Crops are static geometry (centre/edges/manual rect), so a moving subject can leave frame.
