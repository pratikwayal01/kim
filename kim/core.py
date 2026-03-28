"""
Core configuration, paths, and logging for kim.
"""

import json
import logging
import os
from pathlib import Path

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


def load_config() -> dict:
    """Load config from disk, creating default if missing."""
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        print(f"Created default config: {CONFIG}")
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def parse_interval(value) -> float:
    """
    Convert interval_minutes to seconds.
    Supports:
      - int / float  → treated as minutes
      - "30m"        → 30 minutes
      - "2h"         → 2 hours
      - "1d"         → 1 day
    Returns seconds as float.
    """
    if isinstance(value, (int, float)):
        return float(value) * 60
    if isinstance(value, str):
        value = value.strip().lower()
        if value.endswith("d"):
            return float(value[:-1]) * 24 * 60 * 60
        elif value.endswith("h"):
            return float(value[:-1]) * 60 * 60
        elif value.endswith("m"):
            return float(value[:-1]) * 60
        elif value.endswith("s"):
            return float(value[:-1])
        try:
            return float(value) * 60
        except ValueError:
            pass
    return 30 * 60
