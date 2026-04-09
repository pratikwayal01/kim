"""
CLI argument parsing and command dispatch for kim.
"""

import argparse
import os
import platform
import re
import subprocess
import sys

from .core import VERSION


def _ensure_path_windows():
    """
    Windows-only: if the Scripts directory that contains this kim entry-point
    is not on the user PATH, add it with `setx` so future shells find `kim`.
    Runs silently — any error is swallowed so it never breaks a command.
    """
    if platform.system() != "Windows":
        return
    try:
        import sysconfig

        scripts_dir = sysconfig.get_path("scripts", "nt_user")
        if not scripts_dir:
            return

        # Read the persistent user PATH from the registry (what setx writes to)
        result = subprocess.run(
            [
                "reg",
                "query",
                r"HKCU\Environment",
                "/v",
                "PATH",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        user_path = ""
        for line in result.stdout.splitlines():
            if "PATH" in line and "REG_" in line:
                # line looks like: "    PATH    REG_EXPAND_SZ    C:\foo;C:\bar"
                parts = line.strip().split(None, 2)
                if len(parts) == 3:
                    user_path = parts[2]
                break

        # Normalise separators for comparison
        dirs_in_path = [p.strip().lower() for p in user_path.split(";") if p.strip()]
        if scripts_dir.lower() in dirs_in_path:
            return  # already there

        # Add it permanently via setx (writes to HKCU\Environment)
        new_path = (
            user_path.rstrip(";") + ";" + scripts_dir if user_path else scripts_dir
        )
        subprocess.run(
            ["setx", "PATH", new_path],
            capture_output=True,
            timeout=10,
        )

        # Also patch the current process so this session works immediately
        os.environ["PATH"] = os.environ.get("PATH", "") + ";" + scripts_dir

        print(
            f"[kim] Added {scripts_dir} to your PATH.\n"
            "      Open a new terminal window for the change to take effect."
        )
    except Exception:
        pass  # never break the CLI over a PATH fix


from .interactive import _enable_windows_ansi, cmd_interactive
from .commands.daemon import cmd_start, cmd_stop, cmd_status
from .commands.management import (
    cmd_add,
    cmd_remove,
    cmd_enable,
    cmd_disable,
    cmd_update,
)
from .commands.config import (
    cmd_edit,
    cmd_list,
    cmd_logs,
    cmd_validate,
    cmd_export,
    cmd_import,
)
from .commands.misc import (
    cmd_remind,
    cmd_remind_fire,
    cmd_slack,
    cmd_sound,
    cmd_completion,
)
from .selfupdate import cmd_selfupdate, cmd_uninstall


def cmd_ui(_args) -> None:
    """Launch the graphical management UI (requires PySide6)."""
    from .ui import require_pyside6

    require_pyside6()
    from .ui.app import run

    run()


def main():
    _ensure_path_windows()  # add Scripts dir to PATH on first run if missing
    _enable_windows_ansi()  # enable ANSI colour codes on Windows for all commands

    class _Formatter(argparse.RawDescriptionHelpFormatter):
        """Hide the {cmd1,cmd2,...} metavar; keep the subcommand table in epilog."""

        def _format_actions_usage(self, actions, groups):
            text = super()._format_actions_usage(actions, groups)
            # Replace the long {start,stop,...} metavar with a short placeholder
            text = re.sub(r"\{[a-z,_-]{10,}\}", "<command>", text)
            return text

        def _format_action(self, action):
            # Suppress the positional subcommand list (we have the epilog table)
            if action.nargs == argparse.PARSER:
                return ""
            return super()._format_action(action)

    parser = argparse.ArgumentParser(
        prog="kim",
        description="keep in mind — lightweight reminder daemon",
        formatter_class=_Formatter,
        epilog="""commands:
  start       Start the daemon
  stop        Stop the daemon
  status      Show status and active reminders
  list [-o]   List reminders  (-o also shows pending one-shots)
  logs        Show recent log entries
  edit        Open config in $EDITOR
  add         Add a new reminder
  remove      Remove a reminder  (-o to cancel a one-shot)
  enable      Enable a reminder
  disable     Disable a reminder
  update      Update a reminder
  remind      Fire a one-shot reminder after a delay or at a time
  interactive Enter interactive mode  (alias: -i)
  ui          Open graphical manager  (requires PySide6)
  self-update Check for and install updates
  uninstall   Uninstall kim completely
  export      Export reminders to file  (--oneshots also exports pending one-shots)
  import      Import reminders from file  (--oneshots also imports one-shots)
  validate    Validate config file
  sound       Manage the notification sound file
  completion  Generate shell completions

config:   ~/.kim/config.json
oneshots: ~/.kim/oneshots.json
logs:     ~/.kim/kim.log""",
    )
    parser.add_argument("-v", "--version", action="version", version=f"kim {VERSION}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser("start", help="Start the daemon")
    sub.add_parser("stop", help="Stop the daemon")
    sub.add_parser("status", help="Show status and active reminders")

    list_p = sub.add_parser("list", help="List all reminders from config")
    list_p.add_argument(
        "-o",
        "--oneshots",
        action="store_true",
        help="Also show pending one-shot reminders",
    )

    sub.add_parser("edit", help="Open config in $EDITOR")

    logs_p = sub.add_parser("logs", help="Show recent log entries")
    logs_p.add_argument(
        "-n",
        "--lines",
        type=int,
        default=30,
        help="Number of lines to show (default: 30)",
    )

    add_p = sub.add_parser("add", help="Add a new reminder")
    add_p.add_argument("name", help="Reminder name")
    add_interval = add_p.add_mutually_exclusive_group(required=True)
    add_interval.add_argument(
        "-I",
        "--interval",
        "--every",
        dest="interval",
        type=str,
        metavar="INTERVAL",
        help="Interval (e.g., 30m, 1h, 1d, or just number for minutes)",
    )
    add_interval.add_argument(
        "--at",
        dest="at_time",
        type=str,
        metavar="HH:MM",
        help="Fire daily at a fixed time, e.g. --at 10:00 (uses local timezone)",
    )
    add_p.add_argument("-t", "--title", help="Notification title")
    add_p.add_argument("-m", "--message", help="Notification message")
    add_p.add_argument(
        "-u",
        "--urgency",
        choices=["low", "normal", "critical"],
        default="normal",
        help="Urgency level",
    )
    add_p.add_argument(
        "--tz",
        dest="timezone",
        metavar="TZ",
        help="Timezone for --at, e.g. Asia/Kolkata (default: local system timezone)",
    )
    add_p.add_argument("--sound-file", help="Per-reminder sound file path")
    add_p.add_argument("--slack-channel", help="Per-reminder Slack channel")
    add_p.add_argument("--slack-webhook", help="Per-reminder Slack webhook URL")

    remove_p = sub.add_parser("remove", help="Remove a reminder")
    remove_p.add_argument("name", help="Reminder name, or index/message for --oneshot")
    remove_p.add_argument(
        "-o",
        "--oneshot",
        action="store_true",
        help="Cancel a pending one-shot reminder by index (from 'kim list -o') or message substring",
    )

    enable_p = sub.add_parser("enable", help="Enable a reminder")
    enable_p.add_argument("name", help="Reminder name")

    disable_p = sub.add_parser("disable", help="Disable a reminder")
    disable_p.add_argument("name", help="Reminder name")

    update_p = sub.add_parser("update", help="Update a reminder")
    update_p.add_argument("name", help="Reminder name")
    update_p.add_argument(
        "-I",
        "--interval",
        "--every",
        dest="interval",
        type=str,
        metavar="INTERVAL",
        help="New interval (e.g., 30m, 1h, 1d)",
    )
    update_p.add_argument(
        "--at",
        dest="at_time",
        type=str,
        metavar="HH:MM",
        help="Change to daily at a fixed time, e.g. --at 10:00",
    )
    update_p.add_argument(
        "--tz",
        dest="timezone",
        metavar="TZ",
        help="Timezone for --at (default: local system timezone)",
    )
    update_p.add_argument("-t", "--title", help="New notification title")
    update_p.add_argument("-m", "--message", help="New notification message")
    update_p.add_argument(
        "-u",
        "--urgency",
        choices=["low", "normal", "critical"],
        help="New urgency level",
    )
    update_p.add_argument("--enable", action="store_true", help="Enable the reminder")
    update_p.add_argument("--disable", action="store_true", help="Disable the reminder")
    update_p.add_argument("--sound-file", help="Per-reminder sound file path")
    update_p.add_argument("--slack-channel", help="Per-reminder Slack channel")
    update_p.add_argument("--slack-webhook", help="Per-reminder Slack webhook URL")

    remind_p = sub.add_parser(
        "remind", help="Fire a one-shot reminder after a delay or at a specific time"
    )
    remind_p.add_argument("message", help="Reminder message")
    remind_p.add_argument(
        "time",
        nargs="+",
        help=(
            "When to fire. Relative: 'in 10m', '1h', '2h 30m', '90s'. "
            "Absolute: 'at 14:30', 'at tomorrow 10am', 'at 2026-04-06 09:00'"
        ),
    )
    remind_p.add_argument(
        "-t", "--title", help="Notification title (default: Reminder)"
    )
    remind_p.add_argument(
        "--urgency",
        choices=["low", "normal", "critical"],
        default="normal",
        help="Notification urgency: low, normal, critical (default: normal)",
    )
    remind_p.add_argument(
        "--tz",
        dest="timezone",
        metavar="TZ",
        help="Timezone for 'at' datetime (default: local system timezone)",
    )

    fire_p = sub.add_parser("_remind-fire", help=argparse.SUPPRESS)
    fire_p.add_argument("--message", required=True)
    fire_p.add_argument("--title", default="Reminder")
    fire_p.add_argument("--urgency", default="normal")
    fire_p.add_argument("--seconds", type=float, required=True)

    sub.add_parser("interactive", help="Enter interactive mode").add_argument(
        "-i", action="store_true", dest="interactive_alias"
    )

    selfupdate_p = sub.add_parser("self-update", help="Check for and install updates")
    selfupdate_p.add_argument(
        "-f", "--force", action="store_true", help="Skip confirmation prompt"
    )

    sub.add_parser("uninstall", help="Uninstall kim completely")

    export_p = sub.add_parser("export", help="Export reminders to a file")
    export_p.add_argument(
        "-f",
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Export format (default: json)",
    )
    export_p.add_argument(
        "-o", "--output", help="Output file (prints to stdout if not specified)"
    )
    export_p.add_argument(
        "--oneshots",
        action="store_true",
        help="Also include pending one-shot reminders in the export",
    )

    import_p = sub.add_parser("import", help="Import reminders from a file")
    import_p.add_argument("file", help="File to import from")
    import_p.add_argument(
        "-f",
        "--format",
        choices=["json", "csv", "auto"],
        default="auto",
        help="Input format (default: auto-detect)",
    )
    import_p.add_argument(
        "--merge",
        action="store_true",
        help="Merge with existing reminders instead of replacing",
    )
    import_p.add_argument(
        "--oneshots",
        action="store_true",
        help="Also import one-shot reminders from the file (future fire times only)",
    )

    sub.add_parser("validate", help="Validate config file")

    slack_p = sub.add_parser("slack", help="Slack notification settings")
    slack_p.add_argument("--test", action="store_true", help="Send test notification")
    slack_p.add_argument("-t", "--title", help="Test notification title")
    slack_p.add_argument("-m", "--message", help="Test notification message")

    sound_p = sub.add_parser("sound", help="Manage the notification sound file")
    sound_p.add_argument(
        "--set",
        metavar="FILE",
        help="Set a custom sound file (wav/mp3/ogg/flac/aiff/m4a)",
    )
    sound_p.add_argument(
        "--clear",
        action="store_true",
        help="Remove custom sound and revert to system default",
    )
    sound_p.add_argument(
        "--test", action="store_true", help="Play the current sound immediately"
    )
    sound_p.add_argument(
        "--enable", action="store_true", help="Enable sound notifications"
    )
    sound_p.add_argument(
        "--disable", action="store_true", help="Disable sound notifications"
    )

    comp_p = sub.add_parser("completion", help="Generate shell completions")
    comp_p.add_argument("shell", choices=["bash", "zsh", "fish"], help="Shell type")

    sub.add_parser("ui", help="Open graphical manager (requires PySide6)")

    # Case-insensitive command handling
    known_commands = {
        "start",
        "stop",
        "status",
        "list",
        "logs",
        "edit",
        "add",
        "remove",
        "enable",
        "disable",
        "update",
        "remind",
        "interactive",
        "self-update",
        "uninstall",
        "export",
        "import",
        "validate",
        "slack",
        "sound",
        "completion",
        "ui",
        "_remind-fire",
    }
    new_argv = []
    for arg in sys.argv[1:]:  # skip program name
        lower = arg.lower()
        if lower in known_commands:
            new_argv.append(lower)
        else:
            new_argv.append(arg)
    sys.argv = [sys.argv[0]] + new_argv

    # Convert -i flag to interactive command — only at argv[1] (subcommand slot)
    if len(sys.argv) > 1 and sys.argv[1].lower() == "-i":
        sys.argv[1] = "interactive"

    args = parser.parse_args()

    cmds = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "list": cmd_list,
        "logs": cmd_logs,
        "edit": cmd_edit,
        "add": cmd_add,
        "remove": cmd_remove,
        "enable": cmd_enable,
        "disable": cmd_disable,
        "update": cmd_update,
        "remind": cmd_remind,
        "_remind-fire": cmd_remind_fire,
        "interactive": cmd_interactive,
        "self-update": cmd_selfupdate,
        "uninstall": cmd_uninstall,
        "export": cmd_export,
        "import": cmd_import,
        "validate": cmd_validate,
        "slack": cmd_slack,
        "sound": cmd_sound,
        "completion": cmd_completion,
        "ui": cmd_ui,
    }

    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()
        # No subcommand given — exit cleanly (not an error)
