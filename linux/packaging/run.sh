#!/usr/bin/env bash
# Build the release AppImage on the host by running the pinned build container.
#
#   ./linux/packaging/run.sh
#
# Writes dist/Neptune.AppImage and dist/Neptune.AppImage.sha256. Docker must be running.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
image="neptune-appimage-builder:12"

echo "== docker build"
docker build -t "$image" -f "$root/linux/packaging/Containerfile" "$root"

mkdir -p "$root/dist"
echo "== docker run"
docker run --rm -v "$root/dist:/out" "$image"

ls -la "$root/dist/Neptune.AppImage"
cat "$root/dist/Neptune.AppImage.sha256"
