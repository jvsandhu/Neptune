#!/usr/bin/env bash
# Runs inside the release container (see Containerfile). Builds, checks and packages the
# AppImage, then writes it to /out (mounted from the host's dist/).
set -euo pipefail

cd "$(dirname "$0")/../.."
echo "== building in $(. /etc/os-release && echo "$PRETTY_NAME") / $(ldd --version | head -1)"

# The venv (dependencies and PyInstaller) comes from the image so source edits stay fast.
if [ ! -x .venv/bin/python ]; then
    echo "no .venv in the image; build linux/packaging/Containerfile first" >&2
    exit 1
fi

echo "== helper"
python3 linux/build_helper.py

echo "== tests"
.venv/bin/python -m unittest discover -s linux/tests

echo "== headless render"
xvfb-run -a .venv/bin/python linux/smoke_ui.py /tmp/captures

echo "== package"
bash linux/package.sh

echo "== glibc baseline check"
# The highest GLIBC symbol version any bundled ELF asks for is the oldest system this can run
# on. Scan the libraries too, not just the bootloader, or the number is meaningless.
required=$(find build/appimage/Neptune-linux -type f \( -name '*.so*' -o -perm -u+x \) -print0 \
    | xargs -0 -r objdump -T 2>/dev/null \
    | grep -oE 'GLIBC_[0-9]+\.[0-9]+' | sort -V -u | tail -1)
echo "   highest GLIBC symbol required: ${required:-unknown} (build host: $(ldd --version | head -1 | awk '{print $NF}'))"

mkdir -p /out
cp dist/Neptune.AppImage /out/
( cd /out && sha256sum Neptune.AppImage > Neptune.AppImage.sha256 )
echo "== wrote /out/Neptune.AppImage"
