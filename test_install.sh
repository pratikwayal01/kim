#!/usr/bin/env bash
# ┌─────────────────────────────────────────────┐
# │  install.sh test suite                      │
# │  Run: bash test_install.sh                  │
# └─────────────────────────────────────────────┘
set -euo pipefail

PASS=0
FAIL=0
TOTAL=0

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

_ok()   { PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); echo -e "  ${GREEN}PASS${NC} $*"; }
_fail() { FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); echo -e "  ${RED}FAIL${NC} $*"; }
_info() { echo -e "\n${YELLOW}▶ $*${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="$SCRIPT_DIR/install.sh"
TEST_BIN_DIR="$HOME/.local/bin"
TEST_KIM_DIR="$HOME/.kim"

# ── Pre-flight ────────────────────────────────────────────────────────────────
_info "Pre-flight checks"

[[ -f "$INSTALLER" ]] || { echo "install.sh not found at $INSTALLER"; exit 1; }
command -v python3 &>/dev/null || { echo "python3 not found"; exit 1; }
command -v bash &>/dev/null || { echo "bash not found"; exit 1; }

_ok "install.sh exists"
_ok "python3 available"
_ok "bash available"

# ── Cleanup function ──────────────────────────────────────────────────────────
cleanup() {
    _info "Cleaning up test artifacts"
    # Stop any running daemon
    if [[ -f "$TEST_KIM_DIR/kim.pid" ]]; then
        pid=$(cat "$TEST_KIM_DIR/kim.pid" 2>/dev/null || true)
        [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
        rm -f "$TEST_KIM_DIR/kim.pid"
    fi
    # Remove systemd service if created
    rm -f "$HOME/.config/systemd/user/kim.service"
    # Remove binary shim
    rm -f "$TEST_BIN_DIR/kim"
    # Remove data dir
    rm -rf "$TEST_KIM_DIR"
    # Remove launchd plist if on macOS
    rm -f "$HOME/Library/LaunchAgents/io.kim.reminder.plist"
}

# Start clean
cleanup

# ── Test 1: Local install (KIM_LOCAL=1) ──────────────────────────────────────
_info "Test 1: Local install from source"

output=$(KIM_LOCAL=1 bash "$INSTALLER" 2>&1) || true

if echo "$output" | grep -q "Installed to\|Copied kim package"; then
    _ok "Install completed without fatal error"
else
    _fail "Install output missing success indicator"
fi

if [[ -f "$TEST_BIN_DIR/kim" ]]; then
    _ok "Binary shim created at $TEST_BIN_DIR/kim"
else
    _fail "Binary shim not found at $TEST_BIN_DIR/kim"
fi

if [[ -d "$TEST_KIM_DIR/kim" ]]; then
    _ok "kim package installed to $TEST_KIM_DIR/kim"
else
    _fail "kim package not found at $TEST_KIM_DIR/kim"
fi

# ── Test 2: kim binary works ─────────────────────────────────────────────────
_info "Test 2: kim binary executes correctly"

if [[ -f "$TEST_BIN_DIR/kim" ]]; then
    version_output=$("$TEST_BIN_DIR/kim" --version 2>&1) || true
    if echo "$version_output" | grep -q "kim"; then
        _ok "kim --version works: $version_output"
    else
        _fail "kim --version failed: $version_output"
    fi

    help_output=$("$TEST_BIN_DIR/kim" --help 2>&1) || true
    if echo "$help_output" | grep -q "commands:"; then
        _ok "kim --help shows commands"
    else
        _fail "kim --help missing commands section"
    fi

    status_output=$("$TEST_BIN_DIR/kim" status 2>&1) || true
    if echo "$status_output" | grep -q "kim"; then
        _ok "kim status works"
    else
        _fail "kim status failed: $status_output"
    fi
else
    _fail "Binary shim missing, skipping execution tests"
fi

# ── Test 3: Idempotent re-install ────────────────────────────────────────────
_info "Test 3: Idempotent re-install (run install again)"

output2=$(KIM_LOCAL=1 bash "$INSTALLER" 2>&1) || true

if echo "$output2" | grep -q "Installed to\|Copied kim package"; then
    _ok "Re-install completed without fatal error"
else
    _fail "Re-install output missing success indicator"
fi

if [[ -f "$TEST_BIN_DIR/kim" ]] && [[ -d "$TEST_KIM_DIR/kim" ]]; then
    _ok "Files still present after re-install"
else
    _fail "Files missing after re-install"
fi

# ── Test 4: --uninstall flag works ───────────────────────────────────────────
_info "Test 4: --uninstall flag removes everything"

# Feed 'y' to the confirmation prompt
output3=$(echo "y" | bash "$INSTALLER" --uninstall 2>&1) || true

if echo "$output3" | grep -q "uninstalled"; then
    _ok "Uninstall completed successfully"
else
    _fail "Uninstall output missing success indicator: $output3"
fi

if [[ ! -f "$TEST_BIN_DIR/kim" ]]; then
    _ok "Binary shim removed"
else
    _fail "Binary shim still exists after uninstall"
fi

if [[ ! -d "$TEST_KIM_DIR" ]]; then
    _ok "Data directory removed"
else
    _fail "Data directory still exists after uninstall"
fi

# ── Test 5: Install after uninstall (full cycle) ─────────────────────────────
_info "Test 5: Install after uninstall (full cycle)"

output4=$(KIM_LOCAL=1 bash "$INSTALLER" 2>&1) || true

if echo "$output4" | grep -q "Installed to\|Copied kim package"; then
    _ok "Install after uninstall succeeded"
else
    _fail "Install after uninstall failed: $output4"
fi

if [[ -f "$TEST_BIN_DIR/kim" ]]; then
    version_after=$("$TEST_BIN_DIR/kim" --version 2>&1) || true
    if echo "$version_after" | grep -q "kim"; then
        _ok "kim works after full cycle: $version_after"
    else
        _fail "kim broken after full cycle: $version_after"
    fi
else
    _fail "Binary shim missing after full cycle"
fi

# ── Test 6: Config file created with correct permissions ─────────────────────
_info "Test 6: Config file permissions"

if [[ -f "$TEST_KIM_DIR/config.json" ]]; then
    if [[ "$(uname -s)" != "Darwin" ]]; then
        perms=$(stat -c "%a" "$TEST_KIM_DIR/config.json" 2>/dev/null || stat -f "%Lp" "$TEST_KIM_DIR/config.json" 2>/dev/null || echo "unknown")
        if [[ "$perms" == "600" ]]; then
            _ok "Config file has correct permissions (600)"
        else
            _fail "Config file has wrong permissions: $perms (expected 600)"
        fi
    else
        _ok "Config file exists (permissions check skipped on macOS)"
    fi
else
    _fail "Config file not created"
fi

# ── Test 7: Shell completion generation ──────────────────────────────────────
_info "Test 7: Shell completion generation"

for shell in bash zsh fish; do
    comp_output=$("$TEST_BIN_DIR/kim" completion "$shell" 2>&1) || true
    if echo "$comp_output" | grep -q "kim"; then
        _ok "completion $shell generates output"
    else
        _fail "completion $shell failed"
    fi
done

# ── Cleanup ───────────────────────────────────────────────────────────────────
cleanup

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed, $TOTAL total"
echo "═══════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
