"""
Reminder management commands: add, remove, enable, disable, update.
"""

import json
import os
import platform
import sys

from ..core import CONFIG, load_config, log
from ..utils import CHECK

# CREATE_NO_WINDOW flag used when spawning subprocesses on Windows
_CREATE_NO_WINDOW = 0x08000000


def _save_config(config: dict) -> None:
    """
    Atomically write config to disk.
    Writes to a .tmp file first, then renames to avoid partial-write corruption.
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


def cmd_add(args):
    config = load_config()
    name = args.name
    interval_str = args.interval

    for r in config.get("reminders", []):
        if r.get("name") == name:
            print(f"Reminder '{name}' already exists. Use 'kim update' to modify it.")
            sys.exit(1)

    new_reminder = {
        "name": name,
        "interval": interval_str,
        "title": args.title or f"Reminder: {name}",
        "message": args.message or "Time for a reminder!",
        "urgency": args.urgency,
        "enabled": True,
    }

    if args.sound_file:
        new_reminder["sound_file"] = args.sound_file

    if args.slack_channel or args.slack_webhook:
        new_reminder["slack"] = {
            "enabled": True,
            "channel": args.slack_channel or "#general",
        }
        if args.slack_webhook:
            new_reminder["slack"]["webhook_url"] = args.slack_webhook

    config.setdefault("reminders", []).append(new_reminder)
    _save_config(config)

    print(f"{CHECK} Added reminder '{name}' (every {interval_str})")
    log.info("Added reminder: %s", name)


def cmd_remove(args):
    config = load_config()
    name = args.name

    reminders = config.get("reminders", [])
    initial_count = len(reminders)
    config["reminders"] = [r for r in reminders if r.get("name") != name]

    if len(config["reminders"]) == initial_count:
        print(f"Reminder '{name}' not found.")
        sys.exit(1)

    _save_config(config)
    print(f"{CHECK} Removed reminder '{name}'")
    log.info("Removed reminder: %s", name)


def cmd_enable(args):
    config = load_config()
    name = args.name

    found = False
    for r in config.get("reminders", []):
        if r.get("name") == name:
            r["enabled"] = True
            found = True
            break

    if not found:
        print(f"Reminder '{name}' not found.")
        sys.exit(1)

    _save_config(config)
    print(f"{CHECK} Enabled reminder '{name}'")
    log.info("Enabled reminder: %s", name)


def cmd_disable(args):
    config = load_config()
    name = args.name

    found = False
    for r in config.get("reminders", []):
        if r.get("name") == name:
            r["enabled"] = False
            found = True
            break

    if not found:
        print(f"Reminder '{name}' not found.")
        sys.exit(1)

    _save_config(config)
    print(f"{CHECK} Disabled reminder '{name}'")
    log.info("Disabled reminder: %s", name)


def cmd_update(args):
    config = load_config()
    name = args.name

    found = False
    for r in config.get("reminders", []):
        if r.get("name") == name:
            found = True
            if args.interval is not None:
                r["interval"] = args.interval
            if args.title is not None:
                r["title"] = args.title
            if args.message is not None:
                r["message"] = args.message
            if args.urgency is not None:
                r["urgency"] = args.urgency
            if args.enable:
                r["enabled"] = True
            if args.disable:
                r["enabled"] = False
            break

    if not found:
        print(f"Reminder '{name}' not found.")
        sys.exit(1)

    _save_config(config)
    print(f"{CHECK} Updated reminder '{name}'")
    log.info("Updated reminder: %s", name)
