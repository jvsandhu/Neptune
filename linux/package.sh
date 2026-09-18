#!/usr/bin/env bash
# linux/package.sh — Build Neptune as an AppImage (local candidate artifact).
#
# Host requirements: x86_64, glibc >= 2.44 (CachyOS/Arch or equivalent).
# This artifact is a HOST-BUILD CANDIDATE — glibc 2.44 means it will NOT run
# on older distros (Ubuntu 22.04 has glibc 2.35, Fedora 38 has 2.37).
# For broad support, build inside a manylinux container or equivalent CI.
#
# External runtime requirements (NOT bundled):
#   - Steam with Forza Horizon 6 installed
#   - protontricks (system package)
#   - X11 display or Wayland with XWayland
#
# The AppImage does NOT self-update.  Re-download to upgrade.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
BUILD="$ROOT/build/appimage"
DIST="$ROOT/dist"
APPDIR="$BUILD/Neptune.AppDir"
SPEC="$SCRIPT_DIR/neptune.spec"

# appimagetool — pinned version with SHA-256 verification.
APPIMAGETOOL_VERSION="1.9.1"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
APPIMAGETOOL="$BUILD/appimagetool-${APPIMAGETOOL_VERSION}"

# ---------------------------------------------------------------------------
log() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }

verify_sha256() {
    local path="$1" expected="$2" label="$3"
    local got
    got=$(sha256sum "$path" | cut -d' ' -f1)
    if [ "$got" != "$expected" ]; then
        echo "FATAL: $label SHA-256 mismatch" >&2
        echo "  expected: $expected" >&2
        echo "  got:      $got" >&2
        exit 1
    fi
    echo "  $label verified (${got:0:16}…)"
}

# ---------------------------------------------------------------------------
# Step 0: Clean previous builds (keep appimagetool cache).
log "Cleaning previous build"
rm -rf "$BUILD/Neptune.AppDir" "$BUILD/work" "$BUILD/Neptune-linux"
rm -f "$DIST/Neptune.AppImage"
mkdir -p "$DIST" "$BUILD"

# ---------------------------------------------------------------------------
# Step 1: Obtain appimagetool with hash verification.
if [ ! -x "$APPIMAGETOOL" ]; then
    log "Downloading appimagetool $APPIMAGETOOL_VERSION"
    curl -fSL --retry 3 -o "$APPIMAGETOOL" "$APPIMAGETOOL_URL"
    chmod +x "$APPIMAGETOOL"
fi
verify_sha256 "$APPIMAGETOOL" "$APPIMAGETOOL_SHA256" "appimagetool"

# ---------------------------------------------------------------------------
# Step 2: PyInstaller onedir build.
log "PyInstaller onedir build"
"$ROOT/.venv/bin/pyinstaller" --noconfirm \
    --distpath "$BUILD" \
    --workpath "$BUILD/work" \
    "$SPEC"

BUNDLE="$BUILD/Neptune-linux"

# Verify the bundle was produced.
if [ ! -x "$BUNDLE/Neptune" ]; then
    echo "FATAL: PyInstaller did not produce $BUNDLE/Neptune" >&2
    exit 1
fi
echo "  Bundle: $(du -sh "$BUNDLE" | cut -f1)"

# ---------------------------------------------------------------------------
# Step 3: Assemble AppDir.
log "Assembling AppDir"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APPDIR/usr/share/applications"

# Main executable and _internal (shared libs, Python, Qt, bundled assets).
cp -a "$BUNDLE/Neptune"  "$APPDIR/Neptune"
cp -a "$BUNDLE/_internal" "$APPDIR/_internal"

# Icon — desktop entry + AppImage root (appimagetool reads ./neptune.png).
cp "$ROOT/assets/icons/neptune.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/neptune.png"
cp "$ROOT/assets/icons/neptune.png" "$APPDIR/neptune.png"

# Desktop entry.
cat > "$APPDIR/neptune.desktop" << 'EOF'
[Desktop Entry]
Type=Application
Name=Neptune
Exec=Neptune
Icon=neptune
Categories=Utility;
Comment=Forza Horizon 6 tuning tool
Terminal=false
StartupNotify=false
EOF

# ---------------------------------------------------------------------------
# Step 4: AppRun wrapper.
#
# Responsibilities:
#   FUSE fallback is handled by the AppImage runtime BEFORE AppRun:
#   invoke the artifact with --appimage-extract-and-run when needed.
#   2. X11 default — select xcb for X11 and XWayland sessions.
#   3. LD_LIBRARY_PATH hygiene — PyInstaller's bootloader injects _internal/
#      into LD_LIBRARY_PATH.  When Neptune spawns protontricks-launch, the
#      child must load system libraries, not the frozen bundle's copies.
#      The Python code in transport.py also strips this via LD_LIBRARY_PATH_ORIG;
#      this AppRun-level strip is a defense-in-depth measure.
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/sh
# Neptune AppRun
set -e

APPDIR="$(dirname "$(readlink -f "$0")")"

# --- X11/XWayland default ---
if [ -n "${DISPLAY:-}" ] && [ -z "${QT_QPA_PLATFORM:-}" ]; then
    export QT_QPA_PLATFORM=xcb
fi

# --- LD_LIBRARY_PATH defense-in-depth ---
# Strip any paths under $APPDIR from LD_LIBRARY_PATH so that child processes
# (protontricks-launch → pressure-vessel → Wine) load system libraries.
# The frozen binary's own bootloader re-sets LD_LIBRARY_PATH for itself.
if [ -n "${LD_LIBRARY_PATH:-}" ]; then
    _cleaned=""
    _old_ifs="$IFS"
    IFS=:
    for _p in $LD_LIBRARY_PATH; do
        case "$_p" in
            "$APPDIR"|"$APPDIR"/*) ;;  # skip AppDir entries
            *) _cleaned="${_cleaned:+${_cleaned}:}${_p}" ;;
        esac
    done
    IFS="$_old_ifs"
    export LD_LIBRARY_PATH="$_cleaned"
fi

exec "$APPDIR/Neptune" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# ---------------------------------------------------------------------------
# Step 5: Build AppImage.
log "Building AppImage"
ARCH=x86_64 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$DIST/Neptune.AppImage"

# ---------------------------------------------------------------------------
# Step 6: Verify artifact.
log "Artifact"
ls -lh "$DIST/Neptune.AppImage"
echo ""
echo "Host glibc:  $(ldd --version 2>&1 | head -1)"
echo "Host:        $(uname -n) ($(uname -r))"
echo "Architecture: x86_64"
echo ""
echo "The artifact runs on this host's glibc or newer, no older. Build inside"
echo "linux/packaging/Containerfile to set that baseline deliberately."
echo ""
echo "Runtime requirements (not bundled):"
echo "  - Steam with Forza Horizon 6"
echo "  - protontricks (system package)"
echo "  - X11 or Wayland with XWayland"
