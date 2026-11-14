# Desktop App (macOS `.app`)

This build packages the **full web version** (React/Vite frontend + FastAPI backend + SQLite + FFmpeg + bundled Python) into a native Electron shell that runs entirely on the local machine. There is no cloud inference, no account, and no network dependency after installation except any optional future model downloads the user chooses.

## What is bundled

| Component | Location inside the app bundle | Notes |
|---|---|---|
| Electron shell | `Contents/Resources/app.asar` (`main.cjs`, `preload.cjs`) | Spawns backend, waits for `/health`, loads SPA |
| CPython 3.11 runtime | `Contents/Resources/runtime/python/` | Relocatable standalone CPython (uv), copied with `cp -RL` to dereference the uv symlink |
| Python site-packages | `Contents/Resources/runtime/py-packages/` | `fastapi`, `uvicorn`, `sqlalchemy`, `pillow`, `imageio-ffmpeg` (bundled FFmpeg), etc. |
| Backend source | `Contents/Resources/runtime/backend/` | FastAPI app launched as `uvicorn app.main:app` on a free loopback port |
| Built frontend | `Contents/Resources/runtime/frontend-dist/` | Production Vite build served by the backend SPA fallback |
| Bundled assets | `Contents/Resources/runtime/assets/` | CC0-1.0 procedural music/SFX + `licenses.json` manifests |
| Docs / models dir | `Contents/Resources/runtime/docs/`, `.../models/` | Installed docs and an empty models area for optional engines |

## Runtime behavior

1. **Single instance**: a second launch focuses the existing window.
2. **Backend lifecycle**: main process picks a free `127.0.0.1` port, spawns Python with `PYTHONPATH=backend:py-packages` and `LAVS_*` env vars, polls `/health` (up to ~90 s), then loads `http://127.0.0.1:<port>/`.
3. **Data location** (per-user, survives app updates): `~/Library/Application Support/AI Social Video Studio/data/` (`studio.db`, `projects/<id>/...`, previews, logs). Bundled assets/models stay inside the app; renders and project state live in user data.
4. **Clean shutdown**: quitting the window/app sends `SIGTERM` to the backend (with a kill fallback) so FFmpeg/model subprocesses are not left running.
5. **Security posture**: renderer runs with context isolation and a minimal, allowlisted preload bridge (`revealDataFolder`, `openPath` restricted to studio folders, `openExternal` only for `https://`). Page/target content is treated as data by the backend services.
6. **Logging**: backend stdout/stderr are captured to `~/Library/Application Support/AI Social Video Studio/logs/backend.log` (menu: **AI Social Video Studio → Open Backend Log**).

## Building

Prerequisites on the build machine: Node.js/npm, `uv`, the project Python venv with backend deps, and macOS `iconutil`/`hdiutil`.

```bash
# from local-ai-video-studio/
./scripts/build_desktop.sh --frontend --python --deps   # first/full build
./scripts/build_desktop.sh                               # incremental rebuild
```

Outputs:
- `dist-desktop/mac-arm64/AI Social Video Studio.app` — runnable app bundle
- `dist-desktop/AI Social Video Studio-1.0.0-arm64-mac.zip` — zipped app
- `dist-desktop/AI Social Video Studio-1.0.0-arm64.dmg` — installable disk image (built via `scripts/make_dmg.sh` using `hdiutil`)

The DMG is produced with macOS `hdiutil` (no electron-builder DMG helper download) so the final packaging step works offline once the Electron dist is present.

## Electron/toolchain notes

- Electron binary download can be slow or flaky on some networks. The build was completed by downloading `electron-v45.3.2-darwin-arm64.zip` (npmmirror CDN), unpacking to `desktop/node_modules/electron/dist`, writing `path.txt`, and pointing `electron-builder` at it via `build.electronDist`.
- The app is **unsigned** (`identity: null`). On a fresh Mac, first launch may require **right-click → Open → Open** or **System Settings → Privacy & Security → Open Anyway**.

## Verified packaged behavior (2026-11-14, Apple M2 / 8 GB)

- Launched `.app`, backend started on loopback and served `/health` (`ffmpeg_ok=true`, `say=true`, bundled imageio-ffmpeg v7.1, `kokoro=false`, `whisper=false`).
- SPA routes loaded (`/`, `/library`, `/exports`, `/settings`, `/project/:id`), bundled music served from `/media/music/*.wav` (HTTP 200).
- Real render executed through the packaged app backend: **73.66 s** 16:9 1280×720 @ 30 fps, **5.17 MB**, H.264 High + AAC 48 kHz stereo, **33 cues** burned, loudness ≈ **−15.8 LUFS / −3.4 dBTP**, **peak 728 MB**, render **17.0 s**. Output written to user data: `~/Library/Application Support/AI Social Video Studio/data/projects/<id>/renders/final_16x9_720p.mp4` with SRT/VTT/ASS sidecars.

## Known gaps / honest limits

- **Kokoro MLX** and **Whisper.cpp** are not bundled/installed by default; the packaged app uses macOS `say` narration and timing-based subtitles with recorded fallbacks.
- **Diffusion/generated footage** is not enabled on 8 GB; visuals are animated graphics/stills by default and labeled as such.
- The app is not notarized/signed; Gatekeeper steps may be required on first launch.
- Browser-automation click-through of the Electron window was not captured in this environment (a full-screen desktop screenshot was captured while the app was running; backend/UI endpoints and a real packaged render were verified).
