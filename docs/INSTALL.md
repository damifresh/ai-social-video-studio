# Installation & Setup Guide

Target: **macOS on Apple Silicon (M2, 8 GB unified memory)**. The studio runs fully locally (no cloud inference, no accounts).

## Option A — Install the packaged desktop app (recommended)

1. Open `dist-desktop/AI Social Video Studio-1.0.0-arm64.dmg` (or unzip `...-arm64-mac.zip`) and move **AI Social Video Studio** to **Applications**.
2. First launch: the app is **unsigned**. If macOS blocks it, **right-click the app → Open → Open**, or go to **System Settings → Privacy & Security → Open Anyway**.
3. The app starts its bundled Python/FFmpeg/backend automatically on a loopback port and opens the studio UI. No extra installs are required.
4. **Data location:** `~/Library/Application Support/AI Social Video Studio/data/` (SQLite DB, projects, renders, logs). Menu: **AI Social Video Studio → Open Data Folder / Open Backend Log**.

Bundled engines in this build: FFmpeg (imageio-ffmpeg v7.1 arm64), macOS `say` TTS. **Kokoro MLX** and **Whisper.cpp** are not bundled — see “Optional engines”.

## Option B — Run from source (dev)

### Prerequisites
- macOS 13+ (developed/tested on macOS 27.x), Apple Silicon
- **Node.js + npm** (v26 used) for the frontend and desktop build
- **Python 3.11** via [`uv`](https://docs.astral.sh/uv/) (recommended) or Homebrew
- **FFmpeg**: resolved as `FFMPEG_PATH` → bundled app/bin → `imageio-ffmpeg` wheel binary → `ffmpeg` on PATH. `brew install ffmpeg` is fine but not required when `imageio-ffmpeg` is installed.
- (Optional, for desktop packaging) `uv` + macOS `iconutil`/`hdiutil`

### Backend
```bash
cd local-ai-video-studio
uv venv backend/.venv --python 3.11
uv pip install --python backend/.venv -r backend/requirements.txt

# run API (serves API; also serves frontend/dist if built)
PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# or: ./scripts/start_backend.sh
```
Health: `http://127.0.0.1:8000/health`

### Frontend (dev)
```bash
cd local-ai-video-studio/frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api,/health,/data,/media to :8000)
npm run build      # production build -> frontend/dist
```

### Build the macOS desktop app
```bash
cd local-ai-video-studio
./scripts/build_desktop.sh --frontend --python --deps   # full build
./scripts/build_desktop.sh                               # incremental
# outputs in dist-desktop/ (.app, .zip, .dmg)
```
Notes: the build copies a **dereferenced** relocatable CPython (`cp -RL`), installs deps into `desktop/resources/py-packages`, and packages with Electron/electron-builder. If Electron download stalls, fetch the matching `electron-v*-darwin-arm64.zip`, unpack to `desktop/node_modules/electron/dist`, and retry (see `docs/DESKTOP_APP.md`).

## Bundled media assets

Procedural CC0-1.0 music/SFX (generated, no third-party samples) live in `assets/music` and `assets/sfx` with `licenses.json`. Regenerate:
```bash
backend/.venv/bin/python scripts/generate_assets.py
```

## Optional engines (not required, not verified in this build)

### Kokoro TTS (MLX, Apple Silicon)
```bash
# separate Python 3.10–3.12 env recommended
pip install "mlx-audio" misaki   # or: pip install "kokoro-mlx[audio]"
# brew install espeak-ng  # optional
```
Select a `kokoro:*` voice in the UI. If unavailable the pipeline falls back to **macOS `say`** and records `tts_fallback` in project metadata. Feasibility/peak memory on 8 GB is unproven.

### Whisper.cpp (subtitle alignment / ASR)

Engine B can use whisper.cpp for local transcription. The repo ships an explicit installer that also verifies the binary and model:

```bash
scripts/install_whisper_cpp.sh --check   # prerequisites only (no changes)
brew install cmake                       # if cmake is missing
scripts/install_whisper_cpp.sh           # clone + build + download ggml-base.en.bin
```

Manual equivalent:
```bash
git clone https://github.com/ggml-org/whisper.cpp.git models/whisper.cpp
cd models/whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j --config Release
bash ./models/download-ggml-model.sh base
```
Set `WHISPER_BIN` / `WHISPER_MODEL` or place under `models/whisper.cpp/...` as detected by `backend/app/core/config.py`. Default Engine A subtitles are **narration-timing based** (SRT/VTT/ASS) and work without Whisper; Engine B accepts SRT/VTT import and never fabricates a transcript.

## Environment variables (paths)

`LAVS_DATA_DIR`, `LAVS_CLIP_DIR` (Engine B storage, default `data/clip_projects`), `LAVS_ASSETS_DIR`, `LAVS_MODELS_DIR`, `LAVS_FRONTEND_DIST`, `FFMPEG_PATH`, `WHISPER_BIN`, `WHISPER_MODEL` override default locations (useful for packaging).

## Storage layout

- Dev data: `data/studio.db`, `data/projects/<id>/{script.json,scenes.json,timings.json,result.json,audio/,images/,video/,subs/,renders/,logs/}`, `data/clip_projects/<id>/{source,analysis,clips,exports,logs,tmp}`
- Desktop data: `~/Library/Application Support/AI Social Video Studio/data/...`
- Models: `models/` (large, not committed) — see `models/README.md`

