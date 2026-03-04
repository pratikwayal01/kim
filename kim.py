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
import shutil
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

try:
    import tty
    import termios
except ImportError:
    tty = None
    termios = None

# ── Paths ─────────────────────────────────────────────────────────────────────
KIM_DIR = Path.home() / ".kim"
CONFIG = KIM_DIR / "config.json"
LOG_FILE = KIM_DIR / "kim.log"
PID_FILE = KIM_DIR / "kim.pid"
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
            "enabled": True,
        },
        {
            "name": "water",
            "interval_minutes": 60,
            "title": "💧 Drink Water",
            "message": "Stay hydrated — drink a glass of water.",
            "urgency": "normal",
            "enabled": False,
        },
    ],
    "sound": True,
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
        subprocess.run(
            ["notify-send", "--urgency", u, title, message], env=env, check=True
        )
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
            ["osascript", "-e", f'display notification "{m}" with title "{t}" {snd}'],
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
        subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True,
        )
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
    name = r.get("name", "unnamed")
    interval = r["interval_minutes"] * 60
    title = r.get("title", "Reminder")
    message = r.get("message", "Hey!")
    urgency = r.get("urgency", "normal")

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

    config = load_config()
    sound = config.get("sound", True)
    active = [r for r in config.get("reminders", []) if r.get("enabled", True)]

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

    notify(
        "✅ kim started",
        f"{len(active)} reminder(s): " + ", ".join(r["name"] for r in active),
        urgency="low",
        sound=False,
    )

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
            print(
                f"    ✓ {r['name']:<20} every {r['interval_minutes']} min  [{r.get('urgency', 'normal')}]"
            )
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
        print(
            f"{r['name']:<20} {str(r['interval_minutes']) + ' min':>10}   {r.get('urgency', 'normal'):<10} {enabled}"
        )


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


def cmd_add(args):
    config = load_config()
    name = args.name

    for r in config.get("reminders", []):
        if r.get("name") == name:
            print(f"Reminder '{name}' already exists. Use 'kim update' to modify it.")
            sys.exit(1)

    new_reminder = {
        "name": name,
        "interval_minutes": args.interval,
        "title": args.title or f"Reminder: {name}",
        "message": args.message or "Time for a reminder!",
        "urgency": args.urgency,
        "enabled": True,
    }

    config.setdefault("reminders", []).append(new_reminder)

    with open(CONFIG, "w") as f:
        json.dump(config, f, indent=2)

    print(f"✓ Added reminder '{name}' (every {args.interval} min)")
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

    with open(CONFIG, "w") as f:
        json.dump(config, f, indent=2)

    print(f"✓ Removed reminder '{name}'")
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

    with open(CONFIG, "w") as f:
        json.dump(config, f, indent=2)

    print(f"✓ Enabled reminder '{name}'")
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

    with open(CONFIG, "w") as f:
        json.dump(config, f, indent=2)

    print(f"✓ Disabled reminder '{name}'")
    log.info(f"Disabled reminder: {name}")


def cmd_update(args):
    config = load_config()
    name = args.name

    found = False
    for r in config.get("reminders", []):
        if r.get("name") == name:
            found = True
            if args.interval is not None:
                r["interval_minutes"] = args.interval
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

    with open(CONFIG, "w") as f:
        json.dump(config, f, indent=2)

    print(f"✓ Updated reminder '{name}'")
    log.info(f"Updated reminder: {name}")


def get_key():
    if tty is None or termios is None:
        return input("Enter choice: ")

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


def get_screen_size():
    size = shutil.get_terminal_size(fallback=(80, 24))
    return size.columns, size.lines


def cmd_interactive(args):
    config = load_config()

    def clear_screen():
        print("\033[2J\033[H", end="")

    def print_header():
        cols, _ = get_screen_size()
        print("\033[2J\033[H", end="")
        print(
            "\033[1;36m" + " kim — Interactive Mode ".center(cols - 1, "━") + "\033[0m"
        )
        print()

    def print_menu(selected):
        reminders = config.get("reminders", [])
        options = [
            "List Reminders",
            "Add Reminder",
            "Edit Reminder",
            "Toggle Reminder",
            "Remove Reminder",
            "Start kim",
            "Stop kim",
            "Exit",
        ]

        print("\r\033[K", end="")
        for i, opt in enumerate(options):
            prefix = "► " if i == selected else "  "
            color = "\033[1;32m" if i == selected else "\033[0m"
            print(f"{color}{prefix}{opt}\033[0m")
        print()

    def list_reminders():
        clear_screen()
        reminders = config.get("reminders", [])
        if not reminders:
            print("No reminders found.")
        else:
            print(f"{'NAME':<20} {'INTERVAL':>10}   {'URGENCY':<10} {'ENABLED'}")
            print("─" * 55)
            for r in reminders:
                enabled = "✓" if r.get("enabled", True) else "·"
                print(
                    f"{r['name']:<20} {str(r['interval_minutes']) + ' min':>10}   {r.get('urgency', 'normal'):<10} {enabled}"
                )
        print("\nPress Enter to continue...")
        input()

    def add_reminder():
        clear_screen()
        print("\033[1;32m=== Add New Reminder ===\033[0m\n")

        name = input("Name: ").strip()
        if not name:
            print("Name is required.")
            return

        for r in config.get("reminders", []):
            if r.get("name") == name:
                print(f"Reminder '{name}' already exists.")
                return

        try:
            interval = int(input("Interval (minutes): ").strip())
        except ValueError:
            print("Invalid interval.")
            return

        title = input("Title (optional, press Enter for default): ").strip()
        message = input("Message (optional): ").strip()

        print("Urgency (low/normal/critical, default: normal): ", end="")
        urgency = input().strip() or "normal"
        if urgency not in ["low", "normal", "critical"]:
            urgency = "normal"

        new_reminder = {
            "name": name,
            "interval_minutes": interval,
            "title": title or f"Reminder: {name}",
            "message": message or "Time for a reminder!",
            "urgency": urgency,
            "enabled": True,
        }

        config.setdefault("reminders", []).append(new_reminder)

        with open(CONFIG, "w") as f:
            json.dump(config, f, indent=2)

        print(f"\n✓ Added reminder '{name}'")
        log.info(f"Added reminder via interactive: {name}")
        time.sleep(1)

    def edit_reminder():
        clear_screen()
        reminders = config.get("reminders", [])
        if not reminders:
            print("No reminders to edit.")
            print("\nPress Enter to continue...")
            input()
            return

        print("\033[1;32m=== Select Reminder to Edit ===\033[0m\n")
        for i, r in enumerate(reminders):
            print(f"  {i + 1}. {r['name']} (every {r['interval_minutes']} min)")

        try:
            choice = int(input("\nEnter number: ").strip()) - 1
            if choice < 0 or choice >= len(reminders):
                return
        except ValueError:
            return

        r = reminders[choice]
        print(f"\nEditing: {r['name']}")
        print("(Press Enter to keep current value)\n")

        new_interval = input(f"Interval [{r['interval_minutes']}]: ").strip()
        if new_interval:
            try:
                r["interval_minutes"] = int(new_interval)
            except ValueError:
                pass

        new_title = input(f"Title [{r.get('title', '')}]: ").strip()
        if new_title:
            r["title"] = new_title

        new_message = input(f"Message [{r.get('message', '')}]: ").strip()
        if new_message:
            r["message"] = new_message

        new_urgency = input(f"Urgency [{r.get('urgency', 'normal')}]: ").strip()
        if new_urgency in ["low", "normal", "critical"]:
            r["urgency"] = new_urgency

        with open(CONFIG, "w") as f:
            json.dump(config, f, indent=2)

        print(f"\n✓ Updated reminder '{r['name']}'")
        time.sleep(1)

    def toggle_reminder():
        clear_screen()
        reminders = config.get("reminders", [])
        if not reminders:
            print("No reminders to toggle.")
            print("\nPress Enter to continue...")
            input()
            return

        print("\033[1;32m=== Select Reminder to Toggle ===\033[0m\n")
        for i, r in enumerate(reminders):
            status = "✓ enabled" if r.get("enabled", True) else "· disabled"
            print(f"  {i + 1}. {r['name']} [{status}]")

        try:
            choice = int(input("\nEnter number: ").strip()) - 1
            if choice < 0 or choice >= len(reminders):
                return
        except ValueError:
            return

        r = reminders[choice]
        r["enabled"] = not r.get("enabled", True)

        with open(CONFIG, "w") as f:
            json.dump(config, f, indent=2)

        status = "enabled" if r["enabled"] else "disabled"
        print(f"\n✓ Reminder '{r['name']}' is now {status}")
        time.sleep(1)

    def remove_reminder():
        clear_screen()
        reminders = config.get("reminders", [])
        if not reminders:
            print("No reminders to remove.")
            print("\nPress Enter to continue...")
            input()
            return

        print("\033[1;32m=== Select Reminder to Remove ===\033[0m\n")
        for i, r in enumerate(reminders):
            print(f"  {i + 1}. {r['name']}")

        try:
            choice = int(input("\nEnter number: ").strip()) - 1
            if choice < 0 or choice >= len(reminders):
                return
        except ValueError:
            return

        r = reminders[choice]
        confirm = input(f"Remove '{r['name']}'? (y/N): ").strip().lower()
        if confirm != "y":
            return

        config["reminders"].pop(choice)

        with open(CONFIG, "w") as f:
            json.dump(config, f, indent=2)

        print(f"\n✓ Removed reminder '{r['name']}'")
        time.sleep(1)

    def start_kim():
        clear_screen()
        if PID_FILE.exists():
            print("kim is already running.")
        else:
            print("Starting kim... (run 'kim start' from another terminal)")
        print("\nPress Enter to continue...")
        input()

    def stop_kim():
        clear_screen()
        if not PID_FILE.exists():
            print("kim is not running.")
        else:
            print("Stopping kim... (run 'kim stop' from another terminal)")
        print("\nPress Enter to continue...")
        input()

    selected = 0
    options_count = 8

    while True:
        print_header()

        reminders = config.get("reminders", [])
        active = len([r for r in reminders if r.get("enabled", True)])
        print(f"  Active reminders: {active}/{len(reminders)}")
        if PID_FILE.exists():
            print("  Status: \033[1;32m● Running\033[0m")
        else:
            print("  Status: \033[0;90m○ Stopped\033[0m")
        print()

        print_menu(selected)

        key = get_key()

        if key == "\x1b":
            if tty and termios:
                extra = sys.stdin.read(1)
                if extra == "[":
                    direction = sys.stdin.read(1)
                    if direction == "A":
                        selected = (selected - 1) % options_count
                    elif direction == "B":
                        selected = (selected + 1) % options_count
        elif key == "\n":
            if selected == 0:
                list_reminders()
            elif selected == 1:
                add_reminder()
            elif selected == 2:
                edit_reminder()
            elif selected == 3:
                toggle_reminder()
            elif selected == 4:
                remove_reminder()
            elif selected == 5:
                start_kim()
            elif selected == 6:
                stop_kim()
            elif selected == 7:
                break
        elif key in ["q", "\x03"]:
            break


def cmd_selfupdate(args):
    print(f"Current version: {VERSION}")
    print("Checking for updates...")

    try:
        import urllib.request
        import urllib.error

        url = "https://api.github.com/repos/pratikwayal01/kim/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "kim"})

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            latest_version = data.get("tag_name", "").lstrip("v")

            if latest_version == VERSION:
                print(f"You're running the latest version ({VERSION}).")
                return

            print(f"New version available: {latest_version}")

            if not args.force:
                confirm = input("Update? (y/N): ").strip().lower()
                if confirm != "y":
                    print("Update cancelled.")
                    return

            system = platform.system().lower()
            arch = platform.machine()

            if system == "linux":
                arch_map = {
                    "x86_64": "x86_64",
                    "amd64": "x86_64",
                    "aarch64": "arm64",
                    "arm64": "arm64",
                }
                arch = arch_map.get(arch, "x86_64")
                asset_name = f"kim-linux-{arch}"
            elif system == "darwin":
                arch_map = {
                    "x86_64": "x86_64",
                    "amd64": "x86_64",
                    "aarch64": "arm64",
                    "arm64": "arm64",
                }
                arch = arch_map.get(arch, "x86_64")
                asset_name = f"kim-macos-{arch}"
            elif system == "windows":
                asset_name = "kim-windows-x86_64.exe"
            else:
                print(f"Unsupported platform: {system}")
                sys.exit(1)

            asset_url = None
            for a in data.get("assets", []):
                if asset_name in a.get("name", ""):
                    asset_url = a.get("browser_download_url")
                    break

            if not asset_url:
                print(f"No prebuilt binary for {system}-{arch}")
                print("Please update manually from GitHub releases.")
                return

            kim_path = Path(__file__).resolve()
            backup_path = kim_path.with_suffix(".bak")

            print(f"Downloading {asset_url}...")
            urllib.request.urlretrieve(asset_url, backup_path)

            os.chmod(backup_path, 0o755)

            old_path = kim_path
            new_path = backup_path

            new_path.replace(old_path)

            print(f"\n✓ Updated to version {latest_version}")
            print("Run 'kim --version' to verify.")

    except ImportError:
        print("urllib not available. Please update manually.")
    except urllib.error.URLError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"Update failed: {e}")
        if args.force:
            raise


def cmd_uninstall(args):
    print("\033[1;31m=== Uninstall kim ===\033[0m\n")

    if PID_FILE.exists():
        print("kim is running. Stop it first with 'kim stop'")
        sys.exit(1)

    confirm = (
        input("This will remove kim data and the binary. Continue? (y/N): ")
        .strip()
        .lower()
    )
    if confirm != "y":
        print("Uninstall cancelled.")
        return

    system = platform.system()

    if system == "Linux":
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "kim.service"],
            capture_output=True,
        )
        service_path = Path.home() / ".config/systemd/user/kim.service"
        if service_path.exists():
            service_path.unlink()
            print("Removed systemd service.")

    elif system == "Darwin":
        plist = Path.home() / "Library/LaunchAgents/io.kim.reminder.plist"
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            plist.unlink()
            print("Removed launchd plist.")

    elif system == "Windows":
        subprocess.run(
            ["Unregister-ScheduledTask", "-TaskName", "KimReminder", "-Confirm:$false"],
            capture_output=True,
            shell=True,
        )
        print("Removed scheduled task.")

    for path in [KIM_DIR, Path.home() / ".local/bin/kim"]:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            print(f"Removed {path}")

    print("\n✓ kim has been uninstalled.")
    print("Thank you for using kim!")


def cmd_export(args):
    config = load_config()

    if args.format == "json":
        output = json.dumps(config, indent=2)
    elif args.format == "csv":
        reminders = config.get("reminders", [])
        if reminders:
            lines = ["name,interval_minutes,title,message,urgency,enabled"]
            for r in reminders:
                name = r.get("name", "").replace(",", ";")
                title = r.get("title", "").replace(",", ";")
                message = r.get("message", "").replace(",", ";").replace("\n", " ")
                line = f"{name},{r.get('interval_minutes', '')},{title},{message},{r.get('urgency', 'normal')},{r.get('enabled', True)}"
                lines.append(line)
            output = "\n".join(lines)
        else:
            output = "name,interval_minutes,title,message,urgency,enabled"
    else:
        output = json.dumps(config, indent=2)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Exported to {args.output}")
    else:
        print(output)


def cmd_import(args):
    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {args.file}")
        sys.exit(1)

    try:
        content = path.read_text()

        if args.format == "auto":
            if path.suffix == ".csv":
                fmt = "csv"
            else:
                fmt = "json"
        else:
            fmt = args.format

        if fmt == "csv":
            lines = content.strip().split("\n")
            if len(lines) < 2:
                print("Invalid CSV format.")
                sys.exit(1)

            headers = lines[0].split(",")
            reminders = []
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 6:
                    reminders.append(
                        {
                            "name": parts[0],
                            "interval_minutes": int(parts[1])
                            if parts[1].isdigit()
                            else 30,
                            "title": parts[2],
                            "message": parts[3],
                            "urgency": parts[4]
                            if parts[4] in ["low", "normal", "critical"]
                            else "normal",
                            "enabled": parts[5].lower() == "true",
                        }
                    )

            imported_data = {"reminders": reminders, "sound": True}
        else:
            imported_data = json.loads(content)

        config = load_config()

        if args.merge:
            existing_names = {r["name"] for r in config.get("reminders", [])}
            for r in imported_data.get("reminders", []):
                if r["name"] not in existing_names:
                    config.setdefault("reminders", []).append(r)
            action = "Merged"
        else:
            config = imported_data
            action = "Imported"

        with open(CONFIG, "w") as f:
            json.dump(config, f, indent=2)

        print(f"✓ {action} {len(imported_data.get('reminders', []))} reminder(s)")

    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Import failed: {e}")
        sys.exit(1)


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
            if "interval_minutes" not in r:
                print(f"Error: Reminder '{r.get('name')}' missing 'interval_minutes'.")
                sys.exit(1)
            if not isinstance(r["interval_minutes"], int) or r["interval_minutes"] < 1:
                print(f"Error: Reminder '{r.get('name')}' has invalid interval.")
                sys.exit(1)

        print(f"✓ Config is valid ({len(reminders)} reminder(s))")

    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────────

BASH_COMPLETION = """#!/bin/bash
_kim_completions() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    opts="start stop status list logs edit add remove enable disable update interactive self-update uninstall export import validate completion"

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
# kim zsh completion

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
        "completion:Generate shell completions"
    )

    if (( CURRENT == 2 )); then
        _describe 'command' commands
    fi
}

_kim "$@"
"""

FISH_COMPLETION = """#!/usr/bin/env fish
# kim fish completion

complete -c kim -f -a "start stop status list logs edit add remove enable disable update interactive self-update uninstall export import validate completion"

complete -c kim -n "__fish_seen_subcommand_from remove enable disable update" -a "(python3 -c "import json; print(' '.join([r['name'] for r in json.load(open('$HOME/.kim/config.json')).get('reminders', [])]))" 2>/dev/null)"
"""


def cmd_completion(args):
    if args.shell == "bash":
        print(BASH_COMPLETION)
    elif args.shell == "zsh":
        print(ZSH_COMPLETION)
    elif args.shell == "fish":
        print(FISH_COMPLETION)


def main():
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
  interactive Enter interactive mode (alias: -i)
  self-update Check for and install updates
  uninstall   Uninstall kim completely
  export      Export reminders to file
  import      Import reminders from file
  validate    Validate config file
  completion  Generate shell completions

Short flags:
  -i          Enter interactive mode

config: ~/.kim/config.json
logs:   ~/.kim/kim.log
        """,
    )
    parser.add_argument("--version", action="version", version=f"kim {VERSION}")
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
        "-i", "--interval", type=int, required=True, help="Interval in minutes"
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

    remove_p = sub.add_parser("remove", help="Remove a reminder")
    remove_p.add_argument("name", help="Reminder name")

    enable_p = sub.add_parser("enable", help="Enable a reminder")
    enable_p.add_argument("name", help="Reminder name")

    disable_p = sub.add_parser("disable", help="Disable a reminder")
    disable_p.add_argument("name", help="Reminder name")

    update_p = sub.add_parser("update", help="Update a reminder")
    update_p.add_argument("name", help="Reminder name")
    update_p.add_argument("-i", "--interval", type=int, help="New interval in minutes")
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

    sub.add_parser("interactive", help="Enter interactive mode").add_argument(
        "-i", action="store_true", dest="interactive_alias"
    )

    sub.add_parser("self-update", help="Check for and install updates").add_argument(
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

    comp_p = sub.add_parser("completion", help="Generate shell completions")
    comp_p.add_argument("shell", choices=["bash", "zsh", "fish"], help="Shell type")

    if "-i" in sys.argv:
        new_argv = []
        for a in sys.argv:
            if a == "-i":
                new_argv.append("interactive")
            else:
                new_argv.append(a)
        sys.argv = new_argv

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
        "interactive": cmd_interactive,
        "self-update": cmd_selfupdate,
        "uninstall": cmd_uninstall,
        "export": cmd_export,
        "import": cmd_import,
        "validate": cmd_validate,
        "completion": cmd_completion,
    }

    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
