"""
Reminder management commands: add, remove, enable, disable, update.
"""

import json
import os
import platform
import sys
from pathlib import Path

from ..core import CONFIG, load_config, log
from ..utils import CHECK


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

    config.setdefault("reminders", []).append(new_reminder)

    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        # Ensure config file permissions are secure
        if platform.system() != "Windows":
            os.chmod(CONFIG, 0o600)
    except OSError as e:
        print(f"Error writing config file: {e}")
        sys.exit(1)

    print(f"{CHECK} Added reminder '{name}' (every {interval_str})")
    log.info(f"Added reminder: {name}")


def cmd_remove(args):
    config = load_config()
    name = args.name

    reminders = config.get("reminders", [])
    initial_count = len(reminders)
    config["reminders"] = [r for r in reminders if r.get("name") != name]

    if len(config["reminders"]) == initial_count:
        print(f"Reminder '{name}' not found.")
        sys.exit(1)

    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        if platform.system() != "Windows":
            os.chmod(CONFIG, 0o600)
    except OSError as e:
        print(f"Error writing config file: {e}")
        sys.exit(1)

    print(f"{CHECK} Removed reminder '{name}'")
    log.info(f"Removed reminder: {name}")


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

    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        if platform.system() != "Windows":
            os.chmod(CONFIG, 0o600)
    except OSError as e:
        print(f"Error writing config file: {e}")
        sys.exit(1)

    print(f"{CHECK} Enabled reminder '{name}'")
    log.info(f"Enabled reminder: {name}")


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

    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        if platform.system() != "Windows":
            os.chmod(CONFIG, 0o600)
    except OSError as e:
        print(f"Error writing config file: {e}")
        sys.exit(1)

    print(f"{CHECK} Disabled reminder '{name}'")
    log.info(f"Disabled reminder: {name}")


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
            if args.enable is not None:
                r["enabled"] = args.enable
            if args.disable is not None:
                r["enabled"] = not args.disable
            break

    if not found:
        print(f"Reminder '{name}' not found.")
        sys.exit(1)

    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        if platform.system() != "Windows":
            os.chmod(CONFIG, 0o600)
    except OSError as e:
        print(f"Error writing config file: {e}")
        sys.exit(1)

    print(f"{CHECK} Updated reminder '{name}'")
    log.info(f"Updated reminder: {name}")
