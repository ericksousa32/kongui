#!/usr/bin/env bash
# Builds the KonGUI AppImage.
#
#   packaging/appimage/build.sh [WHEEL]
#
# Without WHEEL, the wheel is built from this checkout. Everything is written
# under dist/appimage/ (ignored by git); downloads are cached in
# dist/appimage/cache/.
#
# What goes in:
#   * a relocatable CPython from python-appimage (manylinux_2_28 images);
#   * the KonGUI wheel, PyYAML and PySide6-Essentials (the app only uses
#     QtCore, QtGui, QtWidgets and QtSvg, all in Essentials);
#   * AppRun (kongui, or `konsave` as the first argument), the desktop entry,
#     the AppStream metadata and the icon.
# trim.py then removes the parts of PySide6 KonGUI does not use (QML, Designer,
# SQL, tools, stubs) and checks that nothing left lost a library.
# appimagetool embeds the static type-2 runtime: no libfuse2 is needed on the
# host.
#
# Environment: ARCH (default: this machine), PYTHON_FULL_VERSION, PYSIDE6_VERSION.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/packaging/appimage"
ARCH="${ARCH:-$(uname -m)}"
export ARCH  # read by appimagetool
PYTHON_FULL_VERSION="${PYTHON_FULL_VERSION:-3.12.15}"
PYTHON_VERSION="${PYTHON_FULL_VERSION%.*}"
PYTHON_TAG="cp${PYTHON_VERSION/./}"
PYSIDE6_VERSION="${PYSIDE6_VERSION:-6.12.0}"
OUT="$ROOT/dist/appimage"
CACHE="$OUT/cache"
WORK="$OUT/work-$ARCH"

say() { printf '==> %s\n' "$*"; }

fetch() {  # fetch URL FILE: download once into the cache
    if [ ! -s "$CACHE/$2" ]; then
        say "downloading $2"
        curl -fsSL -o "$CACHE/$2.part" "$1"
        mv "$CACHE/$2.part" "$CACHE/$2"
        chmod +x "$CACHE/$2"
    fi
}

mkdir -p "$CACHE"
rm -rf "$WORK"
mkdir -p "$WORK"

# 1. The KonGUI wheel.
if [ $# -ge 1 ]; then
    WHEEL="$(readlink -f "$1")"
else
    say "building the wheel"
    # Build from a clean copy of the checkout so no build/ or *.egg-info is
    # left in the source tree (an egg-info there looks like an installed
    # kongui to the tests).
    git -C "$ROOT" worktree add -q --detach "$WORK/src" HEAD
    python3 -m pip wheel -q --no-deps -w "$WORK/wheel" "$WORK/src"
    git -C "$ROOT" worktree remove --force "$WORK/src"
    WHEEL="$(ls "$WORK"/wheel/kongui-*.whl)"
fi
VERSION="$(basename "$WHEEL" | cut -d- -f2)"
say "KonGUI $VERSION, $ARCH, Python $PYTHON_FULL_VERSION, PySide6-Essentials $PYSIDE6_VERSION"

# 2. The base Python image and appimagetool.
BASE="python$PYTHON_FULL_VERSION-$PYTHON_TAG-$PYTHON_TAG-manylinux_2_28_$ARCH.AppImage"
fetch "https://github.com/niess/python-appimage/releases/download/python$PYTHON_VERSION/$BASE" "$BASE"
fetch "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage" \
    "appimagetool-$ARCH.AppImage"

say "extracting the base image"
(cd "$WORK" && "$CACHE/$BASE" --appimage-extract >/dev/null)
APPDIR="$WORK/AppDir"
mv "$WORK/squashfs-root" "$APPDIR"
PY="$APPDIR/opt/python$PYTHON_VERSION/bin/python$PYTHON_VERSION"

# 3. KonGUI and its dependencies, into the bundled Python.
say "installing KonGUI and its dependencies"
"$PY" -s -m pip install -q --no-warn-script-location --disable-pip-version-check \
    --no-deps "$WHEEL"
"$PY" -s -m pip install -q --no-warn-script-location --disable-pip-version-check \
    "PyYAML>=5.4.1" "PySide6-Essentials==$PYSIDE6_VERSION"
"$PY" -s -m pip uninstall -q -y pip
say "removing the parts of PySide6 KonGUI does not use"
"$PY" -s "$HERE/trim.py" "$APPDIR/opt/python$PYTHON_VERSION/lib/python$PYTHON_VERSION/site-packages"

# 4. Replace python-appimage's own entry point, desktop entry and icon.
rm -f "$APPDIR"/AppRun "$APPDIR"/*.desktop "$APPDIR"/*.png "$APPDIR"/.DirIcon
rm -rf "$APPDIR"/usr/share/applications "$APPDIR"/usr/share/metainfo "$APPDIR"/usr/share/icons
sed "s/@PYTHON_VERSION@/$PYTHON_VERSION/g" "$HERE/AppRun" >"$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
mkdir -p "$APPDIR/usr/share/applications"
cp "$HERE/kongui.desktop" "$APPDIR/usr/share/applications/kongui.desktop"
ln -s usr/share/applications/kongui.desktop "$APPDIR/kongui.desktop"
mkdir -p "$APPDIR/usr/share/metainfo"
cp "$HERE/kongui.appdata.xml" "$APPDIR/usr/share/metainfo/kongui.appdata.xml"
ICONS="$ROOT/kongui/gui/data/icons/hicolor"
for size_dir in "$ICONS"/*/apps; do
    size="$(basename "$(dirname "$size_dir")")"
    mkdir -p "$APPDIR/usr/share/icons/hicolor/$size/apps"
    cp "$size_dir"/kongui.* "$APPDIR/usr/share/icons/hicolor/$size/apps/"
done
cp "$ICONS/256x256/apps/kongui.png" "$APPDIR/kongui.png"
ln -s kongui.png "$APPDIR/.DirIcon"

# The base image extracts with some 0700 folders: whoever runs the AppImage must
# be able to read everything.
chmod -R a+rX "$APPDIR"

# 5. Package. appimagetool runs extracted, so the build machine needs no FUSE.
# --no-appstream: appimagetool would refuse the metadata over its one accepted
# warning (the id "kongui" is not reverse-DNS); tests/test_appimage.py runs the
# validator itself and allows only that warning.
TARGET="$OUT/KonGUI-$VERSION-$ARCH.AppImage"
say "packaging $TARGET"
APPIMAGE_EXTRACT_AND_RUN=1 "$CACHE/appimagetool-$ARCH.AppImage" \
    --no-appstream "$APPDIR" "$TARGET" >"$WORK/appimagetool.log" 2>&1 \
    || { cat "$WORK/appimagetool.log"; exit 1; }
(cd "$OUT" && sha256sum "$(basename "$TARGET")" >"$(basename "$TARGET").sha256")
say "done: $(du -h "$TARGET" | cut -f1)  $TARGET"
