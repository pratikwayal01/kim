# kim — keep in mind

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
kim interactive    Enter interactive mode
kim self-update    Check for and install updates
kim uninstall      Uninstall kim completely
kim export         Export reminders to file
kim import         Import reminders from file
kim validate       Validate config file
```

---

## Config — `~/.kim/config.json`

This is the only file you need to touch.

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

| Field              | Values                           | Description                      |
|--------------------|----------------------------------|----------------------------------|
| `name`             | string                           | Unique identifier                |
| `interval_minutes` | number                           | How often to fire                |
| `title`            | string                           | Notification heading             |
| `message`          | string                           | Notification body                |
| `urgency`          | `low` / `normal` / `critical`    | Controls notification priority   |
| `enabled`          | `true` / `false`                 | Toggle without deleting          |
| `sound`            | `true` / `false`                 | (top-level) Play sound globally  |

After editing, apply changes:
```bash
kim stop && kim start
```

---

## How it works

| Platform | Autostart          | Notifications         |
|----------|--------------------|-----------------------|
| Linux    | systemd user service | `notify-send`       |
| macOS    | launchd agent      | `osascript`           |
| Windows  | Task Scheduler     | PowerShell toast      |

- **Pure Python stdlib** — no pip installs
- Each reminder runs in its own thread
- Logs at `~/.kim/kim.log`
- PID tracked at `~/.kim/kim.pid`

---

## Uninstall

**Quick uninstall (use the built-in command)**
```bash
kim uninstall
```

**Manual uninstall**

**Linux**
```bash
systemctl --user disable --now kim.service
rm ~/.config/systemd/user/kim.service
rm -rf ~/.kim ~/.local/bin/kim
```

**macOS**
```bash
launchctl unload ~/Library/LaunchAgents/io.kim.reminder.plist
rm ~/Library/LaunchAgents/io.kim.reminder.plist
rm -rf ~/.kim ~/.local/bin/kim
```

**Windows**
```powershell
Unregister-ScheduledTask -TaskName KimReminder -Confirm:$false
Remove-Item -Recurse "$env:USERPROFILE\.kim"
```

---

## Roadmap ideas

- [x] `kim add` / `kim remove` — manage reminders from CLI without editing JSON
- [x] Interactive mode (`kim interactive`)
- [x] Export/import functionality
- [x] Self-update (`kim self-update`)
- [x] Uninstall command (`kim uninstall`)
- [x] Config validation (`kim validate`)
- Slack / webhook notifications as a channel
- One-shot reminders (`kim remind "standup" in 10m`)
- Per-reminder schedule (cron-style, not just interval)
- Plugin system for custom notification channels

---

*Start small. Keep it in mind.*
