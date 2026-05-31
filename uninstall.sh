#!/usr/bin/env bash
# ┌─────────────────────────────────────────────┐
# │  kim — keep in mind                         │
# │  standalone uninstaller for Linux & macOS   │
# └─────────────────────────────────────────────┘
# Usage (works when piped from curl):
#   curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/uninstall.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/uninstall.sh | bash -s -- -y

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

_info()   { echo -e "${CYAN}→${NC} $*"; }
_ok()     { echo -e "${GREEN}✓${NC} $*"; }
_warn()   { echo -e "${YELLOW}!${NC} $*"; }
_header() { echo -e "\n${BOLD}${BLUE}$*${NC}"; echo "──────────────────────────────"; }

BIN_DIR="$HOME/.local/bin"
KIM_DIR="$HOME/.kim"
OS="$(uname -s)"

_header "Uninstall kim"

# -y / --yes flag skips the confirmation prompt
SKIP_CONFIRM=0
for arg in "${@:-}"; do
    [[ "$arg" == "-y" || "$arg" == "--yes" ]] && SKIP_CONFIRM=1
done

if [[ "$SKIP_CONFIRM" == "0" ]]; then
    printf "This will remove kim data, binaries, and autostart config.\nContinue? (y/N): "
    # Read from /dev/tty so this works when piped from curl
    if [[ -t 0 ]]; then
        read -r confirm
    else
        read -r confirm < /dev/tty
    fi
    [[ "$confirm" != "y" && "$confirm" != "Y" ]] && { echo "Cancelled."; exit 0; }
fi

# ── Stop the daemon ────────────────────────────────────────────────────────────
if [[ -f "$KIM_DIR/kim.pid" ]]; then
    pid=$(cat "$KIM_DIR/kim.pid" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        sleep 1
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
        _ok "Stopped daemon (PID $pid)"
    fi
fi

# ── Remove OS autostart ────────────────────────────────────────────────────────
case "$OS" in
    Linux)
        systemctl --user stop    kim.service 2>/dev/null || true
        systemctl --user disable kim.service 2>/dev/null || true
        systemctl --user daemon-reload       2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/kim.service"
        _ok "Removed systemd service"
        ;;
    Darwin)
        plist="$HOME/Library/LaunchAgents/io.kim.reminder.plist"
        launchctl unload "$plist" 2>/dev/null || true
        rm -f "$plist"
        _ok "Removed launchd agent"
        ;;
esac

# ── Remove pip package metadata if present ────────────────────────────────────
if command -v python3 &>/dev/null; then
    python3 -m pip uninstall --break-system-packages kim-reminder -y \
        2>/dev/null || true
    _ok "Removed pip package (if present)"
fi

# ── Remove binary and data ────────────────────────────────────────────────────
rm -f "$BIN_DIR/kim"
_ok "Removed $BIN_DIR/kim"

rm -rf "$KIM_DIR"
_ok "Removed $KIM_DIR"

_header "Done"
echo -e "${GREEN}kim has been completely uninstalled.${NC}"
echo "Open a new terminal for PATH changes to take effect."
