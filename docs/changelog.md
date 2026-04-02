# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [4.0.0] - 2026-04-02

### Added
- **Per-reminder sound overrides** — each reminder can specify its own `sound_file` or disable sound
- **Per-reminder Slack overrides** — route individual reminders to different Slack channels or webhooks
- **Log rotation** — `RotatingFileHandler` with 5 MB max, 3 backups (prevents unbounded log growth)
- **Full shell completions** — bash/zsh/fish now complete subcommand flags, reminder names, and file paths
- **One-shot reminder persistence docs** — documented `~/.kim/oneshots.json` format and behavior
- **Interval seconds support** — `90s` now a valid interval format alongside `30m`, `1h`, `1d`

### Changed
- **Atomic PID file writes** — writes to `.tmp` then renames, eliminating partial-write corruption
- **Direct Python spawn on Windows** — one-shot reminders no longer go through PowerShell (saves 1-2s startup overhead)
- **`kim update --enable/--disable`** — fixed broken flag logic (was using `is not None` on booleans)
- **`kim update -I/--interval`** — changed from int to string to match `kim add` (accepts `30m`, `1h`, etc.)
- **`kim remind` parser** — bare numbers treated as minutes, max duration clamped to 365 days
- **`kim` with no command** — now exits with code 1 instead of silently returning

### Fixed
- **Critical: Slack bot urgency bug** — `_notify_slack_bot()` referenced undefined `urgency` variable (NameError crash)
- **Critical: Slack emoji bug** — `emoji = urgency_emoji.get("normal", ":bell:")` hardcoded "normal" instead of using actual urgency
- **Critical: Missing platform sound functions** — `_play_system_sound_mac()` and `_play_system_sound_linux()` were called but never defined (crash on default sound)
- **PID file TOCTOU race** — stale PIDs from crashed processes caused false "already running" errors; now verifies process is alive
- **Config shallow copy bug** — `DEFAULT_CONFIG.copy()` shared nested dict references between callers; now uses `copy.deepcopy()`
- **Config defaults missing** — `load_config()` now fills in all missing `sound`, `sound_file`, and `slack` sub-fields
- **Interval parser edge cases** — empty string, zero, and negative values now return safe default (30 min) instead of crashing
- **One-shot child process crash** — forked child on Unix now wrapped in `try/except/finally` to prevent silent daemon crashes
- **One-shot Windows spawn** — added `FileNotFoundError` handling for missing PowerShell
- **Startup notification crash** — wrapped in `try/except` so notification failure doesn't kill the daemon
- **Config write permissions** — all 8+ config write paths now set `0o600` on Unix and use `encoding="utf-8"`
- **F-string log calls** — 26 instances converted to `%-formatting` for lazy evaluation (no string formatting when log level is suppressed)
- **Redundant imports** — removed duplicate `import urllib.request` / `import urllib.error` inside functions
- **Dead code** — removed `platform_notifier()`, `start_daemon()` shim, `--HELP` pseudo-flag, `-V`/`--VERSION` aliases
- **Fish completion** — removed broken shebang, added full subcommand flag completions
- **Bash/Zsh completions** — removed broken shebangs, added `remind` and `_remind-fire` commands
- **Duplicate FISH_COMPLETION** — removed second definition that overwrote the first

### Removed
- Non-standard CLI flags: `-V`, `--VERSION`, `--HELP`
- Stale "Config changes are detected automatically" claim from README (no file watcher exists)
- Completed roadmap items (all features now shipped)

### Security
- All config writes set `0o600` permissions on Unix (Slack tokens protected)
- PID file written atomically with `0o600` permissions
- Log file set to `0o600` on Unix
- Secrets (webhook URLs, bot tokens) never appear in log messages

## [3.0.0] - 2026-03-28

### Added
- Modular package structure (multiple folders)
- Cross-platform symbol compatibility (ASCII fallbacks for Windows)
- Unit tests for all platforms
- GitHub Actions CI/CD pipeline
- Documentation website (MkDocs Material theme)
- Comprehensive test suite with CI on Windows, macOS, Linux
- Updated installers to download entire package
- Case-insensitive commands and flags (e.g., `STATUS`, `StAtUs`)
- `-v`/`-V`/`--VERSION`/`--HELP` aliases for version and help

### Changed
- Refactored monolithic `kim.py` into focused modules
- Improved Windows console compatibility
- Updated test suite to work across OS
- Separated CLI, commands, scheduler, notifications, sound, etc.

### Fixed
- Unicode encoding errors on Windows console
- Box drawing character rendering in tests
- File locking issues in tests on Windows
- Installer now downloads complete package structure

## [2.1.0] - 2026-03-28

### Added
- One-shot reminders (`kim remind`)
- Interactive mode TUI
- Self-update command
- Uninstall command
- Export/import functionality
- Config validation
- Slack integration (webhook and bot)
- Custom sound files
- Shell completions (bash, zsh, fish)
- Memory-optimized heapq scheduler

### Changed
- Single-threaded scheduler replaces per-reminder threads
- Platform-specific notification backends
- Config auto-reload

### Fixed
- Windows PowerShell toast notifications
- macOS notification sound handling
- Linux environment variables for notifications

## [2.0.0] - 2026-02-15

### Added
- Cross-platform daemon (Linux systemd, macOS launchd, Windows Task Scheduler)
- Config-driven reminders
- Platform notifications (notify-send, osascript, PowerShell toast)
- Sound notifications
- Logging system
- PID file management

### Changed
- Complete rewrite in Python
- Pure stdlib (no external dependencies)

## [1.0.0] - 2026-01-01

### Added
- Initial release
- Basic reminder functionality
- Linux support only

---

## Versioning

Given a version number MAJOR.MINOR.PATCH:

- **MAJOR**: Incompatible API changes
- **MINOR**: Add functionality in a backward-compatible manner
- **PATCH**: Backward-compatible bug fixes