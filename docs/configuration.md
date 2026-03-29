# Configuration

Configuration is stored in `~/.kim/config.json`. The file is created on first run with default reminders.

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

**Note:** The legacy field `interval_minutes` is still supported for backward compatibility.

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