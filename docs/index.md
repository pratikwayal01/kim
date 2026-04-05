# kim — keep in mind 🧠

> Lightweight cross-platform reminder daemon for developers.  
> No UI. Config-driven. Runs in the background.

## Features

- **Cross-platform**: Linux, macOS, Windows
- **Pure Python stdlib** — no pip installs
- **Low memory**: All reminders run on a single `heapq` scheduler thread (~0.02 MB flat)
- **Config-driven**: JSON configuration file
- **Notifications**: System notifications via native APIs
- **Sound**: Custom sound files or system default
- **Slack integration**: Webhook or bot token
- **One-shot reminders**: `kim remind "standup" in 10m` — persisted to disk, survives reboots
- **Interactive mode**: TUI for managing reminders
- **Self-update**: Automatic updates from GitHub releases

## Quick Start

### Install

**pip** (all platforms) — [![PyPI](https://img.shields.io/pypi/v/kim-reminder)](https://pypi.org/project/kim-reminder/)
```bash
pip install kim-reminder
```

**Linux / macOS** (binary + autostart)
```bash
curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/install.sh | bash
```

**Windows** (PowerShell as Admin, binary + autostart)
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/pratikwayal01/kim/main/install.ps1 | iex"
```

That's it. kim starts automatically on login.

### Basic Usage

```bash
kim start          # Start the daemon
kim stop           # Stop the daemon
kim status         # Show running reminders
kim list           # List all reminders from config
kim add -I 30m --title "Break" --message "Stand up" eye-break
kim remind "standup call" in 10m
```

## Documentation

- [Home](index.md) — Overview and quick start
- [Installation](installation.md) — Detailed installation instructions
- [Configuration](configuration.md) — Config file reference, one-shot storage
- [Commands](commands.md) — All CLI commands
- [Sound](sound.md) — Sound configuration
- [Slack](slack.md) — Slack integration
- [Development](development.md) — Building from source, contributing
- [Changelog](changelog.md) — Version history

## Links

- [GitHub Repository](https://github.com/pratikwayal01/kim)
- [PyPI Package](https://pypi.org/project/kim-reminder/)
- [Issue Tracker](https://github.com/pratikwayal01/kim/issues)
- [Wiki](https://github.com/pratikwayal01/kim/wiki)

*Start small. Keep it in mind.*