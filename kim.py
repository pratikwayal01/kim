#!/usr/bin/env python3
"""
kim — keep in mind
Lightweight cross-platform reminder daemon for developers.

Usage:
  kim start        Start the daemon
  kim stop         Stop the daemon
  kim status       Show running reminders
  kim list         List all reminders from config
  kim logs         Tail the log file
"""

import json
import os
import sys
import time
import signal
import threading
import platform
import subprocess
import logging
import argparse
from pathlib import Path
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
KIM_DIR    = Path.home() / ".kim"
CONFIG     = KIM_DIR / "config.json"
LOG_FILE   = KIM_DIR / "kim.log"
PID_FILE   = KIM_DIR / "kim.pid"
KIM_DIR.mkdir(exist_ok=True)

VERSION = "0.1.0"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("kim")


# ── Default config (written on first run) ────────────────────────────────────
DEFAULT_CONFIG = {
    "reminders": [
        {
            "name": "eye-break",
            "interval_minutes": 30,
            "title": "👁️ Eye Break",
            "message": "Look 20 feet away for 20 seconds. Blink slowly.",
            "urgency": "critical",
            "enabled": True
        },
        {
            "name": "water",
            "interval_minutes": 60,
            "title": "💧 Drink Water",
            "message": "Stay hydrated — drink a glass of water.",
            "urgency": "normal",
            "enabled": False
        }
    ],
    "sound": True
}


# ── Notification backends ─────────────────────────────────────────────────────

def _linux_env():
    uid = os.getuid()
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return env


def _notify_linux(title, message, urgency, sound):
    env = _linux_env()
    u = urgency if urgency in ("low", "normal", "critical") else "normal"
    try:
        subprocess.run(["notify-send", "--urgency", u, title, message],
                       env=env, check=True)
    except FileNotFoundError:
        log.error("notify-send not found. Install libnotify.")
    except Exception as e:
        log.error(f"notify-send: {e}")

    if sound:
        for cmd in (
            ["canberra-gtk-play", "--id=bell"],
            ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
        ):
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                subprocess.Popen(cmd, env=env, stderr=subprocess.DEVNULL)
                break


def _notify_mac(title, message, urgency, sound):
    t = title.replace('"', '\\"')
    m = message.replace('"', '\\"').replace("\n", " ")
    snd = 'sound name "Glass"' if sound else ""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{m}" with title "{t}" {snd}'],
            check=True,
        )
    except Exception as e:
        log.error(f"osascript: {e}")


def _notify_windows(title, message, urgency, sound):
    t = title.replace("'", "\\'")
    m = message.replace("\n", " ").replace("'", "\\'")
    ps = f"""
[Windows.UI.Notifications.ToastNotificationManager,
 Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
$tpl = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($tpl)
$xml.GetElementsByTagName('text')[0].AppendChild($xml.CreateTextNode('{t}')) | Out-Null
$xml.GetElementsByTagName('text')[1].AppendChild($xml.CreateTextNode('{m}')) | Out-Null
$n = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('kim').Show($n)
"""
    try:
        subprocess.run(["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                       capture_output=True)
    except Exception as e:
        log.error(f"powershell toast: {e}")


def notify(title: str, message: str, urgency: str = "normal", sound: bool = True):
    system = platform.system()
    log.info(f"notify [{urgency}] → {title}")
    if system == "Linux":
        _notify_linux(title, message, urgency, sound)
    elif system == "Darwin":
        _notify_mac(title, message, urgency, sound)
    elif system == "Windows":
        _notify_windows(title, message, urgency, sound)
    else:
        log.warning(f"Unsupported platform: {system}")


# ── Reminder thread ───────────────────────────────────────────────────────────

def run_reminder(r: dict, sound: bool, stop_event: threading.Event):
    name     = r.get("name", "unnamed")
    interval = r["interval_minutes"] * 60
    title    = r.get("title", "Reminder")
    message  = r.get("message", "Hey!")
    urgency  = r.get("urgency", "normal")

    log.info(f"[{name}] started — every {r['interval_minutes']} min")

    while not stop_event.wait(interval):
        notify(title, message, urgency, sound)
        log.info(f"[{name}] fired")


# ── Daemon ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        print(f"Created default config: {CONFIG}")
    with open(CONFIG) as f:
        return json.load(f)


def cmd_start(args):
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        print(f"kim is already running (PID {pid}). Use 'kim stop' first.")
        sys.exit(1)

    config  = load_config()
    sound   = config.get("sound", True)
    active  = [r for r in config.get("reminders", []) if r.get("enabled", True)]

    if not active:
        print("No enabled reminders in config. Edit ~/.kim/config.json")
        sys.exit(0)

    # Write PID
    PID_FILE.write_text(str(os.getpid()))

    print(f"kim v{VERSION} — {len(active)} reminder(s) active")
    for r in active:
        print(f"  • {r['name']:<20} every {r['interval_minutes']} min")
    print(f"Log: {LOG_FILE}")

    log.info(f"kim v{VERSION} started — PID {os.getpid()}")

    stop_event = threading.Event()

    def shutdown(sig, frame):
        log.info("Shutting down...")
        stop_event.set()
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    notify("✅ kim started",
           f"{len(active)} reminder(s): " + ", ".join(r["name"] for r in active),
           urgency="low", sound=False)

    threads = []
    for r in active:
        t = threading.Thread(
            target=run_reminder,
            args=(r, sound, stop_event),
            name=r["name"],
            daemon=True,
        )
        t.start()
        threads.append(t)

    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


def cmd_stop(args):
    if not PID_FILE.exists():
        print("kim is not running.")
        sys.exit(0)
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        print(f"kim stopped (PID {pid}).")
        log.info(f"Stopped by user (PID {pid})")
    except ProcessLookupError:
        print("Process not found — cleaning up stale PID file.")
        PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        print(f"Permission denied to kill PID {pid}.")


def cmd_status(args):
    config = load_config()
    active = [r for r in config.get("reminders", []) if r.get("enabled", True)]
    paused = [r for r in config.get("reminders", []) if not r.get("enabled", True)]

    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        print(f"● kim running   PID {pid}")
    else:
        print("○ kim stopped")

    print(f"\n  Config : {CONFIG}")
    print(f"  Log    : {LOG_FILE}\n")

    if active:
        print("  Active reminders:")
        for r in active:
            print(f"    ✓ {r['name']:<20} every {r['interval_minutes']} min  [{r.get('urgency','normal')}]")
    if paused:
        print("  Disabled reminders:")
        for r in paused:
            print(f"    - {r['name']}")


def cmd_list(args):
    config = load_config()
    reminders = config.get("reminders", [])
    print(f"{'NAME':<20} {'INTERVAL':>10}   {'URGENCY':<10} {'ENABLED'}")
    print("─" * 55)
    for r in reminders:
        enabled = "✓" if r.get("enabled", True) else "·"
        print(f"{r['name']:<20} {str(r['interval_minutes']) + ' min':>10}   {r.get('urgency','normal'):<10} {enabled}")


def cmd_logs(args):
    n = args.lines
    if not LOG_FILE.exists():
        print("No log file yet.")
        return
    lines = LOG_FILE.read_text().splitlines()
    for line in lines[-n:]:
        print(line)


def cmd_edit(args):
    editor = os.environ.get("EDITOR", "nano")
    load_config()  # ensure config exists
    os.execvp(editor, [editor, str(CONFIG)])


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="kim",
        description="keep in mind — lightweight reminder daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  start     Start the daemon
  stop      Stop the daemon
  status    Show status and active reminders
  list      List all reminders from config
  logs      Show recent log entries
  edit      Open config in $EDITOR

config: ~/.kim/config.json
logs:   ~/.kim/kim.log
        """
    )
    parser.add_argument("--version", action="version", version=f"kim {VERSION}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start",  help="Start the daemon")
    sub.add_parser("stop",   help="Stop the daemon")
    sub.add_parser("status", help="Show status and active reminders")
    sub.add_parser("list",   help="List all reminders from config")
    sub.add_parser("edit",   help="Open config in $EDITOR")

    logs_p = sub.add_parser("logs", help="Show recent log entries")
    logs_p.add_argument("-n", "--lines", type=int, default=30,
                        help="Number of lines to show (default: 30)")

    args = parser.parse_args()

    cmds = {
        "start":  cmd_start,
        "stop":   cmd_stop,
        "status": cmd_status,
        "list":   cmd_list,
        "logs":   cmd_logs,
        "edit":   cmd_edit,
    }

    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
