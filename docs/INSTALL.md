# Installation Guide

## Prerequisites (macOS Apple Silicon recommended)
- macOS 13+ (tested on macOS 27.x dev environment), Apple M2/8 GB target
- **Node.js + npm** (for frontend; v18+ recommended, v26 used here)
- **Python 3.11+** (recommended via `uv` or Homebrew) for backend
- **FFmpeg** (required). On this machine a working FFmpeg 9.x binary was obtained via `imageio-ffmpeg` inside the backend venv; you can also `brew install ffmpeg`.
- (Optional) `cmake`, `git` for building Whisper.cpp; Python 3.10+ venv for MLX/Kokoro.

## Backend
```bash
cd local-ai-video-studio
# create venv (uv recommended)
uv venv backend/.venv --python 3.11
uv pip install --python backend/.venv -r backend/requirements.txt

# run API
PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Health check: `http://127.0.0.1:8000/health`

## Frontend
```bash
cd local-ai-video-studio/frontend
npm install
npm run dev   # http://localhost:5173 (proxies /api,/health,/data to :8000)
# production build
npm run build
```

## FFmpeg notes
- The app resolves FFmpeg in order: `FFMPEG_PATH` env → `imageio-ffmpeg` bundled binary → `ffmpeg` on PATH.
- If `brew install ffmpeg` is blocked (e.g. outdated CLT), `imageio-ffmpeg` in the venv provides a usable binary.

## Optional: Whisper.cpp (subtitles/transcription alignment)
```bash
git clone https://github.com/ggml-org/whisper.cpp.git models/whisper.cpp
cd models/whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j --config Release
bash ./models/download-ggml-model.sh base   # or tiny/small for 8 GB
```
Use timing-based SRT generation by default; wire whisper.cpp path in settings when available.

## Optional: Kokoro TTS (MLX, Apple Silicon)
```bash
# in a Python 3.10-3.12 venv
pip install "mlx-audio" misaki
# or: pip install "kokoro-mlx[audio]"
# optional: brew install espeak-ng
```
Select a `kokoro:*` voice in UI; if unavailable the pipeline falls back to macOS `say` and records the fallback.

## Storage
- SQLite DB: `data/studio.db`
- Projects/artifacts: `data/projects/<project-id>/` (script, scenes, audio, images, video segments, subs, renders, logs)
- Models: `models/` (gitignored, downloaded separately)
