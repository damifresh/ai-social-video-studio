# Engine B — AI Auto-Clip Studio

Engine B turns one long recording into short, captioned, platform-sized clips. It runs
entirely on this machine: no cloud inference, no paid APIs, no uploads off-device.

It is a **separate engine** from Engine A (topic → generated video). They share only
infrastructure (SQLite session, FFmpeg resolution, memory guard, job serialisation) and
never share tables, files or job rows.

- UI: **Auto-Clip Studio** (`/clip`) and project workspace (`/clip/:id`)
- API: `/api/clip/*`
- Code: `backend/app/clip/`
- Data: `data/clip_projects/<project-id>/{source,analysis,clips,exports,logs,tmp}`

---

## 1. Capability summary (what is real, what is not)

| Capability | Status | Evidence |
|---|---|---|
| Upload MP4 / MOV / MKV / WebM, original bytes preserved | Working | SHA-256 of stored file equals SHA-256 of uploaded file for all four containers (`B1-UPLOAD`) |
| Stream metadata (duration, size, fps, codecs, channels) | Working | ffprobe when present, otherwise FFmpeg stderr parsing (`B1-METADATA`) |
| Audio extraction, loudness envelope, silence gaps, scene cuts | Working | `B2-ANALYZE` measured on a 67.5 s source; long-source runs measured 68.55 s → 3733.12 s (37,332 envelope windows, 809 silence gaps at 62 min) |
| Long-source ingest → highlights → render | Working (synthetic media) | A1–A5 (1/5/15/30/60 min) each 6/6 PASS: analysis 0.46 → 18.51 s, highlights 0.02 → 2.88 s, deep-end render 1.56–2.35 s, all validated. Real-footage long sources **NOT_RUN** |
| Transcript from local whisper.cpp | **Implemented, NOT verified here** | Binary and GGML model are not installed in this environment; capability gating returns `available:false` with reasons (`B3-ASR` = NOT_RUN) |
| Transcript import (SRT / VTT / plain text) | Working | `B3-IMPORT` (15 cues, monotonic, timings labelled "file", word timings labelled "estimated") |
| Transcript editing in-app | Working | `PUT /api/clip/projects/{id}/transcript` rebuilds sentence boundaries |
| Highlight scoring with auditable weights | Working | `B4-HIGHLIGHTS`: every clip stores per-component raw/weight/contribution + reason |
| Non-overlapping, sentence-aligned clip windows | Working | Overlap ≤ 0.2 s tolerance; shortfall reported instead of duplicating spans |
| Render 720p H.264/AAC in 9:16, 16:9, 1:1 | Working | `B5-RENDER`: probes show 720×1280, 1280×720, 720×720; validation includes A/V sync |
| Captions burned per clip | Working | ASS cues generated from the clip's own transcript sentences (28 cues in the measured 44 s clip) |
| Manual crop / reframe | Working | Centred cover-crop or manual rect; deterministic geometry only |
| Automatic face/subject tracking | **Not implemented** | No model is bundled, no tracking is claimed in UI or API |
| Loudness normalisation, optional ducked music | Working | `loudnorm=I=-16:TP=-1.5:LRA=11` + sidechain ducking; measured ≈ −16 LUFS |
| Transcript-grounded title/hook/caption/hashtags | Working | Deterministic `transcript-template/v1`; each field verified as a substring/token of the clip text |
| Batch export with per-item manifest | Working | `B6-BATCH`: manifest lists measured duration, size, validation, loudness, hashtags per clip |
| Cancellation and restart recovery | Working | `B9-CANCEL` (terminal `canceled`, tmp cleaned), `B10-RECOVERY` (in-flight → `interrupted`) |
| WER / ASR accuracy | **NOT measured** | Requires an installed ASR build and an independent ground-truth transcript |

Everything above was measured on the same machine; see
[`TEST_REPORT_ENGINE_B.md`](TEST_REPORT_ENGINE_B.md).

---

## 2. Feature specifications (goal → acceptance)

Each block lists the required spec dimensions: goal, engine, behaviour, acceptance
criteria, constraints, UI, API/backend, documentation.

### B1 · Media ingest and probing

- **Goal:** accept the containers creators actually have without altering the source.
- **Engine:** B (`/api/clip/projects/{id}/source`).
- **Behaviour:** streamed upload in 4 MB chunks with a running SHA-256; extension gate
  (`.mp4`, `.mov`, `.mkv`, `.webm`); probe; reject empty files, files without a video
  stream, files without audio, files over 8 GB or 3 h. The stored file is never
  transcoded or rewritten, so it can be re-downloaded byte-identical.
- **Acceptance:** all four containers upload; stored SHA-256 equals uploaded SHA-256;
  probe returns duration/width/height/fps/codecs; unsupported container → 415.
- **Constraints:** one source per clip project. Uploading again requires
  `replace_existing=true` (default) and clears the previous source, analysis, transcript
  and clips, because their timings refer to the old file. `replace_existing=false`
  returns 409.
- **UI:** step 1 panel — upload/replace, inline video preview, metadata grid, hash.
- **API/backend:** `POST /api/clip/projects/{id}/source`, `GET .../source/file`,
  `GET /api/clip/sources/{sid}/file`; `app/clip/api.py`, `app/clip/probe.py`.
- **Docs:** this section + `TROUBLESHOOTING.md` (no-audio/unsupported container).

### B2 · Structural analysis

- **Goal:** give the scorer real audio/video structure without ML.
- **Engine:** B (`analyze` job).
- **Behaviour:** mono 16 kHz WAV extraction; streamed RMS/peak envelope at 0.1 s
  windows (flat memory, 8 kHz decode); `silencedetect` gaps (noise −32 dB, ≥0.35 s);
  downscaled scene-cut scan (2 fps, 320 px wide, threshold 0.32).
- **Acceptance:** job succeeds; artifact JSON contains envelope windows, gaps and cuts;
  a source without usable audio fails with a clear message.
- **Constraints:** scene detection is approximate by construction (documented sampling);
  no GPU, no ML.
- **UI:** step 1 action + summary counters in the header.
- **API/backend:** `POST /api/clip/projects/{id}/analyze`, `GET /api/clip/projects/{id}`;
  `app/clip/audio.py`, `app/clip/jobs.py`.
- **Docs:** this section, thresholds listed above.

### B3 · Transcription

- **Goal:** produce word/sentence timings locally, or accept a transcript the user already has.
- **Engine:** B (`transcribe` job, `transcript/import`, `transcript` PUT).
- **Behaviour:**
  - whisper.cpp path: capability-gated (`WHISPER_BIN` / `models/whisper.cpp/build/bin/whisper-cli`,
    `WHISPER_MODEL` / `models/whisper.cpp/models/ggml-*.bin`). Runs with JSON token offsets;
    falls back to segment-only JSON; word timings are marked `native` only when the build
    emits token offsets, otherwise `estimated` and labelled as a display approximation.
  - import path: SRT/WebVTT parsed with timings clamped to the source duration and forced
    monotonic; sentences rebuilt from punctuation/pauses; plain text is accepted but
    explicitly marked `timing: "none"` and cannot drive timed clips.
  - edit path: segments validated (`end > start`, non-empty), sentences rebuilt.
- **Acceptance:** import of a 15-cue SRT yields 15 monotonic cues within duration; ASR
  path assertion only runs when a verified backend exists, otherwise the case is NOT_RUN.
- **Constraints:** no ASR → no invented transcript. No cloud fallback. No WER claim.
- **UI:** step 2 — capability banner with reasons, transcribe button (disabled without a
  backend), file import, paste import, editable cue list with save.
- **API/backend:** `POST /api/clip/projects/{id}/transcribe`, `GET/PUT .../transcript`,
  `POST .../transcript/import`; `app/clip/transcribe.py`.
- **Docs:** this section + `models/README.md` + `scripts/install_whisper_cpp.sh`.

### B4 · Highlight detection

- **Goal:** suggest self-contained clip moments, transparently.
- **Engine:** B (`highlights` job).
- **Behaviour:** sentences snapped into nearby silence (≤0.5 s) without overlapping
  neighbours; windows built per requested duration between 80 % and 130 % of target and
  scored on eight components: hook, insight, emotion, density, audio, boundary,
  completeness, novelty. Greedy non-overlapping/near-duplicate-free selection, then
  re-sorted chronologically. Each clip stores the full component table, the weights, the
  window rule and a human-readable reason.
- **Acceptance:** clips are sentence-aligned; zero overlaps beyond 0.2 s; every clip has a
  score, components and reason; titles/hooks are substrings of the clip's own text;
  shortfall is stated when fewer clips fit than requested.
- **Constraints:** heuristic clip-worthiness, not a virality predictor; no LLM; no
  reference ranking exists, so precision/recall is not claimed.
- **UI:** step 3 — duration chips 15/30/45/60/90 + custom (5–180 s, max 6 targets),
  count 1–12, per-clip score bars and reason.
- **API/backend:** `POST /api/clip/projects/{id}/highlights`,
  `GET /api/clip/projects/{id}/clips`; `app/clip/highlights.py`.
- **Docs:** weights are printed in the UI and stored per clip.

### B5 · Reframing, captions, audio, render

- **Goal:** platform-ready 720p MP4 per clip, with honest geometry.
- **Engine:** B (`render` / `batch_export` jobs).
- **Behaviour:**
  - crop: centred cover-crop by default; modes `center/left/right/top/bottom/custom`;
    custom rect is expressed as fractions of the source frame and re-derived to the target
    aspect, then clamped in-bounds.
  - scale: `scale=720:1280` (or the target) with `force_original_aspect_ratio=increase`
    followed by an exact crop, `setsar=1`, `fps` 24/25/30, `format=yuv420p`.
  - captions: ASS cues built from the clip's transcript sentences, chunked to
    `max_chars`, styled (size/position/primary/highlight/outline), burned via `subtitles`.
  - audio: `loudnorm=I=-16:TP=-1.5:LRA=11`; optional music looped/trimmed with a 0.8 s
    fade and sidechain-ducked under speech (`sidechaincompress`), mixed with `amix`.
  - encode: libx264 CRF 21, veryfast, AAC 128 kbit/s 48 kHz stereo, `+faststart`.
  - validation: existence, exact resolution, H.264, AAC, duration ±0.2 s, audio stream,
    size > 10 kB, and A/V duration delta < 0.1 s.
- **Acceptance:** three aspects validate with the checks above; measured loudness ≈ −16 LUFS.
- **Constraints:** no face/subject tracking; no optical-flow stabilisation; music must be a
  local file; output is always 720p-class (portrait 720×1280, landscape 1280×720, square 720×720).
- **UI:** per-clip editor — trim, aspect, fps, crop mode + manual rect, caption
  size/position/max chars/highlight, burn toggle, loudness toggle, music + volume,
  save & render, inline preview and download.
- **API/backend:** `POST /api/clip/clips/{sid}/render`, `PATCH /api/clip/clips/{sid}`,
  `GET /api/clip/clips/{sid}/file`; `app/clip/render.py`, `app/clip/jobs.py`.
- **Docs:** this section, exact filter graph documented here.

### B6 · Copy generation (titles, hooks, captions, hashtags)

- **Goal:** usable copy without inventing claims.
- **Engine:** B (deterministic, at highlight time; `POST /api/clip/clips/{sid}/metadata`
  to regenerate).
- **Behaviour:** `transcript-template/v1` selects the best sentence by cue words and
  length, trims at word boundaries, builds a ≤220-char caption from the first sentences,
  and derives hashtags from the clip's own frequent non-stopword tokens. `verify()` reports
  per-field whether the output is literally contained in the clip text.
- **Acceptance:** `title`, `hook`, `caption` are substrings of the clip transcript;
  every hashtag stem appears in the transcript.
- **Constraints:** no LLM, no external topic suggestions, no claims about accuracy of the
  resulting hook.
- **UI:** shown on each clip; "Regenerate copy" re-runs the templates.
- **API/backend:** `app/clip/metadata.py`.
- **Docs:** this section.

### B7 · Export and provenance

- **Goal:** deliver files plus a record of what was actually produced.
- **Engine:** B (`batch_export`).
- **Behaviour:** renders each selected/requested clip into
  `data/clip_projects/<id>/exports/`, validating every output; a failing clip is recorded
  individually and does not abort the batch; `manifest.json` records source path,
  requested/succeeded/failed counts, per-item duration, size, validation, loudness,
  hashtags and range.
- **Acceptance:** requested count equals exported count in a healthy run; manifest exists;
  export listing matches files on disk.
- **Constraints:** export directory is served read-only through a path-checked endpoint.
- **UI:** step 5 — manifest counters, file list with sizes, per-item table.
- **API/backend:** `POST /api/clip/projects/{id}/export-batch`,
  `GET /api/clip/projects/{id}/exports`, `GET /api/clip/exports/{id}/{name}`.
- **Docs:** this section.

### B8 · Jobs, cancellation, recovery, memory

- **Goal:** behave predictably on an 8 GB machine shared with Engine A.
- **Engine:** both (shared guard only).
- **Behaviour:** clip jobs are rows in `clip_jobs`; one heavyweight job app-wide
  (Engine A `jobs` **or** `clip_jobs`) — enqueue returns 409 otherwise. Progress comes
  from real stage transitions and FFmpeg `-progress` frames. Cancellation is a flag
  checked at every stage boundary (`force`) and at most every 0.2 s inside FFmpeg loops;
  `tmp/` is cleaned on exit for both success and failure. On startup, queued/running clip
  jobs are marked `interrupted` with artifacts preserved.
- **Acceptance:** cancel request on a live job ends `canceled` with no tmp leftovers;
  simulated crash is recovered as `interrupted`; peak RSS is recorded per job.
- **Constraints:** sequential execution; `wait_for_memory` guard before analysis.
- **UI:** job banner with progress, stage, message, peak memory, cancel; job history list.
- **API/backend:** `GET /api/clip/jobs/{id}`, `POST /api/clip/jobs/{id}/cancel`,
  `GET /api/clip/projects/{id}/jobs`; `app/clip/jobs.py`.
- **Docs:** this section + `HARDWARE_LIMITATIONS.md`.

---

## 3. Data model (additive only)

| Table | Purpose |
|---|---|
| `clip_projects` | one row per clip project (title, status, aspect, preset, language, settings) |
| `clip_sources` | uploaded source with SHA-256, dimensions, codecs, probe JSON |
| `clip_candidates` | clip window, transcript text, score JSON, reason, selection, per-clip edit JSON |
| `clip_renders` | one row per rendered aspect, with output path and probe JSON |
| `clip_jobs` | job state machine: type, stage, status, progress, message, error, peak memory |

Engine A's `projects`/`jobs` schema is untouched; `jobs.project_id` remains `NOT NULL`, so
Engine B never writes into Engine A's job table.

Artifacts:

```
data/clip_projects/<id>/
  source/    original upload (never rewritten)
  analysis/  audio16k.wav, structural.json, transcript.json, whisper_output.json
  clips/     <candidate-id>_<aspect>.mp4, captions.ass
  exports/   numbered MP4s + manifest.json
  logs/      clip.log (job failures with tracebacks, source replacement)
  tmp/       upload staging + render `.part.mp4`, cleaned after every job
```

---

## 4. API reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/clip/capabilities` | ASR availability + reasons, aspects, presets, crop modes, durations |
| GET | `/api/clip/diagnostics` | FFmpeg/ffprobe resolution, whisper capability, probe fallback notice |
| GET/POST | `/api/clip/projects` | list / create |
| GET/PATCH/DELETE | `/api/clip/projects/{id}` | detail / update / delete (`delete_files`) |
| POST | `/api/clip/projects/{id}/source` | upload source (`replace_existing`) |
| GET | `/api/clip/projects/{id}/source/file` | stream current source |
| POST | `/api/clip/projects/{id}/analyze` | structural analysis job |
| POST | `/api/clip/projects/{id}/transcribe` | whisper.cpp job (503 when unavailable) |
| GET/PUT | `/api/clip/projects/{id}/transcript` | read / replace cues |
| POST | `/api/clip/projects/{id}/transcript/import` | import SRT/VTT/plain text |
| POST | `/api/clip/projects/{id}/highlights` | scoring job (`durations`, `count`) |
| GET | `/api/clip/projects/{id}/clips` | candidates with score breakdown and renders |
| PATCH/DELETE | `/api/clip/clips/{cid}` | edit window/copy/edit JSON · delete |
| POST | `/api/clip/clips/{cid}/metadata` | regenerate grounded copy |
| POST | `/api/clip/clips/{cid}/render` | render job |
| GET | `/api/clip/clips/{cid}/file` | download a render (`?aspect=`) |
| POST | `/api/clip/projects/{id}/export-batch` | batch render selected/requested clips |
| GET | `/api/clip/projects/{id}/exports` | files + manifest |
| GET | `/api/clip/jobs/{jid}`, POST `.../cancel` | job status / cancellation |
| GET | `/api/system` | includes `clip` block: project count, active job, ASR capability |

Errors are JSON `{"detail": "..."}` with 400/404/409/413/415/503 as appropriate.

---

## 5. Frontend

- `frontend/src/pages/ClipStudio.tsx` — capability panel (ASR state and reasons, manual
  import guarantee, "manual crop, no tracking" statement), project creation, project grid.
- `frontend/src/pages/ClipProject.tsx` — source/analysis, transcript (import, paste, edit),
  highlight controls, per-clip editor with score bars, render/preview/download, exports and
  job history.
- `frontend/src/lib/api.ts` — `clipApi` typed client; `App.tsx` routes `/clip`, `/clip/:id`;
  `Layout.tsx` nav entry "Auto-Clip Studio".

---

## 6. Enabling real speech recognition

```bash
scripts/install_whisper_cpp.sh --check     # report missing prerequisites
brew install cmake                         # if cmake is missing
scripts/install_whisper_cpp.sh             # clone + build + download ggml-base.en.bin
```

Then restart the backend and confirm `GET /api/clip/capabilities` reports
`"available": true`. Model choice changes accuracy and speed; `base.en` is the 8 GB
default, `small.en` is slower. Until then the app imports SRT/VTT and never fabricates a
transcript.

---

## 7. Known limitations

1. **ASR not verified in this build.** No `whisper.cpp` binary/model was present, so
   transcription quality, WER and timing accuracy are unmeasured; the E2E case is
   reported NOT_RUN rather than passed.
2. **No subject tracking.** Crop is static per render; a subject that moves out of the
   chosen rectangle will leave frame.
3. **Highlight quality is unvalidated against human judgement.** Scoring is inspectable
   and deterministic, but no reference ratings exist, so "better clips" is not claimed.
4. **Music is not content-aware.** Ducking is a compressor, not beat/energy alignment.
5. **One source per project.** Replacing a source intentionally discards its analysis,
   transcript and clips.
6. **Standalone `ffprobe` absent in this environment.** Probing falls back to FFmpeg
   stderr parsing; the active method is recorded as `probe_source` on every source/render.
7. **Long-source evidence uses synthetic media.** 1/5/15/30/60-minute files are TTS over
   `testsrc2` colour video (1.56 MB → 84.78 MB). Latency/memory were measured on those
   (analysis 0.46 → 18.51 s, render 1.56–2.35 s, peaks 77 → 452 MB), but a real 720p/1080p
   recording of the same length decodes far more data; real-footage long-source cost is
   unmeasured. See `TEST_REPORT_ENGINE_B.md` §6.1.
