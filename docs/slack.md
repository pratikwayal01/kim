# Slack Integration

kim can send notifications to Slack channels via webhooks or bot tokens.

## Configuration

In `~/.kim/config.json`:

```json
{
  "slack": {
    "enabled": true,
    "webhook_url": "",
    "bot_token": "",
    "channel": "#general"
  }
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | boolean | `false` | Enable Slack notifications |
| `webhook_url` | string | `""` | Slack incoming webhook URL |
| `bot_token` | string | `""` | Slack bot token (`xoxb-...`) |
| `channel` | string | `"#general"` | Channel to post to (required for bot token) |

**Important:** Use **either** `webhook_url` **or** `bot_token` + `channel`, not both.

## Setup Methods

### Method 1: Webhook (Simple)

1. Create an incoming webhook in your Slack workspace:
   - Go to [Slack API: Incoming Webhooks](https://api.slack.com/messaging/webhooks)
   - Click "Create New App" → "From scratch"
   - Add "Incoming Webhooks" feature
   - Activate and create a webhook for your channel
   - Copy the webhook URL

2. Configure kim:
   ```json
   {
     "slack": {
       "enabled": true,
        "webhook_url": "https://hooks.slack.com/services/your-webhook-id"
     }
   }
   ```

### Method 2: Bot Token (Advanced)

1. Create a Slack app:
   - Go to [Slack API: Apps](https://api.slack.com/apps)
   - Click "Create New App" → "From scratch"
   - Add "Bot" user with `chat:write` permissions
   - Install to workspace and copy Bot Token (`xoxb-...`)

2. Invite bot to channel:
   ```slack
   /invite @YourBotName
   ```

3. Configure kim:
   ```json
   {
     "slack": {
       "enabled": true,
        "bot_token": "xoxb-your-bot-token",
       "channel": "#dev-alerts"
     }
   }
   ```

## Testing

Test your Slack configuration:

```bash
kim slack --test -t "Test Notification" -m "Hello from kim!"
```

This will send a test message using your configured method.

## Viewing Configuration

```bash
kim slack
```

Shows current Slack settings (without exposing tokens).

## Notification Format

### Webhook

```
*Reminder Title*
Reminder message
```

### Bot Token

```
🔔 *Reminder Title*
Reminder message
```

(Urgency emoji varies: `ℹ️` low, `🔔` normal, `🚨` critical)

## Troubleshooting

### Webhook Not Working

1. Verify webhook URL is correct
2. Test with `curl`:
   ```bash
   curl -X POST -H 'Content-type: application/json' --data '{"text":"Test"}' YOUR_WEBHOOK_URL
   ```
3. Check Slack workspace permissions

### Bot Token Issues

1. Ensure bot is invited to the channel
2. Verify bot has `chat:write` scope
3. Test with `kim slack --test`

### Channel Not Found

For bot tokens, ensure:
- Channel name starts with `#`
- Bot is a member of the channel
- Channel exists in the workspace

## Security Notes

- Keep webhook URLs and bot tokens secret
- Don't commit them to version control
- Use environment variables or secure secret management
- Rotate tokens if compromised

## Example Configurations

### Webhook to #general

```json
{
  "slack": {
    "enabled": true,
    "webhook_url": "https://hooks.slack.com/services/your-webhook-id"
  }
}
```

### Bot to Multiple Channels

kim currently supports a single channel. For multiple channels, use webhooks or extend the configuration.