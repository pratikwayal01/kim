# Configuration

Configuration is stored in `~/.kim/config.json`. The file is created on first run with default reminders.

## File Locations

| File | Purpose |
|---|---|
| `~/.kim/config.json` | Main configuration (reminders, sound, Slack) |
| `~/.kim/oneshots.json` | Persisted one-shot reminders (survives reboots) |
| `~/.kim/kim.log` | Log file (rotated, max 5 MB × 3 backups) |
| `~/.kim/kim.pid` | Daemon PID file |

## Config File Structure

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

## Fields

### Top-level

| Field | Type | Default | Description |
|---|---|---|---|
| `reminders` | array | `[]` | List of reminder objects |
| `sound` | boolean | `true` | Enable/disable sound globally |
| `sound_file` | string/null | `null` | Path to custom sound file (wav/mp3/ogg/flac/aiff/m4a) |
| `slack` | object | `{}` | Slack integration settings |

### Reminder Object

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Unique identifier |
| `interval` | number/string | Yes | How often to fire. Accepts:<br>- Integer (minutes)<br>- String: `"30m"`, `"2h"`, `"1d"` |
| `title` | string | No | Notification heading (default: `Reminder: {name}`) |
| `message` | string | No | Notification body (default: `Time for a reminder!`) |
| `urgency` | string | No | `low`, `normal`, `critical` (default: `normal`) |
| `enabled` | boolean | No | Enable/disable this reminder (default: `true`) |
| `sound` | boolean | No | Override global sound for this reminder |
| `sound_file` | string | No | Per-reminder sound file (overrides global `sound_file`) |
| `slack` | object | No | Per-reminder Slack config (overrides global `slack`) |

**Note:** The legacy field `interval_minutes` is still supported for backward compatibility.

### Per-Reminder Overrides

Each reminder can override the global sound and Slack settings. This lets you route different reminders to different Slack channels or play different sounds.

```json
{
  "reminders": [
    {
      "name": "standup",
      "interval": "30m",
      "title": "Standup Reminder",
      "message": "Time for standup!",
      "sound_file": "/home/user/sounds/urgent.wav",
      "slack": {
        "enabled": true,
        "webhook_url": "https://hooks.slack.com/services/standup-webhook",
        "channel": "#standup-alerts"
      }
    },
    {
      "name": "water",
      "interval": "1h",
      "title": "Drink Water",
      "message": "Stay hydrated",
      "sound": false,
      "slack": {
        "enabled": true,
        "webhook_url": "https://hooks.slack.com/services/wellness-webhook",
        "channel": "#wellness"
      }
    }
  ],
  "sound": true,
  "sound_file": "/home/user/sounds/default.wav",
  "slack": {
    "enabled": true,
    "webhook_url": "https://hooks.slack.com/services/default-webhook",
    "channel": "#general"
  }
}
```

In this example:
- **standup** plays `/home/user/sounds/urgent.wav` and posts to `#standup-alerts`
- **water** has sound disabled and posts to `#wellness`
- All other reminders use the global defaults

### Slack Object

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Enable Slack notifications |
| `webhook_url` | string | `""` | Slack webhook URL |
| `bot_token` | string | `""` | Slack bot token (`xoxb-...`) |
| `channel` | string | `"#general"` | Channel to post to |

**Note:** Use either `webhook_url` OR `bot_token` + `channel`, not both.

## Editing Configuration

### Command Line

```bash
kim edit   # Opens config in $EDITOR (default: nano/notepad)
```

### Interactive Mode

```bash
kim interactive   # Or `kim -i`
```

### Manual Editing

Edit `~/.kim/config.json` with any text editor.

## Validation

Validate your config file:

```bash
kim validate
```

## Import / Export

Export reminders:
```bash
kim export -f json -o reminders.json
kim export -f csv -o reminders.csv
```

Import reminders:
```bash
kim import reminders.json
kim import reminders.csv --merge   # Merge with existing
```

## Example Configurations

### Basic Reminders

```json
{
  "reminders": [
    {
      "name": "eye-break",
      "interval": "30m",
      "title": "[eye] Eye Break",
      "message": "Look away from screen",
      "urgency": "critical",
      "enabled": true
    },
    {
      "name": "water",
      "interval": "1h",
      "title": "[water] Drink Water",
      "message": "Stay hydrated",
      "urgency": "normal",
      "enabled": true
    }
  ],
  "sound": true
}
```

### With Slack Integration

```json
{
  "reminders": [...],
  "sound": true,
  "slack": {
    "enabled": true,
    "webhook_url": "https://hooks.slack.com/services/your-webhook-id",
    "channel": "#dev-alerts"
  }
}
```

### Custom Sound

```json
{
  "reminders": [...],
  "sound": true,
  "sound_file": "/home/user/sounds/bell.mp3"
}
```

## One-shot Reminders

One-shot reminders (created via `kim remind`) are stored separately in `~/.kim/oneshots.json`. This file is managed automatically by kim — you should not need to edit it manually.

### Format

```json
[
  {
    "message": "standup call",
    "title": "⏰ Reminder",
    "fire_at": 1711632000.0
  }
]
```

| Field | Type | Description |
|---|---|---|
| `message` | string | The reminder message |
| `title` | string | Notification title |
| `fire_at` | number | Unix timestamp when the reminder should fire |

### Behavior

- One-shot reminders are loaded by the daemon on startup
- Expired reminders (past `fire_at`) are automatically cleaned up
- Once fired, the reminder is removed from the file
- Survives daemon restarts and system reboots