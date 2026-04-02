# kim Wiki

## Overview

kim (keep in mind) is a lightweight cross-platform reminder daemon for developers. No UI. Config-driven. Runs in the background.

**Documentation:** [https://pratikwayal01.github.io/kim/](https://pratikwayal01.github.io/kim/)

---

## Package Structure

```
kim/
├── __init__.py
├── __main__.py
├── cli.py              # CLI argument parsing and command dispatch
├── core.py             # Config, paths, logging, interval parser
├── notifications.py    # Platform-specific notifications and Slack
├── sound.py            # Sound playback and validation
├── scheduler.py        # Heapq-based single-thread scheduler
├── interactive.py      # Interactive TUI mode
├── selfupdate.py       # Self-update and uninstall commands
├── utils.py            # Cross-platform symbols and utilities
└── commands/
    ├── config.py       # Config-related commands (edit, list, logs, validate, export, import)
    ├── daemon.py       # Daemon management (start, stop, status)
    ├── management.py   # Reminder management (add, remove, enable, disable, update)
    └── misc.py         # Miscellaneous commands (remind, slack, sound, completion)
```

## File Locations

| File | Purpose |
|---|---|
| `~/.kim/config.json` | Main configuration (reminders, sound, Slack) |
| `~/.kim/oneshots.json` | Persisted one-shot reminders (survives reboots) |
| `~/.kim/kim.log` | Log file (rotated, max 5 MB × 3 backups) |
| `~/.kim/kim.pid` | Daemon PID file |

## Key Features

- **Cross-platform**: Linux (systemd), macOS (launchd), Windows (Task Scheduler)
- **Pure Python stdlib** — no pip installs, no third-party dependencies
- **Low memory**: All reminders run on a single `heapq` scheduler thread (~0.02 MB flat)
- **Config-driven**: JSON configuration file with auto-creation of defaults
- **Notifications**: System notifications via native APIs (notify-send / osascript / PowerShell)
- **Sound**: Custom sound files or system default
- **Slack integration**: Webhook or bot token
- **One-shot reminders**: `kim remind "standup" in 10m` — persisted to disk, survives reboots
- **Interactive mode**: TUI for managing reminders
- **Self-update**: Automatic updates from GitHub releases
- **Export/Import**: JSON and CSV support

## One-shot Reminders

One-shot reminders are created via `kim remind` and stored in `~/.kim/oneshots.json`. They are:

- **Persistent** — survive daemon restarts and system reboots
- **Auto-loaded** — daemon loads pending one-shots on startup
- **Auto-cleaned** — expired reminders are removed on next startup
- **Single-fire** — removed from persistence after firing

### Time Format

Supports: `10m`, `1h`, `2h 30m`, `90s`, or bare numbers (treated as minutes).

### Windows Performance

On Windows, one-shot reminders spawn Python directly via `sys.executable -m kim _remind-fire` with `CREATE_NO_WINDOW`, avoiding the PowerShell overhead that would add 1-2s of interpreter startup time before the actual sleep begins.

## Configuration

Configuration is stored in `~/.kim/config.json`. Missing optional fields are filled with documented defaults automatically.

```json
{
  "reminders": [
    {
      "name": "eye-break",
      "interval": "30m",
      "title": "[eye] Eye Break",
      "message": "Look 20 feet away for 20 seconds. Blink slowly.",
      "urgency": "critical",
      "enabled": true
    }
  ],
  "sound": true,
  "sound_file": null,
  "slack": {
    "enabled": false,
    "webhook_url": "",
    "bot_token": "",
    "channel": "#general"
  }
}
```

### Interval Format

Accepts: integers (minutes), or strings like `"30m"`, `"2h"`, `"1d"`, `"90s"`. The legacy field `interval_minutes` is still supported for backward compatibility.

### Security

- Config file permissions are set to `600` on Unix (readable only by owner)
- Slack webhook URLs and bot tokens never appear in logs
- PID file is written atomically (tmp + rename) with `600` permissions

## Installation

**Linux / macOS**
```bash
curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/install.sh | bash
```

**Windows** (PowerShell as Admin)
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/pratikwayal01/kim/main/install.ps1 | iex"
```

## CLI Commands

```
kim start          Start the daemon
kim stop           Stop the daemon
kim status         Show status and active reminders
kim list           List all reminders from config
kim logs           Show recent log entries
kim edit           Open config in $EDITOR
kim add            Add a new reminder
kim remove         Remove a reminder
kim enable         Enable a reminder
kim disable        Disable a reminder
kim update         Update a reminder
kim remind         Fire a one-shot reminder after a delay
kim interactive    Enter interactive mode (alias: -i)
kim self-update    Check for and install updates
kim uninstall      Uninstall kim completely
kim export         Export reminders to file
kim import         Import reminders from file
kim validate       Validate config file
kim slack          Slack notification settings
kim sound          Manage the notification sound file
kim completion     Generate shell completions
```

## Logging

- Log file: `~/.kim/kim.log`
- Rotation: 5 MB max per file, 3 backups retained
- Uses `%-formatting` for lazy evaluation (no string formatting when log level is suppressed)
- Falls back to stderr if log file is unwritable

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes
4. Run tests: `python -m unittest discover -s tests -v`
5. Submit a pull request

## Links

- [GitHub Repository](https://github.com/pratikwayal01/kim)
- [Issue Tracker](https://github.com/pratikwayal01/kim/issues)
- [Documentation](https://pratikwayal01.github.io/kim/)

---

*Start small. Keep it in mind.*
