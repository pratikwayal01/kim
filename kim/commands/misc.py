"""
Miscellaneous commands: remind, slack, sound, completion.
"""

import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

from ..core import CONFIG, ONESHOT_FILE, VERSION, load_config, log
from ..notifications import notify
from ..sound import SOUND_FORMAT_NOTES, play_sound_file, validate_sound_file
from ..utils import CHECK, CROSS, EM_DASH, ALARM, PLAY, BELL


def cmd_remind(args):
    raw = " ".join(args.time)
    raw = raw.strip().lower().removeprefix("in").strip()

    total_seconds = 0
    for match in re.finditer(r"(\d+)\s*(d|h|m|s)", raw):
        value, unit = int(match.group(1)), match.group(2)
        total_seconds += {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit] * value

    if total_seconds == 0:
        print("Couldn't parse time. Examples: 'in 10m', 'in 1h', 'in 2h 30m'")
        sys.exit(1)

    message = args.message
    # Default title: "Reminder" on Windows, "⏰ Reminder" elsewhere
    title = args.title or ("Reminder" if ALARM == "Reminder" else f"{ALARM} Reminder")
    sleep_seconds = total_seconds

    parts = []
    remaining = total_seconds
    for unit, label in [(3600, "h"), (60, "m"), (1, "s")]:
        if remaining >= unit:
            parts.append(f"{remaining // unit}{label}")
            remaining %= unit
    display = " ".join(parts)

    print(f"{title} set: '{message}' in {display}")
    log.info(f"One-shot reminder set: '{message}' in {display}")

    # Save one-shot reminder for persistence across reboots
    fire_time = time.time() + sleep_seconds
    oneshot = {
        "message": message,
        "title": title,
        "fire_at": fire_time,
    }
    oneshots = []
    if ONESHOT_FILE.exists():
        try:
            oneshots = json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            oneshots = []
    oneshots.append(oneshot)
    try:
        ONESHOT_FILE.write_text(json.dumps(oneshots, indent=2), encoding="utf-8")
        log.debug(f"Saved one-shot reminder to {ONESHOT_FILE}")
    except OSError as e:
        log.warning(f"Could not save one-shot reminder: {e}")

    if platform.system() == "Windows":
        # Spawn background process using PowerShell with hidden window
        cmd = [
            "powershell",
            "-WindowStyle",
            "Hidden",
            "-Command",
            f'python -m kim _remind-fire --message "{message}" --title "{title}" --seconds {sleep_seconds}',
        ]
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        return

    # Unix: fork a background child
    pid = os.fork()
    if pid > 0:
        return  # parent returns immediately

    # Child process: sleep then fire
    config = load_config()
    sound = config.get("sound", True)
    sound_file = config.get("sound_file") or None
    slack_config = config.get("slack", {})

    time.sleep(sleep_seconds)
    notify(
        title,
        message,
        urgency="critical",
        sound=sound,
        sound_file=sound_file,
        slack_config=slack_config if slack_config.get("enabled") else None,
    )
    log.info(f"One-shot reminder fired: '{message}'")
    sys.exit(0)


def cmd_remind_fire(args):
    """Internal command used by Windows to fire a one-shot reminder."""
    time.sleep(args.seconds)
    config = load_config()
    sound = config.get("sound", True)
    sound_file = config.get("sound_file") or None
    slack_config = config.get("slack", {})
    notify(
        args.title,
        args.message,
        urgency="critical",
        sound=sound,
        sound_file=sound_file,
        slack_config=slack_config if slack_config.get("enabled") else None,
    )
    log.info(f"One-shot reminder fired: '{args.message}'")


def load_oneshot_reminders():
    """
    Load persisted one-shot reminders from file.
    Returns list of oneshot dicts with fire_at timestamp.
    Called by daemon on startup.
    """
    if not ONESHOT_FILE.exists():
        return []
    try:
        oneshots = json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
        now = time.time()
        # Filter out oneshots that have already fired (past fire_at)
        valid = [o for o in oneshots if o.get("fire_at", 0) > now]
        if len(valid) != len(oneshots):
            # Clean up expired oneshots
            ONESHOT_FILE.write_text(json.dumps(valid, indent=2), encoding="utf-8")
            log.info(
                f"Cleaned up {len(oneshots) - len(valid)} expired one-shot reminders"
            )
        return valid
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Could not load one-shot reminders: {e}")
        return []


def remove_oneshot(fire_at):
    """Remove a one-shot reminder from the persisted file by fire_at timestamp."""
    if not ONESHOT_FILE.exists():
        return
    try:
        oneshots = json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
        oneshots = [o for o in oneshots if o.get("fire_at") != fire_at]
        ONESHOT_FILE.write_text(json.dumps(oneshots, indent=2), encoding="utf-8")
    except (json.JSONDecodeError, OSError):
        pass


def cmd_slack(args):
    config = load_config()
    slack_config = config.get("slack", {})

    if args.test:
        title = args.title or "Test Notification"
        message = args.message or "This is a test from kim!"

        if slack_config.get("webhook_url"):
            print(f"Sending test to webhook...")
            # Use the internal slack webhook function from notifications module
            from ..notifications import _notify_slack_webhook

            _notify_slack_webhook(title, message, slack_config["webhook_url"])
            print(f"{CHECK} Test notification sent via webhook")
        elif slack_config.get("bot_token") and slack_config.get("channel"):
            print(f"Sending test to #{slack_config.get('channel')}...")
            from ..notifications import _notify_slack_bot

            _notify_slack_bot(
                title, message, slack_config["bot_token"], slack_config["channel"]
            )
            print(f"{CHECK} Test notification sent via bot")
        else:
            print(
                "Slack not configured. Edit ~/.kim/config.json and add slack.webhook_url or slack.bot_token"
            )
            sys.exit(1)
        return

    print("Slack configuration:")
    print(f"  Enabled: {slack_config.get('enabled', False)}")
    print(
        f"  Webhook URL: {'configured' if slack_config.get('webhook_url') else 'not set'}"
    )
    print(
        f"  Bot Token: {'configured' if slack_config.get('bot_token') else 'not set'}"
    )
    print(f"  Channel: {slack_config.get('channel', '#general')}")


def cmd_sound(args):
    """Manage the custom sound file for notifications."""
    config = load_config()

    if args.set:
        path = os.path.abspath(os.path.expanduser(args.set))
        ok, err = validate_sound_file(path)
        if not ok:
            print(f"{CROSS} {err}")
            sys.exit(1)
        config["sound_file"] = path
        config["sound"] = True
        try:
            with open(CONFIG, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            print(f"Error writing config file: {e}")
            sys.exit(1)
        print(f"{CHECK} Custom sound set: {path}")
        print("  Restart kim ('kim stop && kim start') to apply.")
        log.info(f"sound_file set to: {path}")
        return

    if args.clear:
        config["sound_file"] = None
        try:
            with open(CONFIG, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            print(f"Error writing config file: {e}")
            sys.exit(1)
        print(f"{CHECK} Custom sound cleared {EM_DASH} reverted to system default.")
        print("  Restart kim ('kim stop && kim start') to apply.")
        log.info("sound_file cleared")
        return

    if args.test:
        sound_enabled = config.get("sound", True)
        if not sound_enabled:
            print(
                "Sound is currently disabled. Enable it first with 'kim sound --enable'."
            )
            sys.exit(1)
        sound_file = config.get("sound_file") or None
        if sound_file:
            ok, err = validate_sound_file(sound_file)
            if not ok:
                print(f"{CROSS} Cannot play: {err}")
                sys.exit(1)
            print(f"{PLAY} Playing: {sound_file}")
        else:
            print(f"{PLAY} Playing system default sound...")
        notify(
            f"{BELL} kim sound test",
            "This is how your reminder will sound.",
            urgency="normal",
            sound=True,
            sound_file=sound_file,
        )
        return

    if args.enable:
        config["sound"] = True
        try:
            with open(CONFIG, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            print(f"Error writing config file: {e}")
            sys.exit(1)
        print(f"{CHECK} Sound enabled.")
        return

    if args.disable:
        config["sound"] = False
        try:
            with open(CONFIG, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            print(f"Error writing config file: {e}")
            sys.exit(1)
        print(f"{CHECK} Sound disabled.")
        return

    # Default: show current sound config
    sound_enabled = config.get("sound", True)
    sound_file = config.get("sound_file") or None
    system = platform.system()

    print("Sound configuration:")
    print(f"  Enabled   : {'yes' if sound_enabled else 'no'}")
    if sound_file:
        ok, err = validate_sound_file(sound_file)
        status = f"{CHECK} file found" if ok else f"{CROSS} {err}"
        print(f"  Sound file: {sound_file}  [{status}]")
    else:
        print("  Sound file: (system default)")
    print(f"  Platform  : {system}")
    print(f"  Formats   : {SOUND_FORMAT_NOTES.get(system, 'unknown platform')}")
    print()
    print("Commands:")
    print("  kim sound --set /path/to/sound.wav   Set a custom sound file")
    print("  kim sound --clear                    Revert to system default")
    print("  kim sound --test                     Play the current sound")
    print("  kim sound --enable / --disable       Toggle sound on/off")


# ── Shell completion strings ──────────────────────────────────────────────────
BASH_COMPLETION = """#!/bin/bash
_kim_completions() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    opts="start stop status list logs edit add remove enable disable update interactive self-update uninstall export import validate slack sound completion"

    case "${prev}" in
        kim)
            COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
            return 0
            ;;
        remove|enable|disable|update)
            local config="$HOME/.kim/config.json"
            if [[ -f "$config" ]]; then
                local names=$(python3 -c "import json; print(' '.join([r['name'] for r in json.load(open('$config')).get('reminders', [])]))" 2>/dev/null)
                COMPREPLY=( $(compgen -W "${names}" -- ${cur}) )
            fi
            return 0
            ;;
    esac
}
complete -F _kim_completions kim
"""

ZSH_COMPLETION = """#!/usr/bin/env zsh
_kim() {
    local -a commands
    commands=(
        "start:Start the daemon"
        "stop:Stop the daemon"
        "status:Show status and active reminders"
        "list:List all reminders from config"
        "logs:Show recent log entries"
        r"edit:Open config in $EDITOR"
        "add:Add a new reminder"
        "remove:Remove a reminder"
        "enable:Enable a reminder"
        "disable:Disable a reminder"
        "update:Update a reminder"
        "interactive:Enter interactive mode"
        "self-update:Check for and install updates"
        "uninstall:Uninstall kim completely"
        "export:Export reminders to file"
        "import:Import reminders from file"
        "validate:Validate config file"
        "slack:Slack notification settings"
        "sound:Manage the notification sound file"
        "completion:Generate shell completions"
    )
    if (( CURRENT == 2 )); then
        _describe 'command' commands
    fi
}
_kim "$@"
"""

FISH_COMPLETION = """#!/usr/bin/env fish
complete -c kim -f -a "start stop status list logs edit add remove enable disable update interactive self-update uninstall export import validate slack sound completion"
"""


def cmd_completion(args):
    if args.shell == "bash":
        print(BASH_COMPLETION)
    elif args.shell == "zsh":
        print(ZSH_COMPLETION)
    elif args.shell == "fish":
        print(FISH_COMPLETION)
