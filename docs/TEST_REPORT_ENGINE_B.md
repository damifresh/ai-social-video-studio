# Engine B — Test & Acceptance Report (AI Auto-Clip Studio)

**Date:** 2026-11-15
**Machine:** Apple M2, 8 GB unified memory, macOS (Darwin 27.0.0, arm64, as captured by the harness)
**Build under test:** commits `f629237` + `88e16ab` + the long-source/ASR follow-up (see [`CHANGELOG_ENGINE_B.md`](CHANGELOG_ENGINE_B.md)); each report records its environment
**FFmpeg:** imageio-ffmpeg v7.1 arm64 (`ffmpeg-macos-aarch64-v7.1`) — no standalone `ffprobe` on this machine
**ASR:** whisper.cpp `whisper-cli` built locally + `ggml-base.en.bin` (147,964,211 B); `/api/clip/capabilities` → `available: true`
**Harnesses:** `scripts/engine_b_e2e.py` (acceptance, 16 cases), `scripts/engine_b_asr_wer.py` (ASR accuracy), `scripts/engine_b_longrun.py` (1/5/15/30/60-minute matrix) — all use the real HTTP API and real FFmpeg
**Reports:** `benchmarks/data/engine_b/e2e_11d49374a4fb_20261117T081352Z.json` (latest full run after the ASR token-parsing fix), `e2e_cb28b3f43d1f_20261115T080431Z.json` (pre-ASR full run), `.../e2e_072140ee2f2e_...json` (first run, failed — kept for traceability), `wer_971ca893acbe.json`, `.../long_*_{1,5,15,30,60}m.json`

> **Policy:** every PASS/FAIL below comes from a check the harness actually executed and recorded. Missing prerequisites are `NOT_RUN`, never silently passed. There are no fabricated transcripts, quality scores or timings. Source media is **synthetic** (see §2), so nothing here is evidence about real-world footage quality.

---

## 1. Summary

| Metric | Value |
|---|---|
| Cases executed | 16 |
| PASS | 16 |
| FAIL | 0 |
| WARNING | 0 |
| NOT_RUN | 0 |
| Overall status reported by harness | `PASS` |
| Total harness wall time | 37.1 s |
| ASR WER (clean synthetic TTS, known script) | **1.01 %** (2 substitutions / 199 words; 15/15 sentences; 14/15 boundaries within 0.75 s) |
| Long-source matrix (separate harness) | 6/6 PASS in each of 1/5/15/30/60 min runs |
| Engine A regression (separate suite) | PASS — `benchmarks/data/runs/9bd9e75d5312.json` |

What this run **does** establish: ingest of all four containers with byte-identical preservation, probing accuracy, structural analysis, local whisper.cpp transcription with native word timings, SRT import, deterministic highlight scoring, 720p H.264/AAC rendering in three aspects with burned captions and loudness normalisation, an ASR-only transcript driving highlights/captions/render, batch export with a per-item manifest, persistence after reload, validation errors, source replacement semantics, live cancellation, restart recovery, and that Engine A's tables/endpoints still work.

A separate harness (`scripts/engine_b_longrun.py`) additionally measured ingest → analysis → SRT import → highlight selection → deep-end render on synthetic sources of **68.55 s, 5:44, 16:05, 31:05 and 62:13** — all six cases PASS at every size (§6.1). That is real measured latency/memory for long files, not extrapolation.

What it **does not** establish: ASR accuracy on human speech (the only ground truth is the synthetic fixture's own script), word-timing fidelity beyond monotonic coverage, highlight quality versus human judgement, real-footage behaviour, or that a 60-minute *real* recording behaves like the synthetic one (synthetic video is cheap to decode). See §7.

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
- The SRT is **not** an ASR result; its timings come from the measured TTS durations. The import path is labelled accordingly (`timing: file`, `word_timing: estimated`).
- The ASR case runs whisper.cpp on the extracted audio and is scored against the fixture's known script. That is a real WER measurement for this build, but it is clean single-speaker TTS — **not** a human-speech benchmark.
- No human reference ratings exist, so highlight "quality" is not scored — only transparency, groundedness and non-overlap are asserted.

---

## 3. Case results (full run)

| Case | What was checked | Result | Measured evidence |
|---|---|---|---|
| `FIXTURE` | Fixture has video, audio, SRT, valid probe | **PASS** | 67.52 s, 1280×720, 1 audio stream |
| `B1-UPLOAD` | MP4/MOV/MKV/WebM upload; stored bytes unchanged | **PASS** | all four upload `200`; SHA-256 of stored file equals SHA-256 of uploaded file for all four |
| `B1-METADATA` | Probe duration/fps/dimensions/codecs per container | **PASS** | MP4 67.52 s, 30 fps, 1280×720, h264/aac; all containers report 1280×720 and ≥1 audio stream |
| `B2-ANALYZE` | Audio extraction + envelope + silence + scene scan | **PASS** | job `succeeded`; 676 envelope windows, 14 silence gaps, 0 scene cuts (static colour source); 0.4 s, peak 79 MB |
| `B3-ASR` | whisper.cpp transcription + timestamps + WER | **PASS** | `succeeded`; 17 segments → 15 sentences; native word timings; monotonic; last word ≤ source; **WER 1.01 %** (2 S / 0 D / 0 I, 199 words) |
| `B3-IMPORT` | SRT import, clamping, monotonicity | **PASS** | `200`, 15 cues, `timing=file`, `word_timing=estimated`, monotonic, all within duration |
| `B3-ASR-PIPELINE` | ASR-only transcript drives highlights, captions, render | **PASS** | upload `200`, analyze/transcribe/highlights `succeeded`, 1 clip, 9 caption cues, 9:16 render validation ok |
| `B4-HIGHLIGHTS` | Scoring, groundedness, non-overlap, reasons | **PASS** | 2 clips from a 67.5 s source at targets `[15,30,45]`; 0 overlaps; every clip has score components + reason; title/hook/caption substrings of its own transcript |
| `B5-RENDER` | Three aspects with captions + normalisation | **PASS** | 9:16 = 720×1280, 16:9 = 1280×720, 1:1 = 720×720 — all H.264/AAC 48 kHz stereo, A/V delta < 0.1 s |
| `B6-BATCH` | Batch export + manifest | **PASS** | requested 2, exported 2, 2 files listed, manifest written; per-item duration/size/validation/loudness/hashtags recorded |
| `B7-REOPEN` | Persistence after reload | **PASS** | 2 clips, transcript present, only the rendered clip has renders, aspects `16:9, 1:1, 9:16` |
| `B8-VALIDATION` | Unsupported container; inverted range | **PASS** | `415` for `.txt`; `400` for `end <= start` |
| `B12-REPLACE` | One source per project; replacement clears state | **PASS** | `409` without `replace_existing`; `200` with it; cleared 1 source + 2 clips; transcript gone; source ext `.mov` |
| `B9-CANCEL` | Cancel a live analysis job | **PASS** | cancel flag set at 0.03 s; terminal `canceled`; `tmp/` empty; no crash |
| `B10-RECOVERY` | Restart marks in-flight job | **PASS** | 1 row → `interrupted` |
| `B11-ENGINE-A` | Engine A tables/endpoints still present | **PASS** | Engine A job tables intact; full regression run separately (§6) |

### 3.1 ASR accuracy (whisper.cpp, clean synthetic TTS)

`scripts/engine_b_asr_wer.py` runs the app's `transcribe()` on the fixture's extracted
16 kHz audio and scores the recognised sentence text against the known script.

| Metric | Measured |
|---|---|
| Backend / model | whisper.cpp `whisper-cli` / `ggml-base.en.bin` (147,964,211 B), built locally |
| Audio / duration | 67.52 s, 16 kHz mono |
| ASR wall / RTF / peak RSS | 1.79 s / 0.0265 / 446.2 MB |
| Segments → sentences | 17 → 15 (reference: 15) |
| Words / word timing | 199 / `native`, monotonic |
| WER | **1.01 %** — 2 substitutions, 0 deletions, 0 insertions, 199 reference words |
| Exact sentence-text matches | 14 / 15 (normalised) |
| Boundaries within 0.75 s | 14 / 15; median start/end delta 0.32 s |

The two substitutions are `pick → take` and `behaviour → behavior` (spelling
normalisation). Report: `benchmarks/data/engine_b/wer_971ca893acbe.json`.

**Do not generalise this number.** The audio is macOS TTS, one speaker, no noise, no
accents, and the reference is the script that generated it. Human speech, accents,
background noise, multi-speaker audio and independently produced ground-truth
transcripts are **NOT_RUN**.

### 3.2 Render measurements (clip 1: 0.00 s → 44.12 s, 28 caption cues)

Values from the latest full run (`e2e_11d49374a4fb_20261117T081352Z.json`); run-to-run
variation on this shared machine was 1.83–2.41 s wall and 299–402 MB peak across three runs.

| Aspect | Output | Duration | Size | Wall | Peak RSS | Loudness |
|---|---|---:|---:|---:|---:|---|
| 9:16 | 720×1280, H.264 + AAC 48 kHz stereo | 44.14 s | 1,416,711 B | 2.30 s | 379 MB | −16.0 LUFS / −4.6 dBTP |
| 16:9 | 1280×720, H.264 + AAC 48 kHz stereo | 44.14 s | 1,243,704 B | 2.15 s | 377 MB | −16.0 LUFS / −4.6 dBTP |
| 1:1 | 720×720, H.264 + AAC 48 kHz stereo | 44.14 s | 1,053,803 B | 1.83 s | 362 MB | −16.0 LUFS / −4.6 dBTP |

Crop geometry recorded per render (fractions of the source frame): 9:16 centred `x=0.3418 w=0.3164`, 16:9 full frame, 1:1 left `w=0.5625`. This is deterministic geometry — **no face or subject tracking is involved**.

### 3.3 Batch export measurements

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
6. **ASR token parsing (found once whisper.cpp was installed).** The adapter passed `-ml 1`, which made whisper.cpp emit one token per transcription item (229 "segments" for a 15-sentence file), and it joined every token with a space, producing `Mot ivation` and visible control tokens such as `[_TT_239]`. Fixed by removing `-ml 1`, filtering `[_…]`/`<|…|>` tokens, and merging subword tokens using whisper's leading-space word boundary. The ASR project now yields 17 segments → 15 clean sentences with native word timings, and `B3-ASR-PIPELINE` proves the recognised transcript drives highlights/captions/render.

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

ASR accuracy (needs the local whisper.cpp build; install with `scripts/install_whisper_cpp.sh`):

```bash
# Builds its own fixture and measures WER against the known script
PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_asr_wer.py
# Reuse an existing fixture directory (source.mp4 + speech.srt)
PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_asr_wer.py --fixture /path/to/fixture
```

Reports are written to `benchmarks/data/engine_b/wer_<id>.json`.

Long-source matrix (builds the fixture itself, so it takes minutes of wall time):

```bash
PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_longrun.py --minutes 5
PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_longrun.py --minutes 60 --keep
```

Reports are written to `benchmarks/data/engine_b/long_<id>_<N>m.json`. Delete the
`--keep` fixture and project afterwards; both are large.

---

## 6. Engine A regression (must stay independent)

Executed with the Engine B code loaded: `PYTHONPATH=backend backend/.venv/bin/python scripts/benchmark_suite.py --quick --json`

| Run | Case | Result | Measured |
|---|---|---|---|
| `9bd9e75d5312` | `VC-60S` (16:9, 30 fps) | **PASS** | wall 16.464 s, output 69.49 s, ratio 0.2369, peak app RSS 725.9 MB, `1280×720` H.264/AAC export validated |

Engine A tables (`projects`, `jobs`) and endpoints are unchanged; Engine B adds `clip_*` tables and `/api/clip/*`. The only shared changes are the FFmpeg/memory helpers, `ensure_schema()` registration, the sequential-job guard (now counts either engine's active job) and the `/api/system` summary block.

---

## 6.1 Long-source matrix (A1–A5, measured)

`scripts/engine_b_longrun.py --minutes N` builds a real local source of the requested
length, then drives the same HTTP API as the acceptance harness. The script repeats the
15-sentence narration in numbered chapters so sentences stay distinct and the SRT stays
exact; each run uploads the file fresh and records upload, analysis, SRT import, highlight
selection and one render of a clip **starting in the last third** of the timeline (deep
seek). Every value below was produced by that run — nothing is extrapolated.

| Target | Source | Sentences | Upload | Analyze (peak RSS) | Highlights | Deep-end render (peak RSS) | Output |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 min | 68.55 s | 15 | 0.03 s / 1.56 MB | 0.46 s / 77 MB | 0.02 s (2 clips) | 1.56 s / 377 MB | 28.56 s, 919,513 B, −16.2 LUFS |
| 5 min | 344.19 s | 75 | 0.04 s / 7.83 MB | 1.81 s / 174 MB | 0.06 s (5 clips) | 2.30 s / 359 MB | 44.39 s, 1,447,304 B, −15.9 LUFS |
| 15 min | 965.24 s | 210 | 0.07 s / 21.92 MB | 4.97 s / 233 MB | 0.26 s (5 clips) | 2.03 s / 371 MB | 38.59 s, 1,223,537 B, −16.2 LUFS |
| 30 min | 1864.85 s | 405 | 0.14 s / 42.35 MB | 9.79 s / 247 MB | 0.82 s (5 clips) | 2.23 s / 384 MB | 38.59 s, 1,248,259 B, −16.2 LUFS |
| 60 min | 3733.12 s | 810 | 0.24 s / 84.78 MB | 18.51 s / 452 MB | 2.88 s (5 clips) | 2.35 s / 415 MB | 44.77 s, 1,446,847 B, −15.8 LUFS |

Reports: `benchmarks/data/engine_b/long_cc1341298172_1m.json`,
`long_46fd0657910e_5m.json`, `long_44d05b39c4b9_15m.json`,
`long_49293b9eaf59_30m.json`, `long_b9fc947aaa5d_60m.json`.

What each run asserted (all true, hence 6/6 PASS per run):

- fixture duration ≥ 90 % of target, ≥ 1 audio stream, SRT exists;
- upload `200` and stored SHA-256 equals the uploaded file's SHA-256;
- analysis job `succeeded` with envelope windows ≈ 1/second of source (37,332 at 60 min) and silence gaps = sentences − 1;
- SRT import returns exactly one segment per sentence, monotonic, last cue ≤ source duration;
- highlights are non-overlapping and fill the requested count when the timeline permits (5 for the ≥5-minute sources; the 1-minute source legitimately fits only 2 at the 20/30 s targets and reports a shortfall); for the ≥5-minute sources at least one clip starts in the second half;
- the deep-end render validates (`exists, resolution_ok, video_codec_h264, audio_codec_aac, duration_ok, audio_present, size_ok, av_sync_ok`).

Honest reading of these numbers:

1. **Analysis scales roughly linearly** (0.46 s / 1.81 s / 4.97 s / 9.79 s / 18.51 s for 68 s → 62 min) and stays under 0.5 % of source length at 60 min.
2. **Highlight selection is transcript-driven**, so it grows with sentence count (0.02 → 2.88 s) rather than decode cost.
3. **Render cost is clip-length bound, not source-length bound** (1.56–2.35 s for 29–45 s outputs), because FFmpeg seeks to the clip window. Deep seeks at 31 and 62 minutes cost the same as a 5-minute seek within measurement noise.
4. **Memory is modest but not flat:** analysis peaks at 452 MB for the hour-long file; render peaks 359–415 MB. This is sampled process-tree RSS, not the kernel high-water mark.
5. **Synthetic source caveat:** colour video with a tone bed compresses to 84.78 MB for 62 minutes. A real 60-minute 720p/1080p recording will be far larger to decode and seek; expect higher upload time and possibly slower analysis/render. Those real-footage numbers are **NOT_RUN**.

An earlier 5-minute run (`long_f804a9d06565_5m.json`) used a stopwatch that started after the
job had already finished, so its analyze time read `0.0 s`; it was discarded and re-run with
a corrected timer (`long_46fd0657910e_5m.json`, cited above).

---

## 7. NOT_RUN / unverified (honest)

| Item | Status | Why |
|---|---|---|
| Human-speech WER / accents / noise / multi-speaker / fast speech | **NOT_RUN** | Only clean single-speaker synthetic TTS was measured; no human speech corpus or independent ground-truth transcripts exist here |
| Word-timestamp fidelity vs human reference | **NOT_RUN** | Timings are native whisper token offsets and monotonic, but no independently aligned reference exists to score them |
| Highlight quality vs human judgement | **NOT_RUN** | No reference ratings; only groundedness, inspectability and non-overlap are asserted |
| Real-footage long sources (broadcast/phone video at 5–60 min) | **NOT_RUN** | A1–A5 are measured (§6.1) but on synthetic colour video + TTS; decode/seek cost of real 720p/1080p footage is not measured |
| Real-footage behaviour in general | **NOT_RUN** | Synthetic fixture: static scene, no camera motion, no noise/music bed, single speaker |
| GPU / Metal utilisation | **NOT_RUN** | Not reliably sampleable without privileged `powermetrics` |
| `/usr/bin/time -l` max RSS | **NOT_RUN** | Peaks are sampled process-tree RSS, not the kernel high-water mark |
| Packaged-app Engine B | **NOT RUN** | The desktop bundle was not rebuilt for Engine B in this session; verification is dev-server + API/harness only |
| Browser click-through of the Engine B UI | **NOT RUN** | No connected browser session; the frontend builds (`tsc -b && vite build` PASS) and the SPA route returns `200`, but no automated interaction was recorded |
| A/V drift beyond duration delta | **NOT RUN** | Validation compares stream durations (< 0.1 s); no per-frame sync analysis |

---

## 8. Limitations that affect interpretation

1. **Synthetic source.** Colour bars + tone, static scene. Scene-cut detection reports 0 because there are no cuts; that is the correct result, not a failure.
2. **No standalone `ffprobe`.** All probing uses FFmpeg stderr parsing, recorded as `probe_source=ffmpeg_fallback` on every source and render.
3. **Import and ASR are separate paths.** `B3-IMPORT` proves the subtitle import path; `B3-ASR` proves local whisper.cpp on clean synthetic TTS. Neither proves accuracy on human recordings.
4. **Two clips from one 67.5 s source.** The shortfall message is reported when fewer non-overlapping windows fit than requested; the harness asserts that behaviour rather than forcing extra clips.
5. **Cancellation timing.** `B9-CANCEL` succeeded because the cancel flag landed while the job was live; on very short jobs a cancel can still arrive after completion, which is reported as a WARNING with the observed terminal status, never as PASS.
6. **Memory numbers are per-job sampled peaks** on a shared 8 GB machine with background load (global memory 83.6 % during the earlier run), not isolated benchmarks.
7. **Long-source fixtures are synthetic.** The 1/5/15/30/60-minute files are spoken narration over `testsrc2` colour video. They exercise the real code paths and disk I/O, but their video is trivially cheap to decode and their file sizes (1.56 MB → 84.78 MB) are far below real footage of the same length. The measured long-source numbers are a lower bound on real-media cost, not a prediction of it.
8. **WER is measured on TTS, not people.** The 1.01 % figure comes from the same script that generated the audio; it verifies the adapter, token merging and timestamps, not accent/noise robustness.
9. **ASR model.** `base.en` is English-only. Other languages are accepted by the API but were not measured on this machine.
