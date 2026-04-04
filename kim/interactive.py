"""
Interactive mode for kim.
"""

import json
import os
import platform
import shutil
import sys
import time

try:
    import tty
    import termios
except ImportError:
    tty = None
    termios = None

from .core import (
    CONFIG,
    ONESHOT_FILE,
    PID_FILE,
    load_config,
    log,
    parse_interval,
    parse_datetime,
    parse_at_time,
)
from .utils import ARROW, HLINE, EM_DASH, CHECK, MIDDOT, CIRCLE_OPEN, CIRCLE_FILLED
from .commands.misc import load_oneshot_reminders, remove_oneshot


def _save_config(config: dict) -> bool:
    """
    Atomically write config to disk (tmp → rename).
    Returns True on success, False on failure (after printing an error).
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
        return True
    except OSError as e:
        print(f"\nError writing config file: {e}")
        return False


def _enable_windows_ansi() -> None:
    """
    Enable VT100/ANSI escape-sequence processing in the Windows console.
    Required on Windows 10+ to make \\033[...m colour codes and \\033[2J clear
    actually work instead of printing as literal garbage.
    No-ops on older Windows or if already enabled.
    """
    try:
        import ctypes

        STD_OUTPUT_HANDLE = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_ulong(0)
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(
                handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
    except Exception:
        pass


def get_key() -> str:
    """
    Read a single keypress and return a normalised key string.

    Normalised values (same on every platform):
      "UP"    arrow up
      "DOWN"  arrow down
      "\\n"   Enter
      "\\x03"  Ctrl-C
      "q"     q
      (any other single printable character)

    On Windows uses msvcrt.getwch() so no Enter is required.
    On Unix uses tty/termios raw mode; falls back to input() if not a tty
    (e.g. when stdin is redirected).
    """
    if platform.system() == "Windows":
        import msvcrt

        ch = msvcrt.getwch()
        # \\x00 and \\xe0 are the two-byte prefix for special keys (arrows etc.)
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return {"H": "UP", "P": "DOWN"}.get(ch2, "")
        if ch == "\r":  # Windows Enter comes as \\r, not \\n
            return "\n"
        return ch

    # ── Unix path ─────────────────────────────────────────────────────────────
    if tty is None or termios is None:
        # tty/termios not available at all — plain line input
        line = input()
        return line if line else "\n"

    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            line = input()
            return line if line else "\n"
    except Exception:
        line = input()
        return line if line else "\n"

    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
        # Escape sequence: \\x1b [ A/B = up/down
        if ch == "\x1b":
            extra = sys.stdin.read(1)
            if extra == "[":
                direction = sys.stdin.read(1)
                return {"A": "UP", "B": "DOWN"}.get(direction, "")
            return ""  # other escape sequence — ignore
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


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
            "\033[1;36m"
            + f" kim {EM_DASH} Interactive Mode ".center(cols - 1, HLINE)
            + "\033[0m"
        )
        print()

    options = [
        "List Reminders",
        "List One-shots",
        "Add Reminder",
        "Add One-shot",
        "Edit Reminder",
        "Toggle Reminder",
        "Remove Reminder",
        "Remove One-shot",
        "Start kim",
        "Stop kim",
        "Exit",
    ]
    options_count = len(options)

    def print_menu(selected):
        print("\r\033[K", end="")
        for i, opt in enumerate(options):
            prefix = f"{ARROW} " if i == selected else "  "
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
            print(HLINE * 55)
            for r in reminders:
                enabled = CHECK if r.get("enabled", True) else MIDDOT
                iv = r.get("interval") or r.get("at")
                if iv is None:
                    iv = f"{r.get('interval_minutes', 30)} min"
                elif isinstance(iv, (int, float)):
                    iv = f"{iv} min"
                print(
                    f"{r['name']:<20} {str(iv):>10}   {r.get('urgency', 'normal'):<10} {enabled}"
                )
        print("\nPress Enter to continue...")
        input()

    def list_oneshots():
        import datetime as _dt

        clear_screen()
        print("\033[1;32m=== Pending One-shot Reminders ===\033[0m\n")
        now = time.time()
        pending = sorted(
            [o for o in load_oneshot_reminders() if o.get("fire_at", 0) > now],
            key=lambda o: o["fire_at"],
        )
        if not pending:
            print("No pending one-shot reminders.")
        else:
            print(f"{'#':<4} {'MESSAGE':<28} {'FIRES AT':<20} {'IN'}")
            print("-" * 68)
            for i, o in enumerate(pending, 1):
                msg = o.get("message", "")[:26]
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
                print(f"{i:<4} {msg:<28} {fire_dt:<20} {eta}")
        print("\nPress Enter to continue...")
        input()

    def add_reminder():
        clear_screen()
        print("\033[1;32m=== Add New Reminder ===\033[0m\n")

        name = input("Name: ").strip()
        if not name:
            print("Name is required.")
            time.sleep(1)
            return

        for r in config.get("reminders", []):
            if r.get("name") == name:
                print(f"Reminder '{name}' already exists.")
                time.sleep(1)
                return

        print("Schedule type:")
        print("  1. Interval  (e.g. every 30m)")
        print("  2. Daily at  (e.g. at 10:00)")
        stype = input("Choice [1]: ").strip() or "1"

        new_reminder = {
            "name": name,
            "title": "",
            "message": "",
            "urgency": "normal",
            "enabled": True,
        }

        if stype == "2":
            at_input = input("Time (HH:MM): ").strip()
            try:
                at_val = parse_at_time(at_input)
            except ValueError as e:
                print(f"Invalid time: {e}")
                time.sleep(1)
                return
            new_reminder["at"] = at_val
            schedule_desc = f"daily at {at_val}"
        else:
            interval_input = input("Interval (e.g. 30m, 1h, 1d): ").strip()
            if not interval_input:
                print("Interval is required.")
                time.sleep(1)
                return
            _iv = interval_input.lower()
            if any(_iv.endswith(u) for u in ("m", "h", "d", "s")):
                interval_str = _iv
            else:
                try:
                    n = int(_iv)
                    if n <= 0:
                        print("Interval must be positive.")
                        time.sleep(1)
                        return
                    interval_str = f"{n}m"
                except ValueError:
                    print("Invalid interval. Use e.g. 30m, 1h, 1d, 90s.")
                    time.sleep(1)
                    return
            new_reminder["interval"] = interval_str
            schedule_desc = f"every {interval_str}"

        title = input("Title (optional): ").strip()
        message = input("Message (optional): ").strip()
        urgency = input("Urgency (low/normal/critical) [normal]: ").strip() or "normal"
        if urgency not in ("low", "normal", "critical"):
            urgency = "normal"

        new_reminder["title"] = title or f"Reminder: {name}"
        new_reminder["message"] = message or "Time for a reminder!"
        new_reminder["urgency"] = urgency

        config.setdefault("reminders", []).append(new_reminder)
        if not _save_config(config):
            time.sleep(2)
            return

        # Signal live reload
        from .commands.management import _signal_reload

        _signal_reload()

        print(f"\n{CHECK} Added reminder '{name}' ({schedule_desc})")
        log.info("Added reminder via interactive: %s", name)
        time.sleep(1)

    def add_oneshot():
        import subprocess as _sp

        clear_screen()
        print("\033[1;32m=== Add One-shot Reminder ===\033[0m\n")
        print("Examples: in 30m  |  in 2h  |  at 14:30  |  at tomorrow 9am")

        message = input("Message: ").strip()
        if not message:
            print("Message is required.")
            time.sleep(1)
            return

        time_input = input("When: ").strip()
        if not time_input:
            print("Time is required.")
            time.sleep(1)
            return

        try:
            fire_time = parse_datetime(time_input.split())
        except ValueError as e:
            print(f"Error: {e}")
            time.sleep(2)
            return

        sleep_seconds = fire_time - time.time()
        if sleep_seconds <= 0:
            print("That time is already in the past.")
            time.sleep(1)
            return
        if sleep_seconds > 365 * 24 * 3600:
            print("Duration too large (max 365 days).")
            time.sleep(1)
            return

        title = input("Title (optional) [Reminder]: ").strip() or "Reminder"

        import datetime as _dt

        fire_dt = _dt.datetime.fromtimestamp(fire_time).strftime("%Y-%m-%d %H:%M")

        # Persist to oneshots.json
        oneshot_entry = {"message": message, "title": title, "fire_at": fire_time}
        existing = []
        if ONESHOT_FILE.exists():
            try:
                existing = json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
            except Exception:
                existing = []
        existing.append(oneshot_entry)
        try:
            _tmp = ONESHOT_FILE.with_suffix(".tmp")
            _tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
            _tmp.replace(ONESHOT_FILE)
        except OSError as e:
            print(f"Could not save one-shot: {e}")
            time.sleep(2)
            return

        # Spawn the background fire process
        if platform.system() == "Windows":
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
            try:
                _sp.Popen(
                    cmd,
                    stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL,
                    stdin=_sp.DEVNULL,
                    creationflags=0x08000000,
                )
            except Exception as e:
                print(f"Warning: could not spawn background process: {e}")
        else:
            pid = os.fork()
            if pid == 0:
                try:
                    os.setsid()
                    time.sleep(sleep_seconds)
                    from .notifications import notify

                    cfg = load_config()
                    notify(
                        title,
                        message,
                        urgency="critical",
                        sound=cfg.get("sound", True),
                        sound_file=cfg.get("sound_file") or None,
                    )
                    log.info("One-shot reminder fired: %s", message)
                except Exception:
                    pass
                finally:
                    sys.exit(0)

        print(f"\n{CHECK} Reminder set: '{message}' at {fire_dt}")
        log.info("One-shot set via interactive: '%s' at %s", message, fire_dt)
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
            iv = r.get("interval") or f"at {r.get('at', '?')}"
            print(f"  {i + 1}. {r['name']} ({iv})")

        try:
            choice = int(input("\nEnter number: ").strip()) - 1
            if choice < 0 or choice >= len(reminders):
                return
        except ValueError:
            return

        r = reminders[choice]
        print(f"\nEditing: {r['name']}")
        print("(Press Enter to keep current value)\n")

        new_interval = input(
            f"Interval [{r.get('interval') or r.get('interval_minutes', 30)}]: "
        ).strip()
        if new_interval:
            _iv = new_interval.lower()
            if any(_iv.endswith(u) for u in ("m", "h", "d", "s")):
                r["interval"] = _iv
            else:
                try:
                    r["interval"] = f"{int(new_interval)}m"
                except ValueError:
                    pass

        new_title = input(f"Title [{r.get('title', '')}]: ").strip()
        if new_title:
            r["title"] = new_title

        new_message = input(f"Message [{r.get('message', '')}]: ").strip()
        if new_message:
            r["message"] = new_message

        new_urgency = input(f"Urgency [{r.get('urgency', 'normal')}]: ").strip()
        if new_urgency in ("low", "normal", "critical"):
            r["urgency"] = new_urgency

        if not _save_config(config):
            time.sleep(2)
            return

        from .commands.management import _signal_reload

        _signal_reload()

        print(f"\n{CHECK} Updated reminder '{r['name']}'")
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
            status = (
                f"{CHECK} enabled" if r.get("enabled", True) else f"{MIDDOT} disabled"
            )
            print(f"  {i + 1}. {r['name']} [{status}]")

        try:
            choice = int(input("\nEnter number: ").strip()) - 1
            if choice < 0 or choice >= len(reminders):
                return
        except ValueError:
            return

        r = reminders[choice]
        r["enabled"] = not r.get("enabled", True)

        if not _save_config(config):
            time.sleep(2)
            return

        from .commands.management import _signal_reload

        _signal_reload()

        status = "enabled" if r["enabled"] else "disabled"
        print(f"\n{CHECK} Reminder '{r['name']}' is now {status}")
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

        if not _save_config(config):
            time.sleep(2)
            return

        from .commands.management import _signal_reload

        _signal_reload()

        print(f"\n{CHECK} Removed reminder '{r['name']}'")
        time.sleep(1)

    def remove_oneshot():
        import datetime as _dt

        clear_screen()
        print("\033[1;32m=== Cancel One-shot Reminder ===\033[0m\n")
        now = time.time()
        pending = sorted(
            [o for o in load_oneshot_reminders() if o.get("fire_at", 0) > now],
            key=lambda o: o["fire_at"],
        )
        if not pending:
            print("No pending one-shot reminders.")
            print("\nPress Enter to continue...")
            input()
            return

        for i, o in enumerate(pending, 1):
            fire_dt = _dt.datetime.fromtimestamp(o["fire_at"]).strftime(
                "%Y-%m-%d %H:%M"
            )
            print(f"  {i}. {o.get('message', '')}  (due {fire_dt})")

        try:
            choice = int(input("\nEnter number to cancel: ").strip()) - 1
            if choice < 0 or choice >= len(pending):
                return
        except ValueError:
            return

        target = pending[choice]
        confirm = (
            input(f"Cancel '{target.get('message', '')}'? (y/N): ").strip().lower()
        )
        if confirm != "y":
            return

        remove_oneshot(target["fire_at"])
        print(f"\n{CHECK} Cancelled one-shot: '{target.get('message', '')}'")
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

    action_map = {
        0: list_reminders,
        1: list_oneshots,
        2: add_reminder,
        3: add_oneshot,
        4: edit_reminder,
        5: toggle_reminder,
        6: remove_reminder,
        7: remove_oneshot,
        8: start_kim,
        9: stop_kim,
    }

    selected = 0
    try:
        while True:
            print_header()

            reminders = config.get("reminders", [])
            active = len([r for r in reminders if r.get("enabled", True)])
            now = time.time()
            pending_oneshots = len(
                [o for o in load_oneshot_reminders() if o.get("fire_at", 0) > now]
            )
            print(
                f"  Reminders: {active}/{len(reminders)} active   One-shots: {pending_oneshots} pending"
            )
            if PID_FILE.exists():
                print(f"  Status: \033[1;32m{CIRCLE_FILLED} Running\033[0m")
            else:
                print(f"  Status: \033[0;90m{CIRCLE_OPEN} Stopped\033[0m")
            print()

            print_menu(selected)

            key = get_key()

            if key == "UP":
                selected = (selected - 1) % options_count
            elif key == "DOWN":
                selected = (selected + 1) % options_count
            elif key == "\n":
                if selected == options_count - 1:  # Exit
                    break
                action = action_map.get(selected)
                if action:
                    action()
                    config = load_config()  # reload after any mutation
            elif key in ("q", "\x03"):
                break
    except KeyboardInterrupt:
        print("\n\033[33mExiting interactive mode...\033[0m")
    finally:
        print("\033[2J\033[H", end="")
