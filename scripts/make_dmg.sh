#!/usr/bin/env bash
# Build the distributable DMG from the packaged .app using only macOS tooling.
#
# electron-builder's DMG target tries to download helper bundles at build time;
# this script avoids that entirely so a fully local rebuild works offline once
# Electron itself is present.
#
#   ./scripts/make_dmg.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP="$ROOT/dist-desktop/mac-arm64/AI Social Video Studio.app"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist" 2>/dev/null || echo 1.0.0)"
OUT="$ROOT/dist-desktop/AI Social Video Studio-$VERSION-arm64.dmg"

if [[ ! -d "$APP" ]]; then
  echo "Packaged app not found: $APP" >&2
  echo "Run ./scripts/build_desktop.sh first." >&2
  exit 1
fi

STAGE="$(mktemp -d "${TMPDIR:-/private/tmp}/lavs_dmg.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

echo "Staging $(basename "$APP") …"
# ditto preserves resource forks, symlinks and permissions better than cp -R for app bundles.
ditto "$APP" "$STAGE/AI Social Video Studio.app"
ln -s /Applications "$STAGE/Applications"

# A small README on the volume is friendlier than an empty window.
cat > "$STAGE/Read Me.txt" <<'TXT'
AI Social Video Studio — fully local, no cloud inference.

Drag the app into Applications, then open it.

First launch notes
  • The app is unsigned (built locally). If macOS blocks it:
      right-click the app → Open → Open, or
      System Settings → Privacy & Security → "Open Anyway".
  • Your projects live in:
      ~/Library/Application Support/AI Social Video Studio/data
  • Bundled music and SFX are original CC0-1.0 audio (assets/music/licenses.json).
TXT

rm -f "$OUT"
echo "Creating DMG …"
hdiutil create \
  -volname "AI Social Video Studio" \
  -srcfolder "$STAGE" \
  -fs HFS+ \
  -format UDZO \
  -ov \
  "$OUT" >/dev/null

echo
ls -lh "$OUT"
echo "Install with:  open \"$OUT\""
