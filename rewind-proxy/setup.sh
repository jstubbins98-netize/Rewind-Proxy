#!/usr/bin/env bash
# =============================================================================
#  Rewind-Proxy - setup.sh
#
#  Checks for Python 3, installs it and pip if missing, creates a virtual
#  environment in ./venv, and installs all required dependencies.
#
#  Tested on: Raspberry Pi OS (Bookworm/Bullseye), Ubuntu 20.04+, Debian 11+
#
#  Usage:
#    chmod +x setup.sh
#    ./setup.sh           # installs as current user (sudo used only when needed)
#    sudo ./setup.sh      # run as root (required for apt-get on fresh installs)
# =============================================================================

set -euo pipefail

VENV_DIR="$(cd "$(dirname "$0")" && pwd)/venv"
REQUIREMENTS="$(cd "$(dirname "$0")" && pwd)/requirements.txt"
MIN_PYTHON_MINOR=10   # Python 3.10 minimum

# -- Colours ------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[setup]${RESET} $*"; }
success() { echo -e "${GREEN}[setup]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[setup]${RESET} $*"; }
error()   { echo -e "${RED}[setup] ERROR:${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }

# -- Helper: run apt-get with sudo if not already root ------------------------
apt_install() {
    if [[ $EUID -eq 0 ]]; then
        apt-get install -y --no-install-recommends "$@"
    elif command -v sudo &>/dev/null; then
        sudo apt-get install -y --no-install-recommends "$@"
    else
        die "Not root and 'sudo' not available. Run as root or install packages manually: $*"
    fi
}

echo ""
echo -e "${BOLD}======================================================"
echo -e "  Rewind-Proxy setup"
echo -e "======================================================${RESET}"
echo ""

# -- 1. Detect OS / package manager -------------------------------------------
info "Detecting operating system..."

USE_APT=false
if command -v apt-get &>/dev/null; then
    USE_APT=true
    info "  Package manager: apt-get (Debian/Raspberry Pi OS)"
else
    warn "  apt-get not found - will skip system-level installs."
    warn "  Make sure Python 3.10+ and python3-venv are installed manually."
fi

# -- 2. Check / install Python 3 ----------------------------------------------
info "Checking for Python 3.${MIN_PYTHON_MINOR}+..."

PYTHON_BIN=""
for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c 'import sys; print(sys.version_info.minor)')
        if [[ "$ver" -ge "$MIN_PYTHON_MINOR" ]]; then
            PYTHON_BIN="$candidate"
            full_ver=$("$candidate" --version 2>&1)
            success "  Found: $full_ver ($(command -v "$candidate"))"
            break
        fi
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    if [[ "$USE_APT" == true ]]; then
        warn "  Python 3.${MIN_PYTHON_MINOR}+ not found - installing via apt-get..."
        if [[ $EUID -ne 0 ]]; then
            info "  (sudo required for apt-get)"
        fi
        apt_install python3 python3-pip python3-venv
        # Re-detect after install
        for candidate in python3 python3.12 python3.11 python3.10; do
            if command -v "$candidate" &>/dev/null; then
                ver=$("$candidate" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
                if [[ "$ver" -ge "$MIN_PYTHON_MINOR" ]]; then
                    PYTHON_BIN="$candidate"
                    break
                fi
            fi
        done
        [[ -n "$PYTHON_BIN" ]] || die "apt-get installed Python but it still isn't accessible. Try opening a new shell and running setup.sh again."
        success "  Installed: $($PYTHON_BIN --version)"
    else
        die "Python 3.${MIN_PYTHON_MINOR}+ is required but was not found.\nInstall it from https://www.python.org/downloads/ and re-run this script."
    fi
fi

# -- 3. Ensure pip is available -----------------------------------------------
info "Checking pip..."
if ! "$PYTHON_BIN" -m pip --version &>/dev/null; then
    warn "  pip not found - installing..."
    if [[ "$USE_APT" == true ]]; then
        apt_install python3-pip
    else
        "$PYTHON_BIN" -c "import urllib.request; exec(urllib.request.urlopen('https://bootstrap.pypa.io/get-pip.py').read())" \
            || die "Failed to install pip. Install it manually and re-run."
    fi
fi
success "  pip: $("$PYTHON_BIN" -m pip --version)"

# -- 4. Ensure python3-venv / ensurepip is available --------------------------
info "Checking venv support..."
if ! "$PYTHON_BIN" -m venv --help &>/dev/null; then
    warn "  python3-venv not found - installing..."
    if [[ "$USE_APT" == true ]]; then
        apt_install python3-venv
    else
        die "python3-venv is required. Install it via your package manager and re-run."
    fi
fi
success "  venv: OK"

# -- 5. Create virtual environment --------------------------------------------
if [[ -d "$VENV_DIR" ]]; then
    info "Virtual environment already exists at ${VENV_DIR}"
    info "  To rebuild from scratch: rm -rf ${VENV_DIR} && ./setup.sh"
else
    info "Creating virtual environment at ${VENV_DIR}..."
    "$PYTHON_BIN" -m venv "${VENV_DIR}"
    success "  Virtual environment created."
fi

# Activate
VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"

# -- 6. Install requirements --------------------------------------------------
if [[ ! -f "$REQUIREMENTS" ]]; then
    die "requirements.txt not found at $REQUIREMENTS"
fi

info "Installing dependencies from requirements.txt..."

# First attempt: use the venv's own pip (works on standard Pi OS / Debian).
# On some environments (e.g. Nix-based, Replit) the venv pip is a wrapper
# that points back to a read-only system pip and fails with a --user error.
# In that case we fall back to installing directly into the venv's
# site-packages directory using the system pip with --target.
VENV_SITE="$("$VENV_PYTHON" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"

if "$VENV_PYTHON" -m pip install -r "$REQUIREMENTS" 2>/dev/null; then
    success "  Dependencies installed via venv pip."
else
    warn "  Venv pip failed (likely a read-only Nix/system pip) - using --target fallback."
    # Use the system python pip with --target so packages land inside the venv
    if "$PYTHON_BIN" -m pip install --target="$VENV_SITE" -r "$REQUIREMENTS"; then
        success "  Dependencies installed via --target into $VENV_SITE."
    else
        die "pip install failed. Try running: $PYTHON_BIN -m pip install --target='$VENV_SITE' -r '$REQUIREMENTS'"
    fi
fi

# -- 8. Verify key imports ----------------------------------------------------
info "Verifying installation..."
"$VENV_PYTHON" -c "import requests, bs4, lxml; print('  requests:', requests.__version__); print('  beautifulsoup4:', bs4.__version__); print('  lxml:', lxml.__version__)"
success "  All imports OK."

# -- 9. Done -----------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}======================================================"
echo -e "  Setup complete!"
echo -e "======================================================${RESET}"
echo ""
echo -e "  To start Rewind-Proxy:"
echo ""
echo -e "    ${BOLD}${VENV_DIR}/bin/python run.py${RESET}"
echo ""
echo -e "  On Linux (for full ethernet and dnsmasq auto-setup):"
echo ""
echo -e "    ${BOLD}sudo ${VENV_DIR}/bin/python run.py${RESET}"
echo ""
echo -e "  Or activate the venv first:"
echo ""
echo -e "    ${BOLD}source ${VENV_DIR}/bin/activate${RESET}"
echo -e "    ${BOLD}python run.py${RESET}          # or: sudo \$(which python) run.py"
echo ""
