#!/bin/sh
# Build dist/K609_Keyboard_Control-<version>-x86_64.AppImage, self-contained (Python, GTK 4, PyGObject).
#
# Releases are built by GitHub Actions on Ubuntu 22.04. To build locally on any distro, have podman
# or docker installed: the script re-runs itself in an Ubuntu 22.04 container.
set -eu
cd "$(dirname "$0")/.."
ROOT="$PWD"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/k609_control/__init__.py)"
TOOL_VERSION=1.9.0

if ! grep -q 'VERSION_ID="22.04"' /etc/os-release 2>/dev/null || [ ! -x /usr/bin/apt-get ]; then
    if [ "${K609_IN_CONTAINER:-}" = 1 ]; then echo "Needs Ubuntu 22.04" >&2; exit 1; fi
    runner="$(command -v podman || command -v docker || true)"
    if [ -z "$runner" ]; then
        echo "Build on Ubuntu 22.04, or install podman or docker to build in a container." >&2
        exit 1
    fi
    exec "$runner" run --rm -e K609_IN_CONTAINER=1 -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
        -v "$ROOT:/src" -w /src docker.io/library/ubuntu:22.04 sh tools/build-appimage.sh
fi

SUDO=""
[ "$(id -u)" = 0 ] || SUDO=sudo
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq --no-install-recommends \
    python3 python3-gi gir1.2-gtk-4.0 gir1.2-graphene-1.0 libgtk-4-1 libgdk-pixbuf2.0-bin \
    librsvg2-common adwaita-icon-theme libglib2.0-bin file curl ca-certificates desktop-file-utils >/dev/null

APPDIR="$ROOT/build/AppDir"
rm -rf "$APPDIR"
mkdir -p build dist
python3 tools/make_appdir.py "$APPDIR"
desktop-file-validate "$APPDIR/io.github.HypestHyper.K609KeyboardControl.desktop"

TOOL="$ROOT/build/appimagetool-$TOOL_VERSION-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL.part" \
        "https://github.com/AppImage/appimagetool/releases/download/$TOOL_VERSION/appimagetool-x86_64.AppImage"
    chmod +x "$TOOL.part" && mv "$TOOL.part" "$TOOL"
fi
OUT="dist/K609_Keyboard_Control-$VERSION-x86_64.AppImage"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"
if [ -n "${HOST_UID:-}" ]; then chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" build dist; fi
echo "Built $OUT"
