"""
CLI argument parsing and command dispatch for kim.
"""

import argparse
import platform
import sys

from .core import VERSION
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


def main():
    _enable_windows_ansi()  # enable ANSI colour codes on Windows for all commands
    parser = argparse.ArgumentParser(
        prog="kim",
        description="keep in mind — lightweight reminder daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  start       Start the daemon
  stop        Stop the daemon
  status      Show status and active reminders
  list        List all reminders from config
  logs        Show recent log entries
  edit        Open config in $EDITOR
  add         Add a new reminder
  remove      Remove a reminder
  enable      Enable a reminder
  disable     Disable a reminder
  update      Update a reminder
  remind      Fire a one-shot reminder after a delay
  interactive Enter interactive mode (alias: -i)
  self-update Check for and install updates
  uninstall   Uninstall kim completely
  export      Export reminders to file
  import      Import reminders from file
  validate    Validate config file
  sound       Manage the notification sound file
  completion  Generate shell completions

Short flags:
  -i          Enter interactive mode

config: ~/.kim/config.json
logs:   ~/.kim/kim.log
        """,
    )
    parser.add_argument("-v", "--version", action="version", version=f"kim {VERSION}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Start the daemon")
    sub.add_parser("stop", help="Stop the daemon")
    sub.add_parser("status", help="Show status and active reminders")
    sub.add_parser("list", help="List all reminders from config")
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
    add_p.add_argument(
        "-I",
        "--interval",
        type=str,
        required=True,
        help="Interval (e.g., 30m, 1h, 1d, or just number for minutes)",
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
    add_p.add_argument("--sound-file", help="Per-reminder sound file path")
    add_p.add_argument("--slack-channel", help="Per-reminder Slack channel")
    add_p.add_argument("--slack-webhook", help="Per-reminder Slack webhook URL")

    remove_p = sub.add_parser("remove", help="Remove a reminder")
    remove_p.add_argument("name", help="Reminder name")

    enable_p = sub.add_parser("enable", help="Enable a reminder")
    enable_p.add_argument("name", help="Reminder name")

    disable_p = sub.add_parser("disable", help="Disable a reminder")
    disable_p.add_argument("name", help="Reminder name")

    update_p = sub.add_parser("update", help="Update a reminder")
    update_p.add_argument("name", help="Reminder name")
    update_p.add_argument(
        "-I", "--interval", type=str, help="New interval (e.g., 30m, 1h, 1d)"
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

    remind_p = sub.add_parser("remind", help="Fire a one-shot reminder after a delay")
    remind_p.add_argument("message", help="Reminder message")
    remind_p.add_argument(
        "time", nargs="+", help="When to fire, e.g: 'in 10m', '1h', '2h 30m', '90s'"
    )
    remind_p.add_argument(
        "-t", "--title", help="Notification title (default: \u23f0 Reminder)"
    )

    fire_p = sub.add_parser("_remind-fire")
    fire_p.add_argument("--message", required=True)
    fire_p.add_argument("--title", default="\u23f0 Reminder")
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
    }

    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)
