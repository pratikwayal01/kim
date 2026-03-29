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
kim add NAME -I INTERVAL [-t TITLE] [-m MESSAGE] [-u URGENCY]
```

**Options:**
- `-I, --interval` — Interval (e.g., `30m`, `1h`, `1d`, or just number for minutes) [required]
- `-t, --title` — Notification title
- `-m, --message` — Notification message  
- `-u, --urgency` — `low`, `normal`, `critical` (default: `normal`)

**Example:**
```bash
kim add eye-break -I 30m -t "👁️ Eye Break" -m "Look away from screen" -u critical
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
kim update NAME [-i INTERVAL] [-t TITLE] [-m MESSAGE] [-u URGENCY] [--enable] [--disable]
```

## One-shot Reminders

```bash
kim remind MESSAGE TIME [TIME ...] [-t TITLE]
```

**TIME format:** `in 10m`, `1h`, `2h 30m`, `90s`

**Examples:**
```bash
kim remind "standup call" in 10m
kim remind "take a break" 1h
kim remind "deploy window opens" 2h 30m
```

**Persistence:** One-shot reminders are persisted to disk (`~/.kim/oneshots.json`) and will survive daemon restarts and system reboots. When the daemon starts, it loads any pending one-shot reminders and fires them at the scheduled time.

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