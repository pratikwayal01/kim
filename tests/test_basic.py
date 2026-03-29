"""
Basic tests for kim package.
"""

import json
import os
import platform
import tempfile
import sys
import unittest
from pathlib import Path

# Add parent directory to path to import kim
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kim.core import load_config, parse_interval, DEFAULT_CONFIG, KIM_DIR, CONFIG
from kim.scheduler import KimScheduler
from kim.notifications import notify
from kim.sound import validate_sound_file, SOUND_FORMAT_NOTES
from kim.utils import (
    CHECK,
    CROSS,
    BULLET,
    EM_DASH,
    WARNING,
    CIRCLE_OPEN,
    CIRCLE_FILLED,
    MIDDOT,
    ARROW,
    HLINE,
)


class TestCore(unittest.TestCase):
    def test_parse_interval(self):
        # int minutes
        self.assertEqual(parse_interval(30), 1800)
        # string minutes
        self.assertEqual(parse_interval("30m"), 1800)
        # hours
        self.assertEqual(parse_interval("2h"), 7200)
        # days
        self.assertEqual(parse_interval("1d"), 86400)
        # seconds
        self.assertEqual(parse_interval("60s"), 60)
        # invalid defaults to 30 minutes
        self.assertEqual(parse_interval("invalid"), 1800)
        # negative interval defaults to 30 minutes
        self.assertEqual(parse_interval(-5), 1800)
        # zero interval defaults to 30 minutes
        self.assertEqual(parse_interval(0), 1800)
        # plain number string (minutes)
        self.assertEqual(parse_interval("45"), 2700)

    def test_load_config_creates_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Override CONFIG to a temp file
            import kim.core

            original_config = kim.core.CONFIG
            original_log = kim.core.LOG_FILE
            try:
                kim.core.CONFIG = Path(tmpdir) / "config.json"
                kim.core.LOG_FILE = Path(tmpdir) / "kim.log"
                config = load_config()
                self.assertIn("reminders", config)
                self.assertEqual(len(config["reminders"]), 2)
                self.assertTrue(kim.core.CONFIG.exists())
            finally:
                kim.core.CONFIG = original_config
                kim.core.LOG_FILE = original_log


class TestScheduler(unittest.TestCase):
    def test_scheduler_init(self):
        config = {
            "reminders": [{"name": "test", "interval_minutes": 1, "enabled": True}]
        }

        def dummy_notifier(reminder):
            pass

        scheduler = KimScheduler(config, dummy_notifier)
        self.assertEqual(len(scheduler._live), 1)
        scheduler.start()
        scheduler.stop()


class TestUtils(unittest.TestCase):
    def test_platform_symbols(self):
        # Ensure symbols are strings
        self.assertIsInstance(CHECK, str)
        self.assertIsInstance(CROSS, str)
        # On Windows, symbols should be ASCII
        if platform.system() == "Windows":
            self.assertEqual(CHECK, "OK")
            self.assertEqual(CROSS, "ERROR")
            self.assertEqual(BULLET, "-")
            self.assertEqual(EM_DASH, "--")
        else:
            self.assertEqual(CHECK, "✓")
            self.assertEqual(CROSS, "✗")
            self.assertEqual(BULLET, "•")
            self.assertEqual(EM_DASH, "—")

    def test_sound_format_notes(self):
        self.assertIn(platform.system(), SOUND_FORMAT_NOTES)


class TestSound(unittest.TestCase):
    def test_validate_sound_file(self):
        # Non-existent file
        ok, err = validate_sound_file("/nonexistent.wav")
        self.assertFalse(ok)
        self.assertIn("File not found", err)
        # Invalid extension
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            fname = f.name
        # file is closed now
        ok, err = validate_sound_file(fname)
        self.assertFalse(ok)
        self.assertIn("Unrecognised extension", err)
        os.unlink(fname)


if __name__ == "__main__":
    unittest.main()
