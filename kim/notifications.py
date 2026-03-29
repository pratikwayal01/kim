"""
Notification backends for kim: platform-specific notifications and Slack.
"""

import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request

from .core import log
from .sound import play_sound_file

# ── Custom sound playback helpers (imported from sound module) ────────────────
# play_sound_file(path, platform_system) is used for custom sound playback.


# ── Linux environment ─────────────────────────────────────────────────────────
def _linux_env():
    uid = os.getuid()
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return env


# ── Platform-specific notification functions ──────────────────────────────────
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
            play_sound_file(sound_file, "Linux")
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
    def _as(s):
        return (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", " ")
            .replace("\r", "")
        )

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
    except FileNotFoundError:
        log.error("osascript not found. Is this macOS?")
    except Exception as e:
        log.error(f"osascript: {e}")

    if sound and sound_file:
        play_sound_file(sound_file, "Darwin")


def _notify_windows(title, message, urgency, sound, sound_file=None):
    # Try balloon notification
    try:
        t = title.replace("'", "''").replace("\n", " ")
        m = message.replace("'", "''").replace("\n", " ")
        ps = f'''
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.BalloonTipIcon = "Info"
$n.BalloonTipTitle = "{t}"
$n.BalloonTipText = "{m}"
$n.ShowBalloonTip(5000)
Start-Sleep -Seconds 6
$n.Visible = $false
$n.Dispose()
'''
        subprocess.run(
            ["powershell", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
    except FileNotFoundError:
        log.error("powershell not found. Is this Windows?")
    except Exception as e:
        log.warning(f"Balloon notification failed: {e}")

    # Play sound file if specified (or system default if sound=True but no custom file)
    if sound or sound_file:
        play_sound_file(sound_file, "Windows")


# ── Main notify dispatcher ────────────────────────────────────────────────────
def notify(
    title: str,
    message: str,
    urgency: str = "normal",
    sound: bool = True,
    sound_file: str = None,
    slack_config: dict = None,
):
    system = platform.system()
    log.debug(f"notify [{urgency}] → {title}")
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


# ── Slack notification helpers ────────────────────────────────────────────────
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
        log.debug(f"Slack webhook notification sent: {title}")
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
        log.debug(f"Slack bot notification sent: {title}")
    except ImportError:
        log.error("urllib not available for Slack bot")
    except urllib.error.URLError as e:
        log.error(f"Slack bot error: {e}")
    except Exception as e:
        log.error(f"Slack bot failed: {e}")
