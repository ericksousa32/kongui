#!/usr/bin/env bash
# Installs, updates or removes KonGUI for the current user.
#
# What it does (nothing outside your home folder, never as root):
#   1. downloads the wheel of a KonGUI release from GitHub (the newest one,
#      pre-releases included, unless --release says which) and checks it against
#      the release's SHA256SUMS; or takes a wheel you already have (--wheel);
#   2. installs it, with PySide6, in its own virtual environment
#      (~/.venvs/kongui), because KonGUI ships its own copy of the `konsave`
#      Python package and must not replace an existing Konsave;
#   3. links the `kongui` command into ~/.local/bin (never `konsave`);
#   4. adds KonGUI to the application menu (~/.local/share/applications), with
#      its icon (~/.local/share/icons/hicolor) when the release has one.
# Running it again updates KonGUI in place. --uninstall undoes 2-4 and keeps your
# profiles, safety copies and conf.yaml (~/.config/konsave).
#
# Usage: bash install.sh [--release VERSION | --wheel FILE] [--uninstall] [--help]
#
# Documentation: README.md, "Installing the pre-release".

set -euo pipefail

REPO="ericksousa32/kongui"
# These can be changed for a mirror or for the tests; the defaults are GitHub's.
DOWNLOAD_BASE="${KONGUI_DOWNLOAD_BASE:-https://github.com/$REPO/releases/download}"
API_URL="${KONGUI_API_URL:-https://api.github.com/repos/$REPO/releases?per_page=20}"
VENV="${KONGUI_VENV:-$HOME/.venvs/kongui}"
EXTRAS="${KONGUI_EXTRAS-gui}"   # the tests install without PySide6 (empty value)
BIN_DIR="$HOME/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
ICON_NAME="kongui"
LINK="$BIN_DIR/kongui"
DESKTOP="$APPS_DIR/kongui.desktop"
MARKER="X-KonGUI-Installed-By=install.sh"
WHEEL_PATTERN='^kongui-[0-9][A-Za-z0-9.!+_]*-py3-none-any\.whl$'

say() { printf 'kongui-install: %s\n' "$*"; }
warn() { printf 'kongui-install: warning: %s\n' "$*" >&2; }
die() {
    printf 'kongui-install: error: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: bash install.sh [OPTION]

Installs or updates KonGUI for the current user, or removes it.

  (no option)         install or update to the newest release (pre-releases
                      included), downloaded from GitHub and checked
  --release VERSION   install or update to that release, e.g. 0.1.0a1
  --wheel FILE        install a wheel you already have (checked against a
                      SHA256SUMS file next to it, if there is one)
  --uninstall         remove KonGUI (keeps ~/.config/konsave)
  -h, --help          show this help

KonGUI goes to ~/.venvs/kongui, the `kongui` command to ~/.local/bin, the
menu entry to ~/.local/share/applications and its icon to
~/.local/share/icons/hicolor. Nothing needs root.
EOF
}

# ---------------------------------------------------------------- arguments

ACTION="install"
RELEASE=""
WHEEL_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --release)
            [ $# -ge 2 ] || { usage >&2; exit 2; }
            RELEASE="${2#v}"
            shift 2
            ;;
        --release=*)
            RELEASE="${1#--release=}"
            RELEASE="${RELEASE#v}"
            shift
            ;;
        --wheel)
            [ $# -ge 2 ] || { usage >&2; exit 2; }
            WHEEL_ARG="$2"
            shift 2
            ;;
        --wheel=*)
            WHEEL_ARG="${1#--wheel=}"
            shift
            ;;
        --uninstall)
            ACTION="uninstall"
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            printf 'kongui-install: unknown option: %s\n\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done
if [ -n "$RELEASE" ] && [ -n "$WHEEL_ARG" ]; then
    die "use either --release or --wheel, not both"
fi
if [ "$ACTION" = "uninstall" ] && { [ -n "$RELEASE" ] || [ -n "$WHEEL_ARG" ]; }; then
    die "--uninstall takes no other option"
fi

# ------------------------------------------------------------------ checks

if [ "$(id -u)" = "0" ]; then
    die "do not run this as root: KonGUI is installed for your own user (and refuses to run as root)"
fi
if [ "$(uname -s)" != "Linux" ]; then
    die "KonGUI only works on Linux"
fi
[ -n "${HOME:-}" ] && [ -d "$HOME" ] || die "HOME is not set to an existing folder"

# A folder is KonGUI's environment only if it is a virtual environment with the
# kongui command in it; nothing else is ever deleted or replaced.
is_kongui_venv() {
    [ -f "$1/pyvenv.cfg" ] && [ -e "$1/bin/kongui" ]
}

# The folder of icons shipped inside the installed package
# (kongui/gui/data/icons/hicolor), found without importing KonGUI. Prints
# nothing for a release without icons (0.1.0a1 and 0.1.0a2 have none).
packaged_icon_dir() {
    local dir
    [ -x "$VENV/bin/python" ] || return 0
    dir="$("$VENV/bin/python" -I -c '
import importlib.util, os
spec = importlib.util.find_spec("kongui")
print(os.path.join(os.path.dirname(spec.origin), "gui", "data", "icons", "hicolor"))
' 2>/dev/null)" || return 0
    if [ -d "$dir" ]; then
        printf '%s\n' "$dir"
    fi
}

# The icon files of a hicolor folder, as SIZE/apps/kongui.EXT, one per line.
icon_files() { # DIR
    (cd "$1" && find . -path "./*/apps/$ICON_NAME.*" -type f | sed 's|^\./||' | sort)
}

refresh_icons() {
    [ -d "$ICON_ROOT" ] || return 0
    touch "$ICON_ROOT" 2>/dev/null || true # tells icon loaders that the theme changed
    # A GTK cache that already exists must be kept in step, or it hides the icon.
    if [ -f "$ICON_ROOT/icon-theme.cache" ] && command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache --quiet --force --ignore-theme-index "$ICON_ROOT" >/dev/null 2>&1 || true
    fi
}

# Removes the installed icons that are the ones of the installed package (same
# bytes); any other kongui icon is left and reported. Runs before the
# environment is deleted, since that is where the originals are.
remove_icons() {
    local src rel why gone=0
    src="$(packaged_icon_dir)"
    if [ -n "$src" ]; then
        while IFS= read -r rel; do
            if [ -f "$ICON_ROOT/$rel" ] && cmp -s "$src/$rel" "$ICON_ROOT/$rel"; then
                rm -f "$ICON_ROOT/$rel"
                # SIZE/apps and SIZE, only if left empty
                rmdir "$ICON_ROOT/${rel%/*}" "$ICON_ROOT/${rel%%/*}" 2>/dev/null || true
                gone=1
            fi
        done < <(icon_files "$src")
        why="is not the icon this script installed"
    else
        why="cannot be checked without KonGUI's environment"
    fi
    if [ -d "$ICON_ROOT" ]; then
        while IFS= read -r rel; do
            warn "$ICON_ROOT/$rel $why; left as it is"
        done < <(icon_files "$ICON_ROOT")
    fi
    if [ "$gone" = 1 ]; then
        say "removed the icons from $ICON_ROOT"
        refresh_icons
    fi
    [ "$gone" = 1 ]
}

# --------------------------------------------------------------- uninstall

uninstall() {
    local removed=0 target
    if [ -L "$LINK" ]; then
        target="$(readlink "$LINK")"
        if [ "$target" = "$VENV/bin/kongui" ] || [ ! -e "$LINK" ]; then
            rm -f "$LINK"
            say "removed the command $LINK"
            removed=1
        else
            warn "$LINK points to $target, not to $VENV; left as it is"
        fi
    elif [ -e "$LINK" ]; then
        warn "$LINK is not a link made by this script; left as it is"
    fi
    if [ -f "$DESKTOP" ]; then
        if grep -qx "$MARKER" "$DESKTOP" || grep -qF "Exec=$VENV/bin/kongui" "$DESKTOP"; then
            rm -f "$DESKTOP"
            say "removed the menu entry $DESKTOP"
            removed=1
        else
            warn "$DESKTOP was not made by this script; left as it is"
        fi
    fi
    if remove_icons; then
        removed=1
    fi
    if [ -d "$VENV" ]; then
        if is_kongui_venv "$VENV"; then
            rm -rf "$VENV"
            rmdir "$(dirname "$VENV")" 2>/dev/null || true # only if left empty
            say "removed $VENV"
            removed=1
        else
            die "$VENV is not KonGUI's environment; refusing to delete it"
        fi
    fi
    refresh_menu
    if [ "$removed" = 1 ]; then
        say "KonGUI was removed. Your profiles, safety copies and conf.yaml are still in ~/.config/konsave."
    else
        say "KonGUI is not installed here; nothing to do."
    fi
}

refresh_menu() {
    if command -v kbuildsycoca6 >/dev/null 2>&1; then
        kbuildsycoca6 >/dev/null 2>&1 || true
    fi
}

if [ "$ACTION" = "uninstall" ]; then
    uninstall
    exit 0
fi

# ----------------------------------------------------------------- install

command -v python3 >/dev/null 2>&1 || die "python3 is missing (on Fedora: sudo dnf install python3)"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' ||
    die "KonGUI needs Python 3.9 or newer; this python3 is $(python3 -c 'import platform; print(platform.python_version())')"
python3 -c 'import venv, ensurepip' 2>/dev/null ||
    die "python3 cannot create virtual environments (on Debian/Ubuntu: install python3-venv)"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is missing (it comes with coreutils)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/kongui-install.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

download() { # URL FILE
    curl --fail --silent --show-error --location --proto '=https,file' \
        --retry 2 --output "$2" "$1"
}

# Checks FILE against a SHA256SUMS file; fails if it is not listed or differs.
check_sum() { # FILE SUMS
    local name expected actual
    name="$(basename "$1")"
    expected="$(awk -v f="$name" '$2 == f || $2 == "*" f { print $1; exit }' "$2")"
    [ -n "$expected" ] || die "$(basename "$2") does not list $name"
    actual="$(sha256sum "$1" | awk '{ print $1 }')"
    [ "$expected" = "$actual" ] || die "checksum mismatch for $name: the file is damaged or not the published one"
    say "checksum ok: $name"
}

newest_release() {
    command -v curl >/dev/null 2>&1 || die "curl is missing (on Fedora: sudo dnf install curl)"
    download "$API_URL" "$WORK/releases.json" ||
        die "could not ask GitHub for the releases (no network?); try again, or use --release VERSION"
    python3 -I - "$WORK/releases.json" <<'PY' || die "no KonGUI release found on GitHub"
import json, re, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    releases = json.load(handle)
for release in releases:
    tag = str(release.get("tag_name", ""))
    if not release.get("draft") and re.fullmatch(r"v[0-9][0-9A-Za-z.]*", tag):
        print(tag[1:])
        break
else:
    sys.exit(1)
PY
}

if [ -n "$WHEEL_ARG" ]; then
    [ -f "$WHEEL_ARG" ] || die "no such file: $WHEEL_ARG"
    WHEEL_NAME="$(basename "$WHEEL_ARG")"
    printf '%s\n' "$WHEEL_NAME" | grep -Eq "$WHEEL_PATTERN" ||
        die "$WHEEL_NAME does not look like a KonGUI wheel (kongui-<version>-py3-none-any.whl)"
    WHEEL="$WORK/$WHEEL_NAME"
    cp "$WHEEL_ARG" "$WHEEL"
    SUMS="$(dirname "$WHEEL_ARG")/SHA256SUMS"
    if [ -f "$SUMS" ]; then
        check_sum "$WHEEL" "$SUMS"
    else
        warn "no SHA256SUMS next to $WHEEL_NAME: its checksum was not checked"
    fi
    VERSION="${WHEEL_NAME#kongui-}"
    VERSION="${VERSION%-py3-none-any.whl}"
else
    command -v curl >/dev/null 2>&1 || die "curl is missing (on Fedora: sudo dnf install curl)"
    if [ -n "$RELEASE" ]; then
        VERSION="$RELEASE"
    else
        VERSION="$(newest_release)"
        say "newest release: $VERSION"
    fi
    printf '%s\n' "kongui-$VERSION-py3-none-any.whl" | grep -Eq "$WHEEL_PATTERN" ||
        die "not a version: $VERSION"
    WHEEL_NAME="kongui-$VERSION-py3-none-any.whl"
    WHEEL="$WORK/$WHEEL_NAME"
    say "downloading KonGUI $VERSION"
    download "$DOWNLOAD_BASE/v$VERSION/SHA256SUMS" "$WORK/SHA256SUMS" ||
        die "release $VERSION not found (or no network): $DOWNLOAD_BASE/v$VERSION/"
    download "$DOWNLOAD_BASE/v$VERSION/$WHEEL_NAME" "$WHEEL" ||
        die "could not download $WHEEL_NAME"
    check_sum "$WHEEL" "$WORK/SHA256SUMS"
fi

# The environment: reused when it works, made again when it does not (for
# example after a Fedora upgrade replaced the Python it was made with).
if [ -e "$VENV" ] && ! is_kongui_venv "$VENV" && [ -n "$(ls -A "$VENV" 2>/dev/null)" ]; then
    die "$VENV exists and is not KonGUI's environment; move it away or set KONGUI_VENV"
fi
if is_kongui_venv "$VENV" && ! "$VENV/bin/python" -c 'import sys' >/dev/null 2>&1; then
    say "the environment in $VENV no longer works (was Python upgraded?); making it again"
    rm -rf "$VENV"
fi
if [ ! -x "$VENV/bin/python" ]; then
    say "creating the environment $VENV"
    mkdir -p "$(dirname "$VENV")"
    python3 -m venv "$VENV" || die "could not create $VENV"
fi

TARGET="$WHEEL"
if [ -n "$EXTRAS" ]; then
    TARGET="${WHEEL}[${EXTRAS}]"
fi
say "installing $WHEEL_NAME${EXTRAS:+ with [$EXTRAS]} (this can take a few minutes the first time)"
"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade "$TARGET" ||
    die "pip could not install KonGUI (see the messages above)"

INSTALLED="$("$VENV/bin/python" -I -c 'import importlib.metadata as m; print(m.version("kongui"))' 2>/dev/null)" ||
    die "KonGUI is not importable after the installation"
[ "$INSTALLED" = "$VERSION" ] ||
    die "installed version is $INSTALLED, expected $VERSION"
[ -x "$VENV/bin/kongui" ] || die "the kongui command is missing from $VENV/bin"

# The command, in ~/.local/bin. Only a link is ever replaced, never a real file.
mkdir -p "$BIN_DIR"
if [ -L "$LINK" ] || [ ! -e "$LINK" ]; then
    if [ -L "$LINK" ] && [ "$(readlink "$LINK")" != "$VENV/bin/kongui" ]; then
        say "replacing the old link $LINK -> $(readlink "$LINK")"
    fi
    ln -sfn "$VENV/bin/kongui" "$LINK"
    LINK_OK=1
else
    warn "$LINK exists and is not a link; left as it is (start KonGUI from the menu or with $VENV/bin/kongui)"
    LINK_OK=0
fi

# The icon, from the installed package into the user's hicolor theme. A release
# without icons still installs; its menu entry just has no Icon= line.
ICON_LINE=""
ICON_SRC="$(packaged_icon_dir)"
if [ -n "$ICON_SRC" ] && [ -n "$(icon_files "$ICON_SRC")" ]; then
    while IFS= read -r rel; do
        mkdir -p "$(dirname "$ICON_ROOT/$rel")"
        cp -f "$ICON_SRC/$rel" "$ICON_ROOT/$rel"
    done < <(icon_files "$ICON_SRC")
    refresh_icons
    ICON_LINE="Icon=$ICON_NAME"
    say "installed the icon into $ICON_ROOT"
else
    say "this release has no icon; the menu shows a generic one"
fi

# The menu entry. StartupWMClass and the desktop file name (set by the app) tie
# the window to this entry, so the panel shows the same name and icon.
mkdir -p "$APPS_DIR"
EXEC="$VENV/bin/kongui"
case "$EXEC" in
    *[[:space:]]*) EXEC="\"$EXEC\"" ;;
esac
if [ -f "$DESKTOP" ] && ! grep -qx "$MARKER" "$DESKTOP" && ! grep -q '^Name=KonGUI$' "$DESKTOP"; then
    warn "$DESKTOP exists and is not KonGUI's menu entry; left as it is"
else
    cat >"$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=KonGUI
GenericName=Plasma profiles
Comment=Save, apply, export and import KDE Plasma configuration profiles (Konsave)
Exec=$EXEC
${ICON_LINE:+$ICON_LINE
}Terminal=false
StartupWMClass=kongui
Categories=Settings;DesktopSettings;Utility;
Keywords=konsave;profile;plasma;backup;theme;
$MARKER
EOF
    refresh_menu
fi

say "KonGUI $INSTALLED is installed."
say "Open it from the application menu (search for KonGUI), or run: kongui (or kongui --demo)."
if [ "$LINK_OK" = 1 ]; then
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) say "note: $BIN_DIR is not in your PATH yet; open a new terminal, or use $VENV/bin/kongui" ;;
    esac
fi
say "To update, run this script again; to remove KonGUI: bash install.sh --uninstall"
