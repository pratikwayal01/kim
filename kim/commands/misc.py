"""
Miscellaneous commands: remind, slack, sound, completion.
"""

import json
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

from ..core import (
    CONFIG,
    KIM_DIR,
    LOG_FILE,
    ONESHOT_FILE,
    VERSION,
    load_config,
    log,
    parse_datetime,
)
from ..notifications import notify
from ..sound import SOUND_FORMAT_NOTES, play_sound_file, validate_sound_file
from ..utils import CHECK, CROSS, EM_DASH, ALARM, PLAY, BELL


def _save_config(config: dict) -> None:
    """Atomically write config; raises SystemExit(1) on failure."""
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


def cmd_remind(args):
    tz_name = getattr(args, "timezone", None)
    try:
        fire_time = parse_datetime(args.time, tz_name=tz_name)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    sleep_seconds = fire_time - time.time()

    if sleep_seconds > 365 * 24 * 3600:
        print("Duration too large (max 365 days).")
        sys.exit(1)

    message = args.message
    title = args.title or (
        "Reminder" if platform.system() == "Windows" else f"{ALARM} Reminder"
    )

    # Human-readable display
    remaining = int(sleep_seconds)
    parts = []
    for unit, label in [(3600, "h"), (60, "m"), (1, "s")]:
        if remaining >= unit:
            parts.append(f"{remaining // unit}{label}")
            remaining %= unit
    display = " ".join(parts) if parts else "now"

    # For absolute "at" times, also show the wall-clock time
    raw_joined = " ".join(args.time).strip().lower()
    if raw_joined.startswith("at"):
        import datetime as _dt

        fire_dt = _dt.datetime.fromtimestamp(fire_time).strftime("%Y-%m-%d %H:%M")
        print(f"{title} set: '{message}' at {fire_dt} (in {display})")
    else:
        print(f"{title} set: '{message}' in {display}")
    log.info("One-shot reminder set: '%s' in %s", message, display)

    # Save one-shot reminder for persistence across reboots
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
        _tmp = ONESHOT_FILE.with_suffix(".tmp")
        _tmp.write_text(json.dumps(oneshots, indent=2), encoding="utf-8")
        if platform.system() != "Windows":
            try:
                os.chmod(_tmp, 0o600)
            except OSError:
                pass
        _tmp.replace(ONESHOT_FILE)
        log.debug("Saved one-shot reminder to %s", ONESHOT_FILE)
    except OSError as e:
        log.warning("Could not save one-shot reminder: %s", e)

    if platform.system() == "Windows":
        # Spawn via "cmd /c kim ..." so we go through the installed kim.bat.
        # This avoids all Windows Store Python stub issues — cmd.exe resolves
        # the .bat on PATH and invokes it with a proper console context.
        # Pass args as a list so subprocess handles quoting; don't build a
        # shell string to avoid double-quoting issues with argparse.
        cmd = [
            "cmd",
            "/c",
            "kim",
            "_remind-fire",
            "--message",
            message,
            "--title",
            title,
            "--seconds",
            str(sleep_seconds),
        ]
        # Redirect stderr to kim.log so failures are diagnosable.
        try:
            log_fd = open(LOG_FILE, "a", encoding="utf-8")
        except OSError:
            log_fd = subprocess.DEVNULL
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=log_fd,
                stdin=subprocess.DEVNULL,
                # CREATE_NO_WINDOW — cmd.exe window stays hidden
                creationflags=0x08000000,
            )
        except FileNotFoundError:
            log.error("cmd.exe not found — cannot spawn background process")
            print("Error: could not spawn background process.")
            sys.exit(1)
        finally:
            if log_fd is not subprocess.DEVNULL:
                log_fd.close()
        return

    pid = os.fork()
    if pid > 0:
        return

    # Detach from parent session and reset signal handlers
    try:
        os.setsid()
    except OSError:
        pass
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    try:
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
        log.info("One-shot reminder fired: %s", message)
    except Exception:
        log.exception("One-shot reminder child process failed")
    finally:
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
    log.info("One-shot reminder fired: '%s'", args.message)

    # Clean up the entry from oneshots.json so it doesn't re-fire on next
    # daemon start.  We match by fire_at (current time + seconds that elapsed).
    fire_at = time.time()  # approximate — within a few ms of the actual time
    if ONESHOT_FILE.exists():
        try:
            oneshots = json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
            # Remove entries whose fire_at is in the past (already fired)
            now = fire_at
            remaining = [o for o in oneshots if o.get("fire_at", 0) > now]
            _tmp = ONESHOT_FILE.with_suffix(".tmp")
            _tmp.write_text(json.dumps(remaining, indent=2), encoding="utf-8")
            _tmp.replace(ONESHOT_FILE)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not clean up oneshots.json after fire: %s", e)


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
            # Clean up expired oneshots atomically
            try:
                _tmp = ONESHOT_FILE.with_suffix(".tmp")
                _tmp.write_text(json.dumps(valid, indent=2), encoding="utf-8")
                _tmp.replace(ONESHOT_FILE)
            except OSError as e:
                log.warning("Could not clean up expired one-shots: %s", e)
            log.info(
                "Cleaned up %d expired one-shot reminders", len(oneshots) - len(valid)
            )
        return valid
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not load one-shot reminders: %s", e)
        return []


def remove_oneshot(fire_at):
    """Remove a one-shot reminder from the persisted file by fire_at timestamp."""
    if not ONESHOT_FILE.exists():
        return
    try:
        oneshots = json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
        remaining = [o for o in oneshots if o.get("fire_at") != fire_at]
        _tmp = ONESHOT_FILE.with_suffix(".tmp")
        _tmp.write_text(json.dumps(remaining, indent=2), encoding="utf-8")
        _tmp.replace(ONESHOT_FILE)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not update oneshots.json: %s", e)


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
        _save_config(config)
        print(f"{CHECK} Custom sound set: {path}")
        print("  Restart kim ('kim stop && kim start') to apply.")
        log.info("sound_file set to: %s", path)
        return

    if args.clear:
        config["sound_file"] = None
        _save_config(config)
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
        _save_config(config)
        print(f"{CHECK} Sound enabled.")
        return

    if args.disable:
        config["sound"] = False
        _save_config(config)
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
BASH_COMPLETION = r"""_kim_completions() {
    local cur prev cword
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cword=$COMP_CWORD
    COMPREPLY=()

    local cmds="start stop status list logs edit add remove enable disable update interactive self-update uninstall export import validate slack sound completion remind"

    # Word 1: complete subcommands
    if [[ $cword -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "$cmds" -- "$cur") )
        return 0
    fi

    local cmd="${COMP_WORDS[1]}"

    # Helper: load reminder names from config; handles spaces via mapfile
    _kim_names() {
        local config="$HOME/.kim/config.json"
        local py
        py=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
        if [[ -n "$py" && -f "$config" ]]; then
            "$py" -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    for r in data.get('reminders', []):
        print(r['name'])
except Exception:
    pass
" "$config" 2>/dev/null
        fi
    }

    case "$cmd" in
        start|stop|status|list|validate|interactive|uninstall|completion|edit)
            # These commands take no arguments — suppress filename fallback
            compopt -o nosort 2>/dev/null
            return 0
            ;;
        remove|enable|disable)
            mapfile -t COMPREPLY < <(compgen -W "$(_kim_names)" -- "$cur")
            ;;
        update)
            if [[ $cword -eq 2 ]]; then
                mapfile -t COMPREPLY < <(compgen -W "$(_kim_names)" -- "$cur")
            else
                COMPREPLY=( $(compgen -W "--interval --title --message --urgency --enable --disable --sound-file --slack-channel --slack-webhook -I -t -m -u" -- "$cur") )
            fi
            ;;
        add)
            COMPREPLY=( $(compgen -W "--interval --title --message --urgency --sound-file --slack-channel --slack-webhook -I -t -m -u" -- "$cur") )
            compopt -o nospace 2>/dev/null
            ;;
        remind)
            COMPREPLY=( $(compgen -W "--title -t" -- "$cur") )
            ;;
        sound)
            COMPREPLY=( $(compgen -W "--set --clear --test --enable --disable" -- "$cur") )
            ;;
        slack)
            COMPREPLY=( $(compgen -W "--test --title --message -t -m" -- "$cur") )
            ;;
        export)
            COMPREPLY=( $(compgen -W "--format --output -f -o" -- "$cur") )
            ;;
        import)
            if [[ $cword -eq 2 ]]; then
                # positional: file argument
                COMPREPLY=( $(compgen -f -- "$cur") )
            else
                COMPREPLY=( $(compgen -W "--format --merge -f" -- "$cur") )
            fi
            ;;
        logs)
            COMPREPLY=( $(compgen -W "--lines -n" -- "$cur") )
            ;;
        self-update)
            COMPREPLY=( $(compgen -W "--force -f" -- "$cur") )
            ;;
    esac
    return 0
}
complete -F _kim_completions kim
"""

ZSH_COMPLETION = r"""#compdef kim

_kim_reminder_names() {
    local config="$HOME/.kim/config.json"
    local py
    py=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
    if [[ -n "$py" && -f "$config" ]]; then
        local -a names
        names=( ${(f)"$("$py" -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    for r in data.get('reminders', []):
        print(r['name'])
except Exception:
    pass
" "$config" 2>/dev/null)"} )
        compadd -a names
    fi
}

_kim() {
    local -a commands
    commands=(
        "start:Start the daemon"
        "stop:Stop the daemon"
        "status:Show status and active reminders"
        "list:List all reminders from config"
        "logs:Show recent log entries"
        "edit:Open config in \$EDITOR"
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
        "remind:Fire a one-shot reminder"
    )

    _arguments -C \
        "(-v --version)"{-v,--version}"[Show version]" \
        "1: :->cmds" \
        "*::arg:->args"

    case $state in
        cmds)
            _describe "command" commands
            ;;
        args)
            case $line[1] in
                start|stop|status|list|validate|interactive|uninstall|completion|edit)
                    # No arguments
                    ;;
                add)
                    _arguments \
                        "(-I --interval)"{-I,--interval}"[Interval (e.g., 30m, 1h, 1d)]:interval:" \
                        "(-t --title)"{-t,--title}"[Notification title]:title:" \
                        "(-m --message)"{-m,--message}"[Notification message]:message:" \
                        "(-u --urgency)"{-u,--urgency}"[Urgency level]:urgency:(low normal critical)" \
                        "--sound-file[Per-reminder sound file]:file:_files" \
                        "--slack-channel[Per-reminder Slack channel]:channel:" \
                        "--slack-webhook[Per-reminder Slack webhook URL]:url:"
                    ;;
                update)
                    _arguments \
                        "1:reminder name:_kim_reminder_names" \
                        "(-I --interval)"{-I,--interval}"[New interval]:interval:" \
                        "(-t --title)"{-t,--title}"[New title]:title:" \
                        "(-m --message)"{-m,--message}"[New message]:message:" \
                        "(-u --urgency)"{-u,--urgency}"[New urgency]:urgency:(low normal critical)" \
                        "--enable[Enable reminder]" \
                        "--disable[Disable reminder]" \
                        "--sound-file[Per-reminder sound file]:file:_files" \
                        "--slack-channel[Per-reminder Slack channel]:channel:" \
                        "--slack-webhook[Per-reminder Slack webhook URL]:url:"
                    ;;
                remove|enable|disable)
                    _arguments "1:reminder name:_kim_reminder_names"
                    ;;
                remind)
                    _arguments \
                        "1:message:" \
                        "(-t --title)"{-t,--title}"[Notification title]:title:" \
                        "*:time expression:"
                    ;;
                sound)
                    _arguments \
                        "--set[Set custom sound file]:file:_files" \
                        "--clear[Revert to system default]" \
                        "--test[Play current sound]" \
                        "--enable[Enable sound]" \
                        "--disable[Disable sound]"
                    ;;
                slack)
                    _arguments \
                        "--test[Send test notification]" \
                        "(-t --title)"{-t,--title}"[Test title]:title:" \
                        "(-m --message)"{-m,--message}"[Test message]:message:"
                    ;;
                export)
                    _arguments \
                        "(-f --format)"{-f,--format}"[Format]:format:(json csv)" \
                        "(-o --output)"{-o,--output}"[Output file]:file:_files"
                    ;;
                import)
                    _arguments \
                        "1:file:_files" \
                        "(-f --format)"{-f,--format}"[Format]:format:(json csv auto)" \
                        "--merge[Merge with existing]"
                    ;;
                logs)
                    _arguments "(-n --lines)"{-n,--lines}"[Number of lines]:n:"
                    ;;
                self-update)
                    _arguments "(-f --force)"{-f,--force}"[Skip confirmation]"
                    ;;
                completion)
                    _arguments "1:shell:(bash zsh fish)"
                    ;;
            esac
            ;;
    esac
}
_kim "$@"
"""

FISH_COMPLETION = r"""# kim shell completion for fish
# Install: kim completion fish > ~/.config/fish/completions/kim.fish

set -l __kim_subcommands start stop status list logs edit add remove enable disable update interactive self-update uninstall export import validate slack sound completion remind

# Helper function: read reminder names from config
function __kim_reminder_names
    set -l config "$HOME/.kim/config.json"
    if test -f $config
        set -l py (command -v python3 2>/dev/null; or command -v python 2>/dev/null)
        if test -n "$py"
            $py -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    for r in data.get('reminders', []):
        print(r['name'])
except Exception:
    pass
" $config 2>/dev/null
        end
    end
end

# Subcommands at position 1 (no subcommand seen yet)
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a start          -d "Start the daemon"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a stop           -d "Stop the daemon"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a status         -d "Show status and active reminders"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a list           -d "List all reminders from config"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a logs           -d "Show recent log entries"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a edit           -d "Open config in \$EDITOR"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a add            -d "Add a new reminder"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a remove         -d "Remove a reminder"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a enable         -d "Enable a reminder"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a disable        -d "Disable a reminder"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a update         -d "Update a reminder"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a interactive    -d "Enter interactive mode"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a self-update    -d "Check for and install updates"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a uninstall      -d "Uninstall kim completely"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a export         -d "Export reminders to file"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a import         -d "Import reminders from file"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a validate       -d "Validate config file"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a slack          -d "Slack notification settings"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a sound          -d "Manage the notification sound file"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a completion     -d "Generate shell completions"
complete -c kim -f -n "not __fish_seen_subcommand_from $__kim_subcommands" -a remind         -d "Fire a one-shot reminder after a delay"

# Commands with no further arguments — suppress filename fallback
complete -c kim -f -n "__fish_seen_subcommand_from start stop status list validate interactive uninstall"

# Reminder-name completions (remove/enable/disable: any position; update: only before flags)
complete -c kim -f -n "__fish_seen_subcommand_from remove enable disable" \
    -a "(__kim_reminder_names)"
complete -c kim -f -n "__fish_seen_subcommand_from update; and test (count (commandline -opc)) -eq 2" \
    -a "(__kim_reminder_names)"

# completion subcommand
complete -c kim -f -n "__fish_seen_subcommand_from completion" -a "bash zsh fish"

# add flags
complete -c kim -f -n "__fish_seen_subcommand_from add" -l interval   -s I -d "Interval (e.g., 30m, 1h, 1d)" -r
complete -c kim -f -n "__fish_seen_subcommand_from add" -l title      -s t -d "Notification title"           -r
complete -c kim -f -n "__fish_seen_subcommand_from add" -l message    -s m -d "Notification message"         -r
complete -c kim -f -n "__fish_seen_subcommand_from add" -l urgency    -s u -d "Urgency level"                -r -a "low normal critical"
complete -c kim -f -n "__fish_seen_subcommand_from add" -l sound-file      -d "Per-reminder sound file"      -r -F
complete -c kim -f -n "__fish_seen_subcommand_from add" -l slack-channel   -d "Per-reminder Slack channel"   -r
complete -c kim -f -n "__fish_seen_subcommand_from add" -l slack-webhook   -d "Per-reminder Slack webhook"   -r

# update flags
complete -c kim -f -n "__fish_seen_subcommand_from update" -l interval   -s I -d "New interval"              -r
complete -c kim -f -n "__fish_seen_subcommand_from update" -l title      -s t -d "New title"                 -r
complete -c kim -f -n "__fish_seen_subcommand_from update" -l message    -s m -d "New message"               -r
complete -c kim -f -n "__fish_seen_subcommand_from update" -l urgency    -s u -d "New urgency"               -r -a "low normal critical"
complete -c kim -f -n "__fish_seen_subcommand_from update" -l enable          -d "Enable reminder"
complete -c kim -f -n "__fish_seen_subcommand_from update" -l disable         -d "Disable reminder"
complete -c kim -f -n "__fish_seen_subcommand_from update" -l sound-file      -d "Per-reminder sound file"   -r -F
complete -c kim -f -n "__fish_seen_subcommand_from update" -l slack-channel   -d "Per-reminder Slack channel" -r
complete -c kim -f -n "__fish_seen_subcommand_from update" -l slack-webhook   -d "Per-reminder Slack webhook"  -r

# remind flags
complete -c kim -f -n "__fish_seen_subcommand_from remind" -l title -s t -d "Notification title" -r

# sound flags
complete -c kim -f -n "__fish_seen_subcommand_from sound" -l set     -d "Set custom sound file"   -r -F
complete -c kim -f -n "__fish_seen_subcommand_from sound" -l clear   -d "Revert to system default"
complete -c kim -f -n "__fish_seen_subcommand_from sound" -l test    -d "Play current sound"
complete -c kim -f -n "__fish_seen_subcommand_from sound" -l enable  -d "Enable sound"
complete -c kim -f -n "__fish_seen_subcommand_from sound" -l disable -d "Disable sound"

# slack flags
complete -c kim -f -n "__fish_seen_subcommand_from slack" -l test    -d "Send test notification"
complete -c kim -f -n "__fish_seen_subcommand_from slack" -l title   -s t -d "Test title"   -r
complete -c kim -f -n "__fish_seen_subcommand_from slack" -l message -s m -d "Test message" -r

# export flags
complete -c kim -f -n "__fish_seen_subcommand_from export" -l format -s f -d "Export format"  -r -a "json csv"
complete -c kim -f -n "__fish_seen_subcommand_from export" -l output -s o -d "Output file"    -r -F

# import flags — file argument uses filesystem completion
complete -c kim -n "__fish_seen_subcommand_from import" -l format -s f -d "Input format"  -r -a "json csv auto"
complete -c kim -n "__fish_seen_subcommand_from import" -l merge       -d "Merge with existing"

# logs flags
complete -c kim -f -n "__fish_seen_subcommand_from logs" -l lines -s n -d "Number of lines" -r

# self-update flags
complete -c kim -f -n "__fish_seen_subcommand_from self-update" -l force -s f -d "Skip confirmation"
"""


def cmd_completion(args):
    if args.shell == "bash":
        print(BASH_COMPLETION)
        print()
        print('# Install: eval "$(kim completion bash)"  or add to ~/.bashrc')
    elif args.shell == "zsh":
        print(ZSH_COMPLETION)
        print()
        print("# Install: save to a file in $fpath, e.g. ~/.zsh/completion/_kim")
    elif args.shell == "fish":
        print(FISH_COMPLETION)
        print()
        print("# Install: kim completion fish > ~/.config/fish/completions/kim.fish")
        print("# Or run:  eval (kim completion fish | psub)")
