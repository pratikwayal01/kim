"""
Config-related commands: edit, list, logs, validate, export, import.
"""

import datetime as _dt
import json
import os
import platform
import subprocess
import sys
import time as _time
from pathlib import Path

from ..core import CONFIG, LOG_FILE, ONESHOT_FILE, load_config, log
from ..utils import CHECK, MIDDOT, HLINE


def _save_config(config: dict) -> None:
    """
    Atomically write config to disk (write .tmp then rename).
    Raises SystemExit(1) on failure.
    """
    try:
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
        if platform.system() != "Windows":
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        tmp.replace(CONFIG)
    except OSError as e:
        print(f"Error writing config file: {e}")
        sys.exit(1)


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
    print(f"{'NAME':<20} {'SCHEDULE':>14}   {'URGENCY':<10} {'ENABLED'}")
    print(HLINE * 60)
    for r in reminders:
        enabled = CHECK if r.get("enabled", True) else MIDDOT
        if r.get("at"):
            interval_str = f"at {r['at']}"
        else:
            interval = r.get("interval") or r.get("interval_minutes", 30)
            if isinstance(interval, str):
                interval_str = interval
            else:
                interval_str = f"{interval} min"
        print(
            f"{r['name']:<20} {interval_str:>14}   {r.get('urgency', 'normal'):<10} {enabled}"
        )

    if getattr(args, "oneshots", False):
        oneshots = []
        if ONESHOT_FILE.exists():
            try:
                oneshots = json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
            except Exception:
                oneshots = []
        now = _time.time()
        pending = sorted(
            [o for o in oneshots if o.get("fire_at", 0) > now],
            key=lambda o: o["fire_at"],
        )
        print()
        if not pending:
            print("One-shots: none pending")
        else:
            print(f"{'#':<4} {'MESSAGE':<30} {'FIRES AT':<20} {'IN'}")
            print("-" * 70)
            for i, o in enumerate(pending, 1):
                msg = o.get("message", "")[:28]
                fire_dt = _dt.datetime.fromtimestamp(o["fire_at"]).strftime(
                    "%Y-%m-%d %H:%M"
                )
                remaining = int(o["fire_at"] - now)
                parts = []
                for unit, label in [(3600, "h"), (60, "m"), (1, "s")]:
                    if remaining >= unit:
                        parts.append(f"{remaining // unit}{label}")
                        remaining %= unit
                eta = " ".join(parts) if parts else "now"
                print(f"{i:<4} {msg:<30} {fire_dt:<20} {eta}")


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
    # Read the raw file directly so JSONDecodeError is catchable.
    # load_config() silently swallows parse errors and returns a default.
    if not CONFIG.exists():
        print("Config file not found. Run 'kim start' to create it.")
        sys.exit(1)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"Error reading config file: {e}")
        sys.exit(1)

    if "reminders" not in config:
        print("Warning: No 'reminders' key found in config.")

    reminders = config.get("reminders", [])
    for r in reminders:
        if "name" not in r:
            print("Error: Reminder missing 'name' field.")
            sys.exit(1)
        # Accept 'at' (daily schedule), 'interval', or legacy 'interval_minutes'
        has_schedule = r.get("at") or r.get("interval") or r.get("interval_minutes")
        if not has_schedule:
            print(
                f"Error: Reminder '{r.get('name')}' missing schedule ('interval' or 'at') field."
            )
            sys.exit(1)
        if r.get("at"):
            import re as _re

            if not _re.fullmatch(r"(\d{1,2}):(\d{2})", str(r["at"]).strip()):
                print(
                    f"Error: Reminder '{r.get('name')}' has invalid 'at' value {r['at']!r}. Use HH:MM format."
                )
                sys.exit(1)
        interval_val = r.get("interval") or r.get("interval_minutes")
        if (
            interval_val is not None
            and not isinstance(interval_val, str)
            and (not isinstance(interval_val, (int, float)) or interval_val <= 0)
        ):
            print(f"Error: Reminder '{r.get('name')}' has invalid interval.")
            sys.exit(1)

    print(f"{CHECK} Config is valid ({len(reminders)} reminder(s))")


def cmd_export(args):
    config = load_config()
    include_oneshots = getattr(args, "oneshots", False)

    # Optionally load pending one-shots
    pending_oneshots = []
    if include_oneshots and ONESHOT_FILE.exists():
        try:
            raw_os = json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
            now = _time.time()
            pending_oneshots = [o for o in raw_os if o.get("fire_at", 0) > now]
        except (json.JSONDecodeError, OSError):
            pending_oneshots = []

    if args.format == "json":
        export_doc = dict(config)
        if include_oneshots:
            export_doc["oneshots"] = pending_oneshots
        output = json.dumps(export_doc, indent=2)
    else:  # csv
        reminders = config.get("reminders", [])
        lines = ["name,interval,title,message,urgency,enabled"]
        for r in reminders:
            name = r.get("name", "").replace(",", ";")
            title = r.get("title", "").replace(",", ";")
            message = r.get("message", "").replace(",", ";").replace("\n", " ")
            line = f"{name},{r.get('interval') or r.get('interval_minutes', '')},{title},{message},{r.get('urgency', 'normal')},{r.get('enabled', True)}"
            lines.append(line)
        if include_oneshots and pending_oneshots:
            lines.append("")
            lines.append("# oneshots: message,title,urgency,fire_at")
            for o in pending_oneshots:
                msg = o.get("message", "").replace(",", ";").replace("\n", " ")
                ttl = o.get("title", "Reminder").replace(",", ";")
                urg = o.get("urgency", "normal")
                lines.append(f"{msg},{ttl},{urg},{o.get('fire_at', 0)}")
        output = "\n".join(lines)

    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
            msg = f"Exported to {args.output}"
            if include_oneshots:
                msg += f" ({len(pending_oneshots)} one-shot(s) included)"
            print(msg)
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

        imported_oneshots = []

        if fmt == "csv":
            lines = content.strip().splitlines()
            if len(lines) < 2:
                print("Invalid CSV format.")
                sys.exit(1)

            reminders = []
            in_oneshots = False
            for line in lines[1:]:
                if line.startswith("# oneshots:"):
                    in_oneshots = True
                    continue
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.split(",")
                if in_oneshots:
                    if len(parts) >= 4:
                        try:
                            fire_at = float(parts[3])
                        except ValueError:
                            continue
                        if fire_at > _time.time():
                            imported_oneshots.append(
                                {
                                    "message": parts[0].replace(";", ","),
                                    "title": parts[1].replace(";", ","),
                                    "urgency": parts[2]
                                    if parts[2] in ("low", "normal", "critical")
                                    else "normal",
                                    "fire_at": fire_at,
                                }
                            )
                elif len(parts) >= 6:
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
            # Extract one-shots from JSON export (future fire times only)
            now = _time.time()
            for o in raw.get("oneshots", []):
                fire_at = o.get("fire_at", 0)
                if isinstance(fire_at, (int, float)) and fire_at > now:
                    imported_oneshots.append(
                        {
                            "message": str(o.get("message", ""))[:500],
                            "title": str(o.get("title", "Reminder"))[:200],
                            "urgency": o.get("urgency", "normal")
                            if o.get("urgency") in ("low", "normal", "critical")
                            else "normal",
                            "fire_at": float(fire_at),
                        }
                    )

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

        _save_config(config)
        print(f"{CHECK} {action} {len(imported_data.get('reminders', []))} reminder(s)")

        # Handle one-shots import
        if getattr(args, "oneshots", False) and imported_oneshots:
            existing_os = []
            if ONESHOT_FILE.exists():
                try:
                    existing_os = json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    existing_os = []
            existing_fire_ats = {o.get("fire_at") for o in existing_os}
            added = [
                o for o in imported_oneshots if o["fire_at"] not in existing_fire_ats
            ]
            if added:
                merged_os = existing_os + added
                try:
                    _tmp = ONESHOT_FILE.with_suffix(".tmp")
                    _tmp.write_text(json.dumps(merged_os, indent=2), encoding="utf-8")
                    if platform.system() != "Windows":
                        try:
                            os.chmod(_tmp, 0o600)
                        except OSError:
                            pass
                    _tmp.replace(ONESHOT_FILE)
                    print(f"{CHECK} Imported {len(added)} pending one-shot(s)")
                except OSError as e:
                    print(f"Warning: could not write oneshots.json: {e}")
            else:
                print(
                    "No new pending one-shots to import (all already exist or expired)."
                )
        elif getattr(args, "oneshots", False):
            print("No pending one-shots found in the import file.")

    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)
    except OSError as e:
        print(f"Import failed (I/O error): {e}")
        sys.exit(1)
    except (KeyError, TypeError, ValueError) as e:
        print(f"Import failed (malformed data): {e}")
        sys.exit(1)
