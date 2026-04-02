"""
Core configuration, paths, and logging for kim.
"""

import copy
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
ONESHOT_FILE = KIM_DIR / "oneshots.json"
try:
    KIM_DIR.mkdir(exist_ok=True)
except OSError:
    pass

VERSION = "3.0.0"

# ── Logging ───────────────────────────────────────────────────────────────────
try:
    from logging.handlers import RotatingFileHandler

    _handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log = logging.getLogger("kim")
    log.addHandler(_handler)
    log.setLevel(logging.INFO)

    if platform.system() != "Windows":
        try:
            os.chmod(LOG_FILE, 0o600)
        except OSError:
            pass
except OSError as e:
    log = logging.getLogger("kim")
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.warning("Could not open log file %s: %s", LOG_FILE, e)


# ── Default config (written on first run) ────────────────────────────────────
DEFAULT_CONFIG = {
    "reminders": [
        {
            "name": "eye-break",
            "interval": "30m",
            "title": "[eye] Eye Break",
            "message": "Look 20 feet away for 20 seconds. Blink slowly.",
            "urgency": "critical",
            "enabled": True,
        },
        {
            "name": "water",
            "interval": "60m",
            "title": "[water] Drink Water",
            "message": "Stay hydrated -- drink a glass of water.",
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
            if platform.system() != "Windows":
                os.chmod(CONFIG, 0o600)
            log.info("Created default config: %s", CONFIG)
        except OSError as e:
            log.warning("Could not create config file: %s", e)
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG, encoding="utf-8") as f:
            config = json.load(f)
        config.setdefault("reminders", [])
        config.setdefault("sound", True)
        config.setdefault("sound_file", None)
        config.setdefault(
            "slack",
            {
                "enabled": False,
                "webhook_url": "",
                "bot_token": "",
                "channel": "#general",
            },
        )
        slack = config["slack"]
        slack.setdefault("enabled", False)
        slack.setdefault("webhook_url", "")
        slack.setdefault("bot_token", "")
        slack.setdefault("channel", "#general")
        for r in config.get("reminders", []):
            r.setdefault("enabled", True)
            r.setdefault("urgency", "normal")
        return config
    except json.JSONDecodeError as e:
        log.error("Invalid JSON in config file: %s", e)
        log.info("Using default config.")
        return copy.deepcopy(DEFAULT_CONFIG)
    except OSError as e:
        log.error("Error reading config file: %s", e)
        log.info("Using default config.")
        return copy.deepcopy(DEFAULT_CONFIG)


def parse_interval(value) -> float:
    """
    Convert interval to seconds.
    Supports:
      - int / float  → treated as minutes
      - "30m"        → 30 minutes
      - "2h"         → 2 hours
      - "1d"         → 1 day
      - "90s"        → 90 seconds
    Returns seconds as float (default 30 minutes for invalid values).
    Negative or zero intervals default to 30 minutes.
    """
    try:
        if isinstance(value, (int, float)):
            seconds = float(value) * 60
        elif isinstance(value, str):
            value = value.strip().lower()
            if not value:
                return 30 * 60
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
