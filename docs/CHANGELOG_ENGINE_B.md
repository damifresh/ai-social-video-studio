# Change Record — Engine B (AI Auto-Clip Studio)

**Date:** 2026-11-15 (Engine B), 2026-11-17 (ASR + long-source follow-ups)
**Type:** additive feature (new engine), no change to Engine A behaviour
**Rollback point:** commit `f629237` ("Add M2 hardware benchmark suite, measured Engine A runs, and reports")
**Last verified commit:** `47f1d1e` ("Add measured 1/5/15/30/60-minute Engine B long-source matrix") — the ASR follow-up (§8) sits on top of it; revert that commit to return to `47f1d1e`. Revert the long-source follow-up (§7) to return to `88e16ab` without losing Engine B.

This file is the change record required by the delivery process: what was added, what was
touched in shared code, how to verify it, and how to back it out.

---

## 1. Scope

Engine B turns one long recording into short, captioned, platform-sized clips, fully
locally. Engine A (topic → generated video) is untouched in behaviour.

| Area | Change |
|---|---|
| New package | `backend/app/clip/` — `models.py`, `store.py`, `probe.py`, `audio.py`, `transcribe.py`, `highlights.py`, `metadata.py`, `render.py`, `jobs.py`, `api.py` |
| New API | `/api/clip/*` (projects, source upload, analyze, transcribe, transcript import/edit, highlights, clip edit/render, batch export, job status/cancel) |
| New tables | `clip_projects`, `clip_sources`, `clip_candidates`, `clip_renders`, `clip_jobs` (additive only) |
| New UI | `frontend/src/pages/ClipStudio.tsx`, `ClipProject.tsx`; routes `/clip`, `/clip/:id`; nav entry "Auto-Clip Studio" |
| New client | `clipApi` + Engine B types in `frontend/src/lib/api.ts` |
| New scripts | `scripts/engine_b_e2e.py` (acceptance harness), `scripts/engine_b_asr_wer.py` (ASR accuracy harness), `scripts/engine_b_longrun.py` (1/5/15/30/60-minute matrix), `scripts/install_whisper_cpp.sh` (local ASR install/build) |
| New docs | `docs/ENGINE_B.md`, `docs/TEST_REPORT_ENGINE_B.md`, this file |
| New data dir | `data/clip_projects/<id>/{source,analysis,clips,exports,logs,tmp}` (gitignored) |

## 2. Shared-code touches (each additive)

| File | Change | Why it cannot break Engine A |
|---|---|---|
| `backend/app/main.py` | includes `clip_router`, calls `recover_interrupted_clip_jobs()` at startup | new router path prefix; recovery only touches `clip_jobs` |
| `backend/app/db/database.py` | registers `app.clip.models` before `create_all` | `create_all` is additive; no Engine A table/column is altered |
| `backend/app/core/config.py` | adds `CLIP_PROJECTS_DIR`, `clip_max_upload_bytes`, `clip_max_duration_sec`, `clip_chunk_bytes`; creates the dir | defaults only; Engine A paths unchanged |
| `backend/app/api/projects.py` | `_running_job()` also consults `ClipJob` | Engine A job lookup keeps first priority; the extra query only applies when no Engine A job is active |
| `backend/app/api/system.py` | `/api/system` gains a `clip` block | new key only; existing keys unchanged |
| `.gitignore` | ignores local `logs/` | no source impact |

Engine A's `jobs.project_id` is `NOT NULL`, so Engine B deliberately does **not** reuse the
`jobs` table; it introduced its own `clip_jobs` with the same conventions (stage, progress,
message, error, peak memory, cancel flag, terminal statuses).

## 3. Behavioural decisions worth recording

1. **No ASR claim.** whisper.cpp is capability-gated. When absent, `/api/clip/capabilities`
   says so with reasons, the transcribe endpoint returns 503, and the UI points at
   SRT/VTT import. No transcript is ever synthesized or guessed.
2. **No tracking claim.** Reframing is deterministic geometry: centred/edge cover-crop or a
   manual rectangle expressed as fractions of the source frame. The UI and docs state that
   no face or subject tracking exists.
3. **No LLM copy.** Titles/hooks/captions/hashtags come from `transcript-template/v1` and
   every field is verified as literally present in the clip's own transcript.
4. **One source per project.** Replacing a source clears the previous source, analysis,
   transcript and clip candidates because their timings refer to the old file. The
   destructive default is explicit (`replace_existing=true`) and `false` returns 409.
5. **Sequential heavy jobs across both engines.** A clip job cannot start while an Engine A
   job is running and vice versa; the guard returns 409 with the blocking job's type.
6. **Honest validation.** Renders are probed after writing; A/V duration delta, resolution,
   codecs, size and audio presence are recorded per output. Batch export lists failed items
   individually instead of hiding them.
7. **No duplicate services.** Engine B reuses the existing FFmpeg resolution, memory guard,
   SQLite session factory and frontend design system.

## 4. Verification performed

| Check | Command | Result |
|---|---|---|
| Backend imports / route count | `PYTHONPATH=backend backend/.venv/bin/python -c "from app.main import app; print(len(app.routes))"` | ok, 75 routes |
| Engine B acceptance | `PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_e2e.py` | 16 PASS / 0 FAIL / 0 NOT_RUN — see `docs/TEST_REPORT_ENGINE_B.md` |
| Engine B ASR accuracy | `PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_asr_wer.py` | PASS on clean synthetic TTS: WER 1.01 %, 15/15 sentences, native word timings (`wer_971ca893acbe.json`) |
| Engine B long sources | `PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_longrun.py --minutes {1,5,15,30,60}` | 6/6 PASS in each run; analysis 0.46 → 18.51 s, highlights 0.02 → 2.88 s, deep-end render 1.56–2.35 s, all validated |
| Engine A regression | `PYTHONPATH=backend backend/.venv/bin/python scripts/benchmark_suite.py --quick --json` | PASS (`9bd9e75d5312`) |
| Frontend build | `cd frontend && npm run build` | PASS (`tsc -b && vite build`) |
| Live server | `curl /health`, `/api/clip/capabilities`, `/clip` | 200, ASR `available:true` (`whisper-cli`, `ggml-base.en.bin`), SPA route 200 |

Artifacts: `benchmarks/data/engine_b/e2e_*.json`, `benchmarks/data/engine_b/long_*_{1,5,15,30,60}m.json`, `benchmarks/data/runs/9bd9e75d5312.json`,
`benchmarks/reports/benchmark_9bd9e75d5312_*.json|html`.

The long-source fixtures and clip projects were deleted after the runs (temporary paths
under the OS temp dir and `data/clip_projects/`), because they occupy hundreds of MB. The
JSON reports remain the evidence. An earlier 5-minute report
(`long_f804a9d06565_5m.json`) was discarded: its analyze stopwatch started after the job had
finished and recorded `0.0 s`, so the run was repeated with a corrected timer
(`long_46fd0657910e_5m.json`).

## 5. Rollback

Engine B is additive, so rollback is a revert of this commit:

```bash
git revert <engine-b-commit>     # or: git checkout f629237 -- .
rm -rf data/clip_projects        # optional: delete Engine B user data
```

If you only want to disable it without reverting, remove the `include_router(clip_router)`
line in `backend/app/main.py`; the clip router then disappears and Engine A continues to
serve `/api/projects/*` normally. The `clip_*` tables may remain in SQLite without effect.

## 6. Known gaps at this commit

- whisper.cpp not installed → ASR path implemented but unverified (`NOT_RUN`), no WER claim.
- Standalone `ffprobe` absent → FFmpeg stderr probing (`probe_source=ffmpeg_fallback`).
- No human highlight reference → ranking is inspectable but not quality-scored.
- Long-duration A1–A5 are measured on **synthetic** sources; real 720p/1080p footage of the same length is not measured.
- Packaged desktop app not rebuilt for Engine B in this session.
- No automated browser click-through of the Engine B UI.

## 7. Follow-up commit — long-source evidence

Added after `88e16ab` without changing Engine B behaviour:

| Change | Detail |
|---|---|
| `scripts/engine_b_longrun.py` | builds a real synthetic source of N minutes, then measures upload → analyze → SRT import → highlights → deep-end render through the HTTP API; writes `benchmarks/data/engine_b/long_<id>_<N>m.json` |
| Reports | `long_cc1341298172_1m`, `long_46fd0657910e_5m`, `long_44d05b39c4b9_15m`, `long_49293b9eaf59_30m`, `long_b9fc947aaa5d_60m` — 6/6 PASS each |
| Docs | `TEST_REPORT_ENGINE_B.md` §6.1, `M2_HARDWARE_BENCHMARK.md` §4/§9/§13/§14/§15, `ENGINE_B.md`, `README.md`, `DELIVERABLES.md`, `HARDWARE_LIMITATIONS.md`, `TEST_REPORT.md` |
| Rollback | `git revert <long-source-commit>` returns to `88e16ab`; no schema/code change |

Fixture files and the generated clip projects were deleted after the runs (they totaled
~400 MB); the JSON reports are the retained evidence. The earlier 5-minute report with a
broken analyze timer (`long_f804a9d06565_5m.json`) was discarded and is not part of the commit.

## 8. Follow-up commit — local ASR installed, measured and wired

Added after `47f1d1e`. No Engine A behaviour change; no schema change.

| Change | Detail |
|---|---|
| ASR install | `scripts/install_whisper_cpp.sh --check` now exits 0. `cmake` 4.4.5 was installed into `backend/.venv` with `uv pip install --python backend/.venv/bin/python cmake` (no Homebrew needed), then the script cloned/built `whisper.cpp` and downloaded `ggml-base.en.bin` (147,964,211 B). Resolved as `whisper-cli` + `models/whisper.cpp/models/ggml-base.en.bin`; `/api/clip/capabilities` → `available: true` |
| Bug fix — token parsing (`backend/app/clip/transcribe.py`) | The adapter passed `-ml 1`, so whisper.cpp emitted one token per item (229 "segments" for a 15-sentence file) and every token was space-joined, producing `Mot ivation` and displaying control tokens like `[_TT_239]`. Fixes: removed `-ml 1`; filter `[_…]` and `<|…|>` control tokens; merge subword tokens using whisper's leading-space word boundary; join CJK languages without spaces |
| New harness `scripts/engine_b_asr_wer.py` | Runs the app's real `transcribe()` on the fixture's 16 kHz audio and scores sentence text against the known script with a Levenshtein S/W/D/I breakdown, plus boundary deltas and RTF/peak RSS. Writes `benchmarks/data/engine_b/wer_<id>.json` |
| Report `benchmarks/data/engine_b/wer_971ca893acbe.json` | 67.52 s clean synthetic TTS: ASR 1.79 s, RTF 0.0265, peak 446.2 MB, 17 segments → 15 sentences, 199 words, native/monotonic timings, **WER 1.01 %** (2 S / 0 D / 0 I; `pick→take`, `behaviour→behavior`), 14/15 exact text, 14/15 boundaries within 0.75 s (median delta 0.32 s) |
| E2E harness (`scripts/engine_b_e2e.py`) | `B3-ASR` now asserts segments/sentences/word timing/monotonicity **and** reports WER. New `B3-ASR-PIPELINE` builds a project that never imports an SRT: whisper transcript → 1 highlight → 9:16 render with 9 cues, validation ok. Suite is now 16 cases |
| Latest E2E report | `benchmarks/data/engine_b/e2e_11d49374a4fb_20261117T081352Z.json` — **16 PASS / 0 FAIL / 0 NOT_RUN**, 37.1 s |
| Docs | `README.md`, `docs/TEST_REPORT_ENGINE_B.md` (§3.1 ASR, §4 case table, §7 NOT_RUN, §8 limitations, §11 reproduction), `docs/M2_HARDWARE_BENCHMARK.md` (§5 accuracy, §13/14/15), `docs/ENGINE_B.md` (capability + §6 install + §7 limitations), `docs/DELIVERABLES.md`, `docs/HARDWARE_LIMITATIONS.md`, `docs/TEST_REPORT.md`, this file |

**Remaining honest gaps after this commit:**

- ASR accuracy is measured only on clean single-speaker macOS TTS with the script as
  reference. Human speech, accents, noise, multi-speaker and fast speech are **NOT_RUN**;
  the 1.01 % must not be quoted as a general WER. The model is English-only.
- Word-timestamp fidelity has no independent human-aligned reference.
- Highlight quality still has no human ratings.
- Long-source matrix fixtures are synthetic colour video; real-footage decode/seek cost
  unmeasured.
- Packaged app not rebuilt for Engine B; no automated browser click-through.

**Rollback:** `git revert <asr-commit>` returns to `47f1d1e`. The ASR binary/model live
under gitignored `models/whisper.cpp/`, so reverting code leaves the local install in
place; `WHISPER_BIN`/`WHISPER_MODEL` may also be unset to gate ASR off without deleting it.
