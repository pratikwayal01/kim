"""
Tests for kim/ui — the optional PySide6 graphical interface.

All tests that require PySide6 are guarded with @skipUnless so the suite
remains fully green on machines where PySide6 is not installed.

Tests that do NOT require PySide6 (e.g. the CLI guard behaviour) run
unconditionally.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kim.ui import PYSIDE6_AVAILABLE

# ---------------------------------------------------------------------------
# CLI guard — runs regardless of PySide6 availability
# ---------------------------------------------------------------------------


class TestCmdUiMissingPyside6(unittest.TestCase):
    """
    cmd_ui() must exit with a helpful message when PySide6 is not installed.

    Bug this catches: if cmd_ui() imported PySide6 unconditionally, running
    `kim ui` on a machine without PySide6 would produce an unhelpful
    ImportError traceback instead of a user-friendly message.
    """

    def test_exits_with_message_when_pyside6_missing(self):
        """require_pyside6() prints instructions and raises SystemExit(1)."""
        with patch("kim.ui.PYSIDE6_AVAILABLE", False):
            from kim.ui import require_pyside6

            with self.assertRaises(SystemExit) as ctx:
                require_pyside6()
            self.assertEqual(ctx.exception.code, 1)

    def test_cmd_ui_calls_require_pyside6(self):
        """cmd_ui() delegates the PySide6 check to require_pyside6()."""
        from kim.cli import cmd_ui

        with patch("kim.ui.require_pyside6", side_effect=SystemExit(1)) as mock_req:
            with self.assertRaises(SystemExit):
                cmd_ui(None)
            mock_req.assert_called_once()

    def test_ui_in_known_commands(self):
        """'ui' must be in the case-normalisation set so 'UI' also works."""
        import re
        import kim.cli as cli_mod
        import inspect

        src = inspect.getsource(cli_mod.main)
        # known_commands set literal contains "ui"
        self.assertIn('"ui"', src)

    def test_ui_in_dispatch_table(self):
        """'ui' must be a key in the cmds dispatch dict inside main()."""
        import kim.cli as cli_mod
        import inspect

        src = inspect.getsource(cli_mod.main)
        self.assertIn('"ui": cmd_ui', src)

    def test_ui_in_epilog(self):
        """'ui' must appear in the help epilog so users can discover it."""
        import re
        import kim.cli as cli_mod
        import inspect

        src = inspect.getsource(cli_mod.main)
        self.assertIn("ui", src)


# ---------------------------------------------------------------------------
# Tests that require PySide6
# ---------------------------------------------------------------------------


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 not installed")
class TestConfigWatcherForceRefresh(unittest.TestCase):
    """
    ConfigWatcher.force_refresh() resets the cached mtime so the very next
    poll emits config_changed even when the file has not changed on disk.

    Bug this catches: after the GUI writes a config change itself, the mtime
    seen by the next poll would equal the cached mtime, so the signal would
    never fire and the UI would not refresh.
    """

    def test_force_refresh_resets_mtime(self):
        from kim.ui.config_watcher import ConfigWatcher

        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            pid_path = Path(td) / "kim.pid"
            cfg_path.write_text(json.dumps({"reminders": []}), encoding="utf-8")

            watcher = ConfigWatcher(cfg_path, pid_path)
            # Simulate a previous successful poll: cache current mtime
            watcher._config_mtime = cfg_path.stat().st_mtime

            # After force_refresh the mtime must be 0.0
            watcher.force_refresh()
            self.assertEqual(watcher._config_mtime, 0.0)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 not installed")
class TestConfigWatcherEmitsConfigChanged(unittest.TestCase):
    """
    ConfigWatcher emits config_changed when config.json mtime changes.

    Bug this catches: if _check_config() compared mtimes incorrectly (e.g.
    using equality on floats that could differ by sub-microsecond rounding),
    legitimate file updates would be silently ignored.
    """

    def test_emits_when_mtime_changes(self):
        from PySide6.QtWidgets import QApplication
        from kim.ui.config_watcher import ConfigWatcher

        app = QApplication.instance() or QApplication(sys.argv[:1])

        received = []

        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            pid_path = Path(td) / "kim.pid"
            cfg = {"reminders": [{"name": "test", "interval": "30m"}]}
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            watcher = ConfigWatcher(cfg_path, pid_path)
            watcher.config_changed.connect(lambda d: received.append(d))

            # Force mtime=0 so the first check always fires
            watcher._config_mtime = 0.0
            watcher._check_config()

            self.assertEqual(len(received), 1)
            self.assertIn("reminders", received[0])


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 not installed")
class TestConfigWatcherEmitsDaemonStatus(unittest.TestCase):
    """
    ConfigWatcher emits daemon_status_changed when the PID file
    appears or disappears.

    Bug this catches: if _check_daemon() compared the running bool to itself
    without updating the cache, every poll would emit the signal spuriously.
    """

    def test_emits_on_pid_file_appear(self):
        from PySide6.QtWidgets import QApplication
        from kim.ui.config_watcher import ConfigWatcher

        app = QApplication.instance() or QApplication(sys.argv[:1])

        events = []

        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            pid_path = Path(td) / "kim.pid"
            cfg_path.write_text(json.dumps({"reminders": []}), encoding="utf-8")

            watcher = ConfigWatcher(cfg_path, pid_path)
            watcher.daemon_status_changed.connect(lambda b: events.append(b))

            # Initially no pid file — state starts as False; no change yet
            watcher._check_daemon()
            self.assertEqual(events, [])  # no transition from False→False

            # Create PID file → should emit True
            pid_path.write_text("1234", encoding="utf-8")
            watcher._check_daemon()
            self.assertEqual(events, [True])

            # Remove PID file → should emit False
            pid_path.unlink()
            watcher._check_daemon()
            self.assertEqual(events, [True, False])

    def test_no_spurious_emit_when_state_unchanged(self):
        from PySide6.QtWidgets import QApplication
        from kim.ui.config_watcher import ConfigWatcher

        app = QApplication.instance() or QApplication(sys.argv[:1])

        events = []

        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            pid_path = Path(td) / "kim.pid"
            cfg_path.write_text(json.dumps({"reminders": []}), encoding="utf-8")

            watcher = ConfigWatcher(cfg_path, pid_path)
            watcher.daemon_status_changed.connect(lambda b: events.append(b))

            # Poll twice with no state change — no emissions expected
            watcher._check_daemon()
            watcher._check_daemon()
            self.assertEqual(events, [])


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 not installed")
class TestReminderDialogIntervalValidation(unittest.TestCase):
    """
    ReminderDialog validates interval strings via KimScheduler._parse_interval.

    Bug this catches: without validation, a user could save an invalid
    interval like "foo" which would later cause the daemon to silently skip
    the reminder on startup.
    """

    def _make_dialog(self, reminder=None, existing_names=None):
        from PySide6.QtWidgets import QApplication
        from kim.ui.reminder_dialog import ReminderDialog

        app = QApplication.instance() or QApplication(sys.argv[:1])
        return ReminderDialog(reminder=reminder, existing_names=existing_names or set())

    def test_accepts_valid_interval(self):
        from kim.scheduler import KimScheduler

        for iv in ("30m", "1h", "1d", "45"):
            result = KimScheduler._parse_interval({"interval": iv})
            self.assertIsNotNone(result, f"Expected valid interval: {iv}")

    def test_rejects_invalid_interval(self):
        from kim.scheduler import KimScheduler

        for iv in ("foo", "abc", "", "-1m", "0m", "90s"):
            result = KimScheduler._parse_interval({"interval": iv})
            self.assertIsNone(result, f"Expected invalid interval: {iv}")


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 not installed")
class TestReminderDialogDuplicateName(unittest.TestCase):
    """
    ReminderDialog rejects duplicate names when adding a new reminder.

    Bug this catches: without this check, two reminders with the same name
    could be written to config.json, causing unpredictable daemon behaviour
    since name is the primary key.
    """

    def test_duplicate_name_rejected(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        from kim.ui.reminder_dialog import ReminderDialog

        app = QApplication.instance() or QApplication(sys.argv[:1])
        existing = {"water", "stretch"}
        dlg = ReminderDialog(existing_names=existing)

        # Manually trigger validation with a duplicate name
        dlg._name_edit.setText("water")
        dlg._radio_interval.setChecked(True)
        dlg._interval_edit.setText("30m")

        # _on_accept should show a warning and NOT set result_reminder
        with patch(
            "kim.ui.reminder_dialog.QMessageBox.warning", return_value=None
        ) as mock_warn:
            dlg._on_accept()
            mock_warn.assert_called_once()
        self.assertIsNone(dlg.result_reminder)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 not installed")
class TestReminderDialogPopulatesFieldsOnEdit(unittest.TestCase):
    """
    ReminderDialog correctly populates all fields when editing an existing
    interval-based reminder.

    Bug this catches: if _populate() used the wrong key (e.g. "interval_minutes"
    when the dict had "interval"), the edit dialog would open with blank fields,
    causing the user to unknowingly overwrite values with defaults on save.
    """

    def test_interval_reminder_fields_populated(self):
        from PySide6.QtWidgets import QApplication
        from kim.ui.reminder_dialog import ReminderDialog

        app = QApplication.instance() or QApplication(sys.argv[:1])
        r = {
            "name": "water",
            "interval": "30m",
            "title": "Drink Water",
            "message": "Stay hydrated",
            "urgency": "low",
            "enabled": False,
        }
        dlg = ReminderDialog(reminder=r)

        self.assertEqual(dlg._name_edit.text(), "water")
        self.assertEqual(dlg._interval_edit.text(), "30m")
        self.assertEqual(dlg._title_edit.text(), "Drink Water")
        self.assertEqual(dlg._message_edit.text(), "Stay hydrated")
        self.assertEqual(dlg._urgency_combo.currentText(), "low")
        self.assertFalse(dlg._enabled_check.isChecked())
        self.assertTrue(dlg._radio_interval.isChecked())

    def test_at_reminder_fields_populated(self):
        from PySide6.QtWidgets import QApplication
        from kim.ui.reminder_dialog import ReminderDialog

        app = QApplication.instance() or QApplication(sys.argv[:1])
        r = {
            "name": "standup",
            "at": "09:30",
            "timezone": "Asia/Kolkata",
            "title": "Standup",
            "message": "Join the call",
            "urgency": "critical",
            "enabled": True,
        }
        dlg = ReminderDialog(reminder=r)

        self.assertTrue(dlg._radio_at.isChecked())
        self.assertEqual(dlg._at_edit.time().hour(), 9)
        self.assertEqual(dlg._at_edit.time().minute(), 30)
        self.assertEqual(dlg._tz_combo.currentText(), "Asia/Kolkata")
        self.assertEqual(dlg._urgency_combo.currentText(), "critical")


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 not installed")
class TestReminderDialogScheduleVisibility(unittest.TestCase):
    """
    Switching between Interval and Daily-at modes shows/hides the correct rows.

    Bug this catches: if _update_schedule_visibility() was not connected to
    the radio button group, both the interval row and at-time row would be
    visible simultaneously, making the dialog confusing and allowing invalid
    combinations to be submitted.
    """

    def test_interval_mode_shows_interval_row(self):
        from PySide6.QtWidgets import QApplication
        from kim.ui.reminder_dialog import ReminderDialog

        app = QApplication.instance() or QApplication(sys.argv[:1])
        dlg = ReminderDialog()
        dlg._radio_interval.setChecked(True)
        dlg._update_schedule_visibility()

        self.assertFalse(dlg._interval_row.isHidden())
        self.assertTrue(dlg._at_row.isHidden())

    def test_at_mode_shows_at_row(self):
        from PySide6.QtWidgets import QApplication
        from kim.ui.reminder_dialog import ReminderDialog

        app = QApplication.instance() or QApplication(sys.argv[:1])
        dlg = ReminderDialog()
        dlg._radio_at.setChecked(True)
        dlg._update_schedule_visibility()

        self.assertTrue(dlg._interval_row.isHidden())
        self.assertFalse(dlg._at_row.isHidden())


if __name__ == "__main__":
    unittest.main()
