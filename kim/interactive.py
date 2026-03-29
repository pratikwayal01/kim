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

from .core import CONFIG, PID_FILE, load_config, log
from .utils import ARROW, HLINE, EM_DASH, CHECK, MIDDOT, CIRCLE_OPEN, CIRCLE_FILLED


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
                print(
                    f"{r['name']:<20} {str(r.get('interval') or r.get('interval_minutes', 30)) + ' min':>10}   {r.get('urgency', 'normal'):<10} {enabled}"
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
            "interval": interval,
            "title": title or f"Reminder: {name}",
            "message": message or "Time for a reminder!",
            "urgency": urgency,
            "enabled": True,
        }

        config.setdefault("reminders", []).append(new_reminder)

        try:
            with open(CONFIG, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            print(f"\nError writing config file: {e}")
            time.sleep(2)
            return

        print(f"\n{CHECK} Added reminder '{name}'")
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
            print(
                f"  {i + 1}. {r['name']} (every {r.get('interval') or r.get('interval_minutes', 30)} min)"
            )

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
            try:
                r["interval"] = int(new_interval)
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

        try:
            with open(CONFIG, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            print(f"\nError writing config file: {e}")
            time.sleep(2)
            return

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

        try:
            with open(CONFIG, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            print(f"\nError writing config file: {e}")
            time.sleep(2)
            return

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

        try:
            with open(CONFIG, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            print(f"\nError writing config file: {e}")
            time.sleep(2)
            return

        print(f"\n{CHECK} Removed reminder '{r['name']}'")
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

    try:
        while True:
            print_header()

            reminders = config.get("reminders", [])
            active = len([r for r in reminders if r.get("enabled", True)])
            print(f"  Active reminders: {active}/{len(reminders)}")
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
    except KeyboardInterrupt:
        print("\n\033[33mExiting interactive mode...\033[0m")
    finally:
        print("\033[2J\033[H", end="")
