# Change Record — Engine B (AI Auto-Clip Studio)

**Date:** 2026-11-15
**Type:** additive feature (new engine), no change to Engine A behaviour
**Rollback point:** commit `f629237` ("Add M2 hardware benchmark suite, measured Engine A runs, and reports")

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
| New scripts | `scripts/engine_b_e2e.py` (acceptance harness), `scripts/install_whisper_cpp.sh` (optional local ASR) |
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
| Engine B acceptance | `PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_e2e.py` | 14 PASS / 0 FAIL / 1 NOT_RUN (ASR) — see `docs/TEST_REPORT_ENGINE_B.md` |
| Engine A regression | `PYTHONPATH=backend backend/.venv/bin/python scripts/benchmark_suite.py --quick --json` | PASS (`9bd9e75d5312`) |
| Frontend build | `cd frontend && npm run build` | PASS (`tsc -b && vite build`) |
| Live server | `curl /health`, `/api/clip/capabilities`, `/clip` | 200, ASR `available:false` with reasons, SPA route 200 |

Artifacts: `benchmarks/data/engine_b/e2e_*.json`, `benchmarks/data/runs/9bd9e75d5312.json`,
`benchmarks/reports/benchmark_9bd9e75d5312_*.json|html`.

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
- Long-duration matrix (5/15/30/60 min) not executed.
- Packaged desktop app not rebuilt for Engine B in this session.
- No automated browser click-through of the Engine B UI.
