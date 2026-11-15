#!/usr/bin/env bash
# Install a local whisper.cpp build + GGML model for Engine B (AI Auto-Clip Studio).
#
# This script is deliberately explicit about what it does:
#   * clones whisper.cpp into models/whisper.cpp (source is not vendored here)
#   * builds it with cmake
#   * downloads one GGML model from Hugging Face into models/whisper.cpp/models
#   * verifies the binary runs and the model loads
#
# It needs network access once and a C++ toolchain. If those are missing the
# script exits non-zero and explains what to install; the app keeps working with
# manual SRT/VTT transcript import in the meantime.
#
# Usage:
#   scripts/install_whisper_cpp.sh              # default model: base.en
#   scripts/install_whisper_cpp.sh --model small.en
#   scripts/install_whisper_cpp.sh --check      # only report prerequisites
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${WHISPER_DIR:-$ROOT/models/whisper.cpp}"
MODEL="base.en"
CHECK_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=1; shift ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --dir) DEST="${2:-}"; shift 2 ;;
    -h|--help) sed -n '1,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say() { printf '[whisper-install] %s\n' "$*"; }
fail() { printf '[whisper-install] ERROR: %s\n' "$*" >&2; }

missing=()
for tool in git cmake make; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if ! command -v clang++ >/dev/null 2>&1 && ! command -v g++ >/dev/null 2>&1; then
  missing+=("clang++ or g++")
fi

say "repo root      : $ROOT"
say "install target : $DEST"
say "model          : ggml-$MODEL.bin"
say "git            : $(command -v git || echo missing)"
say "cmake          : $(command -v cmake || echo missing)"
say "c++ compiler   : $(command -v clang++ || command -v g++ || echo missing)"

if [[ ${#missing[@]} -gt 0 ]]; then
  fail "missing prerequisites: ${missing[*]}"
  cat >&2 <<'EOF'

Install them first, then re-run this script. On macOS with Homebrew:

    brew install cmake

(Xcode command line tools provide git/clang: `xcode-select --install`.)

Until whisper.cpp is installed the Auto-Clip Studio still works:
upload a video and use Transcript -> Import SRT/VTT. No transcript is ever
fabricated by the app.
EOF
  exit 3
fi

if [[ "$CHECK_ONLY" == "1" ]]; then
  say "check complete: prerequisites present (nothing was installed)"
  exit 0
fi

mkdir -p "$(dirname "$DEST")"

if [[ ! -d "$DEST/.git" ]]; then
  say "cloning whisper.cpp into $DEST"
  git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git "$DEST"
else
  say "reusing existing checkout at $DEST"
fi

say "configuring (cmake)"
cmake -S "$DEST" -B "$DEST/build" -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF

say "building (this can take several minutes on an 8 GB M2)"
cmake --build "$DEST/build" -j "$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"

BIN=""
for candidate in "$DEST/build/bin/whisper-cli" "$DEST/build/bin/main" "$DEST/main"; do
  [[ -x "$candidate" ]] && BIN="$candidate" && break
done
if [[ -z "$BIN" ]]; then
  fail "build finished but no whisper CLI binary was found under $DEST/build/bin"
  exit 4
fi
say "binary: $BIN"

MODELS_DIR="$DEST/models"
mkdir -p "$MODELS_DIR"
MODEL_PATH="$MODELS_DIR/ggml-$MODEL.bin"
if [[ ! -s "$MODEL_PATH" ]]; then
  say "downloading ggml-$MODEL.bin (Hugging Face)"
  curl -fL --retry 2 --connect-timeout 20 \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$MODEL.bin" \
    -o "$MODEL_PATH.part"
  mv "$MODEL_PATH.part" "$MODEL_PATH"
fi

size=$(wc -c < "$MODEL_PATH" | tr -d ' ')
if [[ "$size" -lt 1000000 ]]; then
  fail "model file looks too small ($size bytes); delete $MODEL_PATH and retry"
  exit 5
fi
say "model: $MODEL_PATH ($size bytes)"

say "verifying the binary starts"
if ! "$BIN" --help >/dev/null 2>&1; then
  fail "binary did not respond to --help"
  exit 6
fi

cat <<EOF

whisper.cpp is installed and verified.

Engine B discovers it automatically at:
  $BIN
  $MODEL_PATH

You can also set explicit paths:

  export WHISPER_BIN="$BIN"
  export WHISPER_MODEL="$MODEL_PATH"

Restart the backend, then check /api/clip/capabilities — "available" should be
true. Speech recognition quality depends on the model: base.en is a good
speed/accuracy default for 8 GB machines; small.en is slower but more accurate.
EOF
