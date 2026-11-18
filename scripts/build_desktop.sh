#!/usr/bin/env bash
# Assemble the desktop runtime and build the macOS .app / DMG.
#
#   ./scripts/build_desktop.sh              # incremental: sync app files, build
#   ./scripts/build_desktop.sh --python     # also re-copy the CPython runtime
#   ./scripts/build_desktop.sh --deps       # also reinstall bundled site-packages
#   ./scripts/build_desktop.sh --frontend   # rebuild the React app first
#   ./scripts/build_desktop.sh --clean      # wipe dist-desktop before building
#
# The bundled Python is a relocatable standalone CPython (uv-managed). It is
# copied with `cp -RL` to dereference uv's versioned symlink; a plain `cp -R`
# keeps the symlink and sys.prefix follows the original path.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RES="desktop/resources"
UV_PY_DIR="${UV_PYTHON_INSTALL_DIR:-$HOME/.local/share/uv/python}"
LOCAL_PY="/Users/apple/Desktop/forge 4/.data/xdg-data/uv/python/cpython-3.11.18-macos-aarch64-none"
DO_PYTHON=0
DO_DEPS=0
DO_FRONTEND=0
DO_CLEAN=0

for arg in "$@"; do
  case "$arg" in
    --python) DO_PYTHON=1 ;;
    --deps) DO_DEPS=1 ;;
    --frontend) DO_FRONTEND=1 ;;
    --clean) DO_CLEAN=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }; }

need rsync
need npm
need uv

if [[ "$DO_FRONTEND" == "1" || ! -f frontend/dist/index.html ]]; then
  step "Building the web frontend"
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

step "Syncing backend source"
rm -rf "$RES/backend"
mkdir -p "$RES/backend"
rsync -a \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.pytest_cache' --exclude '.DS_Store' \
  backend/ "$RES/backend/"

step "Syncing built frontend"
rm -rf "$RES/frontend-dist"
mkdir -p "$RES/frontend-dist"
rsync -a frontend/dist/ "$RES/frontend-dist/"

step "Syncing assets, docs and models"
rm -rf "$RES/assets" "$RES/docs" "$RES/models"
rsync -a --exclude '.DS_Store' assets/ "$RES/assets/"
rsync -a --exclude '.DS_Store' docs/ "$RES/docs/"
rsync -a --exclude '.DS_Store' models/ "$RES/models/"

# If a local whisper.cpp build exists, ship only what ASR needs at runtime:
# the CLI plus its dylibs (build/bin) and the GGML model. The CMake tree and
# the upstream source add ~85 MB and are not used by the app.
if [[ -d "$RES/models/whisper.cpp" ]]; then
  prune_tmp="$(mktemp -d)"
  mkdir -p "$prune_tmp/bin" "$prune_tmp/models"
  find "$RES/models/whisper.cpp/build/bin" -maxdepth 1 -type f \( -name 'whisper-cli' -o -name 'main' -o -name '*.dylib' \) -exec cp -p {} "$prune_tmp/bin/" \; 2>/dev/null || true
  find "$RES/models/whisper.cpp/models" -maxdepth 1 -type f -name 'ggml-*.bin' -exec cp -p {} "$prune_tmp/models/" \; 2>/dev/null || true
  rm -rf "$RES/models/whisper.cpp"
  mkdir -p "$RES/models/whisper.cpp/build" "$RES/models/whisper.cpp/models"
  [[ -d "$prune_tmp/bin" ]] && cp -Rp "$prune_tmp/bin" "$RES/models/whisper.cpp/build/bin" 2>/dev/null || true
  cp -Rp "$prune_tmp/models/." "$RES/models/whisper.cpp/models/" 2>/dev/null || true
  rm -rf "$prune_tmp"
  printf 'whisper runtime: %s\n' "$(du -sh "$RES/models/whisper.cpp" | cut -f1)"
fi
cp README.md "$RES/README.md" 2>/dev/null || true

if [[ "$DO_PYTHON" == "1" || ! -x "$RES/python/bin/python3" ]]; then
  step "Bundling the CPython runtime"
  SRC="$LOCAL_PY"
  if [[ ! -d "$SRC" ]]; then
    SRC="$(uv python find 3.11 | xargs dirname)/../lib/python3.11/site-packages/.."
  fi
  if [[ ! -d "$SRC" ]]; then
    echo "Could not locate a CPython 3.11 runtime. Install it with: uv python install 3.11" >&2
    exit 1
  fi
  rm -rf "$RES/python"
  cp -RL "$SRC" "$RES/python"
  "$RES/python/bin/python3" - <<'EOF'
import sys, ssl, sqlite3
print(f"bundled python {sys.version.split()[0]} prefix={sys.prefix}")
EOF
fi

if [[ "$DO_DEPS" == "1" || ! -d "$RES/py-packages/fastapi" ]]; then
  step "Installing bundled site-packages"
  rm -rf "$RES/py-packages"
  uv pip install --target "$RES/py-packages" \
    --python "$RES/python/bin/python3" \
    -r backend/requirements.txt
  PYTHONPATH="$RES/py-packages" "$RES/python/bin/python3" - <<'EOF'
import fastapi, uvicorn, sqlalchemy, PIL, imageio_ffmpeg, psutil, httpx, aiosqlite, multipart
print("bundled imports ok · ffmpeg", imageio_ffmpeg.get_ffmpeg_exe().rsplit('/', 1)[-1])
EOF
fi

if [[ ! -f desktop/build/icon.icns ]]; then
  step "Generating the app icon"
  backend/.venv/bin/python scripts/make_icon.py
fi

if [[ ! -d desktop/node_modules ]]; then
  step "Installing Electron toolchain"
  (cd desktop && npm install --no-audit --no-fund)
fi

if [[ "$DO_CLEAN" == "1" ]]; then
  step "Cleaning previous build output"
  rm -rf dist-desktop
fi

step "Packaging the macOS app"
(cd desktop && npx electron-builder --mac --arm64)

step "Building the DMG (macOS hdiutil, no downloads)"
./scripts/make_dmg.sh

step "Build artifacts"
ls -lh dist-desktop 2>/dev/null | sed 's/^/    /'
echo
echo "Open the app with:"
echo "    open \"dist-desktop/mac-arm64/AI Social Video Studio.app\""
echo "or install the DMG:"
echo "    open dist-desktop/*.dmg"
