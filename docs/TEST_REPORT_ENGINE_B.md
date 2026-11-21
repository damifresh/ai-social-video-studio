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

**Director/prompter add-on (separate 2026-11-18 verification, not part of the original 16-case run):** `POST /api/clip/prompt/parse` returned `funny tone; for TIKTOK; focus: habits; avoid: jargon; around 15s`, and `POST /highlights` with that prompt stored the same brief in job meta and on every candidate, each with a `brief_fit` component. The director is now fully deterministic: `prompt.py` parses the brief and `direction.py` builds the plan (preset, target durations, one-clip assembly metadata); no model, network call or desktop LLM bridge is involved. In opt-in one-clip mode the plan records 2–6 ordered transcript sentence ranges with narrative roles; silence gaps and scene cuts are boundary/support evidence, transcript ranges remain authoritative, and `render_assembly()` concatenates them into one render-ready MP4. The full backend suite passes (51 tests, including grounded copy, UI-duration precedence, assembly boundary evidence and a real FFmpeg two-scene render). The Electron UI smoke (25/25) verifies the built-in presets, local-director status, opt-in one-clip toggle, transcript import, deterministic director preview, generated-clip audit metadata, one-video job/candidate flags, ordered scene metadata and a rejected boundary patch. The rebuilt installed app was also checked through CDP for the prompter and one-clip toggle on the category page and in a project. Real API runs confirmed the plan in job `meta`, brief/weights/components/grounded copy in `score_json`, and a one-video candidate with a `0 → 20 s` timeline and two ordered scenes.

**Follow-up (2026-11-19, multi-source combine, Target Duration and Export fix):** the suite grew to 49 tests with `test_clip_combine.py` and `test_clip_captions.py` (transition math, fade/cut graphs, ordered-source fallback, real FFmpeg two-/three-source renders, proportional target fitting with validated 5 s fade/cut trims and over-long-target rejection, per-source SRT import, shifted combine cue timing and caption metadata, and the Export regression: combine dispatch to `render_combine()`, a real `_render_one()` combine render and batch-export manifest metadata). The reported Export failure was reproduced as `ValueError: Assembly segments must be non-overlapping`: combine segments are per-source full ranges but were sent to the single-source transcript assembler. `_render_one()` now dispatches `source_combine` to `render_combine()` using stored paths/order/transition metadata; an isolated TestClient run exported a validated 3.42 s crossfade MP4 and a 4.02 s cut MP4 from two uploaded sources. The Electron UI smoke is 25/25 and additionally covers the default-on Captions and Transitions toggles, multi-source upload/reorder, a 5 s Target Duration applied to both cut + crossfade combine renders, and a successful **Export** of the combined candidate; the rebuilt installed app passed the same 25 checks (`PACKAGED_UI_PASS`). The Captions toggle is on by default on both prompter screens, persists in `settings_json["burn_captions"]`, seeds new transcript candidates, and bulk-updates both transcript and `source_combine` candidates (marking changed ones stale). A combined MP4 is now subtitled from each source's own SRT/VTT or local ASR transcript, with cues clipped at crossfades and shifted onto the combined timeline; no subtitle text is invented. The per-clip burn-in checkbox remains an override. See `ENGINE_B.md` §§ B5a and B7 and `TEST_REPORT.md`.

**Follow-up (2026-11-19, caption synchronization):** the reported desync had two verified causes. First, `build_ass()` emitted SRT/VTT-style centisecond-invalid timestamps (`00:00:00.500`, 3 decimals); libass silently dropped every Dialogue line, so burned-in captions were absent or mistimed in the MP4. A direct FFmpeg frame probe of an app-generated ASS file showed zero caption pixels across the cue window; after switching to `H:MM:SS.cc` centiseconds, pixels appeared only inside the cue. Second, `caption_segments()` redistributed a whole sentence over a clipped clip range, so captions showed words spoken before the clip began or after it ended. It now groups word-level transcript timings (native ASR or proportional words from timed SRT/VTT), and combine crossfades trim cue text to the words still audible on each side of the fade midpoint. `backend/tests/test_caption_sync.py` adds 7 regressions (ASS format, end-to-end burned-in visibility window, clipped word alignment, crossfade word trimming); the full suite was **56 PASS** at that point, frontend build, dev smoke (25/25, including a playable rendered final-video preview check) and the rebuilt installed app's packaged smoke (25/25) all passed. See `ENGINE_B.md` § B5.

**Follow-up (2026-11-19, short-source transcript-grounded assembly):** the reported `ValueError: Source is too short for transcript-grounded assembly` was reproduced when a 30 s SRT was paired with a 2 s source; the render-time variant was `ValueError: Assembly segment extends outside the source duration`. `_job_highlights()` now passes the uploaded source's real `duration_sec` into `highlights.generate(..., single_clip=True)`. `highlights._limit_assembly_to_source()` clamps sentence, word, silence-gap and scene-cut ranges and the target to that duration, keeps `clamped_to_source_duration` plus a notice in `assembly`, and falls back to one grounded scene when only one usable sentence remains rather than raising. `jobs._render_one()` independently clamps legacy assembled segments before `render_assembly()`. Two new regressions in `backend/tests/test_clip_direction.py` verify the clamped four-cue case (`source_duration=3.0`) and a single 2 s sentence; copy remains grounded in both. Full suite after the change: **51 PASS** (`PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests`, `Ran 51 tests ... OK`). The dev smoke fixture for the final preview was shortened to 2 s and passed 25/25, so the render-time clamp is exercised end to end without altering the one-candidate, preview, combine or caption checks. The rebuilt installed app was then rechecked through the packaged smoke: 25/25 PASS (`deliverables/ui_smoke_packaged.json`).

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

## 6c. Packaged desktop app (rebuilt 2026-11-18)

`scripts/build_desktop.sh` was rerun with Engine B and a pruned whisper.cpp runtime
(`build/bin/` CLI + dylibs and `models/ggml-base.en.bin`, ~150 MB; CMake tree and source
excluded). Outputs: `.dmg` 342 MB, `.zip` 319 MB. The app was launched, the backend's
loopback port was read from the app's own log, and `scripts/engine_b_packaged_check.py`
drove a 5-sentence synthetic source (23.36 s) through the real packaged API:

| Check | Result |
|---|---|
| `/health`, `/api/clip/capabilities` | `ok=true`, `whisper=true`, ASR `available: true` with paths inside `*.app/Contents/Resources/runtime/models/whisper.cpp/` |
| Upload → analyze → transcribe | 200 / succeeded / succeeded — 6 segments → 5 sentences, `native` word timings, 369 MB transcription peak |
| Highlights → 9:16 render | 1 clip, render succeeded, 9 caption cues, 720p H.264/AAC validation `ok=true` (all 8 flags) |
| Harness total | **11/11 checks PASS**, 3.42 s — `benchmarks/data/engine_b/packaged_a3af06a18580.json` |

This verifies Engine B's backend and ASR in the packaged app. It does **not** verify the
Electron UI by click-through (no browser automation session was available).

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
| Packaged-app Engine B backend | **PASS** | Rebuilt 2026-11-18; `scripts/engine_b_packaged_check.py` drove a real 5-sentence source through the app's loopback backend: upload/analyze/ASR (6 segments → 5 sentences, native timings)/highlights/9:16 render, 9 cues, validation ok, 11/11 checks (`packaged_a3af06a18580.json`) |
| Packaged-app Engine B UI click-through | **NOT RUN** | No connected browser session; the Electron window was launched and its backend/API verified, but no automated UI interaction was recorded |
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
