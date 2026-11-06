#!/bin/sh
# Build dist/Horus_Control-<version>-x86_64.AppImage from a clean checkout.
set -eu
cd "$(dirname "$0")/.."
ROOT="$PWD"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/horus_control/__init__.py)"
TOOL_VERSION=1.9.0
TOOL="${APPIMAGETOOL:-$ROOT/build/appimagetool-$TOOL_VERSION-x86_64.AppImage}"

if [ ! -x "$TOOL" ]; then
    mkdir -p build
    curl -fL -o "$TOOL.part" \
        "https://github.com/AppImage/appimagetool/releases/download/$TOOL_VERSION/appimagetool-x86_64.AppImage"
    chmod +x "$TOOL.part" && mv "$TOOL.part" "$TOOL"
fi

APPDIR="$ROOT/build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/horus-control" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps" dist
cp -r src/horus_control "$APPDIR/usr/lib/horus-control/"
find "$APPDIR" -name __pycache__ -prune -exec rm -rf {} +
cp packaging/AppRun "$APPDIR/AppRun"
cp packaging/io.github.hypesthyper.HorusControl.desktop "$APPDIR/"
cp packaging/io.github.hypesthyper.HorusControl.desktop "$APPDIR/usr/share/applications/"
cp packaging/horus-control.svg "$APPDIR/horus-control.svg"
cp packaging/horus-control.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
chmod +x "$APPDIR/AppRun"

OUT="dist/Horus_Control-$VERSION-x86_64.AppImage"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"
echo "Built $OUT"
