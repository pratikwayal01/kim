# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.5.7] - 2026-04-07

### Added
- **`kim remove <N>`** — remove a recurring reminder by 1-based index as shown in `kim list`. Existing name-based removal still works unchanged.
- **`kim list` shows `#` index column** — recurring reminders now display a 1-based index so users know what number to pass to `kim remove`.

## [4.5.6] - 2026-04-07

### Added
- **`kim export --oneshots`** — include pending one-shot reminders in the export (JSON: `"oneshots"` array; CSV: appended section). Use with `-o file` to save to a file.
- **`kim import --oneshots`** — restore pending one-shot reminders from a file produced by `kim export --oneshots`. Only future fire times are imported; duplicates are skipped.
- **Help footer** now shows `oneshots: ~/.kim/oneshots.json` alongside the config and log paths.

### Fixed
- **`kim uninstall` now kills orphaned `kim remind` fork children** — on Linux the uninstall reads `/proc` directly to find and SIGTERM every sleeping `kim remind` child process. On macOS/other Unix it falls back to `pkill -f`. This prevents a one-shot reminder from firing after kim has been uninstalled.
- **`kim uninstall` clears `oneshots.json` before removing `~/.kim/`** — even if a fork child survives the SIGTERM (e.g. already woken), the cleared file means it cannot write back or be replayed on any future `kim start`.

## [4.5.5] - 2026-04-05

### Fixed
- **Scheduler race condition** — `_wakeup.clear()` is now called inside the lock so a wakeup signal set between reading the heap and entering `wait()` is never lost.
- **Scheduler: notifier now runs in a daemon thread** — a slow or blocking notifier (e.g. Slack network call) no longer stalls the scheduler loop and delays all future firings.
- **One-shot reminders: remove from `_live` after firing** — fired one-shots are now removed from the scheduler's internal `_live` dict, preventing a memory leak for long-running daemons.
- **One-shot fork child now calls `remove_oneshot()`** — after the Unix `os.fork()` child fires a `kim remind` one-shot, it removes its entry from `oneshots.json` so the reminder does not re-fire on the next daemon start.
- **`oneshots.json` tmp file permissions** — all atomic writes to `oneshots.json` (via `.tmp` rename) now `chmod 0o600` the tmp file on Unix before the rename, preventing world-readable exposure.
- **Negative `sleep_seconds` on clock jump** — `kim remind` now clamps `sleep_seconds` to `max(0.0, ...)` so a backward clock adjustment never causes `time.sleep()` to crash.
- **`kim update --interval` now validates the value** — passing an invalid interval string (e.g. `--interval foo`) is rejected with an error message instead of silently writing bad data to config.
- **`kim validate` now checks `at` field format** — reminders with an `at` field are validated to be in `HH:MM` format; invalid values are reported as errors.
- **Slack webhook response body checked** — `_notify_slack_webhook` now reads the response body and logs a warning if it is not `"ok"`. `_notify_slack_bot` reads the JSON response and logs the API error if `ok` is `false`.
- **`kim interactive` edit: clearing `at` when switching to interval** — editing a reminder to set an interval now removes any existing `at` and `timezone` keys, preventing an invalid mixed-schedule state.
- **`kim interactive` add one-shot: urgency no longer hardcoded to `critical`** — the user is now prompted for urgency (default: `normal`), consistent with `kim remind`.
- **`load_config` prints a warning on JSON corruption** — callers (including the daemon and CLI) now see a stderr message when the config file is invalid JSON, not just a silent log entry.
- **`kim` (bare, no subcommand) now exits 0** — printing help is not an error condition.
- **`sound.py`: `validate_sound_file` now checks read permission** — a file that exists but is not readable is rejected with a clear error message.
- **`import re` moved to module level in `cli.py`** — the deferred `import re` inside `_Formatter._format_actions_usage` is now a top-level import.
- **`import datetime` moved to module level in `misc.py`** — the deferred `import datetime as _dt` inside `cmd_remind` is now a top-level import.
- **`cmd_remove` exception handling narrowed** — the bare `except Exception` when reading `oneshots.json` in `cmd_remove` is now `except (json.JSONDecodeError, OSError)`.
- **Dead-code removal**: `KimScheduler.update_reminder` and `KimScheduler.disable_reminder` (thin wrappers never called externally) removed; `core.parse_interval` marked deprecated (kept for backward compatibility).

## [4.5.0] - 2026-04-05

### Added
- **`kim remind --urgency`** — one-shot reminders now accept `--urgency low|normal|critical` (default: `normal`), matching `kim add` behaviour. Urgency is persisted to `~/.kim/oneshots.json` and correctly restored if the daemon restarts while the reminder is pending.

### Fixed
- **`kim start` daemon detection** — replaced `INVOCATION_ID` env-var check with a TTY check (`/dev/tty`). The old check caused `kim start` to block the terminal on some Linux distros because systemd inherits `INVOCATION_ID` to all child shells, not just supervised processes.
- **`kim start` / `kim stop` messages now include PID**:
  - `kim started. (PID 1234)`
  - `kim is already running. (PID 1234)`
  - `kim stopped. (PID 1234)`
  - `kim is already stopped.`
- **`kim remind` output consistent with `kim add`** — confirmation now uses the `✓` prefix instead of leaking the notification title into the CLI output line.
- **`_remind-fire` hidden from usage line** — internal subcommand no longer appears in `kim` usage/help output.
- **`--break-system-packages` added to all pip calls** — `kim self-update` and `kim uninstall` now work correctly on Arch Linux, Debian 12+, Ubuntu 23.04+, and other distros with externally managed Python environments.

### Changed
- Shell completions for bash, zsh, and fish updated to include `--urgency` for `kim remind`.

## [4.1.8] - 2026-04-05

### Fixed
- **`_find_asset` was orphaned dead code in `selfupdate.py`** — the function body appeared after `_parse_version`'s `return` statement making it unreachable, causing `NameError` at runtime during `self-update`. Extracted into a proper top-level function.
- **`cmd_list` did not display `at`-schedule reminders correctly** — the `INTERVAL` column fell back to `"30 min"` for daily-at reminders. Now shows `"at HH:MM"` and the column is renamed `SCHEDULE`.
- **Interactive mode: `cancel_oneshot` name-shadowing crash** — the local helper inside `cmd_interactive` was named `remove_oneshot`, shadowing the module-level import of the same name, causing a `TypeError` when cancelling a one-shot. Renamed to `cancel_oneshot`.

### Tests
- Added 77 new feature tests in `tests/test_features.py` covering: `cmd_remind`, oneshot load/remove, `cmd_list`, `cmd_status`, config reload, sanitize, export/import, `_find_asset`, scheduler reschedule, parse_interval/parse_datetime edge cases, and `cmd_validate`.
- Added regression tests in `tests/test_regression.py` for `_parse_version`, downgrade guard, install-type detection order, interactive `cancel_oneshot` rename, and `cmd_validate` at-reminder acceptance.

## [4.1.7] - 2026-04-05

### Added
- **Interactive mode: List/Add/Remove One-shots** — three new menu items in `kim interactive` for managing one-shot reminders without touching the CLI.
- **Interactive mode: `--at HH:MM` schedule** — "Add Reminder" now prompts for interval or daily-at schedule type.
- **Status bar one-shot count** — interactive header shows `One-shots: N pending` alongside the reminder count.
- **Config auto-reload after every action** — interactive mode reloads config from disk after each mutation so the display is always current.

### Fixed
- **`kim` help output cleanup** — removed duplicate positional-args block, replaced long `{start,stop,...}` metavar with `<command>`, suppressed internal `_remind-fire` subcommand from help, removed redundant "Short flags" section, and tightened epilog formatting.
- **Interactive daemon signal on mutations** — all mutating actions (`add`, `edit`, `toggle`, `remove`) now call `_signal_reload()` so the running daemon picks up changes immediately.

## [4.1.6] - 2026-04-05

### Fixed
- **`kim uninstall` WinError 32** — explicitly close all logging handlers before removing `~/.kim`, releasing the file lock on `kim.log` on Windows.
- **`kim uninstall` "The batch file cannot be found."** — the currently-running `kim.bat` is no longer deleted in-process. A detached `cmd` is spawned to remove it ~2 s after the process exits, so cmd.exe can return cleanly.
- **"Thank you for using kim!" is now always the last line** of uninstall output.

## [4.1.5] - 2026-04-05

### Added
- **`kim list -o` / `--oneshots`** — appends pending one-shot reminders to the list output, showing index, message, fire time, and time remaining.
- **`kim remove <index|msg> -o` / `--oneshot`** — cancels a pending one-shot by its list index (from `kim list -o`) or message substring, instead of removing a config reminder.

### Removed
- `kim remind --list` and `kim remind --cancel` flags removed in favour of the cleaner `kim list -o` / `kim remove -o` interface.

## [4.1.4] - 2026-04-05

### Added
- **`kim remind --list`** — show all pending one-shot reminders with index, message, fire time, and time remaining.
- **`kim remind --cancel <index|message>`** — cancel a pending one-shot by its list index (from `--list`) or a message substring match.

## [4.1.3] - 2026-04-05

### Fixed
- **Windows script install: `kim start` crash (WinError 193)** — `_spawn_detached()` was calling `Popen(sys.argv)` which fails when `sys.argv[0]` is a `.py` file (script install via `install.ps1`). Now prepends `sys.executable` when argv[0] ends in `.py` on Windows.

## [4.1.2] - 2026-04-05

### Fixed
- **Windows PATH instructions** — README now shows a copy-paste one-liner to fix PATH after `pip install`. `install.ps1` also auto-fixes the pip Scripts PATH for users who already installed via pip.

## [4.1.1] - 2026-04-05

### Fixed
- **Windows PATH auto-fix** — on Windows, `kim` now detects if the pip Scripts directory is missing from the user `PATH` and adds it automatically via `setx` on first run. Users no longer need to manually update their PATH after `pip install kim-reminder`.

## [4.1.0] - 2026-04-05

### Added
- **`--every` flag** — alias for `-I`/`--interval` on `kim add` and `kim update` (e.g. `kim add "drink water" --every 30m`)
- **`--at HH:MM` on `kim add`/`kim update`** — schedule a reminder to fire every day at a fixed time (e.g. `kim add standup --at 10:00`). Mutually exclusive with `--interval`.
- **`--tz TZ` flag** — IANA timezone override for `--at` and `kim remind ... at` (e.g. `--tz Asia/Kolkata`). Defaults to local system timezone.
- **`kim remind ... at <datetime>`** — fire a one-shot reminder at an absolute datetime. Accepts natural language and ISO formats:
  - `at 14:30` — today at 14:30 (or tomorrow if already past)
  - `at tomorrow 10am` — tomorrow at 10:00
  - `at friday 9am` — next Friday at 09:00
  - `at 2026-04-06 09:00` — specific date and time
- **`parse_datetime` utility** — pure stdlib datetime parser in `core.py` supporting both relative (`in 10m`, `2h 30m`) and absolute (`at tomorrow 9am`) formats
- **`parse_at_time` utility** — validates and normalises `--at HH:MM` values
- **Scheduler support for daily at-time reminders** — `KimScheduler` now handles reminders with an `at` field; re-schedules them for the same wall-clock time the next day after firing
- **Live config reload** — `kim add`, `kim remove`, `kim enable`, `kim disable`, and `kim update` now take effect in the running daemon within 1 second — no restart needed. Implemented via a `~/.kim/kim.reload` flag file polled by the daemon loop. On Linux/macOS, `kill -HUP <pid>` also triggers a reload.

### Changed
- **`kim start` no longer blocks the terminal** — when run interactively it spawns a detached background process and returns immediately. Process supervisors (systemd, launchd, Windows Task Scheduler) are detected automatically and still run in-process.
- **`kim start` output** — shows `kim started. (PID 1234)` on fresh start; shows `kim is already running. (PID 1234)` if the daemon is already up.
- **`kim stop` output** — shows `kim stopped. (PID 1234)` on success; shows `kim is already stopped.` if not running.
- **`kim status` running line** — now shows `● kim running  (PID 1234)` for consistency with start/stop output.
- `kim remind` time-parsing refactored to use `parse_datetime` (behaviour-compatible for existing relative syntax)

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