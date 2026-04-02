#!/usr/bin/env bash
# ┌─────────────────────────────────────────────┐
# │  kim — keep in mind                         │
# │  installer for Linux & macOS                │
# └─────────────────────────────────────────────┘
# curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/install.sh | bash

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

_info()   { echo -e "${CYAN}→${NC} $*"; }
_ok()     { echo -e "${GREEN}✓${NC} $*"; }
_warn()   { echo -e "${YELLOW}!${NC} $*"; }
_die()    { echo -e "${RED}✗ $*${NC}"; exit 1; }
_header() { echo -e "\n${BOLD}${BLUE}$*${NC}"; echo "──────────────────────────────"; }

REPO="https://raw.githubusercontent.com/pratikwayal01/kim/main"
BIN_DIR="$HOME/.local/bin"
KIM_DIR="$HOME/.kim"
OS="$(uname -s)"
ARCH="$(uname -m)"

_header "kim — keep in mind"
_info "OS     : $OS ($ARCH)"
_info "Install: $BIN_DIR/kim"
_info "Config : $KIM_DIR/config.json"
echo ""

# ── Python 3 ─────────────────────────────────────────────────────────────────
_header "Checking Python 3"
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        major=$("$cmd" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)
        if [[ "$major" == "3" ]]; then
            PYTHON="$cmd"
            _ok "$cmd $($cmd --version 2>&1 | grep -oE '[0-9.]+')"
            break
        fi
    fi
done

[[ -z "$PYTHON" ]] && {
    _warn "Python 3 not found — attempting install..."
    case "$OS" in
        Linux)
            if   command -v pacman  &>/dev/null; then sudo pacman -Sy --noconfirm python
            elif command -v apt-get &>/dev/null; then sudo apt-get install -y python3
            elif command -v dnf     &>/dev/null; then sudo dnf install -y python3
            elif command -v zypper  &>/dev/null; then sudo zypper install -y python3
            else _die "Can't auto-install Python. Install python3 manually then re-run."
            fi ;;
        Darwin)
            command -v brew &>/dev/null || _die "Homebrew not found. See https://brew.sh"
            brew install python3 ;;
        *) _die "Unsupported OS: $OS" ;;
    esac
    PYTHON="python3"
    _ok "Python 3 installed"
}

PYTHON_PATH="$(command -v "$PYTHON")"

# ── notify-send on Linux ──────────────────────────────────────────────────────
if [[ "$OS" == "Linux" ]] && ! command -v notify-send &>/dev/null; then
    _warn "notify-send not found — installing libnotify..."
    if   command -v pacman  &>/dev/null; then sudo pacman -Sy --noconfirm libnotify
    elif command -v apt-get &>/dev/null; then sudo apt-get install -y libnotify-bin
    elif command -v dnf     &>/dev/null; then sudo dnf install -y libnotify
    fi
    _ok "libnotify installed"
fi

# ── Download kim package and wrapper ──────────────────────────────────────────
_header "Installing kim"
mkdir -p "$BIN_DIR" "$KIM_DIR"

if [[ "${KIM_LOCAL:-0}" == "1" ]]; then
    # Local mode: used when running from cloned repo
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cp -r "$SCRIPT_DIR/kim" "$KIM_DIR/kim"
    _ok "Copied kim package from local source"
else
    _info "Downloading kim package..."
    ZIP_URL="https://github.com/pratikwayal01/kim/archive/refs/heads/main.zip"
    ZIP_PATH="/tmp/kim-main.zip"
    EXTRACT_PATH="/tmp/kim-install"

    curl -fsSL "$ZIP_URL" -o "$ZIP_PATH"
    _ok "Downloaded package"

    # Remove previous extraction if exists
    rm -rf "$EXTRACT_PATH"
    unzip -q "$ZIP_PATH" -d "$EXTRACT_PATH"
    _ok "Extracted package"

    # Copy kim/ package to install directory
    cp -r "$EXTRACT_PATH/kim-main/kim" "$KIM_DIR/kim"
    _ok "Installed to $KIM_DIR"

    # Cleanup
    rm -f "$ZIP_PATH"
    rm -rf "$EXTRACT_PATH"
fi

# ── Create the kim shim in PATH ───────────────────────────────────────────────
cat > "$BIN_DIR/kim" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$KIM_DIR:\$PYTHONPATH"
exec "$PYTHON_PATH" -m kim "\$@"
EOF
chmod +x "$BIN_DIR/kim"
_ok "Created: $BIN_DIR/kim"

# ── PATH check ────────────────────────────────────────────────────────────────
if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    _warn "$BIN_DIR is not in your PATH."
    echo ""

    SHELL_NAME="$(basename "$SHELL")"
    case "$SHELL_NAME" in
        fish)
            FISH_CONF="$HOME/.config/fish/config.fish"
            echo "  Adding to $FISH_CONF ..."
            echo "fish_add_path $BIN_DIR" >> "$FISH_CONF"
            _ok "Added to fish PATH. Restart shell or: source $FISH_CONF"
            ;;
        zsh)
            ZSHRC="$HOME/.zshrc"
            echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$ZSHRC"
            _ok "Added to $ZSHRC. Restart shell or: source $ZSHRC"
            ;;
        bash)
            BASHRC="$HOME/.bashrc"
            echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$BASHRC"
            _ok "Added to $BASHRC. Restart shell or: source $BASHRC"
            ;;
        *)
            _warn "Add this to your shell config manually:"
            echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
            ;;
    esac
fi

# ── Startup setup ─────────────────────────────────────────────────────────────
_header "Setting up autostart"

case "$OS" in
# ── Linux: systemd user service ───────────────────────────────────────────────
Linux)
    SERVICE_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SERVICE_DIR"
    UID_NUM=$(id -u)

    cat > "$SERVICE_DIR/kim.service" <<EOF
[Unit]
Description=kim — keep in mind reminder daemon
After=graphical-session.target

[Service]
Type=simple
ExecStart=$BIN_DIR/kim start
Restart=on-failure
RestartSec=10s
Environment=DISPLAY=:0
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${UID_NUM}/bus
Environment=XDG_RUNTIME_DIR=/run/user/${UID_NUM}
WorkingDirectory=$KIM_DIR

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable kim.service
    systemctl --user restart kim.service
    sleep 1

    if systemctl --user is-active --quiet kim.service; then
        _ok "systemd service running"
    else
        _warn "Service may have failed: systemctl --user status kim.service"
    fi
    ;;

# ── macOS: launchd agent ──────────────────────────────────────────────────────
Darwin)
    PLIST="$HOME/Library/LaunchAgents/io.kim.reminder.plist"
    mkdir -p "$HOME/Library/LaunchAgents"

    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>io.kim.reminder</string>
    <key>ProgramArguments</key>
    <array>
        <string>$BIN_DIR/kim</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>WorkingDirectory</key>
    <string>$KIM_DIR</string>
    <key>StandardOutPath</key>
    <string>$KIM_DIR/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$KIM_DIR/stderr.log</string>
</dict>
</plist>
EOF

    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    _ok "launchd agent loaded"
    ;;
esac

# ── Done ──────────────────────────────────────────────────────────────────────
_header "Done 🎉"
echo -e "  ${BOLD}kim${NC} is installed and running.\n"
echo -e "  ${CYAN}Commands:${NC}"
echo "    kim status          → show what's running"
echo "    kim list            → list all reminders"
echo "    kim edit            → edit config in \$EDITOR"
echo "    kim logs            → view recent logs"
echo "    kim stop / start    → control the daemon"
echo ""
echo -e "  ${CYAN}Config:${NC} $KIM_DIR/config.json"
echo ""
_ok "Stay healthy. Keep it in mind."
