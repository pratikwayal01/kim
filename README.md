# kim — keep in mind 🧠

> Lightweight cross-platform reminder daemon for developers.  
> No UI. Config-driven. Runs in the background.

**Documentation:** [https://pratikwayal01.github.io/kim/](https://pratikwayal01.github.io/kim/)

![kim demo](assets/demo.gif)

---

## Install

**pip** (all platforms)
```bash
pip install kim-reminder
```
[![PyPI](https://img.shields.io/pypi/v/kim-reminder)](https://pypi.org/project/kim-reminder/)

**Linux / macOS** (binary, autostart setup)
```bash
curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/install.sh | bash
```

**Windows** (PowerShell as Admin, binary, autostart setup)
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/pratikwayal01/kim/main/install.ps1 | iex"
```

That's it. kim starts automatically on login.

---

## Usage

```
kim start          Start the daemon
kim stop           Stop the daemon
kim status         Show running reminders
kim list           List all reminders from config
kim logs           Tail the log file
kim edit           Open config in $EDITOR
kim add            Add a new reminder
kim remove         Remove a reminder
kim enable         Enable a reminder
kim disable        Disable a reminder
kim update         Update a reminder
kim remind         Fire a one-shot reminder after a delay or at a time
kim interactive    Enter interactive mode (-i)
kim self-update    Check for and install updates
kim uninstall      Uninstall kim completely
kim export         Export reminders to file
kim import         Import reminders from file
kim validate       Validate config file
kim slack          Slack notification settings
kim completion     Generate shell completions
kim sound                          # show current config + format notes
kim sound --set ~/sounds/bell.mp3  # set custom file (validates on set)
kim sound --clear                  # revert to system default
kim sound --test                   # play it immediately
kim sound --enable / --disable     # toggle sound on/off
```

### Interval reminders

```bash
kim add "drink water" -I 30m          # every 30 minutes
kim add "drink water" --every 30m     # same — --every is an alias for -I
kim add "stretch" --every 1h
```

### Daily at a fixed time

```bash
kim add standup --at 10:00                        # every day at 10:00 local time
kim add standup --at 10:00 --tz Asia/Kolkata      # with explicit timezone
```

### One-shot reminders

```bash
# Relative
kim remind "standup call" in 10m
kim remind "take a break" in 1h
kim remind "check the oven" in 25m
kim remind "deploy window opens" in 2h 30m

# Absolute — fire at a specific time
kim remind "standup" at 10:00
kim remind "standup" at tomorrow 9am
kim remind "call" at friday 2pm
kim remind "deploy" at 2026-04-07 14:30 --tz America/New_York
```

Fires once, runs in the background, frees your terminal immediately.

**Persistent** — one-shot reminders survive daemon restarts and system reboots. Stored in `~/.kim/oneshots.json` and loaded automatically when the daemon starts. Expired reminders are cleaned up on next startup.

---

## Config — `~/.kim/config.json`

```json
{
  "reminders": [
    {
      "name": "eye-break",
      "interval": "30m",
      "title": "👁️ Eye Break",
      "message": "Look 20 feet away for 20 seconds. Blink slowly.",
      "urgency": "critical",
      "enabled": true
    },
    {
      "name": "water",
      "interval": "1h",
      "title": "💧 Drink Water",
      "message": "Stay hydrated.",
      "urgency": "normal",
      "enabled": true
    }
  ],
  "sound": true
}
```

| Field | Values | Description |
|---|---|---|
| `name` | string | Unique identifier |
| `interval` | number or string (`"30m"`, `"1h"`, `"1d"`) | How often to fire |
| `title` | string | Notification heading |
| `message` | string | Notification body |
| `urgency` | `low` / `normal` / `critical` | Notification priority |
| `enabled` | `true` / `false` | Toggle without deleting |
| `sound` | `true` / `false` | (top-level) Play sound globally |
| `slack` | object | (top-level) Slack settings |

### Per-Reminder Overrides

Each reminder can override global sound and Slack settings:

```json
{
  "reminders": [
    {
      "name": "standup",
      "interval": "30m",
      "sound_file": "~/sounds/urgent.wav",
      "slack": {
        "enabled": true,
        "webhook_url": "https://hooks.slack.com/services/...",
        "channel": "#standup-alerts"
      }
    }
  ],
  "sound": true,
  "slack": {
    "enabled": true,
    "webhook_url": "https://hooks.slack.com/services/...",
    "channel": "#general"
  }
}
```

Or via CLI:
```bash
kim add standup -I 30m --sound-file ~/sounds/urgent.wav --slack-channel "#standup"
```

### Slack Integration

```json
{
  "reminders": [...],
  "sound": true,
  "slack": {
    "enabled": true,
    "webhook_url": "https://hooks.slack.com/services/your-webhook-id",
    "bot_token": "xoxb-your-bot-token",
    "channel": "#general"
  }
}
```

Use a **Webhook** or a **Bot Token** — not both. Test with `kim slack --test`.

---

## How it works

| Platform | Autostart | Notifications |
|---|---|---|
| Linux | systemd user service | `notify-send` |
| macOS | launchd agent | `osascript` |
| Windows | Task Scheduler | PowerShell toast |

- **Pure Python stdlib** — no pip installs
- **Zero config** — works out of the box, creates default config on first run
- All reminders run on a single `heapq` scheduler thread — memory stays flat (~0.02 MB) regardless of how many reminders you have
- Logs at `~/.kim/kim.log`, PID at `~/.kim/kim.pid`

---

## Why kim?

| Tool | Pure stdlib | CLI-first | Zero config | One-shot | Recurring | Cross-platform | Slack | Config-driven | Interactive | Self-update | Export/Import |
|------|-------------|-----------|-------------|----------|-----------|----------------|-------|---------------|-------------|-------------|---------------|
| kim | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Remind | ❌ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ❌ | ⚠️ | ❌ | ❌ | ❌ |
| Cron | ✅ | ✅ | ❌ | ⚠️ | ✅ | ⚠️ | ❌ | ✅ | ❌ | ❌ | ⚠️ |
| macOS Reminders | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Google Calendar | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ⚠️ |

---

## Uninstall

```bash
kim uninstall
```

---

*Start small. Keep it in mind.*
