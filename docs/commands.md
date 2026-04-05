# CLI Commands

kim provides a command-line interface for managing reminders and the daemon.

## Global Options

- `--version` — Show version
- `-i` — Alias for `interactive` command

## Daemon Control

| Command | Description |
|---|---|
| `kim start` | Start the daemon |
| `kim stop` | Stop the daemon |
| `kim status` | Show status and active reminders |
| `kim logs` | Show recent log entries (default: 30 lines) |

### Examples

```bash
kim start
kim status
kim logs -n 50   # Last 50 lines
```

## Reminder Management

| Command | Description |
|---|---|
| `kim list` | List all reminders from config |
| `kim add` | Add a new reminder |
| `kim remove` | Remove a reminder |
| `kim enable` | Enable a reminder |
| `kim disable` | Disable a reminder |
| `kim update` | Update a reminder |

### `kim add`

```bash
kim add NAME (-I|-E INTERVAL | --every INTERVAL | --at HH:MM) [-t TITLE] [-m MESSAGE] [-u URGENCY] [--tz TZ] [--sound-file FILE] [--slack-channel CHANNEL] [--slack-webhook URL]
```

**Options:**
- `-I, --interval, --every` — Recurring interval (e.g., `30m`, `1h`, `1d`) [required unless --at]
- `--at HH:MM` — Fire daily at a fixed time, e.g. `--at 10:00` [required unless --interval]
- `-t, --title` — Notification title
- `-m, --message` — Notification message
- `-u, --urgency` — `low`, `normal`, `critical` (default: `normal`)
- `--tz TZ` — IANA timezone for `--at`, e.g. `Asia/Kolkata` (default: local system timezone)
- `--sound-file` — Per-reminder sound file path (overrides global)
- `--slack-channel` — Per-reminder Slack channel
- `--slack-webhook` — Per-reminder Slack webhook URL

**Example:**
```bash
# Interval-based (unchanged, --every is now also accepted)
kim add eye-break -I 30m -t "👁️ Eye Break" -m "Look away from screen" -u critical
kim add "drink water" --every 1h
kim add standup -I 30m --slack-channel "#standup" --sound-file ~/sounds/urgent.wav

# Daily at a fixed time
kim add standup --at 10:00
kim add standup --at 10:00 --tz Asia/Kolkata
```

### `kim remove`

```bash
kim remove NAME
```

### `kim enable` / `kim disable`

```bash
kim enable NAME
kim disable NAME
```

### `kim update`

```bash
kim update NAME [-I INTERVAL] [--every INTERVAL] [--at HH:MM] [--tz TZ] [-t TITLE] [-m MESSAGE] [-u URGENCY] [--enable] [--disable] [--sound-file FILE] [--slack-channel CHANNEL] [--slack-webhook URL]
```

**New options:**
- `--every` — Alias for `--interval`
- `--at HH:MM` — Switch to daily at-time schedule
- `--tz TZ` — Timezone for `--at`
- `--sound-file` — Set per-reminder sound file
- `--slack-channel` — Set per-reminder Slack channel
- `--slack-webhook` — Set per-reminder Slack webhook URL

## One-shot Reminders

```bash
kim remind MESSAGE TIME [...] [-t TITLE] [--urgency URGENCY] [--tz TZ]
```

**TIME — relative:**
```
in 10m      10 minutes from now
1h          1 hour
2h 30m      2 hours 30 minutes
90s         90 seconds
```

**TIME — absolute (`at ...`):**
```
at 14:30               today at 14:30 (or tomorrow if already past)
at tomorrow 10am       tomorrow at 10:00
at friday 9am          next Friday at 09:00
at 2026-04-06 09:00    specific date and time
```

**Options:**
- `-t, --title` — Notification title (default: `Reminder`)
- `--urgency` — `low`, `normal`, `critical` (default: `normal`)
- `--tz TZ` — IANA timezone for absolute times (default: local system timezone)

**Examples:**
```bash
kim remind "standup call" in 10m
kim remind "take a break" 1h
kim remind "deploy window opens" 2h 30m
kim remind "standup" at 10:00
kim remind "standup" at tomorrow 9am
kim remind "call" at 2026-04-06 14:30 --tz America/New_York
kim remind "wake up!" in 5m --urgency critical
```

**Persistence:** One-shot reminders are persisted to disk (`~/.kim/oneshots.json`) and survive daemon restarts and system reboots. Expired reminders are automatically cleaned up.

## Configuration

| Command | Description |
|---|---|
| `kim edit` | Open config in `$EDITOR` |
| `kim validate` | Validate config file |
| `kim export` | Export reminders to file |
| `kim import` | Import reminders from file |

### `kim export`

```bash
kim export [-f FORMAT] [-o OUTPUT]
```

**FORMAT:** `json` (default), `csv`

**Example:**
```bash
kim export -f csv -o reminders.csv
```

### `kim import`

```bash
kim import FILE [-f FORMAT] [--merge]
```

**FORMAT:** `json`, `csv`, `auto` (default: auto-detect)

**Example:**
```bash
kim import reminders.json --merge
```

## Sound Configuration

```bash
kim sound [OPTIONS]
```

**Options:**
- `--set FILE` — Set custom sound file
- `--clear` — Revert to system default
- `--test` — Play current sound
- `--enable` — Enable sound notifications
- `--disable` — Disable sound notifications

**Examples:**
```bash
kim sound --set ~/sounds/bell.mp3
kim sound --test
kim sound --disable
```

## Slack Integration

```bash
kim slack [--test] [-t TITLE] [-m MESSAGE]
```

**Example:**
```bash
kim slack --test -t "Test" -m "Hello from kim"
```

## Interactive Mode

```bash
kim interactive   # or kim -i
```

A text-based UI for managing reminders. Use arrow keys to navigate, Enter to select.

## Self-Update & Uninstall

| Command | Description |
|---|---|
| `kim self-update` | Check for and install updates |
| `kim uninstall` | Uninstall kim completely |

### `kim self-update`

```bash
kim self-update [-f]   # Skip confirmation prompt
```

## Shell Completions

Generate shell completions:

```bash
kim completion bash   # Bash
kim completion zsh    # Zsh  
kim completion fish   # Fish
```

Add to your shell config (e.g., `.bashrc`):
```bash
eval "$(kim completion bash)"
```