# AI Social Video Studio (Local)

A fully local macOS desktop app and web studio with **two independent engines**:

- **Engine A — AI Video Creator:** turns a topic/prompt into a finished **720p H.264/AAC MP4** (1–5 minutes) with script generation, storyboarded scenes, local narration, timed subtitles, music/SFX mixing, animated-graphic motion visuals, and FFmpeg composition.
- **Engine B — AI Auto-Clip Studio:** turns one long recording (MP4/MOV/MKV/WebM) into short, captioned clips at the source's **native resolution** (the 9:16 / 16:9 / 1:1 preset remains a file key) with transcription or SRT/VTT import, transparent highlight scoring, no automatic zoom/cropping, loudness-normalised audio, and transcript-grounded titles/hooks/hashtags. Several uploaded videos can also be combined into one seamless MP4 with smooth transitions or straightforward cuts.

- **Local-only:** no cloud inference, no paid APIs, no accounts, no subscriptions. Internet is only needed for optional one-time downloads (models/tooling) — never for generation.
- **Target hardware:** Apple M2, 8 GB unified memory, macOS (Apple Silicon).
- **Honest visuals:** defaults to **animated stills/graphics** (Pillow + FFmpeg motion). Diffusion/generated footage is not assumed feasible on 8 GB and is never silently substituted.

## Deliverables in this repo

- **Packaged desktop app:** `dist-desktop/mac-arm64/AI Social Video Studio.app`, `...-arm64-mac.zip`, and `...-arm64.dmg` (built locally). See [`docs/DESKTOP_APP.md`](docs/DESKTOP_APP.md).
- **Source:** `backend/` (FastAPI, SQLite, sequential pipeline), `frontend/` (React + TypeScript + Vite), `desktop/` (Electron shell), `scripts/` (build/verify/asset generation), `assets/` (bundled CC0 music/SFX).
- **Docs:** [`docs/INSTALL.md`](docs/INSTALL.md), [`docs/DESKTOP_APP.md`](docs/DESKTOP_APP.md), [`docs/ENGINE_B.md`](docs/ENGINE_B.md), [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md), [`docs/HARDWARE_LIMITATIONS.md`](docs/HARDWARE_LIMITATIONS.md), [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md), [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md), [`docs/TEST_REPORT_ENGINE_B.md`](docs/TEST_REPORT_ENGINE_B.md), [`docs/CHANGELOG_ENGINE_B.md`](docs/CHANGELOG_ENGINE_B.md), [`docs/DELIVERABLES.md`](docs/DELIVERABLES.md), [`models/README.md`](models/README.md).
- **Verified outputs & evidence:** `deliverables/` (60 s 16:9 & 9:16, 3-min 16:9 MP4/SRT, `acceptance_extended.json` with 5-min + 1:1 results) and `docs/screenshots/01-dashboard-full.png`.

## Verified capability snapshot (2026-11-14)

| Case | Result | Measured |
|---|---|---|
| 60 s class 16:9 (30 fps) | PASS | 78.52 s, 1280×720, 5.40 MB, 34 cues burned, peak 724–730 MB, render 10–16 s |
| 60 s class 9:16 (24 fps) | PASS | 69.92 s, 720×1280, 3.93 MB, 30 cues burned, peak 659 MB |
| 60 s class 1:1 (30 fps) | PASS | 74.61 s, 720×720, 3.82 MB, 34 cues, peak 490 MB |
| 3 min 16:9 | PASS | 183.55 s, 1280×720, 8.51 MB, 9 scenes |
| 5 min 16:9 | PASS | **329.1 s**, 1280×720 @ 30 fps, **21.44 MB**, 147 cues, 15 scenes, **peak 746 MB**, generate 72.3 s |
| Packaged `.app` render | PASS | 73.66 s, 1280×720, 5.17 MB, 33 cues, peak 728 MB, output in `~/Library/Application Support/AI Social Video Studio/data/...` |

All measured renders: H.264 High / yuv420p, AAC 48 kHz stereo, burned subtitles, loudness-normalized mix (~−15.8 LUFS / −3.4 dBTP), **no cloud inference**. Narration engine: macOS `say` (offline). Kokoro MLX is not installed/verified (adapter + fallback in place); whisper.cpp `base.en` is installed and measured for Engine B.

## Engine B verified snapshot (2026-11-17)

Harness `scripts/engine_b_e2e.py` (16 cases, whisper.cpp installed) with a synthetic 67.52 s source (macOS `say` narration + FFmpeg colour video), measured locally:

| Case | Result | Measured |
|---|---|---|
| Upload MP4/MOV/MKV/WebM, original preserved | PASS | SHA-256 of stored file equals uploaded bytes for all four containers |
| Probe metadata | PASS | 67.52 s, 1280×720, 30 fps, H.264/AAC (FFmpeg-fallback probe; no standalone `ffprobe`) |
| Structural analysis | PASS | 676 envelope windows, 14 silence gaps, 0 scene cuts, 0.4 s, 79 MB peak |
| Transcript import (SRT) | PASS | 15 cues, monotonic, `timing=file`, `word_timing=estimated` |
| Local transcription (whisper.cpp base.en) | PASS | 17 segments → 15 sentences, native word timings, monotonic, 1.83 s, 376 MB peak |
| WER on the known fixture script | PASS (clean synthetic TTS) | **1.01 %** (2 substitutions / 199 words; no deletions or insertions) |
| ASR-only clip pipeline | PASS | whisper transcript → 1 highlight → 9:16 render, 9 cues, validation ok |
| Highlight scoring | PASS | 2 non-overlapping clips, per-component weights + reasons, copy grounded in clip text |
| Render 9:16 / 16:9 / 1:1 | PASS | 720×1280 (1.42 MB), 1280×720 (1.24 MB), 720×720 (1.05 MB); H.264/AAC, 28 cues, −16.0 LUFS, A/V delta < 0.1 s |
| Batch export | PASS | 2 requested → 2 exported, per-item manifest with duration/size/validation/loudness/hashtags |
| Cancel live job / restart recovery | PASS | terminal `canceled`, tmp cleaned; in-flight row → `interrupted` |
| Long sources 1 / 5 / 15 / 30 / 60 min | PASS (synthetic) | A1–A5 each 6/6: analysis 0.46 → 18.51 s (77 → 452 MB), highlights 0.02 → 2.88 s, deep-end render 1.56–2.35 s (359–415 MB), all validated |

16 PASS / 0 FAIL / 0 NOT_RUN in acceptance (37.1 s). Long-source harness `scripts/engine_b_longrun.py` measured 68.55 s → 3733.12 s sources with byte-identical upload, exact SRT import and validated 720p renders (`benchmarks/data/engine_b/long_*_{1,5,15,30,60}m.json`). Fixtures are TTS over colour video, so real-footage long-source cost is **not** measured. Engine A regression re-run after the change: **PASS** (`VC-60S`, 16.464 s wall, 69.49 s output, 725.9 MB peak). Full honesty notes: [`docs/TEST_REPORT_ENGINE_B.md`](docs/TEST_REPORT_ENGINE_B.md).

**Deterministic director/prompter (2026-11-19):** Auto-Clip Studio has a prompter on the category page and inside clip projects; a category-page brief is carried into newly created projects. Five built-in set prompts (`tiktok`, `reels`, `linkedin`, `educational`, `motivational`) can be selected or edited as free text. Planning is fully local: `prompter-rules/v1` parses the brief into transparent, auditable scoring rules (`backend/app/clip/prompt.py`), and `backend/app/clip/direction.py` builds the plan — preset, target durations, and in one-clip mode the assembly metadata. There is no model, network call or desktop LLM bridge anywhere in the flow. The plan is stored in job `meta`, and the brief, rules, weights, components and grounded copy in each candidate's `score_json`.

**Auto-clip to one assembled video (opt-in):** the prompter's **One clip** toggle is available on the category page and in projects. When enabled, the local director composes **one final short video** from 2–6 ordered transcript-grounded segments; each segment is a contiguous sentence range with a narrative role (`hook`, `context`, `payoff`, `proof`, `close`, `moment`). Silence gaps and visual scene-cut markers are supplied as boundary/support evidence, but transcript sentence ranges remain authoritative. The backend rejects out-of-range, overlapping, mis-roled or ungrounded segments, fills missing scenes with deterministic transcript windows, forces `count=1`, and creates exactly one selected candidate ready to render. The project then renders that candidate and shows a **Final video preview** player — the actual full-frame, captioned MP4 at native resolution, not the unclipped source — before Export. Its timeline is `0 → total duration`; source ranges stay in `segments`, and the `single_clip` flag plus `assembly`/`segments` metadata are recorded in job `meta` and `score_json`. Boundary edits on assembled candidates are rejected by the API so the validated scene order cannot drift. **Short sources stay grounded:** when a timed transcript outlives the uploaded file, generation clamps sentence, word, silence-gap and scene-cut boundaries to the real source duration, caps the target, records `clamped_to_source_duration` and uses one grounded scene with a visible notice when only one usable sentence remains; at render time legacy candidates are also clamped, so short files no longer fail with `Source is too short for transcript-grounded assembly` or `Assembly segment extends outside the source duration`. Existing multi-clip behavior is unchanged when the toggle is off. Verified with 51 unit tests (including real FFmpeg two-scene assembly renders and two short-source regressions), real API runs, and 25/25 Electron UI smoke checks; the smoke's 2 s preview source exercises the render-time clamp, and the rebuilt installed app was checked on both screens.

**Combine several videos into one (smooth transitions or straight cuts):** the prompter's **Transitions: smooth/cut** toggle is on by default on the category page and in projects; a category-page choice is carried into newly created projects. In a project, use **Add videos** to upload several files in order, reorder them with ↑/↓ or remove them, then **Combine N videos**. Sources are deduped by SHA-256 and their order is stored in `settings_json["source_order"]` and treated as authoritative. **The shortest selected Target duration is the final timeframe for the combined MP4:** every ordered source is trimmed proportionally, crossfade overlap is included in the fit, and no source is dropped, reordered or stretched. A target longer than the available material is rejected with an explicit error. Smooth mode joins adjacent clips with FFmpeg `xfade`/`acrossfade` (default 0.6 s, adjustable 0.1–1.5 s and capped at 35 % of the shorter neighbouring clip); cut mode uses plain `concat`. The job produces one selected, render-ready `source_combine` candidate with audited source order, target/effective duration, transition mode and per-boundary offsets in `score_json`; captions are burned in from each source's own SRT/VTT or local ASR transcript (no subtitle copy is invented), and adding/reordering/removing a source marks existing candidates stale until re-combined. The legacy single-source upload still replaces and clears the project as before. **Export uses the same multi-source semantics:** clicking **Export** for a combined candidate re-renders it from its stored source paths and order (with the saved fade/cut mode and target duration), not from a single source, and the manifest records the ordered sources and transition metadata. Verified with 51 unit tests (including real two- and three-source FFmpeg renders, targeted trims in both modes, per-source caption cues and real FFmpeg batch-export dispatch) and 25/25 Electron UI smoke checks covering multi-source upload, reorder, a 5 s targeted cut and crossfade render, the persisted toggle and a successful Export of the combined candidate.

**Captions on/off (category and project):** the prompter's **Captions: on/off** toggle is on by default on the category page and inside projects; a category-page choice is carried into newly created projects. In a project, the setting is persisted in `settings_json["burn_captions"]`, seeds newly generated transcript candidates, and bulk-updates existing candidates — including `source_combine` — to the new value, marking changed candidates stale so they can be re-rendered. The existing per-clip **Burn captions** checkbox remains as an override. Combined MP4s are subtitled from each ordered source's own timed transcript: use **SRT/VTT** or **ASR** on a source row (or let the combine job run local ASR automatically when available), and cues are shifted onto the combined timeline with transition overlap clipped. No subtitle text is invented. Verified by caption-toggle and combine-caption unit tests, real Electron UI checks on both screens, and the dev and packaged smokes.

## Quick start (dev)

```bash
# Backend
cd local-ai-video-studio
uv venv backend/.venv --python 3.11
uv pip install --python backend/.venv -r backend/requirements.txt
./scripts/start_backend.sh   # http://127.0.0.1:8000

# Frontend
cd frontend && npm install
./scripts/start_frontend.sh  # http://127.0.0.1:5173
```

## Run the packaged app

Open `dist-desktop/AI Social Video Studio-1.0.0-arm64.dmg` and drag to Applications, or open `dist-desktop/mac-arm64/AI Social Video Studio.app`. The app is unsigned: if blocked, use **right-click → Open** or **System Settings → Privacy & Security → Open Anyway**. Data is stored in `~/Library/Application Support/AI Social Video Studio/`.

## Features

- Dashboard, guided new-project flow, templates, recent/drafts, and export center
- Script engine (duration-aware, editable) + scene-by-scene storyboard with camera/transition/overlay/SFX controls and per-scene regeneration
- Local TTS: macOS `say` (verified) with Kokoro MLX adapter + graceful fallback and metadata recording
- Subtitles: SRT/VTT/ASS, timing-based cues, keyword highlighting/style controls, burn-in toggle, custom-cue preservation on re-render
- Audio: narration + bundled/procedural CC0 music and SFX, sidechain ducking, normalization/limiting
- Composition: per-scene animated motion (zoom/pan), concat, 720p H.264/AAC MP4, 9:16/16:9/1:1, 24/30 fps
- Project persistence (SQLite + on-disk artifacts), reopen/edit/duplicate/delete, render history, sequential 8 GB-safe job queue, progress, cancellation, interrupted-job recovery, and manifest-verified stage resume on re-render
- System/settings: engine detection, memory/disk, cleanup, voice preview, paths, docs

### Engine B — AI Auto-Clip Studio

- Upload MP4/MOV/MKV/WebM — one file (legacy replace semantics that explicitly clear stale clips) or several files appended in order for a combine; original bytes preserved (SHA-256 recorded), probe metadata, reorder/remove sources
- Structural analysis: 16 kHz audio, loudness envelope, silence gaps, approximate scene-cut scan
- Transcript: local whisper.cpp when installed (capability-gated, word timings marked `native` only when the build emits token offsets), otherwise SRT/VTT/plain-text import and in-app cue editing
- Highlights: sentence-aligned windows at 15/30/45/60/90 s or custom durations, eight weighted score components shown per clip, greedy non-overlapping selection, explicit shortfall reporting
- Director/prompter: chat-style brief on the Auto-Clip Studio category page and inside projects ("funny 15s TikTok clips about habits; avoid jargon") with five built-in set prompts plus free text; `prompter-rules/v1` parses the brief locally into transparent scoring rules, `direction.py` builds the deterministic plan, and Preview shows the parsed brief and modifiers
- Multi-video combine: append several sources in user-defined order and render one captioned MP4 with smooth `xfade`/`acrossfade` transitions (default 0.6 s, 0.1–1.5 s) or straightforward `concat` cuts; the shortest selected Target duration trims all ordered sources proportionally so the final file respects the timeframe; one audited `source_combine` candidate per project with subtitles grounded only in per-source transcripts; batch export of that candidate uses the same ordered multi-source render and captions. Combined output keeps the first ordered source's exact native width/height (no preset downscale or cover-crop); sources of a different size are scaled to fit and padded, never cropped. The Final video preview and the downloaded MP4 share this render, so resolution, quality and dimensions match.
- Geometry: native source canvas with fit-and-pad (never zoom or cut); only an explicitly entered custom rectangle crops — **no automatic reframing and no face or subject tracking is claimed**
- Captions: project-level **Captions: on/off** toggle (default on) persisted in project settings and propagated to transcript and combine candidates; per-source SRT/VTT import or local ASR for combines; ASS cues shifted onto the combined timeline, size/position/max-chars/highlight colour and a retained per-clip burn-in override
- Audio: `loudnorm` to ≈ −16 LUFS, optional local music with sidechain ducking, AAC 48 kHz stereo
- Copy: `transcript-template/v1` titles/hooks/captions/hashtags, transcript-grounded only (no invented copy)
- Export: per-clip render validation and batch export with `manifest.json`
- Jobs: sequential with Engine A, live progress from real stages, cancellation at stage boundaries, `interrupted` recovery, peak RSS recorded

## Limitations (honest)

- **Kokoro TTS:** not installed/verified in this build; macOS `say` and narration-timing subtitles are the working local path (fallbacks recorded). **Whisper.cpp ASR (Engine B):** installed and measured locally — 1.01 % WER on the clean synthetic TTS fixture with native word timings; human-speech accuracy is unmeasured, and Engine A still uses timing-based subtitles.
- **Diffusion image/video generation:** not enabled on 8 GB; visuals are animated graphics/stills unless you add labeled footage.
- **Narration-driven duration:** final length follows synthesized speech/timing (observed 174 wpm for Samantha); a 1-min target typically yields ~70–80 s and a 5-min target ~5.5 min unless narration is shortened.
- **Unsigned app** (Gatekeeper override may be needed). An automated Electron UI smoke test exists (`node scripts/ui_smoke.cjs`, 25 checks PASS including the presets, local-director status, captions and transitions toggles, opt-in one-clip toggle on the category page, transcript import, deterministic director preview, generated-clip audit metadata, the project prompter, a playable rendered final-video preview before export, one-video assembly, guarded boundary edits, and multi-source upload/reorder with cut and crossfade combine renders); the rebuilt installed app's UI was also checked through CDP for the prompter, captions and one-clip toggles on both screens. Rebuild/sync `desktop/resources` before running the smoke test so it exercises current source.
- **Engine B ASR is verified only on clean synthetic speech:** whisper.cpp `base.en` is installed locally and measured (1.01 % WER, native word timings), but the fixture is macOS TTS with a known script. Human speech, accents, noise, multi-speaker audio and ground-truth human transcripts are **not** measured; no general WER claim is made. SRT/VTT import remains available.
- **Engine B highlight quality is unrated:** scoring is deterministic and inspectable. The local `prompter-rules/v1` director parses the brief into scoring rules and target durations; in one-video mode the rules order several transcript sentence ranges and fill any missing scenes. There is no model, network call or LLM bridge, and no copy is invented. There are no human reference ratings and no virality claim.
- **Engine B has no tracking:** an explicit custom crop is static geometry; a moving subject can leave the chosen rectangle.
- **Engine B long-source evidence is synthetic:** 1/5/15/30/60-minute fixtures are TTS over colour video (84.78 MB for the 62-minute case); measured analysis 0.46 → 18.51 s and render cost bound by clip length, but real 720p/1080p footage of the same length is `NOT_RUN`.
- **Engine B in the packaged app:** rebuilt and verified on 2026-11-18 — bundled whisper.cpp ASR is available and a 5-sentence synthetic source went upload → analyze → ASR → highlights → validated 9:16 render through the app's loopback backend (`packaged_a3af06a18580.json`, 11/11 checks PASS). The dev Electron UI is click-tested by `scripts/ui_smoke.cjs` (25/25, including the category-page presets, local-director status, captions and transitions toggles, opt-in one-clip, transcript import, deterministic director preview, generated-clip audit metadata, project prompter, one-video assembly metadata, a playable rendered final-video preview, guarded boundary edits, multi-source combine with cuts/crossfades and a successful batch export of the combined candidate); the rebuilt installed app at `/Applications/AI Social Video Studio.app` was also checked through CDP (`PACKAGED_UI_PASS`, 25/25; `deliverables/ui_smoke_packaged.json`); it was rebuilt and rechecked after the short-source fix, again 25/25.

## Documentation

- [`PLAN_STAGE_A.md`](PLAN_STAGE_A.md) · [`docs/STAGE_B_REVERSE_ENGINEERING.md`](docs/STAGE_B_REVERSE_ENGINEERING.md) · [`docs/RESEARCH_NOTES.md`](docs/RESEARCH_NOTES.md)
- [`docs/INSTALL.md`](docs/INSTALL.md) · [`docs/DESKTOP_APP.md`](docs/DESKTOP_APP.md) · [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md)
- [`docs/HARDWARE_LIMITATIONS.md`](docs/HARDWARE_LIMITATIONS.md) · [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- [`docs/ENGINE_B.md`](docs/ENGINE_B.md) · [`docs/TEST_REPORT_ENGINE_B.md`](docs/TEST_REPORT_ENGINE_B.md) · [`docs/CHANGELOG_ENGINE_B.md`](docs/CHANGELOG_ENGINE_B.md)
- [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) · [`docs/DELIVERABLES.md`](docs/DELIVERABLES.md) · [`models/README.md`](models/README.md)

## License / sources

Open-source components only (FastAPI, React, Electron, FFmpeg via imageio-ffmpeg, Pillow, SQLAlchemy, etc.). Bundled music/SFX are **original procedural audio generated by `scripts/generate_assets.py` (CC0-1.0)** with manifests in `assets/*/licenses.json`. Optional model weights have their own licenses (e.g. Kokoro Apache 2.0, Whisper.cpp MIT). Use only properly licensed assets you add. No proprietary Higgsfield code or models are included.

