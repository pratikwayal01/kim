# kim — keep in mind 🧠

> Lightweight cross-platform reminder daemon for developers.  
> No UI. Config-driven. Runs in the background.

---

## Install

**Linux / macOS**
```bash
curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/install.sh | bash
```

**Windows** (PowerShell as Admin)
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
kim remind         Fire a one-shot reminder after a delay
kim interactive    Enter interactive mode (-i)
kim self-update    Check for and install updates
kim uninstall      Uninstall kim completely
kim export         Export reminders to file
kim import         Import reminders from file
kim validate       Validate config file
kim slack          Slack notification settings
kim completion     Generate shell completions
```

### One-shot reminders

```bash
kim remind "standup call" in 10m
kim remind "take a break" in 1h
kim remind "check the oven" in 25m
kim remind "deploy window opens" in 2h 30m
```

Fires once, runs in the background, frees your terminal immediately.

---

## Config — `~/.kim/config.json`

```json
{
  "reminders": [
    {
      "name": "eye-break",
      "interval_minutes": 30,
      "title": "👁️ Eye Break",
      "message": "Look 20 feet away for 20 seconds. Blink slowly.",
      "urgency": "critical",
      "enabled": true
    },
    {
      "name": "water",
      "interval_minutes": 60,
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
| `interval_minutes` | number or string (`"30m"`, `"1h"`, `"1d"`) | How often to fire |
| `title` | string | Notification heading |
| `message` | string | Notification body |
| `urgency` | `low` / `normal` / `critical` | Notification priority |
| `enabled` | `true` / `false` | Toggle without deleting |
| `sound` | `true` / `false` | (top-level) Play sound globally |
| `slack` | object | (top-level) Slack settings |

### Slack Integration

```json
{
  "reminders": [...],
  "sound": true,
  "slack": {
    "enabled": true,
    "webhook_url": "https://hooks.slack.com/services/...",
    "bot_token": "xoxb-...",
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
- All reminders run on a single `heapq` scheduler thread — memory stays flat (~0.02 MB) regardless of how many reminders you have
- Config changes are detected automatically — no need to restart manually
- Logs at `~/.kim/kim.log`, PID at `~/.kim/kim.pid`

---

## Uninstall

```bash
kim uninstall
```

---

## Roadmap

- [x] CLI reminder management (`kim add`, `kim remove`, etc.)
- [x] Interactive mode
- [x] Export / import
- [x] Self-update
- [x] Uninstall command
- [x] Config validation
- [x] Slack / webhook notifications
- [x] One-shot reminders (`kim remind "standup" in 10m`)
- [ ] Per-reminder cron-style schedule
- [ ] Plugin system for custom notification channels

---

*Start small. Keep it in mind.*