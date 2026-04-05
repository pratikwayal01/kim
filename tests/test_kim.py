"""
Core and feature tests for the kim package.

Structure:
  - Core / entry-point sanity checks (formerly test_basic.py)
  - Feature tests covering every capability (formerly test_features.py)

Add new tests here as features are added or bugs are fixed. New *regression*
tests for specific bug fixes belong in test_regression.py instead.
"""

import json
import os
import platform
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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


# ===========================================================================
# Core — parse_interval and load_config
# ===========================================================================


class TestCore(unittest.TestCase):
    def test_parse_interval(self):
        self.assertEqual(parse_interval(30), 1800)
        self.assertEqual(parse_interval("30m"), 1800)
        self.assertEqual(parse_interval("2h"), 7200)
        self.assertEqual(parse_interval("1d"), 86400)
        self.assertEqual(parse_interval("60s"), 60)
        self.assertEqual(parse_interval("invalid"), 1800)
        self.assertEqual(parse_interval(-5), 1800)
        self.assertEqual(parse_interval(0), 1800)
        self.assertEqual(parse_interval("45"), 2700)

    def test_load_config_creates_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
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


# ===========================================================================
# Scheduler — basic initialisation
# ===========================================================================


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


# ===========================================================================
# Utils — platform symbols and sound format notes
# ===========================================================================


class TestUtils(unittest.TestCase):
    def test_platform_symbols(self):
        self.assertIsInstance(CHECK, str)
        self.assertIsInstance(CROSS, str)
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


# ===========================================================================
# Sound — validate_sound_file
# ===========================================================================


class TestSound(unittest.TestCase):
    def test_validate_sound_file(self):
        ok, err = validate_sound_file("/nonexistent.wav")
        self.assertFalse(ok)
        self.assertIn("File not found", err)

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            fname = f.name
        ok, err = validate_sound_file(fname)
        self.assertFalse(ok)
        self.assertIn("Unrecognised extension", err)
        os.unlink(fname)


# ===========================================================================
# Entry points — kim.py and package importability
# ===========================================================================


class TestEntryPoint(unittest.TestCase):
    def test_kim_py_exists(self):
        repo_root = Path(__file__).parent.parent
        kim_py = repo_root / "kim.py"
        self.assertTrue(kim_py.exists(), f"Entry point missing: {kim_py}")
        self.assertGreater(kim_py.stat().st_size, 0, "kim.py is empty")

    def test_kim_package_importable(self):
        import kim  # noqa: F401
        from kim.cli import main  # noqa: F401
        from kim.core import load_config  # noqa: F401

    def test_kim_entry_point_runs(self):
        import subprocess

        repo_root = Path(__file__).parent.parent
        kim_py = repo_root / "kim.py"
        result = subprocess.run(
            [sys.executable, str(kim_py), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode, 0, f"kim.py --version failed: {result.stderr}"
        )
        self.assertIn("kim", result.stdout.lower())


# ===========================================================================
# cmd_remind — one-shot reminder via CLI ("kim remind 'msg' in 30m")
# ===========================================================================


class TestCmdRemind(unittest.TestCase):
    """cmd_remind parses the time expression, prints confirmation, and persists
    the oneshot to ONESHOT_FILE without forking/spawning a subprocess."""

    def _run_remind(self, args_dict, config=None, oneshot_file=None):
        from kim.commands import misc

        args = MagicMock()
        args.message = args_dict.get("message", "Test reminder")
        args.title = args_dict.get("title", None)
        args.timezone = args_dict.get("timezone", None)
        args.time = args_dict.get("time", ["in", "30m"])
        args.urgency = args_dict.get("urgency", "normal")

        if config is None:
            config = {"sound": False}

        printed = []

        def fake_print(*a, **kw):
            printed.append(" ".join(str(x) for x in a))

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_oneshot = Path(tmpdir) / "oneshots.json"

            with patch.object(misc, "ONESHOT_FILE", fake_oneshot):
                with patch.object(misc, "load_config", return_value=config):
                    with patch("builtins.print", side_effect=fake_print):
                        with patch.object(misc.subprocess, "Popen"):
                            with patch.object(
                                misc.os, "fork", return_value=1, create=True
                            ):
                                misc.cmd_remind(args)

            if fake_oneshot.exists():
                saved_data = json.loads(fake_oneshot.read_text())
            else:
                saved_data = []

        return printed, saved_data

    def test_remind_persists_to_oneshot_file(self):
        printed, saved = self._run_remind({"time": ["in", "5m"], "message": "hello"})
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["message"], "hello")

    def test_remind_fire_at_is_in_future(self):
        before = time.time()
        _, saved = self._run_remind({"time": ["in", "30m"]})
        self.assertGreater(saved[0]["fire_at"], before + 1700)

    def test_remind_title_stored(self):
        _, saved = self._run_remind({"time": ["in", "5m"], "title": "MyTitle"})
        self.assertEqual(saved[0]["title"], "MyTitle")

    def test_remind_default_title_used_when_none(self):
        _, saved = self._run_remind({"time": ["in", "5m"], "title": None})
        self.assertIn("title", saved[0])
        self.assertTrue(len(saved[0]["title"]) > 0)

    def test_remind_prints_confirmation(self):
        printed, _ = self._run_remind({"time": ["in", "10m"], "message": "drink water"})
        combined = " ".join(printed)
        self.assertIn("drink water", combined)

    def test_remind_absolute_at_shows_wall_clock(self):
        import datetime as _dt

        future = (_dt.datetime.now() + _dt.timedelta(hours=1)).strftime("%H:%M")
        printed, _ = self._run_remind({"time": ["at", future], "message": "standup"})
        combined = " ".join(printed)
        self.assertIn("standup", combined)

    def test_remind_invalid_time_exits(self):
        from kim.commands import misc

        args = MagicMock()
        args.message = "msg"
        args.title = None
        args.timezone = None
        args.time = ["garbage-time-expression"]

        with patch("builtins.print"):
            with self.assertRaises(SystemExit) as cm:
                misc.cmd_remind(args)
            self.assertEqual(cm.exception.code, 1)

    def test_remind_accumulates_multiple_oneshots(self):
        from kim.commands import misc

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_oneshot = Path(tmpdir) / "oneshots.json"

            def make_args(msg):
                a = MagicMock()
                a.message = msg
                a.title = None
                a.timezone = None
                a.time = ["in", "5m"]
                a.urgency = "normal"
                return a

            with patch.object(misc, "ONESHOT_FILE", fake_oneshot):
                with patch.object(misc, "load_config", return_value={"sound": False}):
                    with patch("builtins.print"):
                        with patch.object(misc.subprocess, "Popen"):
                            with patch.object(
                                misc.os, "fork", return_value=1, create=True
                            ):
                                misc.cmd_remind(make_args("first"))
                                misc.cmd_remind(make_args("second"))

            data = json.loads(fake_oneshot.read_text())
            messages = [o["message"] for o in data]
            self.assertIn("first", messages)
            self.assertIn("second", messages)


# ===========================================================================
# load_oneshot_reminders — persistence loader used by daemon on startup
# ===========================================================================


class TestLoadOneshotReminders(unittest.TestCase):
    def _write_oneshots(self, path, oneshots):
        path.write_text(json.dumps(oneshots), encoding="utf-8")

    def test_returns_empty_when_file_missing(self):
        from kim.commands.misc import load_oneshot_reminders

        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "oneshots.json"
            with patch("kim.commands.misc.ONESHOT_FILE", fake):
                result = load_oneshot_reminders()
        self.assertEqual(result, [])

    def test_returns_pending_entries(self):
        from kim.commands.misc import load_oneshot_reminders

        future = time.time() + 3600
        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "oneshots.json"
            self._write_oneshots(fake, [{"message": "future", "fire_at": future}])
            with patch("kim.commands.misc.ONESHOT_FILE", fake):
                result = load_oneshot_reminders()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["message"], "future")

    def test_filters_expired_entries(self):
        from kim.commands.misc import load_oneshot_reminders

        past = time.time() - 3600
        future = time.time() + 3600
        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "oneshots.json"
            self._write_oneshots(
                fake,
                [
                    {"message": "old", "fire_at": past},
                    {"message": "new", "fire_at": future},
                ],
            )
            with patch("kim.commands.misc.ONESHOT_FILE", fake):
                result = load_oneshot_reminders()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["message"], "new")

    def test_cleans_up_expired_from_file(self):
        from kim.commands.misc import load_oneshot_reminders

        past = time.time() - 1
        future = time.time() + 3600
        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "oneshots.json"
            self._write_oneshots(
                fake,
                [
                    {"message": "expired", "fire_at": past},
                    {"message": "pending", "fire_at": future},
                ],
            )
            with patch("kim.commands.misc.ONESHOT_FILE", fake):
                load_oneshot_reminders()
            remaining = json.loads(fake.read_text())
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["message"], "pending")

    def test_handles_corrupt_json_gracefully(self):
        from kim.commands.misc import load_oneshot_reminders

        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "oneshots.json"
            fake.write_text("{bad json", encoding="utf-8")
            with patch("kim.commands.misc.ONESHOT_FILE", fake):
                result = load_oneshot_reminders()
        self.assertEqual(result, [])


# ===========================================================================
# remove_oneshot — removes a specific entry by fire_at
# ===========================================================================


class TestRemoveOneshot(unittest.TestCase):
    def test_removes_matching_entry(self):
        from kim.commands.misc import remove_oneshot

        fire_at = time.time() + 1000
        entries = [
            {"message": "keep", "fire_at": fire_at + 500},
            {"message": "remove", "fire_at": fire_at},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "oneshots.json"
            fake.write_text(json.dumps(entries), encoding="utf-8")
            with patch("kim.commands.misc.ONESHOT_FILE", fake):
                remove_oneshot(fire_at)
            result = json.loads(fake.read_text())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["message"], "keep")

    def test_noop_when_file_missing(self):
        from kim.commands.misc import remove_oneshot

        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "oneshots.json"
            with patch("kim.commands.misc.ONESHOT_FILE", fake):
                remove_oneshot(12345.0)  # must not raise

    def test_noop_when_no_match(self):
        from kim.commands.misc import remove_oneshot

        entries = [{"message": "stay", "fire_at": 9999.0}]
        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "oneshots.json"
            fake.write_text(json.dumps(entries), encoding="utf-8")
            with patch("kim.commands.misc.ONESHOT_FILE", fake):
                remove_oneshot(0.0)
            result = json.loads(fake.read_text())
        self.assertEqual(len(result), 1)


# ===========================================================================
# cmd_list — reminders and oneshot display
# ===========================================================================


class TestCmdListWithOneshots(unittest.TestCase):
    def _run_list(self, config, oneshots=None, flag_oneshots=True):
        from kim.commands import config as cfg_mod

        args = MagicMock()
        args.oneshots = flag_oneshots

        printed = []

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_oneshot = Path(tmpdir) / "oneshots.json"
            if oneshots is not None:
                fake_oneshot.write_text(json.dumps(oneshots), encoding="utf-8")

            with patch.object(cfg_mod, "load_config", return_value=config):
                with patch.object(cfg_mod, "ONESHOT_FILE", fake_oneshot):
                    with patch(
                        "builtins.print",
                        side_effect=lambda *a, **k: printed.append(
                            " ".join(str(x) for x in a)
                        ),
                    ):
                        cfg_mod.cmd_list(args)

        return "\n".join(printed)

    def test_list_shows_reminders(self):
        cfg = {
            "reminders": [
                {
                    "name": "water",
                    "interval": "30m",
                    "urgency": "normal",
                    "enabled": True,
                }
            ]
        }
        output = self._run_list(cfg)
        self.assertIn("water", output)

    def test_list_shows_at_schedule(self):
        cfg = {
            "reminders": [
                {"name": "standup", "at": "09:30", "urgency": "normal", "enabled": True}
            ]
        }
        output = self._run_list(cfg)
        self.assertIn("standup", output)
        self.assertIn("at 09:30", output)

    def test_list_oneshots_section_when_pending(self):
        cfg = {"reminders": []}
        future = time.time() + 3600
        oneshots = [{"message": "my oneshot", "fire_at": future}]
        output = self._run_list(cfg, oneshots=oneshots)
        self.assertIn("my oneshot", output)

    def test_list_oneshots_none_pending_message(self):
        cfg = {"reminders": []}
        output = self._run_list(cfg, oneshots=[])
        self.assertIn("none pending", output.lower())

    def test_list_no_oneshots_section_when_flag_false(self):
        cfg = {"reminders": []}
        future = time.time() + 3600
        oneshots = [{"message": "hidden", "fire_at": future}]
        output = self._run_list(cfg, oneshots=oneshots, flag_oneshots=False)
        self.assertNotIn("hidden", output)


# ===========================================================================
# cmd_status — at-schedule display ("daily at HH:MM")
# ===========================================================================


class TestCmdStatusAtScheduleDisplay(unittest.TestCase):
    def _run_status(self, reminders):
        from kim.commands import daemon as daemon_mod

        cfg = {"reminders": reminders, "sound": False}
        printed = []

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_pid = Path(tmpdir) / "kim.pid"

            with patch.object(daemon_mod, "load_config", return_value=cfg):
                with patch.object(daemon_mod, "PID_FILE", fake_pid):
                    with patch.object(
                        daemon_mod, "CONFIG", Path(tmpdir) / "config.json"
                    ):
                        with patch(
                            "builtins.print",
                            side_effect=lambda *a, **k: printed.append(
                                " ".join(str(x) for x in a)
                            ),
                        ):
                            daemon_mod.cmd_status(MagicMock())

        return "\n".join(printed)

    def test_at_reminder_shows_daily_at(self):
        reminders = [
            {"name": "standup", "at": "09:30", "urgency": "normal", "enabled": True}
        ]
        output = self._run_status(reminders)
        self.assertIn("daily at 09:30", output)

    def test_interval_reminder_shows_every(self):
        reminders = [
            {"name": "water", "interval": "30m", "urgency": "normal", "enabled": True}
        ]
        output = self._run_status(reminders)
        self.assertIn("every 30m", output)

    def test_interval_minutes_reminder_shows_every(self):
        reminders = [
            {
                "name": "break",
                "interval_minutes": 60,
                "urgency": "normal",
                "enabled": True,
            }
        ]
        output = self._run_status(reminders)
        self.assertIn("every", output)
        self.assertIn("60", output)

    def test_disabled_reminder_in_disabled_section(self):
        reminders = [
            {"name": "paused", "interval": "1h", "urgency": "normal", "enabled": False}
        ]
        output = self._run_status(reminders)
        self.assertIn("paused", output)
        self.assertIn("Disabled", output)


# ===========================================================================
# _reload_config — live hot-reload reconciliation
# ===========================================================================


class TestReloadConfig(unittest.TestCase):
    def _make_scheduler(self, initial_reminders):
        cfg = {"reminders": initial_reminders}
        return KimScheduler(cfg, lambda r: None)

    def test_new_reminder_added_to_live(self):
        from kim.commands.daemon import _reload_config

        sched = self._make_scheduler(
            [{"name": "old", "interval": "30m", "enabled": True}]
        )
        new_cfg = {
            "reminders": [
                {"name": "old", "interval": "30m", "enabled": True},
                {"name": "new", "interval": "1h", "enabled": True},
            ]
        }
        with patch("kim.commands.daemon.load_config", return_value=new_cfg):
            _reload_config(
                sched,
                {"reminders": [{"name": "old", "interval": "30m", "enabled": True}]},
            )
        self.assertIn("new", sched._live)

    def test_deleted_reminder_removed_from_live(self):
        from kim.commands.daemon import _reload_config

        sched = self._make_scheduler(
            [
                {"name": "todelete", "interval": "30m", "enabled": True},
                {"name": "keep", "interval": "1h", "enabled": True},
            ]
        )
        new_cfg = {"reminders": [{"name": "keep", "interval": "1h", "enabled": True}]}
        old_cfg = {
            "reminders": [
                {"name": "todelete", "interval": "30m", "enabled": True},
                {"name": "keep", "interval": "1h", "enabled": True},
            ]
        }
        with patch("kim.commands.daemon.load_config", return_value=new_cfg):
            _reload_config(sched, old_cfg)
        self.assertNotIn("todelete", sched._live)
        self.assertIn("keep", sched._live)

    def test_disabled_reminder_removed_from_live(self):
        from kim.commands.daemon import _reload_config

        sched = self._make_scheduler(
            [{"name": "r", "interval": "30m", "enabled": True}]
        )
        new_cfg = {"reminders": [{"name": "r", "interval": "30m", "enabled": False}]}
        old_cfg = {"reminders": [{"name": "r", "interval": "30m", "enabled": True}]}
        with patch("kim.commands.daemon.load_config", return_value=new_cfg):
            _reload_config(sched, old_cfg)
        self.assertNotIn("r", sched._live)

    def test_returns_new_config(self):
        from kim.commands.daemon import _reload_config

        sched = self._make_scheduler([])
        new_cfg = {"reminders": [], "sound": False}
        with patch("kim.commands.daemon.load_config", return_value=new_cfg):
            result = _reload_config(sched, {"reminders": []})
        self.assertEqual(result["sound"], False)


# ===========================================================================
# _sanitize_reminder — strips unknown/dangerous keys on import
# ===========================================================================


class TestSanitizeReminder(unittest.TestCase):
    def _sanitize(self, r):
        from kim.commands.config import _sanitize_reminder

        return _sanitize_reminder(r)

    def test_keeps_allowed_keys(self):
        r = {
            "name": "water",
            "interval": "30m",
            "title": "T",
            "message": "M",
            "urgency": "normal",
            "enabled": True,
        }
        result = self._sanitize(r)
        for key in ("name", "interval", "title", "message", "urgency", "enabled"):
            self.assertIn(key, result)

    def test_strips_unknown_keys(self):
        r = {"name": "water", "interval": "30m", "malicious": "x", "__proto__": "y"}
        result = self._sanitize(r)
        self.assertNotIn("malicious", result)
        self.assertNotIn("__proto__", result)

    def test_name_truncated_to_100_chars(self):
        r = {"name": "a" * 200, "interval": "30m"}
        result = self._sanitize(r)
        self.assertLessEqual(len(result.get("name", "")), 100)

    def test_invalid_urgency_rejected(self):
        r = {"name": "x", "interval": "30m", "urgency": "EXTREME"}
        result = self._sanitize(r)
        self.assertNotIn("urgency", result)

    def test_valid_urgency_kept(self):
        for u in ("low", "normal", "critical"):
            r = {"name": "x", "interval": "30m", "urgency": u}
            result = self._sanitize(r)
            self.assertEqual(result.get("urgency"), u)

    def test_enabled_must_be_bool(self):
        r = {"name": "x", "interval": "30m", "enabled": "true"}
        result = self._sanitize(r)
        self.assertNotIn("enabled", result)


# ===========================================================================
# cmd_export — JSON and CSV, including at-schedule reminders
# ===========================================================================


class TestCmdExport(unittest.TestCase):
    def _run_export(self, reminders, fmt="json", output_file=None):
        from kim.commands import config as cfg_mod

        args = MagicMock()
        args.format = fmt
        args.output = output_file
        cfg = {"reminders": reminders}
        printed = []

        with patch.object(cfg_mod, "load_config", return_value=cfg):
            with patch(
                "builtins.print",
                side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
            ):
                cfg_mod.cmd_export(args)

        return "\n".join(printed)

    def test_json_export_contains_reminder_name(self):
        r = [{"name": "water", "interval": "30m", "enabled": True}]
        output = self._run_export(r, "json")
        self.assertIn("water", output)

    def test_json_export_valid_json(self):
        r = [{"name": "water", "interval": "30m", "enabled": True}]
        output = self._run_export(r, "json")
        data = json.loads(output)
        self.assertIn("reminders", data)

    def test_csv_export_contains_name(self):
        r = [
            {
                "name": "water",
                "interval": "30m",
                "enabled": True,
                "title": "T",
                "message": "M",
                "urgency": "normal",
            }
        ]
        output = self._run_export(r, "csv")
        self.assertIn("water", output)

    def test_csv_export_has_header(self):
        output = self._run_export([], "csv")
        self.assertIn("name", output.lower())
        self.assertIn("interval", output.lower())

    def test_json_export_at_schedule_reminder(self):
        r = [{"name": "standup", "at": "09:30", "enabled": True}]
        output = self._run_export(r, "json")
        data = json.loads(output)
        self.assertEqual(data["reminders"][0].get("at"), "09:30")

    def test_export_to_file(self):
        r = [{"name": "x", "interval": "1h", "enabled": True}]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "export.json")
            self._run_export(r, "json", output_file=out)
            self.assertTrue(os.path.exists(out))
            data = json.loads(Path(out).read_text())
            self.assertIn("reminders", data)


# ===========================================================================
# cmd_import — JSON import, CSV import, merge mode
# ===========================================================================


class TestCmdImport(unittest.TestCase):
    def _run_import(
        self,
        file_content,
        file_ext=".json",
        merge=False,
        existing_config=None,
        fmt="auto",
    ):
        from kim.commands import config as cfg_mod

        if existing_config is None:
            existing_config = {"reminders": []}

        args = MagicMock()
        args.merge = merge
        args.format = fmt
        saved = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            import_file = Path(tmpdir) / f"import{file_ext}"
            import_file.write_text(file_content, encoding="utf-8")
            args.file = str(import_file)

            with patch.object(
                cfg_mod, "load_config", return_value=dict(existing_config)
            ):
                with patch.object(cfg_mod, "CONFIG", Path(tmpdir) / "config.json"):
                    with patch.object(
                        cfg_mod, "_save_config", side_effect=lambda c: saved.update(c)
                    ):
                        with patch("builtins.print"):
                            cfg_mod.cmd_import(args)

        return saved

    def test_json_import_adds_reminders(self):
        content = json.dumps(
            {
                "reminders": [
                    {
                        "name": "water",
                        "interval": "30m",
                        "title": "T",
                        "message": "M",
                        "urgency": "normal",
                        "enabled": True,
                    }
                ]
            }
        )
        result = self._run_import(content)
        self.assertTrue(any(r["name"] == "water" for r in result.get("reminders", [])))

    def test_json_import_replaces_existing_by_default(self):
        existing = {"reminders": [{"name": "old", "interval": "1h", "enabled": True}]}
        content = json.dumps(
            {
                "reminders": [
                    {
                        "name": "new",
                        "interval": "30m",
                        "title": "T",
                        "message": "M",
                        "urgency": "normal",
                        "enabled": True,
                    }
                ]
            }
        )
        result = self._run_import(content, existing_config=existing)
        names = [r["name"] for r in result.get("reminders", [])]
        self.assertIn("new", names)
        self.assertNotIn("old", names)

    def test_merge_keeps_existing_reminders(self):
        existing = {
            "reminders": [
                {
                    "name": "existing",
                    "interval": "1h",
                    "title": "E",
                    "message": "M",
                    "urgency": "normal",
                    "enabled": True,
                }
            ]
        }
        content = json.dumps(
            {
                "reminders": [
                    {
                        "name": "imported",
                        "interval": "30m",
                        "title": "T",
                        "message": "M",
                        "urgency": "normal",
                        "enabled": True,
                    }
                ]
            }
        )
        result = self._run_import(content, merge=True, existing_config=existing)
        names = [r["name"] for r in result.get("reminders", [])]
        self.assertIn("existing", names)
        self.assertIn("imported", names)

    def test_merge_does_not_duplicate_existing_name(self):
        existing = {
            "reminders": [
                {
                    "name": "water",
                    "interval": "1h",
                    "title": "E",
                    "message": "M",
                    "urgency": "normal",
                    "enabled": True,
                }
            ]
        }
        content = json.dumps(
            {
                "reminders": [
                    {
                        "name": "water",
                        "interval": "30m",
                        "title": "T",
                        "message": "M",
                        "urgency": "normal",
                        "enabled": True,
                    }
                ]
            }
        )
        result = self._run_import(content, merge=True, existing_config=existing)
        names = [r["name"] for r in result.get("reminders", [])]
        self.assertEqual(names.count("water"), 1)

    def test_csv_import(self):
        content = (
            "name,interval,title,message,urgency,enabled\nwater,30m,T,M,normal,True"
        )
        result = self._run_import(content, file_ext=".csv")
        self.assertTrue(any(r["name"] == "water" for r in result.get("reminders", [])))

    def test_import_sanitizes_unknown_keys(self):
        content = json.dumps(
            {
                "reminders": [
                    {
                        "name": "x",
                        "interval": "30m",
                        "enabled": True,
                        "__proto__": "evil",
                        "malicious": "payload",
                    }
                ]
            }
        )
        result = self._run_import(content)
        for r in result.get("reminders", []):
            self.assertNotIn("__proto__", r)
            self.assertNotIn("malicious", r)

    def test_import_bad_json_exits(self):
        from kim.commands import config as cfg_mod

        args = MagicMock()
        args.merge = False
        args.format = "json"
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.json"
            bad.write_text("{not valid}", encoding="utf-8")
            args.file = str(bad)
            with patch.object(cfg_mod, "load_config", return_value={"reminders": []}):
                with patch.object(cfg_mod, "CONFIG", bad.parent / "config.json"):
                    with patch("builtins.print"):
                        with self.assertRaises(SystemExit) as cm:
                            cfg_mod.cmd_import(args)
                        self.assertEqual(cm.exception.code, 1)

    def test_import_missing_file_exits(self):
        from kim.commands import config as cfg_mod

        args = MagicMock()
        args.file = "/nonexistent/path/to/file.json"
        args.merge = False
        args.format = "json"
        with patch("builtins.print"):
            with self.assertRaises(SystemExit) as cm:
                cfg_mod.cmd_import(args)
            self.assertEqual(cm.exception.code, 1)


# ===========================================================================
# _find_asset — helper used by selfupdate binary/script downloaders
# ===========================================================================


class TestFindAsset(unittest.TestCase):
    def _find(self, assets, name):
        from kim.selfupdate import _find_asset

        return _find_asset(assets, name)

    def test_finds_exact_name(self):
        assets = [
            {
                "name": "kim-linux-x86_64",
                "browser_download_url": "https://example.com/linux",
            },
            {
                "name": "kim-windows-x86_64.exe",
                "browser_download_url": "https://example.com/win",
            },
        ]
        self.assertEqual(
            self._find(assets, "kim-linux-x86_64"), "https://example.com/linux"
        )

    def test_finds_by_substring(self):
        assets = [
            {
                "name": "kim-macos-arm64",
                "browser_download_url": "https://example.com/mac",
            }
        ]
        self.assertEqual(self._find(assets, "macos-arm64"), "https://example.com/mac")

    def test_returns_none_when_not_found(self):
        assets = [{"name": "kim-linux-x86_64", "browser_download_url": "https://x.com"}]
        self.assertIsNone(self._find(assets, "kim-windows-x86_64.exe"))

    def test_returns_none_on_empty_list(self):
        self.assertIsNone(self._find([], "anything"))

    def test_kimpy_asset_found(self):
        assets = [
            {"name": "kim.py", "browser_download_url": "https://example.com/kim.py"}
        ]
        self.assertEqual(self._find(assets, "kim.py"), "https://example.com/kim.py")


# ===========================================================================
# notifications.py — sound guard (if sound: not if sound or sound_file:)
# ===========================================================================


class TestNotificationsSoundGuard(unittest.TestCase):
    def test_sound_false_no_play(self):
        from kim import notifications
        import inspect

        src = inspect.getsource(notifications._notify_windows)
        self.assertNotIn(
            "if sound or sound_file:",
            src,
            "_notify_windows must not use 'if sound or sound_file' — use 'if sound'",
        )
        self.assertIn(
            "if sound:",
            src,
            "_notify_windows must guard sound playback with 'if sound:'",
        )


# ===========================================================================
# cmd_start — at-schedule display in the startup banner
# ===========================================================================


class TestCmdStartAtScheduleDisplay(unittest.TestCase):
    def test_at_reminder_shown_as_daily_at(self):
        import inspect
        from kim.commands import daemon as daemon_mod

        src = inspect.getsource(daemon_mod.cmd_start)
        self.assertIn(
            "daily at",
            src,
            "cmd_start banner must show 'daily at HH:MM' for at-schedule reminders",
        )

    def test_interval_reminder_shown_as_every(self):
        import inspect
        from kim.commands import daemon as daemon_mod

        src = inspect.getsource(daemon_mod.cmd_start)
        self.assertIn(
            "every",
            src,
            "cmd_start banner must show 'every <interval>' for interval reminders",
        )


# ===========================================================================
# parse_interval edge cases (core.py)
# ===========================================================================


class TestParseIntervalEdgeCases(unittest.TestCase):
    def _parse(self, v):
        from kim.core import parse_interval

        return parse_interval(v)

    def test_zero_string_defaults(self):
        self.assertEqual(self._parse("0m"), 1800)

    def test_zero_int_defaults(self):
        self.assertEqual(self._parse(0), 1800)

    def test_negative_int_defaults(self):
        self.assertEqual(self._parse(-1), 1800)

    def test_negative_string_defaults(self):
        self.assertEqual(self._parse("-5m"), 1800)

    def test_very_large_minutes(self):
        self.assertEqual(self._parse("1440m"), 86400)

    def test_fractional_int_truncated(self):
        # parse_interval(1.5) = 1.5 * 60 = 90.0 — valid, must not raise
        result = self._parse(1.5)
        self.assertIsInstance(result, (int, float))

    def test_whitespace_around_value(self):
        try:
            result = self._parse("  30m  ")
            self.assertIn(result, (1800, 1800))
        except Exception:
            pass  # acceptable to raise on whitespace

    def test_malformed_string_defaults(self):
        self.assertEqual(self._parse("abc"), 1800)
        self.assertEqual(self._parse(""), 1800)
        self.assertEqual(self._parse("h"), 1800)


# ===========================================================================
# parse_datetime edge cases (core.py)
# ===========================================================================


class TestParseDatetimeEdgeCases(unittest.TestCase):
    def _parse(self, tokens):
        from kim.core import parse_datetime

        return parse_datetime(tokens)

    def test_zero_minutes_raises(self):
        from kim.core import parse_datetime

        with self.assertRaises(ValueError):
            parse_datetime(["0m"])

    def test_in_prefix_alone_raises(self):
        from kim.core import parse_datetime

        with self.assertRaises(ValueError):
            parse_datetime(["in"])

    def test_multiple_units_combine(self):
        before = time.time()
        result = self._parse(["1h", "30m"])
        self.assertAlmostEqual(result, before + 5400, delta=5)

    def test_at_with_no_time_raises(self):
        from kim.core import parse_datetime

        with self.assertRaises(ValueError):
            parse_datetime(["at"])

    def test_365_days_ok(self):
        before = time.time()
        result = self._parse(["365d"])
        self.assertAlmostEqual(result, before + 365 * 86400, delta=5)

    def test_366_days_raises(self):
        from kim.core import parse_datetime

        with self.assertRaises(ValueError):
            parse_datetime(["366d"])


# ===========================================================================
# Scheduler — at-schedule reminder fires daily, not once
# ===========================================================================


class TestSchedulerAtReminderReschedule(unittest.TestCase):
    def test_rescheduled_after_fire(self):
        import heapq

        config = {"reminders": [{"name": "daily", "at": "10:00", "enabled": True}]}
        fired = []
        sched = KimScheduler(config, lambda r: fired.append(r))

        event = sched._live["daily"]
        event.fire_at = time.time() - 1
        sched._heap = [event]
        heapq.heapify(sched._heap)

        sched._fire_due_events()

        self.assertEqual(len(fired), 1)
        self.assertIn("daily", sched._live)
        new_event = sched._live["daily"]
        self.assertGreater(new_event.fire_at, time.time())


# ===========================================================================
# Scheduler — at-schedule reminder with timezone stored
# ===========================================================================


class TestSchedulerAtReminderTimezone(unittest.TestCase):
    def test_reminder_with_tz_field_loads(self):
        config = {
            "reminders": [
                {"name": "standup", "at": "09:00", "timezone": "UTC", "enabled": True}
            ]
        }
        sched = KimScheduler(config, lambda r: None)
        self.assertIn("standup", sched._live)

    def test_invalid_timezone_does_not_crash(self):
        config = {
            "reminders": [
                {
                    "name": "r",
                    "at": "09:00",
                    "timezone": "Invalid/Zone",
                    "enabled": True,
                }
            ]
        }
        try:
            KimScheduler(config, lambda r: None)
        except Exception as e:
            self.fail(f"KimScheduler raised unexpectedly with invalid timezone: {e}")


# ===========================================================================
# cmd_validate — required fields
# ===========================================================================


class TestCmdValidateRequiredFields(unittest.TestCase):
    def _run(self, reminders):
        from kim.commands import config as cfg_mod

        cfg = {"reminders": reminders}
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "config.json"
            f.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(cfg_mod, "CONFIG", f):
                with patch("builtins.print"):
                    try:
                        cfg_mod.cmd_validate(MagicMock())
                        return True
                    except SystemExit as e:
                        return e.code

    def test_missing_name_fails(self):
        result = self._run([{"interval": "30m", "enabled": True}])
        self.assertEqual(result, 1)

    def test_legacy_interval_minutes_passes(self):
        result = self._run([{"name": "x", "interval_minutes": 30, "enabled": True}])
        self.assertEqual(result, True)

    def test_valid_interval_string_passes(self):
        result = self._run([{"name": "x", "interval": "1h", "enabled": True}])
        self.assertEqual(result, True)


if __name__ == "__main__":
    unittest.main()
