"""
KimMainWindow — the primary management window.

Layout
------
  Menu bar:  (future)
  Toolbar:   Add | Edit | Remove | Enable | Disable | ── | One-shot | ── | Settings | Refresh
  Tab bar:   Reminders | One-shots
    Reminders tab:  QTableWidget — Name | Schedule | Urgency | Enabled
    One-shots tab:  QTableWidget — Message | Title | Fire at | Urgency | [Cancel]
  Status bar: daemon status · reminder count · version

The window auto-refreshes whenever ConfigWatcher emits config_changed.
Double-clicking a reminder row opens ReminderDialog in edit mode.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import time
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from kim.core import CONFIG, LOG_FILE, ONESHOT_FILE, PID_FILE, VERSION, load_config
from kim.commands.misc import (
    _save_config as _misc_save_config,
    load_oneshot_reminders,
    remove_oneshot,
)
from kim.commands.management import _signal_reload

from .reminder_dialog import ReminderDialog
from .settings_dialog import SettingsDialog
from .oneshot_dialog import OneShotDialog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_schedule(r: dict) -> str:
    if r.get("at"):
        tz = r.get("timezone", "")
        return f"Daily  {r['at']}" + (f"  ({tz})" if tz else "")
    iv = r.get("interval") or r.get("interval_minutes", "")
    return f"Every  {iv}" if iv else "—"


def _format_fire_at(ts: float) -> str:
    """Convert a Unix timestamp to a human-readable local datetime string."""
    try:
        dt = datetime.datetime.fromtimestamp(ts)
        # How far away is it?
        delta = ts - time.time()
        if delta < 60:
            when = "< 1 min"
        elif delta < 3600:
            when = f"{int(delta // 60)} min"
        elif delta < 86400:
            when = f"{int(delta // 3600)}h {int((delta % 3600) // 60)}m"
        else:
            when = f"{int(delta // 86400)}d {int((delta % 86400) // 3600)}h"
        return dt.strftime("%Y-%m-%d  %H:%M") + f"  (in {when})"
    except (OSError, OverflowError, ValueError):
        return str(ts)


_URGENCY_COLORS = {
    "critical": QColor("#c62828"),
    "normal": QColor("#212121"),
    "low": QColor("#616161"),
}

_CHECK = "✔"
_CROSS = "✘"


def _urgency_item(urgency: str) -> QTableWidgetItem:
    item = QTableWidgetItem(urgency)
    item.setForeground(_URGENCY_COLORS.get(urgency, QColor("#212121")))
    if urgency == "critical":
        f = QFont()
        f.setBold(True)
        item.setFont(f)
    return item


def _human_delay(seconds: float) -> str:
    secs = int(seconds)
    parts = []
    for unit, label in [(86400, "d"), (3600, "h"), (60, "m"), (1, "s")]:
        if secs >= unit:
            parts.append(f"{secs // unit}{label}")
            secs %= unit
    return " ".join(parts) if parts else "now"


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class KimMainWindow(QMainWindow):
    """Primary management window."""

    def __init__(self, watcher, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._watcher = watcher
        self._config: Dict = {}
        self._reminders: List[Dict] = []

        self.setWindowTitle(f"kim — keep in mind  v{VERSION}")
        self.setMinimumSize(780, 460)
        self.resize(900, 560)

        self._build_central()
        self._build_toolbar()
        self._build_statusbar()

        watcher.config_changed.connect(self._on_config_changed)
        watcher.daemon_status_changed.connect(self._on_daemon_status_changed)

        self._reload_config()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_central(self) -> None:
        self._tabs = QTabWidget()

        self._tabs.addTab(self._build_reminders_tab(), "Reminders")
        self._tabs.addTab(self._build_oneshots_tab(), "One-shots")

        # Connect AFTER both tabs are fully built so the currentChanged(0)
        # signal that fires during addTab() doesn't reference _os_table before
        # it exists.
        self._tabs.currentChanged.connect(self._on_tab_changed)

        self.setCentralWidget(self._tabs)

    def _build_reminders_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._rem_table = QTableWidget(0, 4)
        self._rem_table.setHorizontalHeaderLabels(
            ["Name", "Schedule", "Urgency", "Enabled"]
        )
        self._rem_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._rem_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._rem_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._rem_table.setAlternatingRowColors(True)
        self._rem_table.setShowGrid(False)
        self._rem_table.verticalHeader().setVisible(False)
        self._rem_table.doubleClicked.connect(self._edit_reminder)
        self._rem_table.itemSelectionChanged.connect(self._update_action_states)

        hh = self._rem_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        self._rem_table.verticalHeader().setDefaultSectionSize(28)

        layout.addWidget(self._rem_table)
        return w

    def _build_oneshots_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        hint = QLabel(
            "Pending one-shot reminders scheduled with  ⏰ One-shot  or  kim remind."
        )
        hint.setStyleSheet("color: #666; padding: 4px 8px;")
        layout.addWidget(hint)

        self._os_table = QTableWidget(0, 4)
        self._os_table.setHorizontalHeaderLabels(
            ["Message", "Title", "Fire at", "Urgency"]
        )
        self._os_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._os_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._os_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._os_table.setAlternatingRowColors(True)
        self._os_table.setShowGrid(False)
        self._os_table.verticalHeader().setVisible(False)
        self._os_table.itemSelectionChanged.connect(self._update_action_states)

        hh = self._os_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._os_table.verticalHeader().setDefaultSectionSize(28)

        layout.addWidget(self._os_table)
        return w

    def _build_toolbar(self) -> None:
        tb = QToolBar("Actions")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)

        self._act_add = tb.addAction("＋ Add", self._add_reminder)
        self._act_edit = tb.addAction("✎ Edit", self._edit_reminder)
        self._act_remove = tb.addAction("✖ Remove", self._remove_reminder)
        tb.addSeparator()
        self._act_enable = tb.addAction("✔ Enable", self._enable_reminder)
        self._act_disable = tb.addAction("⊘ Disable", self._disable_reminder)
        tb.addSeparator()
        self._act_oneshot = tb.addAction("⏰ One-shot", self._add_oneshot)
        self._act_cancel_os = tb.addAction("✖ Cancel one-shot", self._cancel_oneshot)
        tb.addSeparator()
        self._act_start_daemon = tb.addAction("▶ Start", self._start_daemon)
        self._act_stop_daemon = tb.addAction("■ Stop", self._stop_daemon)
        tb.addSeparator()
        tb.addAction("⚙ Settings", self._open_settings)
        tb.addAction("↺ Refresh", self._reload_config)

        self._update_action_states()

    def _build_statusbar(self) -> None:
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Loading…")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = load_config()
        except Exception:
            self._config = {"reminders": []}
        self._reminders = self._config.get("reminders", [])
        self._refresh_reminders_table()
        self._refresh_oneshots_table()
        self._refresh_status()

    def _on_config_changed(self, cfg: dict) -> None:
        self._config = cfg
        self._reminders = cfg.get("reminders", [])
        self._refresh_reminders_table()
        self._refresh_status()

    def _on_daemon_status_changed(self, running: bool) -> None:
        self._refresh_status(daemon_running=running)

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:  # One-shots tab
            self._refresh_oneshots_table()
        self._update_action_states()

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def _refresh_reminders_table(self) -> None:
        selected_name = self._selected_reminder_name()
        self._rem_table.setRowCount(0)

        for r in self._reminders:
            row = self._rem_table.rowCount()
            self._rem_table.insertRow(row)

            name_item = QTableWidgetItem(r.get("name", ""))
            name_item.setData(Qt.ItemDataRole.UserRole, r)
            self._rem_table.setItem(row, 0, name_item)
            self._rem_table.setItem(row, 1, QTableWidgetItem(_format_schedule(r)))
            self._rem_table.setItem(row, 2, _urgency_item(r.get("urgency", "normal")))

            enabled = r.get("enabled", True)
            en_item = QTableWidgetItem(_CHECK if enabled else _CROSS)
            en_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            en_item.setForeground(QColor("#2e7d32") if enabled else QColor("#c62828"))
            self._rem_table.setItem(row, 3, en_item)

        if selected_name:
            self._select_reminder_by_name(selected_name)

        self._update_action_states()

    def _refresh_oneshots_table(self) -> None:
        self._os_table.setRowCount(0)
        oneshots = load_oneshot_reminders()
        # Sort by fire_at ascending
        oneshots = sorted(oneshots, key=lambda o: o.get("fire_at", 0))
        for o in oneshots:
            row = self._os_table.rowCount()
            self._os_table.insertRow(row)

            msg_item = QTableWidgetItem(o.get("message", ""))
            msg_item.setData(Qt.ItemDataRole.UserRole, o.get("fire_at"))
            self._os_table.setItem(row, 0, msg_item)
            self._os_table.setItem(row, 1, QTableWidgetItem(o.get("title", "Reminder")))
            self._os_table.setItem(
                row, 2, QTableWidgetItem(_format_fire_at(o.get("fire_at", 0)))
            )
            self._os_table.setItem(row, 3, _urgency_item(o.get("urgency", "normal")))

        self._update_action_states()

    def _refresh_status(self, daemon_running: Optional[bool] = None) -> None:
        if daemon_running is None:
            daemon_running = PID_FILE.exists()
        dot = "●" if daemon_running else "○"
        state = "Running" if daemon_running else "Stopped"
        n = len(self._reminders)
        self._statusbar.showMessage(
            f"{dot} Daemon: {state}   ·   {n} reminder{'s' if n != 1 else ''}   ·   kim v{VERSION}"
        )

    # ------------------------------------------------------------------
    # Selection helpers — reminders tab
    # ------------------------------------------------------------------

    def _selected_reminder_row(self) -> int:
        rows = self._rem_table.selectedItems()
        return self._rem_table.row(rows[0]) if rows else -1

    def _selected_reminder(self) -> Optional[Dict]:
        row = self._selected_reminder_row()
        if row < 0:
            return None
        item = self._rem_table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_reminder_name(self) -> Optional[str]:
        r = self._selected_reminder()
        return r.get("name") if r else None

    def _select_reminder_by_name(self, name: str) -> None:
        for row in range(self._rem_table.rowCount()):
            item = self._rem_table.item(row, 0)
            if item and item.text() == name:
                self._rem_table.selectRow(row)
                return

    # ------------------------------------------------------------------
    # Selection helpers — one-shots tab
    # ------------------------------------------------------------------

    def _selected_oneshot_row(self) -> int:
        rows = self._os_table.selectedItems()
        return self._os_table.row(rows[0]) if rows else -1

    def _selected_oneshot_fire_at(self) -> Optional[float]:
        row = self._selected_oneshot_row()
        if row < 0:
            return None
        item = self._os_table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    # ------------------------------------------------------------------
    # Toolbar state
    # ------------------------------------------------------------------

    def _update_action_states(self) -> None:
        on_reminders = self._tabs.currentIndex() == 0
        on_oneshots = self._tabs.currentIndex() == 1

        has_rem = self._selected_reminder_row() >= 0
        r = self._selected_reminder()
        has_os = self._selected_oneshot_row() >= 0
        daemon_running = PID_FILE.exists()

        self._act_add.setEnabled(on_reminders)
        self._act_edit.setEnabled(on_reminders and has_rem)
        self._act_remove.setEnabled(on_reminders and has_rem)
        self._act_enable.setEnabled(
            on_reminders and has_rem and r is not None and not r.get("enabled", True)
        )
        self._act_disable.setEnabled(
            on_reminders and has_rem and r is not None and r.get("enabled", True)
        )
        self._act_oneshot.setEnabled(True)
        self._act_cancel_os.setEnabled(on_oneshots and has_os)
        self._act_start_daemon.setEnabled(not daemon_running)
        self._act_stop_daemon.setEnabled(daemon_running)

    # ------------------------------------------------------------------
    # Actions — reminders
    # ------------------------------------------------------------------

    def _add_reminder(self) -> None:
        existing = {r["name"] for r in self._reminders}
        dlg = ReminderDialog(existing_names=existing, parent=self)
        if dlg.exec() and dlg.result_reminder:
            self._config.setdefault("reminders", []).append(dlg.result_reminder)
            self._save_and_reload()

    def _edit_reminder(self) -> None:
        r = self._selected_reminder()
        if r is None:
            return
        existing = {rem["name"] for rem in self._reminders}
        dlg = ReminderDialog(reminder=r, existing_names=existing, parent=self)
        if dlg.exec() and dlg.result_reminder:
            reminders = self._config.get("reminders", [])
            for i, rem in enumerate(reminders):
                if rem.get("name") == r.get("name"):
                    reminders[i] = dlg.result_reminder
                    break
            self._save_and_reload()

    def _remove_reminder(self) -> None:
        r = self._selected_reminder()
        if r is None:
            return
        name = r.get("name", "")
        reply = QMessageBox.question(
            self,
            "Remove reminder",
            f"Remove '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._config["reminders"] = [
                rem
                for rem in self._config.get("reminders", [])
                if rem.get("name") != name
            ]
            self._save_and_reload()

    def _enable_reminder(self) -> None:
        self._set_enabled(True)

    def _disable_reminder(self) -> None:
        self._set_enabled(False)

    def _set_enabled(self, value: bool) -> None:
        r = self._selected_reminder()
        if r is None:
            return
        name = r.get("name")
        for rem in self._config.get("reminders", []):
            if rem.get("name") == name:
                rem["enabled"] = value
                break
        self._save_and_reload()

    # ------------------------------------------------------------------
    # Actions — one-shots
    # ------------------------------------------------------------------

    def _add_oneshot(self) -> None:
        import subprocess, sys as _sys

        dlg = OneShotDialog(parent=self)
        if not dlg.exec() or dlg.result_fire_time is None:
            return
        sleep_secs = max(0.0, dlg.result_fire_time - time.time())

        # Write to oneshots.json FIRST (same as cmd_remind does) so the
        # one-shot appears in the One-shots tab and survives a reboot.
        import json as _json

        oneshot_entry = {
            "message": dlg.result_message,
            "title": dlg.result_title,
            "urgency": dlg.result_urgency,
            "fire_at": dlg.result_fire_time,
        }
        try:
            existing = []
            if ONESHOT_FILE.exists():
                try:
                    existing = _json.loads(ONESHOT_FILE.read_text(encoding="utf-8"))
                except Exception:
                    existing = []
            existing.append(oneshot_entry)
            _tmp = ONESHOT_FILE.with_suffix(".tmp")
            _tmp.write_text(_json.dumps(existing, indent=2), encoding="utf-8")
            if platform.system() != "Windows":
                try:
                    os.chmod(_tmp, 0o600)
                except OSError:
                    pass
            _tmp.replace(ONESHOT_FILE)
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not save one-shot:\n{e}")
            return

        try:
            subprocess.Popen(
                [
                    _sys.executable,
                    "-m",
                    "kim",
                    "_remind-fire",
                    "--message",
                    dlg.result_message,
                    "--title",
                    dlg.result_title,
                    "--urgency",
                    dlg.result_urgency,
                    "--seconds",
                    str(sleep_secs),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            QMessageBox.information(
                self,
                "One-shot scheduled",
                f"'{dlg.result_message}' will fire in {_human_delay(sleep_secs)}.",
            )
            # Switch to one-shots tab so user sees it listed
            self._tabs.setCurrentIndex(1)
            self._refresh_oneshots_table()
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Could not schedule reminder:\n{e}")

    def _cancel_oneshot(self) -> None:
        fire_at = self._selected_oneshot_fire_at()
        if fire_at is None:
            return
        row = self._selected_oneshot_row()
        msg_item = self._os_table.item(row, 0)
        msg = msg_item.text() if msg_item else ""
        reply = QMessageBox.question(
            self,
            "Cancel one-shot",
            f"Cancel '{msg}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            remove_oneshot(fire_at)
            self._refresh_oneshots_table()

    # ------------------------------------------------------------------
    # Daemon control
    # ------------------------------------------------------------------

    def _start_daemon(self) -> None:
        import subprocess, sys as _sys

        try:
            subprocess.Popen(
                [_sys.executable, "-m", "kim", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            QMessageBox.warning(self, "Daemon", f"Could not start daemon:\n{e}")

    def _stop_daemon(self) -> None:
        import subprocess, sys as _sys

        try:
            # Use Popen (non-blocking) — subprocess.run would freeze the UI
            subprocess.Popen(
                [_sys.executable, "-m", "kim", "stop"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            QMessageBox.warning(self, "Daemon", f"Could not stop daemon:\n{e}")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(
            config=self._config,
            save_config_fn=_misc_save_config,
            log_path=LOG_FILE,
            parent=self,
        )
        if dlg.exec():
            self._watcher.force_refresh()
            self._reload_config()

    # ------------------------------------------------------------------
    # Config write
    # ------------------------------------------------------------------

    def _save_and_reload(self) -> None:
        try:
            _misc_save_config(self._config)
        except SystemExit:
            QMessageBox.critical(self, "Error", "Could not write config file.")
            return
        _signal_reload()
        self._watcher.force_refresh()
        self._reload_config()
