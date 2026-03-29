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
- All reminders run on a single `heapq` scheduler thread — memory stays flat (~0.02 MB) regardless of how many reminders you have
- Config changes are detected automatically — no need to restart manually
- Logs at `~/.kim/kim.log`, PID at `~/.kim/kim.pid`

---

## Why kim?

| Feature | kim | Remind | Cron | macOS Reminders | Google Calendar |
 |---------|-----|--------|------|-----------------|-----------------|
 | Pure stdlib (no deps) | ✅ | ❌ | ✅ | ❌ | ❌ |
 | CLI-first | ✅ | ✅ | ✅ | ❌ | ❌ |
 | One-shot reminders | ✅ | ✅ | ⚠️ | ✅ | ✅ |
 | Recurring intervals | ✅ | ✅ | ✅ | ✅ | ✅ |
 | Cross-platform | ✅ | ⚠️ | ⚠️ | ❌ | ✅ |
 | Slack notifications | ✅ | ❌ | ❌ | ❌ | ❌ |
 | Config-driven | ✅ | ⚠️ | ✅ | ❌ | ❌ |
 | Interactive mode | ✅ | ❌ | ❌ | ❌ | ❌ |
 | Self-update | ✅ | ❌ | ❌ | ❌ | ❌ |
 | Export/Import | ✅ | ❌ | ⚠️ | ❌ | ⚠️ |
 | Zero config | ⚠️ | ✅ | ❌ | ✅ | ❌ |

**kim** is designed for developers who want:
- Terminal-based workflow (no GUI apps)
- Config-driven reminders (version control your reminders)
- Cross-platform consistency (Linux/macOS/Windows)
- Zero dependencies (pure Python stdlib)
- Slack integration out of the box

---

## Uninstall

```bash
kim uninstall
```

---

## v3.1.1 Release Notes

### ✨ New Features
- **Windows balloon notifications** - Now shows native Windows toast notifications with proper icon
- **One-shot reminder persistence** - Reminders survive daemon restarts and system reboots
- **Custom sound files** - Set custom notification sounds via `kim sound --set`

### 🐛 Bug Fixes
- Fixed Windows notification popup not displaying (missing icon initialization)
- Fixed bare `except:` clause catching KeyboardInterrupt/SystemExit
- Fixed missing `FileNotFoundError` handling for subprocess calls
- Fixed interval validation to match scheduler behavior
- Fixed duplicate Windows subprocess code
- Fixed unused imports and dead code

### 🔧 Refactoring
- Removed duplicate `_windows_subprocess_cmd()` function
- Removed unused `urllib` imports in misc.py
- Changed `print()` to proper logging in core.py
- Improved error handling across all notification backends
- Added platform detection for macOS (osascript) and Linux (notify-send)

### 📝 Documentation
- Added comparison table with other reminder tools
- Updated interval field to `interval` (was `interval_minutes`)
- Improved CLI help text

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
- [x] Windows balloon notifications
- [ ] Per-reminder cron-style schedule
- [ ] Plugin system for custom notification channels

## Future Features (Backward Compatible)

These features can be added without breaking existing functionality:

- **Multiple reminder lists**: Separate config files for work/personal
- **Priority queues**: Critical reminders can override others
- **Calendar integration**: Sync with Google Calendar/Outlook
- **Email notifications**: Send reminders via email
- **SMS integration**: Via Twilio or similar services
- **Desktop widget**: Optional GUI for monitoring
- **Mobile companion app**: Remote control of reminders
- **Voice assistant integration**: Alexa/Google Home skills
- **Geofencing reminders**: Trigger based on location
- **Natural language processing**: `kim remind "tomorrow at 3pm" meeting`
- **Shared team reminders**: Collaborative reminder lists
- **Analytics dashboard**: Track reminder completion rates
- **Dark mode for interactive TUI**
- **Custom sound packs**
- **Themes for notifications**
- **Backup/restore to cloud**

---

*Start small. Keep it in mind.*
