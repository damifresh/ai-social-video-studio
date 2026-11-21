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
| Transcript from local whisper.cpp | Working (measured on clean synthetic TTS) | whisper.cpp `whisper-cli` + `ggml-base.en.bin` built locally; 67.52 s → 17 segments / 15 sentences / 199 words, native timings, 1.79 s, 446 MB peak; **WER 1.01 %** on the fixture's known script (`B3-ASR`, `wer_971ca893acbe.json`). Human speech **NOT_RUN** |
| Transcript import (SRT / VTT / plain text) | Working | `B3-IMPORT` (15 cues, monotonic, timings labelled "file", word timings labelled "estimated") |
| Transcript editing in-app | Working | `PUT /api/clip/projects/{id}/transcript` rebuilds sentence boundaries |
| Highlight scoring with auditable weights | Working | `B4-HIGHLIGHTS`: every clip stores per-component raw/weight/contribution + reason |
| Director/prompter (deterministic) | Working | Shared on the Auto-Clip Studio category page and inside projects; five built-in set prompts plus free text. `prompt.py` parses the brief into transparent scoring rules and `direction.py` builds the deterministic plan (preset, target durations, one-clip assembly metadata). No model, network call or desktop LLM bridge. Plan stored in job `meta`; brief, rules, weights, components and grounded copy on each candidate's `score_json` (including `brief_fit`). Opt-in **One clip** mode composes one final video from 2–6 ordered transcript sentence ranges with roles; silence gaps and scene cuts are boundary support, transcript ranges remain authoritative, and `render_assembly()` concatenates them into exactly one selected, render-ready candidate with a `0 → total duration` timeline. Short sources clamp transcript/structural boundaries and the target to the uploaded duration (or emit one grounded scene with a notice) and legacy candidates are clamped at render time. Verified by 51 unit tests (including real FFmpeg assembly and short-source regressions), real API runs, and 25/25 Electron UI smoke checks |
| Non-overlapping, sentence-aligned clip windows | Working | Overlap ≤ 0.2 s tolerance; shortfall reported instead of duplicating spans |
| Render H.264/AAC at native source resolution | Working | `B5-RENDER`: output probes report the source's own dimensions (default fixture 1280×720); presets 9:16 / 16:9 / 1:1 remain file keys, validation includes A/V sync |
| Multi-scene one-video assembly | Working | `render_assembly()` trims and concatenates 2–6 ordered transcript ranges in director order, remaps caption cues to the assembled timeline, and applies the same native fit-and-pad/captions/loudness/ducking chain; one selected candidate is render-ready and boundary patches are rejected |
| Multi-video combine (one seamless MP4, smooth or cut) | Working | Append several videos in user-defined order; `render_combine()` joins them with FFmpeg `xfade`/`acrossfade` (default 0.6 s, capped 0.1–1.5 s) or plain `concat`. The shortest selected Target duration trims all ordered sources proportionally (fade overlap included) so the final MP4 respects the timeframe; omissions keep legacy whole-source behaviour. One selected, render-ready `source_combine` candidate with audited order/transition/duration metadata; no transcript copy invented. Combine output keeps the first ordered source's native pixel dimensions at visually lossless quality; differently sized sources are fitted and padded, never cover-cropped. Verified by unit tests (incl. real 2-/3-source FFmpeg renders, native-resolution and mixed-size padding, targeted trims) and the Electron smoke |
| Captions burned per clip | Working | ASS cues generated from the clip's own transcript sentences (28 cues in the measured 44 s clip) |
| Explicit custom crop | Working | Only a user-entered rectangle crops; no automatic cover-crop/zoom; deterministic geometry only |
| Automatic face/subject tracking | **Not implemented** | No model is bundled, no tracking is claimed in UI or API |
| Loudness normalisation, optional ducked music | Working | `loudnorm=I=-16:TP=-1.5:LRA=11` + sidechain ducking; measured ≈ −16 LUFS |
| Transcript-grounded title/hook/caption/hashtags | Working | Deterministic `transcript-template/v1`; each field verified as a substring/token of the clip text |
| Batch export with per-item manifest | Working | `B6-BATCH`: manifest lists measured duration, size, validation, loudness, hashtags per clip |
| Cancellation and restart recovery | Working | `B9-CANCEL` (terminal `canceled`, tmp cleaned), `B10-RECOVERY` (in-flight → `interrupted`) |
| WER / ASR accuracy | Measured on clean synthetic TTS only | 1.01 % (2 substitutions `pick→take`, `behaviour→behavior`; 0 del / 0 ins; 199 words), 15/15 sentences, 14/15 boundaries within 0.75 s. Human speech/accents/noise **NOT_RUN** |
| ASR → highlights → captions → render | Working | `B3-ASR-PIPELINE`: ASR-only project (no SRT) produced 1 highlight and a validated 9:16 render with 9 cues |

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
- **Constraints:** the single-source endpoint keeps its original replace semantics:
  uploading again requires `replace_existing=true` (default) and clears the previous
  source, analysis, transcript and clips, because their timings refer to the old file.
  `replace_existing=false` returns 409. To keep several videos, use the additive
  multi-source endpoint (§ B5a); it never replaces existing sources, skips exact
  SHA-256 duplicates, and marks existing candidates stale until regenerated or re-combined.
- **UI:** step 1 panel — add several videos, reorder/remove them, or replace them all with
  one source (original behaviour); inline previews, metadata grid, hash.
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
- **Acceptance:** import of a 15-cue SRT yields 15 monotonic cues within duration; with an
  installed backend, a 67.52 s clean-TTS fixture yields 17 segments → 15 sentences with
  native word timings, monotonic starts, and WER 1.01 % against its known script; an
  ASR-only project then drives highlights and a validated render (`B3-ASR-PIPELINE`).
  Without a backend the case is NOT_RUN, never PASS.
- **Constraints:** no backend → no invented transcript. No cloud fallback. WER is claimed
  only for the clean synthetic fixture; human-speech accuracy is unmeasured.
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
- **Constraints:** heuristic clip-worthiness, not a virality predictor; no LLM in
  the scorer; no reference ranking exists, so precision/recall is not claimed.
- **UI:** the prompter with five built-in set prompts, free text, three suggestion chips,
  an opt-in **One clip** toggle and a **Preview** button is available
  on the Auto-Clip Studio category page and in project step 3; the category choice is carried into
  new projects and project changes are persisted. Step 3 also has duration chips 15/30/45/60/90 +
  custom (5–180 s, max 6 targets), count 1–12 (disabled at 1 in one-clip mode), per-clip score bars,
  reason, the validated plan summary, and ordered scene chips with source ranges and boundary cues
  for assembled candidates.
- **API/backend:** `GET /api/clip/prompt/presets`, `POST /api/clip/prompt/parse` (preview only),
  `POST /api/clip/projects/{id}/direction/preview`,
  `POST /api/clip/projects/{id}/highlights` with optional `prompt`/`director_preset`/`single_clip`,
  `GET /api/clip/projects/{id}/clips`; `app/clip/direction.py`, `app/clip/prompt.py`, `app/clip/highlights.py`.
- **Docs:** weights and parsed rules are printed in the UI and stored per clip.

#### B4a · Director/prompter (deterministic, transcript-grounded plan)

- **Goal:** let a creator describe the desired outcome in plain English (or choose one of five
  built-in set prompts) and have the local director parse it into transparent scoring rules and
  target durations without inventing any copy.
- **Engine:** B (`direction.py` plan builder, `prompt.py` rule parser, highlight reweighting). No
  model, network call or desktop LLM bridge is involved.
- **Behaviour:** `prompt.parse()` converts the preset instruction plus free-text brief into an
  auditable brief (tone, platform, audience, keywords, avoid list, length hint, bounded weight
  multipliers and human-readable rules). `direction.deterministic_plan()` combines that brief with
  explicit UI durations (falling back to the prompt's length hint, then 30 s) and records the
  preset and engine. The plan is stored in job `meta`, and the brief, rules, weights, components
  and grounded copy in each candidate's `score_json` (including `brief_fit`). Copy always comes
  from `transcript-template/v1` and is verified against the clip's own transcript.
  With `single_clip`, the plan adds assembly metadata (`mode`, `target_seconds`, boundary
  authority and counted silence gaps / scene cuts). Silence gaps and visual scene cuts are
  included as boundary/support evidence, but transcript sentence ranges remain the authority.
  Scoring forces one candidate whose `segments` retain source ranges while its timeline runs
  `0 → total duration`, and `render_assembly()` concatenates those ranges into one captioned MP4.
  Boundary patches on the assembled candidate are rejected by `PATCH /api/clip/clips/{id}`. When
  the transcript outlives a short upload, generation clamps all transcript/structural boundaries
  and the target to the source duration and records `clamped_to_source_duration`; with only one
  usable sentence it emits one grounded scene plus a notice (zero usable sentences remains a hard
  error). Render-time clamping also keeps older candidates inside the file, so short sources no
  longer raise `Source is too short for transcript-grounded assembly` or
  `Assembly segment extends outside the source duration`.
- **Acceptance:** unchanged or empty prompts preserve the default eight-weight scoring; a
  non-empty prompt yields an auditable `brief` plus `brief_fit` on every candidate; verified with
  `backend/tests/test_clip_prompt.py`, `test_clip_direction.py`, `test_clip_render.py`,
  `test_clip_combine.py`, `test_clip_captions.py` and `test_caption_sync.py` (51 unit tests total,
  including real two-scene FFmpeg assembly, two-/three-source combine renders, caption-sync and
  short-source regressions), real API runs for both scoring modes, 25/25 Electron UI checks, and a
  25/25 packaged-app rerun, including the 2 s final-preview source, ordered scene metadata and
  guarded boundary edits.
- **Constraints:** no model or external service is consulted. No reference ranking exists, and
  the director cannot invent title/hook/caption/hashtag text; it is not a virality predictor.

### B5 · Reframing, captions, audio, render

- **Goal:** platform-ready MP4 per clip at the source's native pixel size, with honest geometry.
- **Engine:** B (`render` / `batch_export` jobs).
- **Behaviour:**
  - crop: **no automatic crop**. Only a user-entered `custom` rectangle (fractions of the
    source frame, clamped in-bounds) is applied before fitting; `center/left/right/top/bottom`
    no longer zoom or cut the frame.
  - canvas: the decoded source's own width/height (rotation-aware, even-aligned). Every input
    uses `setsar=1,scale=W:H:force_original_aspect_ratio=decrease:flags=lanczos,pad=W:H:...`,
    so the full frame is kept and mismatched sizes are padded, never cropped. The aspect
    preset stays a project/file key and no longer forces a 720p cover-crop.
  - captions: cues grouped from word-level transcript timing (native ASR tokens
    or proportional words estimated inside timed SRT/VTT cues), so a clipped
    sentence shows only the words actually spoken inside the clip range;
    chunks respect `max_chars` and sentence pauses, ASS timestamps use libass's
    centisecond format (`H:MM:SS.cc`), and cues are burned via `subtitles`.
  - audio: `loudnorm=I=-16:TP=-1.5:LRA=11`; optional music looped/trimmed with a 0.8 s
    fade and sidechain-ducked under speech (`sidechaincompress`), mixed with `amix`.
  - encode: libx264 CRF 18, medium, AAC 128 kbit/s 48 kHz stereo, `+faststart` — the Final
    preview and the export share this encode, so quality matches.
  - validation: existence, exact resolution, H.264, AAC, duration ±0.2 s, audio stream,
    size > 10 kB, and A/V duration delta < 0.1 s.
- **Acceptance:** validation uses the reported native `resolution`, not the preset size;
  measured loudness ≈ −16 LUFS.
- **Constraints:** no face/subject tracking; no optical-flow stabilisation; music must be a
  local file; output is the source's native dimensions (e.g. the 1280×720 fixture), which may
  differ from the selected 9:16 / 16:9 / 1:1 preset.
- **UI:** per-clip editor — trim, aspect, fps, crop mode + manual rect, caption
  size/position/max chars/highlight, burn toggle, loudness toggle, music + volume,
  save & render, inline preview and download. The prompter also exposes a project-level
  **Captions: on/off** switch (default on) on the category and project pages: it persists in
  `settings_json["burn_captions"]`, seeds new transcript candidates, bulk-updates existing
  transcript and `source_combine` candidates (marking changed ones stale), and controls
  burned-in subtitles for both render paths; the per-clip burn toggle remains an override.
- **API/backend:** `POST /api/clip/clips/{sid}/render`, `PATCH /api/clip/clips/{sid}`,
  `GET /api/clip/clips/{sid}/file`; `app/clip/render.py`, `app/clip/jobs.py`.
- **Docs:** this section, exact filter graph documented here.

### B5a · Multi-source combine (one seamless video)

- **Goal:** join several uploaded videos into one output MP4 with a visible choice of
  smooth transitions or straightforward cuts, without changing the deterministic director
  or transcript logic.
- **Engine:** B (`combine` job, `render_combine()`).
- **Behaviour:** sources are stored in upload order in
  `settings_json["source_order"]` and can be reordered or removed through the API/UI;
  that order is authoritative. Upload dedupes by SHA-256. With no `target_duration`,
  each source contributes its whole duration (`start=0 → end=duration`), preserving the
  legacy combine behaviour. When a target is supplied, the UI sends the **shortest
  selected Target duration** and `fit_combine_segments()` trims every source
  proportionally (all stay in order with positive ranges) so the final MP4 lands on
  that timeframe; crossfade overlap is included in the fit. With transitions on (the
  default), adjacent clips are joined by a short video `xfade` + audio `acrossfade`;
  with transitions off, a plain `concat` produces straight cuts. The crossfade defaults
  to 0.6 s, is user configurable in 0.1–1.5 s, and is capped at 35 % of the shorter
  neighbouring clip so no boundary can consume a whole video. A target longer than the
  available source material is rejected with an explicit 400/job error rather than
  silently stretching or padding. Captions/loudness/ducking and validation follow B5.
  Like the now-native single-source and assembly renders, a combine does **not** cover-crop
  or downscale to the aspect preset: the output canvas is the first ordered source's exact
  native width/height, encoded with `libx264 -preset medium -crf 18`. **Every** input goes
  through `setsar=1,scale=...:force_original_aspect_ratio=decrease:flags=lanczos`
  plus `pad=...:(ow-iw)/2:(oh-ih)/2` to that canvas. Sizes already matching scale 1:1
  and are pixel-identical; no frame is cut. Normalising all inputs is required because
  `xfade`/`concat` reject links with different dimensions, and a probe can disagree
  with decoded frame size (rotation side data, SAR or a stale probe). A regression test
  simulates exactly that mismatch (1080×1920 vs 1920×1080). Probe results now also carry
  rotation-aware `display_width`/`display_height` so a rotated source chooses the correct
  canvas. The first source's resolution and dimensions are preserved in both the Final
  preview and the export.
  Captions are grounded in each source's own timed transcript:
  cached per-source SRT/VTT/ASR data is loaded from
  `analysis/sources/{source_id}/transcript.json`, clipped to that source's selected range,
  and shifted onto the combined timeline; cues overlapping a crossfade are trimmed
  to the words still audible on each side of the fade midpoint.
  `POST /sources/{sid}/transcript/import`, `GET /sources/{sid}/transcript` and
  `POST /sources/{sid}/transcribe` manage those per-source transcripts, and the combine
  job runs local ASR automatically for any source that lacks one when the backend is available.
- **Acceptance:** two or more sources required; one selected render-ready candidate with
  `score_json.assembly.kind = "source_combine"`, ordered source names/IDs, transition mode,
  per-boundary fade durations and offsets, and `engine = "source-combine/v1"`. Both modes
  produce a validated H.264/AAC file at the first source's native resolution (default
  fixture 1280×720), reported as `resolution` / `source_resolution` with
  `resolution_mode = "source-native"` and `crop = null`; the aspect preset remains the
  project file/DB key (measured whole-source: 2-source fade 3.4 s, cut 4.0 s;
  3-source fade 5.0 s with boundaries `[0.5, 0.5]`; measured targeted: 2 × 3 s sources
  trimmed to a 5 s target in both fade and cut modes). The assembly records
  `target_duration`, `duration_mode`, the source timeline length, `resolution`,
  `source_resolution`, `resolution_mode` and the final timeframe. `assembly.captions` records whether burned-in subtitles are enabled, their
  source (`per-source transcript/ASR`), final cue count and any per-source notices.
  No subtitle copy is invented for a combine. Source
  additions/reorders/removals mark existing candidates stale.
  The same multi-source render path is used when the candidate is rendered or batch-exported
  later: `_render_one()` dispatches `assembly.kind == "source_combine"` to `render_combine()`
  with the candidate's stored per-source paths, order and transition metadata, so an Export
  never re-renders it as a single-source transcript assembly. Missing source files are a hard
  error rather than a silent fallback to the project's latest source.
- **Constraints:** combine operates on uploaded source ranges, not transcript ranges
  (transcript assembly is B4a/B5); it needs no *single-project* transcript, but burned-in
  captions require a timed transcript for each source. A target trims those ranges
  but never drops, reorders, stretches or pads a source. Adding/reordering/removing a
  source requires an explicit re-combine to refresh the output. The director is not involved;
  the combine job is fully deterministic.
- **UI:** step 1 "Add videos" (multiple file picker), ordered source list with ↑/↓/Remove,
  "Combine N videos (smooth/cuts)" button with the active **Target {n}s** chip (the
  shortest selected Target duration), and a shared **Transitions: smooth/cut** toggle
  on both the category page and project page (default on, persisted in project settings).
  Each ordered source row also offers **SRT/VTT** import and **ASR** generation so captions
  can be grounded in that source; the combine job runs ASR automatically when the backend
  is available. The combine candidate shows the source order, transition mode, target and
  the note "Uploaded source order is authoritative; burned-in subtitles come only from each
  source transcript".
- **API/backend:** `POST /api/clip/projects/{id}/sources` (append many),
  `GET .../sources`, `PATCH .../sources/order`, `DELETE /api/clip/sources/{sid}`,
  `POST .../combine` (`target_duration` optional); `app/clip/render.py`
  (`render_combine`, `fit_combine_segments`, `max_combine_duration`, `build_combine_graph`,
  `normalize_combine_segments`), `app/clip/jobs.py` (`_job_combine`, `_render_one`,
  `_job_batch_export`), `app/clip/api.py`.
- **Docs:** this section + `docs/TEST_REPORT.md` verification.

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
- **Constraints:** no model, no external topic suggestions, no claims about accuracy of the
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
  hashtags and range. For a `source_combine` item the manifest additionally records the
  ordered source paths, the `combine` render metadata (per-source ranges and order) and
  the `transition` metadata (mode, boundaries, offsets), plus `resolution`,
  `source_resolution` and `resolution_mode = "source-native"`; no transcript hashtags are
  generated for it. The top-level manifest marks `source_combine` and lists `combine_sources`.
- **Acceptance:** requested count equals exported count in a healthy run; manifest exists;
  export listing matches files on disk. A combined candidate exported from the Export level
  produces one validated MP4 using every stored source in its saved order, in both smooth and
  cut modes; it is never re-rendered from a single source.
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
| POST | `/api/clip/projects/{id}/source` | upload/replace single source (`replace_existing`, legacy behaviour) |
| GET | `/api/clip/projects/{id}/source/file` | stream last source in order |
| POST | `/api/clip/projects/{id}/sources` | append several sources (upload order, SHA-256 dedupe) |
| GET | `/api/clip/projects/{id}/sources` | list ordered sources |
| PATCH | `/api/clip/projects/{id}/sources/order` | reorder sources (`source_ids`) |
| DELETE | `/api/clip/sources/{sid}` | remove a source |
| POST | `/api/clip/projects/{id}/combine` | combine job (`transitions`, `transition_seconds`, `target_duration`, `aspect`) |
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
  import guarantee, "manual crop, no tracking" statement), project creation (sends `transitions`),
  project grid.
- `frontend/src/components/Prompter.tsx` — shared prompt box, five presets, suggestion chips,
  One-clip/**Captions**/**Transitions** toggles and deterministic brief preview; the toggle persists to project settings.
- `frontend/src/pages/ClipProject.tsx` — multi-source upload/order/remove and combine controls,
  analysis, transcript (import, paste, edit), highlight controls, per-clip editor with score
  bars, render/preview/download, exports and job history.
- `frontend/src/lib/api.ts` — `clipApi` typed client; `App.tsx` routes `/clip`, `/clip/:id`;
  `Layout.tsx` nav entry "Auto-Clip Studio".

---

## 6. Enabling real speech recognition

```bash
scripts/install_whisper_cpp.sh --check     # report missing prerequisites
brew install cmake                         # if cmake is missing
# equivalent on this machine (no Homebrew needed):
uv pip install --python backend/.venv/bin/python cmake
scripts/install_whisper_cpp.sh             # clone + build + download ggml-base.en.bin
```

Then restart the backend and confirm `GET /api/clip/capabilities` reports
`"available": true` with the resolved `bin_path` and `model_path`. Model choice changes
accuracy and speed; `base.en` is the 8 GB default (measured: RTF 0.0265, 446 MB peak),
`small.en` is slower and was not measured here. Until a backend is installed the app
imports SRT/VTT and never fabricates a transcript.

Accuracy harness:

```bash
PYTHONPATH=backend backend/.venv/bin/python scripts/engine_b_asr_wer.py
# → benchmarks/data/engine_b/wer_<id>.json
```

Measured result on this machine: 1.01 % WER, 15/15 sentences, native word timings, on
clean single-speaker macOS TTS with a known script.

---

## 7. Known limitations

1. **ASR accuracy is only measured on clean synthetic speech.** whisper.cpp `base.en` is
   installed and measured (1.01 % WER on the fixture's own TTS script, native word
   timings, RTF 0.0265, 446 MB peak), but accents, background noise, multi-speaker audio,
   fast speech and human ground-truth transcripts are **NOT_RUN**. The model is
   English-only. Word-timestamp fidelity is unmeasured against any human-aligned reference.
2. **No subject tracking.** Crop is static per render; a subject that moves out of the
   chosen rectangle will leave frame.
3. **Highlight quality is unvalidated against human judgement.** Scoring is inspectable
   and deterministic, but no reference ratings exist, so "better clips" is not claimed.
4. **Music is not content-aware.** Ducking is a compressor, not beat/energy alignment.
5. **Single-source replace still resets the project.** The legacy `.../source` endpoint
   intentionally discards the previous source's analysis, transcript and clips. The
   additive `.../sources` combine path keeps all uploaded files but needs an explicit
   re-combine after any add/reorder/remove. Transcript assembly (B4a) and source-video
   combine (B5a) are separate operations; neither invents transcript copy.
6. **Standalone `ffprobe` absent in this environment.** Probing falls back to FFmpeg
   stderr parsing; the active method is recorded as `probe_source` on every source/render.
7. **Long-source evidence uses synthetic media.** 1/5/15/30/60-minute files are TTS over
   `testsrc2` colour video (1.56 MB → 84.78 MB). Latency/memory were measured on those
   (analysis 0.46 → 18.51 s, render 1.56–2.35 s, peaks 77 → 452 MB), but a real 720p/1080p
   recording of the same length decodes far more data; real-footage long-source cost is
   unmeasured. See `TEST_REPORT_ENGINE_B.md` §6.1.
