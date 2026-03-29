"""
Core configuration, paths, and logging for kim.
"""

import json
import logging
import os
import platform
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
KIM_DIR = Path.home() / ".kim"
CONFIG = KIM_DIR / "config.json"
LOG_FILE = KIM_DIR / "kim.log"
PID_FILE = KIM_DIR / "kim.pid"
KIM_DIR.mkdir(exist_ok=True)

VERSION = "3.0.0"

# ── Logging ───────────────────────────────────────────────────────────────────
try:
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        encoding="utf-8",
    )
    # Set secure permissions on log file (readable only by owner)
    if platform.system() != "Windows":
        try:
            os.chmod(LOG_FILE, 0o600)
        except OSError:
            pass
except OSError as e:
    # Fall back to stderr logging if file logging fails
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.warning(f"Could not open log file {LOG_FILE}: {e}")
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


def load_config() -> dict:
    """Load config from disk, creating default if missing."""
    if not CONFIG.exists():
        try:
            CONFIG.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
            # Set secure permissions on Unix (readable only by owner)
            if platform.system() != "Windows":
                os.chmod(CONFIG, 0o600)
        except OSError as e:
            print(f"Warning: Could not create config file: {e}")
        print(f"Created default config: {CONFIG}")
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG, encoding="utf-8") as f:
            config = json.load(f)
        # Ensure required fields exist
        if "reminders" not in config:
            config["reminders"] = []
        for r in config.get("reminders", []):
            r.setdefault("enabled", True)
            r.setdefault("urgency", "normal")
        return config
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in config file: {e}")
        print("Using default config.")
        return DEFAULT_CONFIG.copy()
    except OSError as e:
        print(f"Error reading config file: {e}")
        print("Using default config.")
        return DEFAULT_CONFIG.copy()


def parse_interval(value) -> float:
    """
    Convert interval_minutes to seconds.
    Supports:
      - int / float  → treated as minutes
      - "30m"        → 30 minutes
      - "2h"         → 2 hours
      - "1d"         → 1 day
    Returns seconds as float (default 30 minutes for invalid values).
    Negative or zero intervals default to 30 minutes.
    """
    try:
        if isinstance(value, (int, float)):
            seconds = float(value) * 60
        elif isinstance(value, str):
            value = value.strip().lower()
            if value.endswith("d"):
                seconds = float(value[:-1]) * 24 * 60 * 60
            elif value.endswith("h"):
                seconds = float(value[:-1]) * 60 * 60
            elif value.endswith("m"):
                seconds = float(value[:-1]) * 60
            elif value.endswith("s"):
                seconds = float(value[:-1])
            else:
                seconds = float(value) * 60
        else:
            return 30 * 60
        if seconds <= 0:
            return 30 * 60
        return seconds
    except (ValueError, TypeError):
        return 30 * 60
