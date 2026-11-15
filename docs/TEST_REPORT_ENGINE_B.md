# Engine B — Test & Acceptance Report (AI Auto-Clip Studio)

**Date:** 2026-11-15
**Machine:** Apple M2, 8 GB unified memory, macOS (Darwin 27.0.0, arm64, as captured by the harness)
**Build under test:** base commit `f629237` + the Engine B change set (see [`CHANGELOG_ENGINE_B.md`](CHANGELOG_ENGINE_B.md)); working tree was dirty during the runs and each report records its environment
**FFmpeg:** imageio-ffmpeg v7.1 arm64 (`ffmpeg-macos-aarch64-v7.1`) — no standalone `ffprobe` on this machine
**ASR:** whisper.cpp binary **and** GGML model absent (`/api/clip/capabilities` → `available: false` with explicit reasons)
**Harness:** `scripts/engine_b_e2e.py` (FastAPI `TestClient`, in-process job threads, real FFmpeg)
**Reports:** `benchmarks/data/engine_b/e2e_cb28b3f43d1f_20261115T080431Z.json` (full run), `.../e2e_9eeda88fc15b_...json` (earlier full run), `.../e2e_072140ee2f2e_...json` (first run, failed — kept for traceability)

> **Policy:** every PASS/FAIL below comes from a check the harness actually executed and recorded. Missing prerequisites are `NOT_RUN`, never silently passed. There are no fabricated transcripts, quality scores or timings. Source media is **synthetic** (see §2), so nothing here is evidence about real-world footage quality.

---

## 1. Summary

| Metric | Value |
|---|---|
| Cases executed | 15 |
| PASS | 14 |
| FAIL | 0 |
| WARNING | 0 |
| NOT_RUN | 1 (`B3-ASR`: no whisper.cpp binary/model) |
| Overall status reported by harness | `WARNING` (a NOT_RUN is never reported as PASS) |
| Total harness wall time | 31.64 s |
| Engine A regression (separate suite) | PASS — `benchmarks/data/runs/9bd9e75d5312.json` |

What this run **does** establish: ingest of all four containers with byte-identical preservation, probing accuracy, structural analysis, SRT import, deterministic highlight scoring, 720p H.264/AAC rendering in three aspects with burned captions and loudness normalisation, batch export with a per-item manifest, persistence after reload, validation errors, source replacement semantics, live cancellation, restart recovery, and that Engine A's tables/endpoints still work.

What it **does not** establish: ASR accuracy (no backend), word-level timing fidelity, WER, highlight quality versus human judgement, long-duration (5/15/30/60-minute) performance, or real-footage behaviour. See §7.

---

## 2. Test fixture (synthetic, generated on this machine)

`build_fixture()` in `scripts/engine_b_e2e.py`:

1. Generates speech with macOS `say` (offline TTS) — 15 sentences on habit formation.
2. Measures each synthesized clip with the same FFmpeg probe used by the app (`probe_media`).
3. Builds the SRT from those **measured** speech durations (cue `start`/`end` bracketing each spoken sentence, 0.42 s gaps).
4. Renders a 1280×720 @ 30 fps H.264/AAC colour video (FFmpeg `testsrc2` + tone bed) and pads/trims it to the narration length.
5. Re-encodes short `.mov`, `.mkv`, `.webm` variants for the container tests.

Measured fixture: **67.52 s**, 1280×720, 30 fps, H.264/AAC, 1,543,027 bytes, `probe_source=ffmpeg_fallback`.

Why this is honest:
- The media is real and local, and the app processes it end to end.
- The transcript is **not** an ASR result; its timings come from the measured TTS durations. The harness labels the import path accordingly (`timing: file`, `word_timing: estimated`).
- No human reference ratings exist, so highlight "quality" is not scored — only transparency, groundedness and non-overlap are asserted.

---

## 3. Case results (full run)

| Case | What was checked | Result | Measured evidence |
|---|---|---|---|
| `FIXTURE` | Fixture has video, audio, SRT, valid probe | **PASS** | 67.52 s, 1280×720, 1 audio stream |
| `B1-UPLOAD` | MP4/MOV/MKV/WebM upload; stored bytes unchanged | **PASS** | all four upload `200`; SHA-256 of stored file equals SHA-256 of uploaded file for all four |
| `B1-METADATA` | Probe duration/fps/dimensions/codecs per container | **PASS** | MP4 67.52 s, 30 fps, 1280×720, h264/aac; all containers report 1280×720 and ≥1 audio stream |
| `B2-ANALYZE` | Audio extraction + envelope + silence + scene scan | **PASS** | job `succeeded`; 676 envelope windows, 14 silence gaps, 0 scene cuts (static colour source); 0.4 s, peak 79 MB |
| `B3-ASR` | whisper.cpp transcription | **NOT_RUN** | binary and model absent; capability gating returns reasons; no transcript is fabricated |
| `B3-IMPORT` | SRT import, clamping, monotonicity | **PASS** | `200`, 15 cues, `timing=file`, `word_timing=estimated`, monotonic, all within duration |
| `B4-HIGHLIGHTS` | Scoring, groundedness, non-overlap, reasons | **PASS** | 2 clips from a 67.5 s source at targets `[15,30,45]`; 0 overlaps; every clip has score components + reason; title/hook/caption substrings of its own transcript |
| `B5-RENDER` | Three aspects with captions + normalisation | **PASS** | 9:16 = 720×1280, 16:9 = 1280×720, 1:1 = 720×720 — all H.264/AAC 48 kHz stereo, A/V delta < 0.1 s |
| `B6-BATCH` | Batch export + manifest | **PASS** | requested 2, exported 2, 2 files listed, manifest written; per-item duration/size/validation/loudness/hashtags recorded |
| `B7-REOPEN` | Persistence after reload | **PASS** | 2 clips, transcript present, only the rendered clip has renders, aspects `16:9, 1:1, 9:16` |
| `B8-VALIDATION` | Unsupported container; inverted range | **PASS** | `415` for `.txt`; `400` for `end <= start` |
| `B12-REPLACE` | One source per project; replacement clears state | **PASS** | `409` without `replace_existing`; `200` with it; cleared 1 source + 2 clips; transcript gone; source ext `.mov` |
| `B9-CANCEL` | Cancel a live analysis job | **PASS** | cancel flag set at 0.03 s; terminal `canceled`; `tmp/` empty; no crash |
| `B10-RECOVERY` | Restart marks in-flight job | **PASS** | 1 row → `interrupted` |
| `B11-ENGINE-A` | Engine A tables/endpoints still present | **PASS** | Engine A job tables intact; full regression run separately (§6) |

### 3.1 Render measurements (clip 1: 0.00 s → 44.12 s, 28 caption cues)

| Aspect | Output | Duration | Size | Wall | Peak RSS | Loudness |
|---|---|---:|---:|---:|---:|---|
| 9:16 | 720×1280, H.264 + AAC 48 kHz stereo | 44.14 s | 1,416,711 B | 2.41 s | 402 MB | −16.0 LUFS / −4.6 dBTP |
| 16:9 | 1280×720, H.264 + AAC 48 kHz stereo | 44.14 s | 1,243,704 B | 2.17 s | 376 MB | −16.0 LUFS / −4.6 dBTP |
| 1:1 | 720×720, H.264 + AAC 48 kHz stereo | 44.14 s | 1,053,803 B | 1.85 s | 348 MB | −16.0 LUFS / −4.6 dBTP |

Crop geometry recorded per render (fractions of the source frame): 9:16 centred `x=0.3418 w=0.3164`, 16:9 full frame, 1:1 left `w=0.5625`. This is deterministic geometry — **no face or subject tracking is involved**.

### 3.2 Batch export measurements

| Item | Window | Aspect | Duration | Size | Loudness | Validation |
|---|---|---|---:|---:|---|---|
| 01 | 0.00 → 44.12 s | 9:16 | 44.14 s | 881,759 B | −16.0 LUFS / −4.6 dBTP | all checks ok |
| 02 | 54.20 → 67.51 s | 9:16 | 13.33 s | 426,005 B | −16.1 LUFS / −3.7 dBTP | all checks ok |

Validation flags per item: `exists, resolution_ok, video_codec_h264, audio_codec_aac, duration_ok, audio_present, size_ok, av_sync_ok` all true. `probe_source=ffmpeg_fallback` because no standalone `ffprobe` is installed.

---

## 4. What earlier failing runs changed (traceability)

The first full run (`e2e_072140ee2f2e_20261115T074220Z.json`) failed and is kept as evidence. Defects it exposed, all fixed before the run above:

1. **MKV/WebM probing** returned no width/height. The FFmpeg-stderr parser split on commas, but Matroska prints `yuv420p(tv, progressive)`, which contains a comma. Fixed by parsing the whole `Stream … Video:` line.
2. **SRT import monotonicity** could be violated by overlapping cues. Fixed by sorting and clamping overlaps in `transcribe.py` (0.05 s minimum cue).
3. **E2E harness defect** — it asserted metadata on the last uploaded variant instead of the primary MP4. Fixed by uploading the primary MP4 first and asserting per container.
4. **Source replacement was not implemented** — a second upload silently left stale clips/transcript that referenced the old timeline. Fixed with explicit `replace_existing` semantics, 409 conflict, stale-artifact cleanup, and case `B12-REPLACE`.
5. **Cancellation could lose the race** in short analyses. Fixed by forcing a cancel check at stage boundaries (`force=True`) and documenting the 0.2 s in-loop throttle; `B9-CANCEL` now reaches `canceled`.

---

## 5. Reproduce

```bash
cd local-ai-video-studio
# Full run (~35 s of work on this machine, synthetic source)
PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_e2e.py

# Smaller fixture for fast iteration
PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_e2e.py --quick
# --keep retains the fixture and clip project directories for inspection
```

Reports are written to `benchmarks/data/engine_b/e2e_<id>_<timestamp>.json`. The harness aborts are recorded as a `RUN` FAIL case with a traceback rather than being swallowed.

---

## 6. Engine A regression (must stay independent)

Executed with the Engine B code loaded: `PYTHONPATH=backend backend/.venv/bin/python scripts/benchmark_suite.py --quick --json`

| Run | Case | Result | Measured |
|---|---|---|---|
| `9bd9e75d5312` | `VC-60S` (16:9, 30 fps) | **PASS** | wall 16.464 s, output 69.49 s, ratio 0.2369, peak app RSS 725.9 MB, `1280×720` H.264/AAC export validated |

Engine A tables (`projects`, `jobs`) and endpoints are unchanged; Engine B adds `clip_*` tables and `/api/clip/*`. The only shared changes are the FFmpeg/memory helpers, `ensure_schema()` registration, the sequential-job guard (now counts either engine's active job) and the `/api/system` summary block.

---

## 7. NOT_RUN / unverified (honest)

| Item | Status | Why |
|---|---|---|
| whisper.cpp transcription | **NOT_RUN** | No binary and no GGML model on this machine; `scripts/install_whisper_cpp.sh --check` reports `cmake` missing and exits 3 |
| WER / word-timestamp accuracy | **NOT_RUN** | Requires an installed ASR backend *and* independent ground-truth transcripts; neither exists here |
| Highlight quality vs human judgement | **NOT_RUN** | No reference ratings; only groundedness, inspectability and non-overlap are asserted |
| 5 / 15 / 30 / 60-minute sources (benchmark matrix A1–A5) | **NOT_RUN** | Not executed in this session; the measured source is 67.5 s |
| GPU / Metal utilisation | **NOT_RUN** | Not reliably sampleable without privileged `powermetrics` |
| `/usr/bin/time -l` max RSS | **NOT_RUN** | Peaks are sampled process-tree RSS, not the kernel high-water mark |
| Packaged-app Engine B | **NOT RUN** | The desktop bundle was not rebuilt for Engine B in this session; verification is dev-server + API/harness only |
| Browser click-through of the Engine B UI | **NOT RUN** | No connected browser session; the frontend builds (`tsc -b && vite build` PASS) and the SPA route returns `200`, but no automated interaction was recorded |
| A/V drift beyond duration delta | **NOT RUN** | Validation compares stream durations (< 0.1 s); no per-frame sync analysis |

---

## 8. Limitations that affect interpretation

1. **Synthetic source.** Colour bars + tone, static scene. Scene-cut detection reports 0 because there are no cuts; that is the correct result, not a failure.
2. **No standalone `ffprobe`.** All probing uses FFmpeg stderr parsing, recorded as `probe_source=ffmpeg_fallback` on every source and render.
3. **Imported timings, not recognised speech.** `B3-IMPORT` proves the import path; it says nothing about ASR accuracy.
4. **Two clips from one 67.5 s source.** The shortfall message is reported when fewer non-overlapping windows fit than requested; the harness asserts that behaviour rather than forcing extra clips.
5. **Cancellation timing.** `B9-CANCEL` succeeded because the cancel flag landed while the job was live; on very short jobs a cancel can still arrive after completion, which is reported as a WARNING with the observed terminal status, never as PASS.
6. **Memory numbers are per-job sampled peaks** on a shared 8 GB machine with background load (global memory 83.6 % during the run), not isolated benchmarks.
