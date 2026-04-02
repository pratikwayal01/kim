"""
Config-related commands: edit, list, logs, validate, export, import.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from ..core import CONFIG, LOG_FILE, load_config, log
from ..utils import CHECK, MIDDOT, HLINE


def cmd_edit(args):
    load_config()  # ensure config exists
    editor = os.environ.get("EDITOR")
    if platform.system() == "Windows":
        if not editor:
            editor = "notepad"
        try:
            subprocess.run([editor, str(CONFIG)])
        except FileNotFoundError:
            print(
                f"Editor '{editor}' not found. Please set EDITOR environment variable."
            )
            sys.exit(1)
        except OSError as e:
            print(f"Error launching editor: {e}")
            sys.exit(1)
    else:
        if not editor:
            editor = "nano"
        try:
            os.execvp(editor, [editor, str(CONFIG)])
        except FileNotFoundError:
            print(
                f"Editor '{editor}' not found. Please set EDITOR environment variable."
            )
            sys.exit(1)
        except OSError as e:
            print(f"Error launching editor: {e}")
            sys.exit(1)


def cmd_list(args):
    config = load_config()
    reminders = config.get("reminders", [])
    print(f"{'NAME':<20} {'INTERVAL':>12}   {'URGENCY':<10} {'ENABLED'}")
    print(HLINE * 58)
    for r in reminders:
        enabled = CHECK if r.get("enabled", True) else MIDDOT
        interval = r.get("interval") or r.get("interval_minutes", 30)
        if isinstance(interval, str):
            interval_str = interval
        else:
            interval_str = f"{interval} min"
        print(
            f"{r['name']:<20} {interval_str:>12}   {r.get('urgency', 'normal'):<10} {enabled}"
        )


def cmd_logs(args):
    n = args.lines
    if not LOG_FILE.exists():
        print("No log file yet.")
        return
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines[-n:]:
            print(line)
    except OSError as e:
        print(f"Error reading log file: {e}")


def cmd_validate(args):
    try:
        config = load_config()

        if "reminders" not in config:
            print("Warning: No 'reminders' key found in config.")

        reminders = config.get("reminders", [])
        for r in reminders:
            if "name" not in r:
                print("Error: Reminder missing 'name' field.")
                sys.exit(1)
            # Accept both 'interval' and 'interval_minutes' (legacy)
            interval_val = r.get("interval") or r.get("interval_minutes")
            if interval_val is None:
                print(f"Error: Reminder '{r.get('name')}' missing 'interval' field.")
                sys.exit(1)
            if isinstance(interval_val, str):
                pass
            elif not isinstance(interval_val, (int, float)) or interval_val < 0:
                print(f"Error: Reminder '{r.get('name')}' has invalid interval.")
                sys.exit(1)

        print(f"{CHECK} Config is valid ({len(reminders)} reminder(s))")

    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"Error reading config file: {e}")
        sys.exit(1)


def cmd_export(args):
    config = load_config()

    if args.format == "json":
        output = json.dumps(config, indent=2)
    elif args.format == "csv":
        reminders = config.get("reminders", [])
        if reminders:
            lines = ["name,interval,title,message,urgency,enabled"]
            for r in reminders:
                name = r.get("name", "").replace(",", ";")
                title = r.get("title", "").replace(",", ";")
                message = r.get("message", "").replace(",", ";").replace("\n", " ")
                line = f"{name},{r.get('interval') or r.get('interval_minutes', '')},{title},{message},{r.get('urgency', 'normal')},{r.get('enabled', True)}"
                lines.append(line)
            output = "\n".join(lines)
        else:
            output = "name,interval,title,message,urgency,enabled"
    else:
        output = json.dumps(config, indent=2)

    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"Exported to {args.output}")
        except OSError as e:
            print(f"Error writing file: {e}")
            sys.exit(1)
    else:
        print(output)


def _sanitize_reminder(r: dict) -> dict:
    """Strip dangerous or unknown keys from a reminder dict."""
    ALLOWED_KEYS = {
        "name",
        "interval",
        "title",
        "message",
        "urgency",
        "enabled",
        "sound",
        "sound_file",
        "slack",
    }
    safe = {}
    for k in ALLOWED_KEYS:
        if k in r:
            if k == "name" and isinstance(r[k], str):
                safe[k] = r[k][:100].strip()
            elif k == "interval" and isinstance(r[k], (str, int, float)):
                safe[k] = r[k]
            elif k in ("title", "message") and isinstance(r[k], str):
                safe[k] = r[k][:500]
            elif k == "urgency" and r[k] in ("low", "normal", "critical"):
                safe[k] = r[k]
            elif k == "enabled" and isinstance(r[k], bool):
                safe[k] = r[k]
            elif k == "sound" and isinstance(r[k], bool):
                safe[k] = r[k]
            elif k == "sound_file" and isinstance(r[k], str):
                safe[k] = r[k][:500]
            elif k == "slack" and isinstance(r[k], dict):
                safe[k] = {
                    "enabled": bool(r[k].get("enabled", False)),
                    "webhook_url": str(r[k].get("webhook_url", ""))[:500],
                    "bot_token": str(r[k].get("bot_token", ""))[:500],
                    "channel": str(r[k].get("channel", "#general"))[:100],
                }
    return safe


def cmd_import(args):
    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {args.file}")
        sys.exit(1)

    try:
        content = path.read_text(encoding="utf-8")

        if args.format == "auto":
            fmt = "csv" if path.suffix == ".csv" else "json"
        else:
            fmt = args.format

        if fmt == "csv":
            lines = content.strip().splitlines()
            if len(lines) < 2:
                print("Invalid CSV format.")
                sys.exit(1)

            reminders = []
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 6:
                    reminders.append(
                        _sanitize_reminder(
                            {
                                "name": parts[0],
                                "interval": parts[1]
                                if not parts[1].isdigit()
                                else int(parts[1]),
                                "title": parts[2],
                                "message": parts[3],
                                "urgency": parts[4]
                                if parts[4] in ["low", "normal", "critical"]
                                else "normal",
                                "enabled": parts[5].lower() == "true",
                            }
                        )
                    )
            imported_data = {"reminders": reminders, "sound": True}
        else:
            raw = json.loads(content)
            imported_data = {
                "reminders": [_sanitize_reminder(r) for r in raw.get("reminders", [])],
                "sound": raw.get("sound", True),
                "sound_file": raw.get("sound_file"),
                "slack": {
                    "enabled": bool(raw.get("slack", {}).get("enabled", False)),
                    "webhook_url": str(raw.get("slack", {}).get("webhook_url", ""))[
                        :500
                    ],
                    "bot_token": str(raw.get("slack", {}).get("bot_token", ""))[:500],
                    "channel": str(raw.get("slack", {}).get("channel", "#general"))[
                        :100
                    ],
                },
            }

        config = load_config()

        if args.merge:
            existing_names = {r["name"] for r in config.get("reminders", [])}
            for r in imported_data.get("reminders", []):
                if r.get("name") not in existing_names:
                    config.setdefault("reminders", []).append(r)
            action = "Merged"
        else:
            config["reminders"] = imported_data.get("reminders", [])
            config["sound"] = imported_data.get("sound", True)
            config["sound_file"] = imported_data.get("sound_file")
            config["slack"] = imported_data.get("slack", config.get("slack", {}))
            action = "Imported"

        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        if platform.system() != "Windows":
            os.chmod(CONFIG, 0o600)

        print(f"{CHECK} {action} {len(imported_data.get('reminders', []))} reminder(s)")

    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Import failed: {e}")
        sys.exit(1)
