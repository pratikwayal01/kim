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

VERSION = "2.1.0"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
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
    "sound_file": None,
    "slack": {
        "enabled": False,
        "webhook_url": "",
        "bot_token": "",
        "channel": "#general",
    },
}


# ── Notification backends ─────────────────────────────────────────────────────


def _linux_env():
    uid = os.getuid()
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return env


# ── Custom sound playback ─────────────────────────────────────────────────────

# Supported formats per player (informational; players may accept more).
# Documented so users know what to expect per platform.
_SOUND_FORMAT_NOTES = {
    "Linux":   "paplay: wav/ogg/flac/mp3  |  aplay: wav  |  ffplay/mpv: any",
    "Darwin":  "afplay: wav/mp3/aiff/m4a/aac and most formats macOS can decode",
    "Windows": "winsound: wav only  |  powershell SoundPlayer: wav only",
}


def _play_sound_file_linux(path: str, env: dict) -> None:
    """Play a custom sound file on Linux, trying players in order of preference."""
    players = [
        ["paplay", path],
        ["aplay", path],
        ["ffplay", "-nodisp", "-autoexit", path],
        ["mpv", "--no-video", path],
        ["cvlc", "--play-and-exit", path],
    ]
    for cmd in players:
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception as e:
                log.warning(f"Sound player {cmd[0]} failed: {e}")
    log.error(f"No supported audio player found to play: {path}")


def _play_sound_file_mac(path: str) -> None:
    """Play a custom sound file on macOS using afplay."""
    if shutil.which("afplay"):
        try:
            subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log.error(f"afplay failed: {e}")
    else:
        log.error("afplay not found — cannot play custom sound on macOS")


def _play_sound_file_windows(path: str) -> None:
    """
    Play a custom sound file on Windows.
    Prefers the stdlib winsound module (wav only, no external deps).
    Falls back to PowerShell SoundPlayer for wav, or Windows Media Player for other formats.
    """
    p = Path(path)
    if not p.exists():
        log.error(f"Sound file not found: {path}")
        return

    if p.suffix.lower() == ".wav":
        # Try stdlib winsound first (zero-dependency, wav only)
        try:
            import winsound
            winsound.PlaySound(str(p), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        except Exception as e:
            log.warning(f"winsound failed: {e}")

        # Fallback: PowerShell SoundPlayer (also wav only)
        ps_path = str(p).replace("'", "''")
        ps = f"[System.Media.SoundPlayer]::new('{ps_path}').Play()"
        try:
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            return
        except Exception as e:
            log.warning(f"PowerShell SoundPlayer failed: {e}")
    else:
        # Non-wav: try Windows Media Player via PowerShell, then wmplayer.exe
        safe = str(p).replace("'", "''")
        ps = (
            f"$wmp = New-Object -ComObject WMPlayer.OCX; "
            f"$wmp.URL = '{safe}'; "
            f"$wmp.controls.play(); "
            f"Start-Sleep -s ([int]$wmp.currentMedia.duration + 1)"
        )
        try:
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            return
        except Exception as e:
            log.warning(f"PowerShell WMP failed: {e}")

        if shutil.which("ffplay"):
            try:
                subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", str(p)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
                return
            except Exception as e:
                log.warning(f"ffplay failed: {e}")

    log.error(f"Could not play sound file: {path}")


def _validate_sound_file(path: str) -> tuple[bool, str]:
    """
    Validate that a sound file exists and has a recognised audio extension.
    Returns (ok: bool, error_message: str).
    """
    SUPPORTED_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".aiff", ".aif", ".m4a", ".aac", ".oga"}
    p = Path(path)
    if not p.exists():
        return False, f"File not found: {path}"
    if not p.is_file():
        return False, f"Not a file: {path}"
    if p.suffix.lower() not in SUPPORTED_EXTS:
        return False, (
            f"Unrecognised extension '{p.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTS))}"
        )
    return True, ""


def _notify_linux(title, message, urgency, sound, sound_file=None):
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
        if sound_file:
            _play_sound_file_linux(sound_file, env)
        else:
            for cmd in (
                ["canberra-gtk-play", "--id=bell"],
                ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
            ):
                if shutil.which(cmd[0]):
                    subprocess.Popen(cmd, env=env, stderr=subprocess.DEVNULL)
                    break


def _notify_mac(title, message, urgency, sound, sound_file=None):
    # Escape for AppleScript string literals: backslash first, then double-quote
    def _as(s): return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').replace('\r', '')
    t = _as(title)
    m = _as(message)

    if sound and sound_file:
        # Show toast without built-in sound; play custom file separately via afplay
        snd = ""
    else:
        snd = 'sound name "Glass"' if sound else ""

    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{m}" with title "{t}" {snd}'],
            check=True,
        )
    except Exception as e:
        log.error(f"osascript: {e}")

    if sound and sound_file:
        _play_sound_file_mac(sound_file)


def _notify_windows(title, message, urgency, sound, sound_file=None):
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

    if sound and sound_file:
        _play_sound_file_windows(sound_file)


def notify(
    title: str,
    message: str,
    urgency: str = "normal",
    sound: bool = True,
    sound_file: str = None,
    slack_config: dict = None,
):
    system = platform.system()
    log.info(f"notify [{urgency}] → {title}")
    if system == "Linux":
        _notify_linux(title, message, urgency, sound, sound_file)
    elif system == "Darwin":
        _notify_mac(title, message, urgency, sound, sound_file)
    elif system == "Windows":
        _notify_windows(title, message, urgency, sound, sound_file)
    else:
        log.warning(f"Unsupported platform: {system}")

    if slack_config and slack_config.get("enabled"):
        if slack_config.get("webhook_url"):
            _notify_slack_webhook(title, message, slack_config["webhook_url"])
        elif slack_config.get("bot_token") and slack_config.get("channel"):
            _notify_slack_bot(
                title, message, slack_config["bot_token"], slack_config["channel"]
            )


def _notify_slack_webhook(title: str, message: str, webhook_url: str):
    try:
        import urllib.request
        import urllib.error

        payload = {
            "text": f"*{title}*\n{message}",
            "username": "kim reminder",
            "icon_emoji": ":bell:",
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=data, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        log.info(f"Slack webhook notification sent: {title}")
    except ImportError:
        log.error("urllib not available for Slack webhook")
    except urllib.error.URLError as e:
        log.error(f"Slack webhook error: {e}")
    except Exception as e:
        log.error(f"Slack webhook failed: {e}")


def _notify_slack_bot(title: str, message: str, bot_token: str, channel: str):
    try:
        import urllib.request
        import urllib.error

        urgency_emoji = {
            "low": ":information_source:",
            "normal": ":bell:",
            "critical": ":rotating_light:",
        }
        emoji = urgency_emoji.get("normal", ":bell:")

        payload = {
            "channel": channel,
            "text": f"{emoji} *{title}*\n{message}",
            "username": "kim reminder",
            "icon_emoji": ":bell:",
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bot_token}",
            },
        )
        urllib.request.urlopen(req, timeout=10)
        log.info(f"Slack bot notification sent: {title}")
    except ImportError:
        log.error("urllib not available for Slack bot")
    except urllib.error.URLError as e:
        log.error(f"Slack bot error: {e}")
    except Exception as e:
        log.error(f"Slack bot failed: {e}")


# ── Reminder thread ───────────────────────────────────────────────────────────


def parse_interval(value):
    if isinstance(value, int):
        return value * 60
    if isinstance(value, str):
        value = value.strip().lower()
        if value.endswith("d"):
            return int(value[:-1]) * 24 * 60 * 60
        elif value.endswith("h"):
            return int(value[:-1]) * 60 * 60
        elif value.endswith("m"):
            return int(value[:-1]) * 60
        elif value.endswith("s"):
            return int(value[:-1])
        try:
            return int(value) * 60
        except ValueError:
            pass
    return 30 * 60


def run_reminder(
    r: dict, sound: bool, stop_event: threading.Event, slack_config: dict = None
):
    name = r.get("name", "unnamed")
    interval_seconds = parse_interval(r.get("interval_minutes", 30))
    title = r.get("title", "Reminder")
    message = r.get("message", "Hey!")
    urgency = r.get("urgency", "normal")

    interval_display = r.get("interval_minutes", 30)
    log.info(f"[{name}] started — every {interval_display}")

    while not stop_event.wait(interval_seconds):
        notify(title, message, urgency, sound, slack_config)
        log.info(f"[{name}] fired")


# ── heapq Scheduler ───────────────────────────────────────────────────────────
# Replaces one-thread-per-reminder with a single scheduler thread.
# Memory: ~0.02 MB per reminder vs ~1.6 MB per thread (80x improvement).

import heapq
from copy import deepcopy
from typing import Callable, Dict, List, Optional


class _Event:
    """A scheduled fire event stored in the min-heap."""
    __slots__ = ("fire_at", "reminder", "cancelled")

    def __init__(self, fire_at: float, reminder: dict):
        self.fire_at = fire_at
        self.reminder = reminder
        self.cancelled = False

    def __lt__(self, other): return self.fire_at < other.fire_at
    def __le__(self, other): return self.fire_at <= other.fire_at


class KimScheduler:
    """
    Single-thread heapq scheduler.
    One background thread sleeps until the next reminder is due,
    fires it, reschedules it, then sleeps again.
    All public methods are thread-safe.
    """
    _IDLE_SLEEP = 60.0

    def __init__(self, config: dict, notifier: Callable[[dict], None]):
        self._notifier  = notifier
        self._lock      = threading.Lock()
        self._wakeup    = threading.Event()
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._live: Dict[str, _Event] = {}
        self._heap: List[_Event] = []
        self._load_config(config)

    def _load_config(self, config: dict) -> None:
        now = time.time()
        for reminder in config.get("reminders", []):
            if not reminder.get("enabled", True):
                continue
            interval = parse_interval(reminder.get("interval_minutes", 30))
            event = _Event(fire_at=now + interval, reminder=deepcopy(reminder))
            self._live[reminder["name"]] = event
            heapq.heappush(self._heap, event)

    def start(self) -> None:
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._run, name="kim-scheduler", daemon=True
        )
        self._thread.start()
        log.info(f"KimScheduler started ({len(self._live)} reminders)")

    def stop(self) -> None:
        self._stop_flag.set()
        self._wakeup.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("KimScheduler stopped")

    def add_reminder(self, reminder: dict) -> None:
        name = reminder["name"]
        interval = parse_interval(reminder.get("interval_minutes", 30))
        with self._lock:
            if name in self._live:
                self._live[name].cancelled = True
            event = _Event(fire_at=time.time() + interval, reminder=deepcopy(reminder))
            self._live[name] = event
            heapq.heappush(self._heap, event)
        self._wakeup.set()

    def remove_reminder(self, name: str) -> bool:
        with self._lock:
            event = self._live.pop(name, None)
            if event is None:
                return False
            event.cancelled = True
        self._wakeup.set()
        return True

    def update_reminder(self, reminder: dict) -> None:
        self.add_reminder(reminder)

    def _run(self) -> None:
        while not self._stop_flag.is_set():
            self._wakeup.clear()
            with self._lock:
                while self._heap and self._heap[0].cancelled:
                    heapq.heappop(self._heap)
                sleep_for = (
                    max(0.0, self._heap[0].fire_at - time.time())
                    if self._heap else self._IDLE_SLEEP
                )
            self._wakeup.wait(timeout=sleep_for)
            if self._stop_flag.is_set():
                break
            self._fire_due_events()

    def _fire_due_events(self) -> None:
        now = time.time()
        to_fire = []
        with self._lock:
            while self._heap and self._heap[0].fire_at <= now:
                event = heapq.heappop(self._heap)
                if event.cancelled:
                    continue
                if self._live.get(event.reminder["name"]) is not event:
                    continue
                to_fire.append(event)

        for event in to_fire:
            try:
                self._notifier(event.reminder)
            except Exception:
                log.exception(f"Notifier error for {event.reminder.get('name')}")
            interval = parse_interval(event.reminder.get("interval_minutes", 30))
            next_event = _Event(
                fire_at=event.fire_at + interval,
                reminder=event.reminder,
            )
            with self._lock:
                name = event.reminder["name"]
                if name in self._live and self._live[name] is event:
                    self._live[name] = next_event
                    heapq.heappush(self._heap, next_event)


# ── Daemon ────────────────────────────────────────────────────────────────────


def load_config() -> dict:
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding='utf-8')
        print(f"Created default config: {CONFIG}")
    with open(CONFIG, encoding='utf-8') as f:
        return json.load(f)


def cmd_start(args):
    if PID_FILE.exists():
        pid = PID_FILE.read_text(encoding='utf-8').strip()
        print(f"kim is already running (PID {pid}). Use 'kim stop' first.")
        sys.exit(1)

    config = load_config()
    sound = config.get("sound", True)
    sound_file = config.get("sound_file") or None
    slack_config = config.get("slack", {})
    active = [r for r in config.get("reminders", []) if r.get("enabled", True)]

    if not active:
        print("No enabled reminders in config. Edit ~/.kim/config.json")
        sys.exit(0)

    # Validate sound_file at startup so users get an early warning
    if sound and sound_file:
        ok, err = _validate_sound_file(sound_file)
        if not ok:
            print(f"\u26a0 Warning: sound_file problem \u2014 {err}")
            print("  Falling back to system default sound.")
            sound_file = None

    PID_FILE.write_text(str(os.getpid()), encoding='utf-8')

    print(f"kim v{VERSION} \u2014 {len(active)} reminder(s) active")
    for r in active:
        interval = r.get("interval_minutes", 30)
        interval_str = f"{interval} min" if isinstance(interval, int) else str(interval)
        print(f"  \u2022 {r['name']:<20} every {interval_str}")
    if sound_file:
        print(f"  Sound: {sound_file}")
    print(f"Log: {LOG_FILE}")

    log.info(f"kim v{VERSION} started \u2014 PID {os.getpid()}")

    # \u2500\u2500 Build a notifier that uses KIM's existing notify() with sound + slack \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    _slack = slack_config if slack_config.get("enabled") else None

    def kim_notifier(reminder: dict) -> None:
        notify(
            title=reminder.get("title", "Reminder"),
            message=reminder.get("message", ""),
            urgency=reminder.get("urgency", "normal"),
            sound=sound,
            sound_file=sound_file,
            slack_config=_slack,
        )
        log.info(f"[{reminder.get('name')}] fired")

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

    notify(
        "✅ kim started",
        f"{len(active)} reminder(s): " + ", ".join(r["name"] for r in active),
        urgency="low",
        sound=False,
        slack_config=_slack,
    )

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
    pid = int(PID_FILE.read_text(encoding='utf-8').strip())
    try:
        _terminate_process(pid)
        # On Windows the process is killed before its cleanup handler runs,
        # so we always remove the PID file here on all platforms.
        PID_FILE.unlink(missing_ok=True)
        print(f"kim stopped (PID {pid}).")
        log.info(f"Stopped by user (PID {pid})")
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
                capture_output=True, text=True,
            )
            return str(pid) in result.stdout
        else:
            os.kill(pid, 0)   # signal 0 = existence check only
            return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def cmd_status(args):
    config = load_config()
    active = [r for r in config.get("reminders", []) if r.get("enabled", True)]
    paused = [r for r in config.get("reminders", []) if not r.get("enabled", True)]

    if PID_FILE.exists():
        pid_str = PID_FILE.read_text(encoding='utf-8').strip()
        try:
            pid = int(pid_str)
            if _is_process_running(pid):
                print(f"● kim running   PID {pid}")
            else:
                PID_FILE.unlink(missing_ok=True)
                print("○ kim stopped  (removed stale PID file)")
        except ValueError:
            PID_FILE.unlink(missing_ok=True)
            print("○ kim stopped  (removed invalid PID file)")
    else:
        print("○ kim stopped")

    print(f"\n  Config : {CONFIG}")
    print(f"  Log    : {LOG_FILE}")

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
                f"    ✓ {r['name']:<20} every {r['interval_minutes']} min  [{r.get('urgency', 'normal')}]"
            )
    if paused:
        print("  Disabled reminders:")
        for r in paused:
            print(f"    - {r['name']}")


def cmd_sound(args):
    """Manage the custom sound file for notifications."""
    config = load_config()

    if args.set:
        path = os.path.abspath(os.path.expanduser(args.set))
        ok, err = _validate_sound_file(path)
        if not ok:
            print(f"✗ {err}")
            sys.exit(1)
        config["sound_file"] = path
        config["sound"] = True
        with open(CONFIG, "w") as f:
            json.dump(config, f, indent=2)
        print(f"✓ Custom sound set: {path}")
        print("  Restart kim ('kim stop && kim start') to apply.")
        log.info(f"sound_file set to: {path}")
        return

    if args.clear:
        config["sound_file"] = None
        with open(CONFIG, "w") as f:
            json.dump(config, f, indent=2)
        print("✓ Custom sound cleared — reverted to system default.")
        print("  Restart kim ('kim stop && kim start') to apply.")
        log.info("sound_file cleared")
        return

    if args.test:
        sound_enabled = config.get("sound", True)
        if not sound_enabled:
            print("Sound is currently disabled. Enable it first with 'kim sound --enable'.")
            sys.exit(1)
        sound_file = config.get("sound_file") or None
        if sound_file:
            ok, err = _validate_sound_file(sound_file)
            if not ok:
                print(f"✗ Cannot play: {err}")
                sys.exit(1)
            print(f"▶ Playing: {sound_file}")
        else:
            print("▶ Playing system default sound...")
        notify(
            "🔔 kim sound test",
            "This is how your reminder will sound.",
            urgency="normal",
            sound=True,
            sound_file=sound_file,
        )
        return

    if args.enable:
        config["sound"] = True
        with open(CONFIG, "w") as f:
            json.dump(config, f, indent=2)
        print("✓ Sound enabled.")
        return

    if args.disable:
        config["sound"] = False
        with open(CONFIG, "w") as f:
            json.dump(config, f, indent=2)
        print("✓ Sound disabled.")
        return

    # Default: show current sound config
    sound_enabled = config.get("sound", True)
    sound_file = config.get("sound_file") or None
    system = platform.system()

    print("Sound configuration:")
    print(f"  Enabled   : {'yes' if sound_enabled else 'no'}")
    if sound_file:
        ok, err = _validate_sound_file(sound_file)
        status = "✓ file found" if ok else f"✗ {err}"
        print(f"  Sound file: {sound_file}  [{status}]")
    else:
        print("  Sound file: (system default)")
    print(f"  Platform  : {system}")
    print(f"  Formats   : {_SOUND_FORMAT_NOTES.get(system, 'unknown platform')}")
    print()
    print("Commands:")
    print("  kim sound --set /path/to/sound.wav   Set a custom sound file")
    print("  kim sound --clear                    Revert to system default")
    print("  kim sound --test                     Play the current sound")
    print("  kim sound --enable / --disable       Toggle sound on/off")


def cmd_list(args):
    config = load_config()
    reminders = config.get("reminders", [])
    print(f"{'NAME':<20} {'INTERVAL':>12}   {'URGENCY':<10} {'ENABLED'}")
    print("─" * 58)
    for r in reminders:
        enabled = "✓" if r.get("enabled", True) else "·"
        interval = r.get("interval_minutes", 30)
        if isinstance(interval, str):
            interval_str = interval
        else:
            interval_str = f"{interval} min"
        print(
            f"{r['name']:<20} {interval_str:>12}   {r.get('urgency', 'normal'):<10} {enabled}"
        )


def cmd_logs(args):
    n = args.lines
    if not LOG_FILE.exists():
        print("No log file yet.")
        return
    lines = LOG_FILE.read_text(encoding='utf-8').splitlines()
    for line in lines[-n:]:
        print(line)


def cmd_edit(args):
    load_config()  # ensure config exists
    if platform.system() == "Windows":
        # os.execvp is POSIX-only; notepad is always available on Windows
        editor = os.environ.get("EDITOR", "notepad")
        subprocess.run([editor, str(CONFIG)])
    else:
        editor = os.environ.get("EDITOR", "nano")
        os.execvp(editor, [editor, str(CONFIG)])


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
        "interval_minutes": interval_str,
        "title": args.title or f"Reminder: {name}",
        "message": args.message or "Time for a reminder!",
        "urgency": args.urgency,
        "enabled": True,
    }

    config.setdefault("reminders", []).append(new_reminder)

    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    print(f"✓ Added reminder '{name}' (every {interval_str})")
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

    with open(CONFIG, "w", encoding="utf-8") as f:
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

    with open(CONFIG, "w", encoding="utf-8") as f:
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

    with open(CONFIG, "w", encoding="utf-8") as f:
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

    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    print(f"✓ Updated reminder '{name}'")
    log.info(f"Updated reminder: {name}")


def _windows_subprocess_cmd():
    """
    Return the correct command prefix to re-invoke this script on Windows.

    - If running as a PyInstaller/cx_Freeze frozen exe: [sys.executable]
    - If running as a .py script via python.exe:        [sys.executable, script_path]
    - If running via a pip-installed console_scripts entry point (.exe wrapper):
      the wrapper already embeds the python path, but sys.argv[0] is the .exe,
      so we still use [sys.executable, script_path] pointing to the real .py.
    """
    if getattr(sys, "frozen", False):
        # Frozen executable — the exe IS the interpreter
        return [sys.executable]
    script = os.path.abspath(sys.argv[0])
    return [sys.executable, script]


def cmd_remind(args):
    raw = " ".join(args.time)
    raw = raw.strip().lower().removeprefix("in").strip()

    total_seconds = 0
    import re
    for match in re.finditer(r"(\d+)\s*(d|h|m|s)", raw):
        value, unit = int(match.group(1)), match.group(2)
        total_seconds += {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit] * value

    if total_seconds == 0:
        print("Couldn't parse time. Examples: 'in 10m', 'in 1h', 'in 2h 30m'")
        sys.exit(1)

    message = args.message
    title = args.title or "⏰ Reminder"
    sleep_seconds = total_seconds

    parts = []
    remaining = total_seconds
    for unit, label in [(3600, "h"), (60, "m"), (1, "s")]:
        if remaining >= unit:
            parts.append(f"{remaining // unit}{label}")
            remaining %= unit
    display = " ".join(parts)

    print(f"⏰ Reminder set: '{message}' in {display}")
    log.info(f"One-shot reminder set: '{message}' in {display}")

    if platform.system() == "Windows":
        # FIX 1: build cmd with sys.executable so Windows can actually launch it.
        # FIX 2: omit close_fds=True — it is not supported on Windows.
        cmd = _windows_subprocess_cmd() + [
            "_remind-fire",
            "--message", message,
            "--title", title,
            "--seconds", str(sleep_seconds),
        ]
        subprocess.Popen(
            cmd,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
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

def _enable_windows_ansi() -> None:
    """
    Enable VT100/ANSI escape-sequence processing in the Windows console.
    Required on Windows 10+ to make \033[...m colour codes and \033[2J clear
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
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


def get_key() -> str:
    """
    Read a single keypress and return a normalised key string.

    Normalised values (same on every platform):
      "UP"    arrow up
      "DOWN"  arrow down
      "\n"    Enter
      "\x03"  Ctrl-C
      "q"     q
      (any other single printable character)

    On Windows uses msvcrt.getwch() so no Enter is required.
    On Unix uses tty/termios raw mode; falls back to input() if not a tty
    (e.g. when stdin is redirected).
    """
    if platform.system() == "Windows":
        import msvcrt
        ch = msvcrt.getwch()
        # \x00 and \xe0 are the two-byte prefix for special keys (arrows etc.)
        if ch in ('\x00', '\xe0'):
            ch2 = msvcrt.getwch()
            return {"H": "UP", "P": "DOWN"}.get(ch2, "")
        if ch == "\r":   # Windows Enter comes as \r, not \n
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
        # Escape sequence: \x1b [ A/B = up/down
        if ch == "\x1b":
            extra = sys.stdin.read(1)
            if extra == "[":
                direction = sys.stdin.read(1)
                return {"A": "UP", "B": "DOWN"}.get(direction, "")
            return ""   # other escape sequence — ignore
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

    try:
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


def cmd_selfupdate(args):
    print(f"Current version: {VERSION}")
    print("Checking for updates...")

    try:
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
                arch_map = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}
                arch = arch_map.get(arch, "x86_64")
                asset_name = f"kim-linux-{arch}"
            elif system == "darwin":
                arch_map = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}
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

            kim_in_path = shutil.which("kim")
            if kim_in_path:
                kim_path = Path(kim_in_path).resolve()
            else:
                if platform.system() == "Windows":
                    kim_path = Path.home() / "AppData" / "Local" / "Programs" / "kim" / "kim.exe"
                elif platform.system() == "Darwin":
                    # Prefer Homebrew prefix if available, otherwise ~/.local/bin
                    brew_bin = Path("/opt/homebrew/bin/kim")
                    kim_path = brew_bin if brew_bin.parent.exists() else Path.home() / ".local" / "bin" / "kim"
                else:
                    kim_path = Path.home() / ".local" / "bin" / "kim"
                kim_path.parent.mkdir(parents=True, exist_ok=True)

            tmp_path = kim_path.with_suffix(".new")

            print(f"Downloading {asset_url}...")
            urllib.request.urlretrieve(asset_url, tmp_path)

            if platform.system() != "Windows":
                os.chmod(tmp_path, 0o755)
            try:
                tmp_path.replace(kim_path)
            except PermissionError:
                print(f"Could not replace binary (file in use).")
                print(f"New version at: {tmp_path}")
                print(f"Manually replace: {kim_path}")
                return

            print(f"\n✓ Updated to version {latest_version}")
            print("Run 'kim --version' to verify.")

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
        input("This will remove kim data and the binary. Continue? (Y/N): ")
        .strip()
        .lower()
    )
    if confirm != "y":
        print("Uninstall cancelled.")
        return

    system = platform.system()

    if system == "Linux":
        subprocess.run(["systemctl", "--user", "disable", "--now", "kim.service"], capture_output=True)
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
            capture_output=True, shell=True,
        )
        print("Removed scheduled task.")

    # Release the log file handle before wiping KIM_DIR.
    # On Windows, open file handles prevent deletion (WinError 32).
    # logging.shutdown() flushes and closes every handler registered
    # with the root logger, including the FileHandler on kim.log.
    logging.shutdown()

    # Collect binary locations to clean up beyond KIM_DIR
    _system = platform.system()
    binary_candidates = [Path.home() / ".local" / "bin" / "kim"]
    if _system == "Darwin":
        binary_candidates += [
            Path("/usr/local/bin/kim"),
            Path("/opt/homebrew/bin/kim"),
        ]
    elif _system == "Windows":
        binary_candidates += [
            Path.home() / "AppData" / "Local" / "Programs" / "kim" / "kim.exe",
        ]
    # Also add whatever shutil.which finds (covers pip entry-point wrappers)
    _which = shutil.which("kim")
    if _which:
        binary_candidates.append(Path(_which).resolve())
    for path in [KIM_DIR] + list(dict.fromkeys(binary_candidates)):  # dedup
        if path.exists():
            if path.is_dir():
                try:
                    shutil.rmtree(path)
                except PermissionError as e:
                    print(f"Could not remove {path}: {e}")
                    print("  Close any programs using files in that folder, then delete it manually.")
                    continue
            else:
                try:
                    path.unlink()
                except PermissionError as e:
                    print(f"Could not remove {path}: {e}")
                    continue
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
        Path(args.output).write_text(output, encoding='utf-8')
        print(f"Exported to {args.output}")
    else:
        print(output)


def cmd_import(args):
    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {args.file}")
        sys.exit(1)

    try:
        content = path.read_text(encoding='utf-8')

        if args.format == "auto":
            fmt = "csv" if path.suffix == ".csv" else "json"
        else:
            fmt = args.format

        if fmt == "csv":
            lines = content.strip().splitlines()
            if len(lines) < 2:
                print("Invalid CSV format.")
                sys.exit(1)

            reminders = []
            for line in lines[1:]:
                parts = line.split(",")
                if len(parts) >= 6:
                    reminders.append({
                        "name": parts[0],
                        "interval_minutes": int(parts[1]) if parts[1].isdigit() else 30,
                        "title": parts[2],
                        "message": parts[3],
                        "urgency": parts[4] if parts[4] in ["low", "normal", "critical"] else "normal",
                        "enabled": parts[5].lower() == "true",
                    })
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
            interval_val = r["interval_minutes"]
            if isinstance(interval_val, str):
                pass
            elif not isinstance(interval_val, int) or interval_val < 1:
                print(f"Error: Reminder '{r.get('name')}' has invalid interval.")
                sys.exit(1)

        print(f"✓ Config is valid ({len(reminders)} reminder(s))")

    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        sys.exit(1)


def cmd_slack(args):
    config = load_config()
    slack_config = config.get("slack", {})

    if args.test:
        title = args.title or "Test Notification"
        message = args.message or "This is a test from kim!"

        if slack_config.get("webhook_url"):
            print(f"Sending test to webhook...")
            _notify_slack_webhook(title, message, slack_config["webhook_url"])
            print("✓ Test notification sent via webhook")
        elif slack_config.get("bot_token") and slack_config.get("channel"):
            print(f"Sending test to #{slack_config.get('channel')}...")
            _notify_slack_bot(title, message, slack_config["bot_token"], slack_config["channel"])
            print("✓ Test notification sent via bot")
        else:
            print("Slack not configured. Edit ~/.kim/config.json and add slack.webhook_url or slack.bot_token")
            sys.exit(1)
        return

    print("Slack configuration:")
    print(f"  Enabled: {slack_config.get('enabled', False)}")
    print(f"  Webhook URL: {'configured' if slack_config.get('webhook_url') else 'not set'}")
    print(f"  Bot Token: {'configured' if slack_config.get('bot_token') else 'not set'}")
    print(f"  Channel: {slack_config.get('channel', '#general')}")


# ── CLI ───────────────────────────────────────────────────────────────────────

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
    parser.add_argument("--version", action="version", version=f"kim {VERSION}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Start the daemon")
    sub.add_parser("stop", help="Stop the daemon")
    sub.add_parser("status", help="Show status and active reminders")
    sub.add_parser("list", help="List all reminders from config")
    sub.add_parser("edit", help="Open config in $EDITOR")

    logs_p = sub.add_parser("logs", help="Show recent log entries")
    logs_p.add_argument("-n", "--lines", type=int, default=30, help="Number of lines to show (default: 30)")

    add_p = sub.add_parser("add", help="Add a new reminder")
    add_p.add_argument("name", help="Reminder name")
    add_p.add_argument("-I", "--interval", type=str, required=True, help="Interval (e.g., 30m, 1h, 1d, or just number for minutes)")
    add_p.add_argument("-t", "--title", help="Notification title")
    add_p.add_argument("-m", "--message", help="Notification message")
    add_p.add_argument("-u", "--urgency", choices=["low", "normal", "critical"], default="normal", help="Urgency level")

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
    update_p.add_argument("-u", "--urgency", choices=["low", "normal", "critical"], help="New urgency level")
    update_p.add_argument("--enable", action="store_true", help="Enable the reminder")
    update_p.add_argument("--disable", action="store_true", help="Disable the reminder")

    remind_p = sub.add_parser("remind", help="Fire a one-shot reminder after a delay")
    remind_p.add_argument("message", help="Reminder message")
    remind_p.add_argument("time", nargs="+", help="When to fire, e.g: 'in 10m', '1h', '2h 30m', '90s'")
    remind_p.add_argument("-t", "--title", help="Notification title (default: ⏰ Reminder)")

    fire_p = sub.add_parser("_remind-fire")
    fire_p.add_argument("--message", required=True)
    fire_p.add_argument("--title", default="⏰ Reminder")
    fire_p.add_argument("--seconds", type=float, required=True)

    sub.add_parser("interactive", help="Enter interactive mode").add_argument(
        "-i", action="store_true", dest="interactive_alias"
    )

    selfupdate_p = sub.add_parser("self-update", help="Check for and install updates")
    selfupdate_p.add_argument("-f", "--force", action="store_true", help="Skip confirmation prompt")

    sub.add_parser("uninstall", help="Uninstall kim completely")

    export_p = sub.add_parser("export", help="Export reminders to a file")
    export_p.add_argument("-f", "--format", choices=["json", "csv"], default="json", help="Export format (default: json)")
    export_p.add_argument("-o", "--output", help="Output file (prints to stdout if not specified)")

    import_p = sub.add_parser("import", help="Import reminders from a file")
    import_p.add_argument("file", help="File to import from")
    import_p.add_argument("-f", "--format", choices=["json", "csv", "auto"], default="auto", help="Input format (default: auto-detect)")
    import_p.add_argument("--merge", action="store_true", help="Merge with existing reminders instead of replacing")

    sub.add_parser("validate", help="Validate config file")

    slack_p = sub.add_parser("slack", help="Slack notification settings")
    slack_p.add_argument("--test", action="store_true", help="Send test notification")
    slack_p.add_argument("-t", "--title", help="Test notification title")
    slack_p.add_argument("-m", "--message", help="Test notification message")

    sound_p = sub.add_parser("sound", help="Manage the notification sound file")
    sound_p.add_argument("--set", metavar="FILE", help="Set a custom sound file (wav/mp3/ogg/flac/aiff/m4a)")
    sound_p.add_argument("--clear", action="store_true", help="Remove custom sound and revert to system default")
    sound_p.add_argument("--test", action="store_true", help="Play the current sound immediately")
    sound_p.add_argument("--enable", action="store_true", help="Enable sound notifications")
    sound_p.add_argument("--disable", action="store_true", help="Disable sound notifications")

    comp_p = sub.add_parser("completion", help="Generate shell completions")
    comp_p.add_argument("shell", choices=["bash", "zsh", "fish"], help="Shell type")

    if "-i" in sys.argv:
        sys.argv = [a if a != "-i" else "interactive" for a in sys.argv]

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


if __name__ == "__main__":
    main()