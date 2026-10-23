#!/usr/bin/env bash
# Install the widget and its companion service from a checkout or GitHub release.
set -euo pipefail

VERSION="1.1.1"
REPOSITORY="military1/KCromecast"
NO_PACKAGES=0
CHECK_ONLY=0
INSTALL_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --no-system-packages) NO_PACKAGES=1 ;;
        --check) CHECK_ONLY=1; INSTALL_ARGS+=("$arg") ;;
        --no-restart|--no-panel) INSTALL_ARGS+=("$arg") ;;
        -h|--help)
            cat <<'EOF'
Usage: bash install.sh [--check] [--no-system-packages] [--no-restart] [--no-panel]

Run from a terminal inside KDE Plasma 6, without sudo.
Missing dependencies are installed with your system package manager.
--check               Report missing requirements without installing anything
--no-system-packages  Do not run a system package manager
--no-restart          Load updated QML at your next login
--no-panel            Add the widget manually after installation
EOF
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

if [[ "$(id -u)" -eq 0 ]]; then
    printf 'Run this script as your desktop user, without sudo.\n' >&2
    exit 1
fi
if ! command -v plasmashell >/dev/null; then
    printf 'A running KDE Plasma 6 desktop is required.\n' >&2
    exit 1
fi
PLASMA_VERSION="$(plasmashell --version 2>/dev/null)"
if [[ ! "$PLASMA_VERSION" =~ (^|[[:space:]])6\. ]]; then
    printf 'KDE Plasma 6 is required; detected: %s\n' "$PLASMA_VERSION" >&2
    exit 1
fi

has_qdbus() {
    command -v qdbus6 >/dev/null || command -v qdbus-qt6 >/dev/null ||
        [[ -x /usr/lib/qt6/bin/qdbus || -x /usr/lib64/qt6/bin/qdbus || -x /usr/lib/x86_64-linux-gnu/qt6/bin/qdbus ]]
}
has_qml_module() {
    local module="$1" root
    local -a extra=()
    IFS=: read -r -a extra <<< "${QML_IMPORT_PATH:-}"
    for root in "${extra[@]}" /usr/lib/qt6/qml /usr/lib64/qt6/qml /usr/lib/*-linux-gnu/qt6/qml; do
        [[ -n "$root" && -f "$root/$module/qmldir" ]] && return 0
    done
    return 1
}
missing_dependencies() {
    local missing=0 name
    for name in python3 msgfmt kpackagetool6 systemctl; do
        if ! command -v "$name" >/dev/null; then printf 'Missing: %s\n' "$name"; missing=1; fi
    done
    if ! has_qdbus; then printf 'Missing: Qt 6 qdbus\n'; missing=1; fi
    if ! has_qml_module QtWebSockets; then printf 'Missing: QtWebSockets QML module\n'; missing=1; fi
    if ! has_qml_module QtQuick/Effects; then printf 'Missing: QtQuick.Effects QML module\n'; missing=1; fi
    if command -v python3 >/dev/null && ! python3 -c 'import sys, venv, ensurepip; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
        printf 'Missing: Python 3.11+ with venv and ensurepip\n'; missing=1
    fi
    return "$missing"
}
if ! missing_dependencies; then
    if [[ "$CHECK_ONLY" -eq 1 || "$NO_PACKAGES" -eq 1 ]]; then
        printf 'Install the missing requirements, then run the installer again.\n' >&2
        exit 1
    fi
    if ! command -v sudo >/dev/null; then printf 'Install the missing packages as administrator, then rerun this script.\n' >&2; exit 1; fi
    printf 'Installing missing system dependencies. sudo may ask for your password.\n'
    if command -v pacman >/dev/null; then
        sudo pacman -S --needed --noconfirm python python-pip gettext qt6-tools qt6-websockets qt6-declarative kpackage
    elif command -v apt-get >/dev/null; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv python3-pip gettext kpackagetool6 qdbus-qt6 qml6-module-qtwebsockets qml6-module-qtquick-effects
    elif command -v dnf >/dev/null; then
        sudo dnf install -y python3 python3-pip gettext qt6-qttools qt6-qtwebsockets qt6-qtdeclarative kf6-kpackage
    else
        printf 'Automatic dependency installation supports Arch, Debian/Ubuntu and Fedora.\nInstall the listed requirements using your distribution, then rerun with --no-system-packages.\n' >&2
        exit 1
    fi
    missing_dependencies || { printf 'Some requirements are still missing. Check the messages above.\n' >&2; exit 1; }
fi

SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fi
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/scripts/install.py" ]]; then
    python3 "$SCRIPT_DIR/scripts/install.py" "${INSTALL_ARGS[@]}"
elif [[ "$CHECK_ONLY" -eq 1 ]]; then
    printf 'Requirements found. Run the installer without --check to install KCromecast.\n'
else
    TEMP_DIR="$(mktemp -d -t kcromecast-install.XXXXXXXX)"
    trap 'rm -rf -- "$TEMP_DIR"' EXIT
    # urllib and zipfile avoid requiring git, curl or unzip after bootstrap.
    python3 - "$TEMP_DIR" "$REPOSITORY" "$VERSION" <<'PY'
from pathlib import Path
import hashlib
import sys
from urllib.request import Request, urlopen
import zipfile

folder, repository, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
filename = f"KCromecast-{version}-source.zip"
base = f"https://github.com/{repository}/releases/download/v{version}/"
def download(name):
    request = Request(base + name, headers={"User-Agent": "KCromecast installer"})
    with urlopen(request, timeout=60) as response:
        return response.read(32 * 1024 * 1024)
data = download(filename)
checksums = download("SHA256SUMS").decode()
expected = next((line.split()[0] for line in checksums.splitlines() if line.split()[-1] == filename), None)
if not expected or hashlib.sha256(data).hexdigest() != expected:
    raise SystemExit("Download checksum mismatch; please retry.")
archive = folder / filename
archive.write_bytes(data)
with zipfile.ZipFile(archive) as source:
    for member in source.infolist():
        path = Path(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit("Invalid archive path")
    source.extractall(folder)
PY
    python3 "$TEMP_DIR/KCromecast-$VERSION/scripts/install.py" "${INSTALL_ARGS[@]}"
fi
