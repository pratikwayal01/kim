# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.0.0] - 2026-03-28

### Added
- Modular package structure (multiple folders)
- Cross-platform symbol compatibility (ASCII fallbacks for Windows)
- Unit tests for all platforms
- GitHub Actions CI/CD pipeline
- Documentation website (MkDocs Material theme)
- Comprehensive test suite with CI on Windows, macOS, Linux
- Updated installers to download entire package

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