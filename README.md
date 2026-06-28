# kim — keep in mind

> Lightweight cross-platform reminder daemon for developers.  
> No UI. Config-driven. Runs in the background.

**Documentation:** [pratikwayal01.github.io/kim](https://pratikwayal01.github.io/kim/)  
[![PyPI](https://img.shields.io/pypi/v/kim-reminder)](https://pypi.org/project/kim-reminder/)

![kim demo](assets/demo.gif)

---

## Install

**Linux / macOS**
```bash
curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/install.sh | bash
```

**Windows** (PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/pratikwayal01/kim/main/install.ps1 | iex"
```

**pip**
```bash
pip install --break-system-packages kim-reminder
```

That's it. kim starts automatically on login.

> **Windows + pip:** If `kim` is not found after install, run this once to add it to your PATH:
> ```powershell
> $p = python -c "import sysconfig; print(sysconfig.get_path('scripts','nt_user'))"
> [Environment]::SetEnvironmentVariable("PATH",$env:PATH+";"+$p,"User")
> $env:PATH += ";$p"
> ```

---

## Usage

```
kim start          Start the daemon
kim stop           Stop the daemon
kim status         Show running reminders and config paths
kim list           List all reminders  (shows index #)
kim list -o        Also show pending one-shot reminders
kim logs           Tail the log file
kim edit           Open config in $EDITOR
kim add            Add a new reminder
kim remove         Remove a reminder  (by name or index)
kim enable         Enable a reminder
kim disable        Disable a reminder
kim update         Update a reminder
kim remind         One-shot reminder after a delay or at a time
kim interactive    Arrow-key TUI  (-i shortcut)
kim self-update    Update to latest release
kim uninstall      Remove kim completely
kim export         Export reminders to JSON or CSV
kim import         Import reminders from JSON or CSV
kim validate       Validate config file
kim slack          Show or test Slack configuration
kim sound          Manage notification sound
kim completion     Generate shell completions (bash/zsh/fish)
```

### Recurring reminders

```bash
# Interval-based
kim add eye-break -I 30m -t "Eye Break" -m "Look away" -u critical
kim add water --every 1h

# Daily at a fixed time
kim add standup --at 10:00
kim add standup --at 10:00 --tz Asia/Kolkata
```

### One-shot reminders

```bash
# Relative
kim remind "standup call" in 10m
kim remind "deploy window opens" in 2h 30m

# Absolute
kim remind "standup" at 10:00
kim remind "standup" at tomorrow 9am
kim remind "call" at friday 2pm
kim remind "deploy" at 2026-04-07 14:30 --tz America/New_York

# Urgency
kim remind "wake up!" in 5m --urgency critical
```

Fires once, runs in the background, frees your terminal immediately. Survives daemon restarts and reboots — stored in `~/.kim/oneshots.json`.

### Removing reminders

```bash
# Recurring — by name or index from `kim list`
kim remove water
kim remove 2

# One-shot — by index or message substring from `kim list -o`
kim remove 1 -o
kim remove "standup" -o
```

### Graphical UI (optional)

```bash
pip install kim-reminder[ui]   # or: uv pip install -e ".[ui]"
kim ui
```

A native-looking desktop window with system tray icon. Manage recurring reminders, view and cancel pending one-shots, start/stop the daemon — all without touching the terminal.

---

## Config — `~/.kim/config.json`

```json
{
  "reminders": [
    {
      "name": "eye-break",
      "interval": "30m",
      "title": "Eye Break",
      "message": "Look 20 feet away for 20 seconds.",
      "urgency": "critical",
      "enabled": true
    },
    {
      "name": "standup",
      "at": "10:00",
      "timezone": "Asia/Kolkata",
      "title": "Standup",
      "message": "Time for standup!",
      "urgency": "normal",
      "enabled": true
    }
  ],
  "sound": true,
  "slack": {
    "enabled": false,
    "webhook_url": "https://hooks.slack.com/services/...",
    "channel": "#general"
  }
}
```

| Field | Values | Description |
|---|---|---|
| `name` | string | Unique identifier |
| `interval` | `"30m"`, `"1h"`, `"1d"`, `"90s"` | Recurring interval (*required unless `at` is set*) |
| `at` | `"HH:MM"` | Fire daily at a fixed time (*required unless `interval` is set*) |
| `timezone` | IANA name e.g. `"Asia/Kolkata"` | Timezone for `at` (default: local) |
| `title` | string | Notification heading |
| `message` | string | Notification body |
| `urgency` | `low` / `normal` / `critical` | Notification priority |
| `enabled` | `true` / `false` | Toggle without deleting |
| `sound_file` | path | Per-reminder sound file (overrides global) |
| `slack` | object | Per-reminder Slack override |

Use `kim validate` to check your config. Use `kim edit` to open it in `$EDITOR`.

---

## How it works

| Platform | Autostart | Notifications |
|---|---|---|
| Linux | systemd user service | `notify-send` |
| macOS | launchd agent | `osascript` |
| Windows | Task Scheduler | PowerShell toast |

- **Pure Python stdlib** — zero runtime dependencies
- **Single scheduler thread** — all reminders share one `heapq` event loop (~0.02 MB flat)
- **Atomic writes** — all config and state files written via `.tmp` → rename
- **Secrets never logged** — Slack tokens and webhook URLs are not written to `~/.kim/kim.log`
- Logs at `~/.kim/kim.log` (5 MB rotating, 3 backups)

---

## Uninstall

```bash
kim uninstall
```

Cancels pending one-shot reminders, removes autostart entries, deletes `~/.kim/` and the binary.

If kim is broken, use the standalone script:
```bash
curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/uninstall.sh | bash
```

---

*Start small. Keep it in mind.*

