"""
Sound playback and validation for kim.
"""

import shutil
import subprocess
from pathlib import Path

from .core import log

# Supported formats per player (informational; players may accept more).
# Documented so users know what to expect per platform.
SOUND_FORMAT_NOTES = {
    "Linux": "paplay: wav/ogg/flac/mp3  |  aplay: wav  |  ffplay/mpv: any",
    "Darwin": "afplay: wav/mp3/aiff/m4a/aac and most formats macOS can decode",
    "Windows": "winsound: wav only  |  powershell SoundPlayer: wav only",
}


def _play_sound_file_linux(path: str) -> None:
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
                subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                return
            except Exception as e:
                log.warning(f"Sound player {cmd[0]} failed: {e}")
    log.error(f"No supported audio player found to play: {path}")


def _play_sound_file_mac(path: str) -> None:
    """Play a custom sound file on macOS using afplay."""
    if shutil.which("afplay"):
        try:
            subprocess.Popen(
                ["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            return
        except Exception as e:
            log.warning(f"PowerShell WMP failed: {e}")

        if shutil.which("ffplay"):
            try:
                subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", str(p)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
                return
            except Exception as e:
                log.warning(f"ffplay failed: {e}")

    log.error(f"Could not play sound file: {path}")


def play_sound_file(path: str, system: str) -> None:
    """Dispatch sound playback to platform-specific function."""
    if system == "Linux":
        _play_sound_file_linux(path)
    elif system == "Darwin":
        _play_sound_file_mac(path)
    elif system == "Windows":
        _play_sound_file_windows(path)
    else:
        log.warning(f"Unsupported platform for sound playback: {system}")


def validate_sound_file(path: str) -> tuple[bool, str]:
    """
    Validate that a sound file exists and has a recognised audio extension.
    Returns (ok: bool, error_message: str).
    """
    SUPPORTED_EXTS = {
        ".wav",
        ".mp3",
        ".ogg",
        ".flac",
        ".aiff",
        ".aif",
        ".m4a",
        ".aac",
        ".oga",
    }
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
