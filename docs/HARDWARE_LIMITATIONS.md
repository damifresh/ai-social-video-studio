# Hardware Limitations & Optimization Guide (Apple M2 / 8 GB)

## Target constraints
- **Unified memory:** 8 GB shared by CPU/GPU/ANE. Memory pressure causes swap thrash, slowdowns, or OOM kills.
- **No 16/24/48 GB workflows.** All defaults must function (or degrade gracefully) within 8 GB.

## Implemented optimizations
- **Sequential execution:** single background job at a time (`409` if a job is running). Stages run in order: script → storyboard → visuals → TTS → subtitles → audio mix → per-scene render → compose.
- **Disk-backed intermediates:** per-scene images, WAVs, MP4 segments, concat lists, SRT/VTT, and final render are written to `data/projects/<id>/` (never held as a full in-memory timeline).
- **Per-scene rendering:** each scene is rendered to its own MP4 segment via FFmpeg, then concatenated and muxed with audio.
- **Lazy/subprocess media work:** FFmpeg and `say` run as subprocesses; memory is reclaimed by the OS on exit.
- **Conservative defaults:** 720p, 30 fps, deterministic script, macOS `say` narration fallback, animated-graphic visuals (PIL + zoompan), SRT-from-timings.
- **Cleanup/resilience:** intermediates are preserved on failure for recovery/debugging; projects/assets are not deleted by failed renders.

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

## Known limitations (this machine/session)
- Python 3.9 system; MLX/Kokoro packages typically need 3.10+ isolated env and model downloads (not fully installed/verified here).
- Whisper.cpp binary/models not installed in this session; subtitle alignment uses narration-timing generation (accurate to synthesized audio, no ASR correction).
- No bundled licensed music/SFX shipped by default; user must supply properly licensed files in `assets/music` or `assets/sfx`.
- Motion Canvas and diffusion video generation not enabled by default on 8 GB.
