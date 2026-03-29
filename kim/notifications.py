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
    except Exception as e:
        log.error(f"osascript: {e}")

    if sound and sound_file:
        play_sound_file(sound_file, "Darwin")


def _notify_windows(title, message, urgency, sound, sound_file=None):
    # Escape for PowerShell single-quoted string: double any single quotes
    def ps_single_escape(s):
        return s.replace("'", "''")

    t = ps_single_escape(title)
    m = ps_single_escape(message.replace("\n", " "))
    # Use single quotes in PowerShell; escape embedded single quotes by doubling
    ps = f"""
$tpl = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($tpl)
$xml.GetElementsByTagName('text')[0].AppendChild($xml.CreateTextNode('{t}')) | Out-Null
$xml.GetElementsByTagName('text')[1].AppendChild($xml.CreateTextNode('{m}')) | Out-Null
$n = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('kim').Show($n)
"""
    try:
        log.debug(f"PowerShell toast command: {ps}")
        result = subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.error(
                f"PowerShell toast failed (rc={result.returncode}): {result.stderr}"
            )
        elif result.stderr:
            log.debug(f"PowerShell toast stderr: {result.stderr}")
    except Exception as e:
        log.error(f"powershell toast: {e}")

    if sound and sound_file:
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
