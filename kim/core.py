"""
Core configuration, paths, and logging for kim.
"""

import copy
import datetime
import json
import logging
import os
import platform
import re
import time
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
KIM_DIR = Path.home() / ".kim"
CONFIG = KIM_DIR / "config.json"
LOG_FILE = KIM_DIR / "kim.log"
PID_FILE = KIM_DIR / "kim.pid"
ONESHOT_FILE = KIM_DIR / "oneshots.json"
RELOAD_FILE = KIM_DIR / "kim.reload"
try:
    KIM_DIR.mkdir(exist_ok=True)
except OSError:
    pass

VERSION = "4.5.0"

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
            _tmp = CONFIG.with_suffix(".tmp")
            _tmp.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
            if platform.system() != "Windows":
                os.chmod(_tmp, 0o600)
            _tmp.replace(CONFIG)
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


# ── Timezone helpers ──────────────────────────────────────────────────────────


def _get_utc_offset(tz_name: str) -> datetime.timezone:
    """
    Return a datetime.timezone for `tz_name`.

    Strategy (pure stdlib, no third-party deps):
      1. Try zoneinfo (Python 3.9+, or backport tzdata package).
      2. Fall back to reading /usr/share/zoneinfo/<tz_name> directly and
         computing the current UTC offset from the TZ POSIX string.
      3. On Windows, try the 'time' module TZ env approach.
      4. If everything fails, raise ValueError with a helpful message.
    """
    # --- 1. zoneinfo (best path) -------------------------------------------
    try:
        import zoneinfo  # Python 3.9+

        zi = zoneinfo.ZoneInfo(tz_name)
        now = datetime.datetime.now(tz=zi)
        return now.tzinfo  # type: ignore[return-value]
    except (ImportError, Exception):
        pass

    # --- 2. /usr/share/zoneinfo binary parse (UTC offset only) --------------
    try:
        tz_path = Path("/usr/share/zoneinfo") / tz_name.replace(" ", "_")
        if tz_path.exists():
            raw = tz_path.read_bytes()
            # TZif v2/v3: POSIX string is after final NUL in last section
            # Quick approach: grab the last bytes; scan for UTC offset pattern
            tail = raw[-256:].decode("ascii", errors="ignore")
            # POSIX TZ string like "IST-5:30" or "EST5" or "UTC-8"
            m = re.search(r"[A-Z]{2,6}[-+]?(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?", tail)
            if m:
                hours = int(m.group(1))
                mins = int(m.group(2) or 0)
                secs = int(m.group(3) or 0)
                # POSIX sign is inverted vs ISO: "IST-5:30" means UTC+5:30
                sign_char = tail[m.start() + len(m.group(0).split(m.group(1))[0]) - 1]
                sign = -1 if sign_char == "-" else 1
                offset = datetime.timedelta(
                    hours=hours * sign, minutes=mins * sign, seconds=secs * sign
                )
                return datetime.timezone(offset, name=tz_name)
    except Exception:
        pass

    # --- 3. Windows: TZ env var + time.timezone ----------------------------
    try:
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = tz_name
        time.tzset()  # only on Unix, but try
        offset = -time.timezone  # seconds east of UTC
        tz = datetime.timezone(datetime.timedelta(seconds=offset), name=tz_name)
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()
        return tz
    except Exception:
        pass

    raise ValueError(
        f"Unknown timezone: {tz_name!r}. "
        "Use an IANA name like 'Asia/Kolkata', 'America/New_York', 'Europe/London'. "
        "On Python 3.9+ you can install 'tzdata' for full IANA support: "
        "pip install tzdata"
    )


def parse_datetime(tokens: list, tz_name: str = None) -> float:
    """
    Parse a datetime specification from a list of string tokens and return
    a Unix timestamp (seconds since epoch).

    Two modes:
      RELATIVE — tokens start with something other than "at":
        Examples: ['in', '10m'], ['1h'], ['2h', '30m'], ['90s']
        Returns time.time() + parsed_seconds.

      ABSOLUTE — tokens start with "at":
        Examples: ['at', '14:30'], ['at', 'tomorrow', '10am'],
                  ['at', '2026-04-06', '09:00'], ['at', 'friday', '9am']
        Parses the rest as a wall-clock datetime in local (or --tz) timezone.
        Returns the Unix timestamp for that moment.

    Raises ValueError with a user-friendly message on bad input.
    """
    if not tokens:
        raise ValueError("No time specified.")

    raw = " ".join(tokens).strip()

    # ── Absolute mode ──────────────────────────────────────────────────────
    if raw.lower().startswith("at ") or raw.lower() == "at":
        dt_str = raw[3:].strip()
        if not dt_str:
            raise ValueError(
                "Nothing after 'at'. Example: 'at 14:30' or 'at tomorrow 9am'"
            )

        # Determine timezone
        if tz_name:
            tz = _get_utc_offset(tz_name)
        else:
            # Local timezone: use datetime.now().astimezone().tzinfo
            tz = datetime.datetime.now().astimezone().tzinfo

        now_local = datetime.datetime.now(tz=tz)
        today = now_local.date()

        # Normalise: lowercase, remove commas, collapse whitespace
        ds = dt_str.lower().strip().replace(",", "").replace("  ", " ")

        # Replace natural day words
        if ds.startswith("today"):
            ds = ds.replace("today", today.isoformat(), 1)
        elif ds.startswith("tomorrow"):
            ds = ds.replace(
                "tomorrow", (today + datetime.timedelta(days=1)).isoformat(), 1
            )
        else:
            # Named weekdays: monday, tuesday, ...
            _days = [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
            for i, day_name in enumerate(_days):
                if ds.startswith(day_name):
                    days_ahead = (i - today.weekday()) % 7 or 7  # next occurrence
                    target = today + datetime.timedelta(days=days_ahead)
                    ds = ds.replace(day_name, target.isoformat(), 1)
                    break

        ds = ds.strip()

        # Normalise time suffixes: "10am" → "10:00", "2:30pm" → "14:30"
        def _norm_ampm(s):
            s = re.sub(
                r"(\d{1,2})(?::(\d{2}))?([ap]m)",
                lambda m: (
                    "{:02d}:{:02d}".format(
                        (int(m.group(1)) % 12) + (12 if m.group(3) == "pm" else 0),
                        int(m.group(2) or 0),
                    )
                ),
                s,
            )
            return s

        ds = _norm_ampm(ds)

        # Try parsing with various formats
        fmts = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H",
            "%Y-%m-%d",
            "%H:%M:%S",
            "%H:%M",
            "%H",
        ]
        parsed = None
        for fmt in fmts:
            try:
                parsed = datetime.datetime.strptime(ds, fmt)
                break
            except ValueError:
                continue

        if parsed is None:
            raise ValueError(
                f"Could not parse datetime: {dt_str!r}.\n"
                "Examples: 'at 14:30', 'at tomorrow 10am', 'at friday 9am', "
                "'at 2026-04-06 09:00'"
            )

        # If only time was given (no date), use today; if it's already past, use tomorrow
        if parsed.year == 1900:
            candidate = parsed.replace(
                year=today.year, month=today.month, day=today.day
            )
            candidate = candidate.replace(tzinfo=tz)
            if candidate <= now_local:
                candidate = candidate + datetime.timedelta(days=1)
            parsed = candidate
        else:
            parsed = parsed.replace(tzinfo=tz)

        if parsed <= now_local:
            raise ValueError(
                f"Datetime {parsed.strftime('%Y-%m-%d %H:%M')} is in the past."
            )

        return parsed.timestamp()

    # ── Relative mode ──────────────────────────────────────────────────────
    relative = raw.lower().removeprefix("in").strip()
    total_seconds = 0.0
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(d|h|m|s)", relative):
        value, unit = float(match.group(1)), match.group(2)
        total_seconds += {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0}[unit] * value

    if total_seconds == 0:
        try:
            total_seconds = float(relative) * 60
        except (ValueError, TypeError):
            pass

    if total_seconds <= 0:
        raise ValueError(
            f"Could not parse time: {raw!r}.\n"
            "Relative: 'in 10m', '1h', '2h 30m', '90s'\n"
            "Absolute: 'at 14:30', 'at tomorrow 10am', 'at friday 9am'"
        )
    if total_seconds > 365 * 24 * 3600:
        raise ValueError("Duration too large (max 365 days).")

    return time.time() + total_seconds


def parse_at_time(at_str: str, tz_name: str = None) -> str:
    """
    Validate and normalise a --at HH:MM string.
    Returns the canonical "HH:MM" string or raises ValueError.
    """
    s = at_str.strip()
    # Accept HH:MM or H:MM
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if not m:
        raise ValueError(
            f"Invalid --at value: {s!r}. Use HH:MM format, e.g. --at 10:00"
        )
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time {s!r}: hour must be 0-23, minute 0-59.")
    return f"{hour:02d}:{minute:02d}"
