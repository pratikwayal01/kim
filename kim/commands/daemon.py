"""
Daemon management commands: start, stop, status.
"""

import json
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..core import CONFIG, KIM_DIR, PID_FILE, VERSION, load_config, log
from ..notifications import notify
from ..sound import validate_sound_file
from ..scheduler import KimScheduler

from ..utils import BULLET, EM_DASH, WARNING, CIRCLE_OPEN, CIRCLE_FILLED, CHECK
from .misc import load_oneshot_reminders, remove_oneshot


def cmd_start(args):
    if PID_FILE.exists():
        try:
            pid_str = PID_FILE.read_text(encoding="utf-8").strip()
            pid = int(pid_str)
            if _is_process_running(pid):
                print(f"kim is already running (PID {pid}). Use 'kim stop' first.")
                sys.exit(1)
            else:
                log.info("Removing stale PID file (PID %s not running)", pid)
                PID_FILE.unlink(missing_ok=True)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            log.warning("Could not read PID file: %s. Removing.", e)
            PID_FILE.unlink(missing_ok=True)

    config = load_config()
    global_sound = config.get("sound", True)
    global_sound_file = config.get("sound_file") or None
    global_slack = config.get("slack", {})
    active = [r for r in config.get("reminders", []) if r.get("enabled", True)]

    if not active:
        print("No enabled reminders in config. Edit ~/.kim/config.json")
        sys.exit(1)

    # Validate global sound_file at startup so users get an early warning
    if global_sound and global_sound_file:
        ok, err = validate_sound_file(global_sound_file)
        if not ok:
            print(f"{WARNING} Warning: sound_file problem {EM_DASH} {err}")
            print("  Falling back to system default sound.")
            global_sound_file = None

    try:
        pid_tmp = PID_FILE.with_suffix(".tmp")
        pid_tmp.write_text(str(os.getpid()), encoding="utf-8")
        if platform.system() != "Windows":
            os.chmod(pid_tmp, 0o600)
        pid_tmp.replace(PID_FILE)
    except OSError as e:
        print(f"Error writing PID file: {e}")
        sys.exit(1)

    print(f"kim v{VERSION} {EM_DASH} {len(active)} reminder(s) active")
    for r in active:
        interval = r.get("interval") or r.get("interval_minutes", 30)
        interval_str = f"{interval} min" if isinstance(interval, int) else str(interval)
        print(f"  {BULLET} {r['name']:<20} every {interval_str}")
    if global_sound_file:
        print(f"  Sound: {global_sound_file}")
    _log_path = (
        log.handlers[0].baseFilename
        if log.handlers and hasattr(log.handlers[0], "baseFilename")
        else str(KIM_DIR / "kim.log")
    )
    print(f"Log: {_log_path}")

    log.info("kim v%s started %s PID %s", VERSION, EM_DASH, os.getpid())

    # ── Build a notifier that uses KIM's existing notify() with per-reminder sound + slack ──

    def kim_notifier(reminder: dict) -> None:
        # Check if this is a one-shot reminder (has _oneshot_fire_at)
        is_oneshot = "_oneshot_fire_at" in reminder
        fire_at = reminder.get("_oneshot_fire_at")

        # Per-reminder sound override (falls back to global)
        r_sound = reminder.get("sound")
        sound = r_sound if r_sound is not None else global_sound

        # Per-reminder sound_file override (falls back to global)
        r_sound_file = reminder.get("sound_file")
        sound_file = r_sound_file if r_sound_file else global_sound_file

        # Per-reminder slack override (falls back to global)
        r_slack = reminder.get("slack")
        if r_slack and r_slack.get("enabled"):
            slack_config = r_slack
        elif global_slack.get("enabled"):
            slack_config = global_slack
        else:
            slack_config = None

        notify(
            title=reminder.get("title", "Reminder"),
            message=reminder.get("message", ""),
            urgency=reminder.get("urgency", "normal"),
            sound=sound,
            sound_file=sound_file,
            slack_config=slack_config,
        )
        log.info("[%s] fired", reminder.get("name"))

        # If this was a one-shot, remove from persistence
        if is_oneshot and fire_at is not None:
            remove_oneshot(fire_at)

    # Load persisted one-shot reminders BEFORE creating scheduler
    oneshots = load_oneshot_reminders()

    # ── Start heapq scheduler (replaces per-reminder threads) ─────────────────
    scheduler = KimScheduler(config, kim_notifier)

    def shutdown(sig, frame):
        log.info("Shutting down...")
        scheduler.stop()
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    # SIGTERM can be delivered on Unix; on Windows it cannot be sent from
    # another process (os.kill raises WinError 87), so only register it
    # where it actually works.  SIGINT (Ctrl-C) works on both platforms.
    if platform.system() != "Windows":
        signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        notify(
            "kim started",
            "{} reminder(s): {}".format(
                len(active), ", ".join(r["name"] for r in active)
            ),
            urgency="low",
            sound=False,
            slack_config=global_slack if global_slack.get("enabled") else None,
        )
    except Exception:
        log.exception("Startup notification failed")

    # Add persisted one-shot reminders to scheduler BEFORE starting
    if oneshots:
        log.info("Loading %d persisted one-shot reminder(s)", len(oneshots))
        for o in oneshots:
            oneshot_reminder = {
                "name": f"oneshot-{int(o['fire_at'])}",
                "title": o.get("title", "One-shot Reminder"),
                "message": o.get("message", ""),
                "urgency": "critical",
                "enabled": True,
                "_oneshot_fire_at": o["fire_at"],
            }
            scheduler._oneshot_add(oneshot_reminder)

    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


def _terminate_process(pid: int) -> None:
    """
    Terminate a process by PID in a cross-platform way.

    - Unix: sends SIGTERM so the shutdown handler runs gracefully.
    - Windows: os.kill(pid, signal.SIGTERM) raises WinError 87 because SIGTERM
      is not a real Win32 signal that can be delivered across processes.
      Instead we use taskkill /F which forcefully terminates the process.
      Because the process is killed before it can run cleanup code, the caller
      is responsible for removing the PID file.

    Raises:
        ProcessLookupError  if the PID does not exist.
        PermissionError     if the caller lacks rights to terminate the process.
        RuntimeError        if taskkill fails for another reason (Windows only).
    """
    if platform.system() == "Windows":
        result = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
        stderr = result.stderr.lower()
        if "not found" in stderr or "no running instance" in stderr:
            raise ProcessLookupError(f"No process with PID {pid}")
        if "access is denied" in stderr:
            raise PermissionError(f"Access denied for PID {pid}")
        raise RuntimeError(f"taskkill failed: {result.stderr.strip()}")
    else:
        os.kill(pid, signal.SIGTERM)


def cmd_stop(args):
    if not PID_FILE.exists():
        print("kim is not running.")
        sys.exit(0)
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError, ValueError) as e:
        print(f"Could not read PID file: {e}")
        PID_FILE.unlink(missing_ok=True)
        return
    try:
        _terminate_process(pid)
        # On Windows the process is killed before its cleanup handler runs,
        # so we always remove the PID file here on all platforms.
        PID_FILE.unlink(missing_ok=True)
        print(f"kim stopped (PID {pid}).")
        log.info("Stopped by user (PID %d)", pid)
    except ProcessLookupError:
        print("Process not found — cleaning up stale PID file.")
        PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        print(f"Permission denied to stop PID {pid}.")
    except RuntimeError as e:
        print(f"Failed to stop kim: {e}")


def _is_process_running(pid: int) -> bool:
    """
    Cross-platform process-existence check.
    Uses signal 0 on Unix (doesn't kill, just probes).
    Uses tasklist on Windows.
    Returns False for any error, including permission errors — caller
    should treat an unverifiable PID as potentially stale.
    """
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
            )
            return str(pid) in result.stdout
        else:
            os.kill(pid, 0)  # signal 0 = existence check only
            return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def cmd_status(args):
    config = load_config()
    active = [r for r in config.get("reminders", []) if r.get("enabled", True)]
    paused = [r for r in config.get("reminders", []) if not r.get("enabled", True)]

    if PID_FILE.exists():
        try:
            pid_str = PID_FILE.read_text(encoding="utf-8").strip()
            pid = int(pid_str)
            if _is_process_running(pid):
                print(f"{CIRCLE_FILLED} kim running   PID {pid}")
            else:
                PID_FILE.unlink(missing_ok=True)
                print(f"{CIRCLE_OPEN} kim stopped  (removed stale PID file)")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            PID_FILE.unlink(missing_ok=True)
            print(f"{CIRCLE_OPEN} kim stopped  (removed invalid PID file)")
    else:
        print(f"{CIRCLE_OPEN} kim stopped")

    print(f"\n  Config : {CONFIG}")
    _log_path = (
        log.handlers[0].baseFilename
        if log.handlers and hasattr(log.handlers[0], "baseFilename")
        else str(KIM_DIR / "kim.log")
    )
    print(f"  Log    : {_log_path}")

    sound_enabled = config.get("sound", True)
    sound_file = config.get("sound_file") or None
    if not sound_enabled:
        print("  Sound  : disabled")
    elif sound_file:
        print(f"  Sound  : {sound_file}")
    else:
        print("  Sound  : system default")
    print()

    if active:
        print("  Active reminders:")
        for r in active:
            print(
                f"    {CHECK} {r['name']:<20} every {r.get('interval') or r.get('interval_minutes', '30')}  [{r.get('urgency', 'normal')}]"
            )
    if paused:
        print("  Disabled reminders:")
        for r in paused:
            print(f"    - {r['name']}")
