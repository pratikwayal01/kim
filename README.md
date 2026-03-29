# kim — keep in mind 🧠

> Lightweight cross-platform reminder daemon for developers.  
> No UI. Config-driven. Runs in the background.

**Documentation:** [https://pratikwayal01.github.io/kim/](https://pratikwayal01.github.io/kim/)

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
kim sound                          # show current config + format notes
kim sound --set ~/sounds/bell.mp3  # set custom file (validates on set)
kim sound --clear                  # revert to system default
kim sound --test                   # play it immediately
kim sound --enable / --disable     # toggle sound on/off
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
- Config changes are detected automatically — no need to restart manually
- Logs at `~/.kim/kim.log`, PID at `~/.kim/kim.pid`

---

## Why kim?

| Feature | kim | Remind | Cron | macOS Reminders | Google Calendar |
|---------|-----|--------|------|-----------------|-----------------|
| Pure stdlib (no deps) | ✅ | ❌ | ✅ | ❌ | ❌ |
| CLI-first | ✅ | ✅ | ✅ | ❌ | ❌ |
| Zero config | ✅ | ✅ | ❌ | ✅ | ❌ |
| One-shot reminders | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| Recurring intervals | ✅ | ✅ | ✅ | ✅ | ✅ |
| Cross-platform | ✅ | ⚠️ | ⚠️ | ❌ | ✅ |
| Slack notifications | ✅ | ❌ | ❌ | ❌ | ❌ |
| Config-driven | ✅ | ⚠️ | ✅ | ❌ | ❌ |
| Interactive mode | ✅ | ❌ | ❌ | ❌ | ❌ |
| Self-update | ✅ | ❌ | ❌ | ❌ | ❌ |
| Export/Import | ✅ | ❌ | ⚠️ | ❌ | ⚠️ |

---

## Uninstall

```bash
kim uninstall
```

---

## Roadmap

- [x] CLI reminder management
- [x] Interactive mode
- [x] Export / import
- [x] Self-update
- [x] Uninstall command
- [x] Config validation
- [x] Slack notifications
- [x] One-shot reminders
- [x] Custom sound files
- [x] Windows notifications

---

*Start small. Keep it in mind.*
