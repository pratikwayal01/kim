"""
KimMainWindow — the primary management window.

Layout
------
  Toolbar:  Add | Edit | Remove | Enable | Disable | ── | Settings | Refresh
  Table:    Name | Schedule | Next fire | Urgency | Enabled
  Status bar: daemon status + version

The window auto-refreshes whenever ConfigWatcher emits config_changed.
Double-clicking a row opens ReminderDialog in edit mode.
"""

from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QWidget,
)

from kim.core import CONFIG, LOG_FILE, PID_FILE, VERSION, load_config
from kim.commands.misc import _save_config as _misc_save_config
from kim.commands.management import _signal_reload

from .reminder_dialog import ReminderDialog
from .settings_dialog import SettingsDialog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_schedule(r: dict) -> str:
    if r.get("at"):
        tz = r.get("timezone", "")
        return f"daily {r['at']}" + (f" ({tz})" if tz else "")
    iv = r.get("interval") or r.get("interval_minutes", "")
    return f"every {iv}" if iv else "—"


def _format_next_fire(r: dict) -> str:
    """Best-effort 'next fire in X' string without running the scheduler."""
    if r.get("at"):
        return "next occurrence today/tomorrow"
    iv = r.get("interval") or r.get("interval_minutes", "")
    if not iv:
        return "—"
    # We can't know the exact next fire without the scheduler state,
    # so show the interval as the cadence.
    return f"every {iv}"


_URGENCY_COLORS = {
    "critical": QColor("#ff5252"),
    "normal": QColor("#212121"),
    "low": QColor("#757575"),
}

_CHECK = "✔"
_CROSS = "✘"


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class KimMainWindow(QMainWindow):
    """
    Primary management window.

    Parameters
    ----------
    watcher:
        The ConfigWatcher instance (already started) so the window can
        connect to its signals.
    parent:
        Parent widget (usually None for a top-level window).
    """

    def __init__(self, watcher, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._watcher = watcher
        self._config: Dict = {}
        self._reminders: List[Dict] = []

        self.setWindowTitle(f"kim — keep in mind  v{VERSION}")
        self.setMinimumSize(700, 400)
        self.resize(820, 500)

        self._build_toolbar()
        self._build_table()
        self._build_statusbar()

        # Connect watcher signals
        watcher.config_changed.connect(self._on_config_changed)
        watcher.daemon_status_changed.connect(self._on_daemon_status_changed)

        # Initial load
        self._reload_config()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = QToolBar("Actions")
        tb.setMovable(False)
        self.addToolBar(tb)

        self._act_add = tb.addAction("＋ Add", self._add_reminder)
        self._act_edit = tb.addAction("✎ Edit", self._edit_reminder)
        self._act_remove = tb.addAction("✖ Remove", self._remove_reminder)
        tb.addSeparator()
        self._act_enable = tb.addAction("✔ Enable", self._enable_reminder)
        self._act_disable = tb.addAction("⊘ Disable", self._disable_reminder)
        tb.addSeparator()
        tb.addAction("⚙ Settings", self._open_settings)
        tb.addAction("↺ Refresh", self._reload_config)

        self._update_action_states()

    def _build_table(self) -> None:
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Schedule", "Cadence / Next fire", "Urgency", "Enabled"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.doubleClicked.connect(self._edit_reminder)
        self._table.itemSelectionChanged.connect(self._update_action_states)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.setCentralWidget(self._table)

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
        self._refresh_table()
        self._refresh_status()

    def _on_config_changed(self, cfg: dict) -> None:
        self._config = cfg
        self._reminders = cfg.get("reminders", [])
        self._refresh_table()
        self._refresh_status()

    def _on_daemon_status_changed(self, running: bool) -> None:
        self._refresh_status(daemon_running=running)

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        selected_name = self._selected_name()
        self._table.setRowCount(0)

        for r in self._reminders:
            row = self._table.rowCount()
            self._table.insertRow(row)

            name_item = QTableWidgetItem(r.get("name", ""))
            name_item.setData(Qt.ItemDataRole.UserRole, r)
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, QTableWidgetItem(_format_schedule(r)))
            self._table.setItem(row, 2, QTableWidgetItem(_format_next_fire(r)))

            urgency = r.get("urgency", "normal")
            urg_item = QTableWidgetItem(urgency)
            urg_item.setForeground(_URGENCY_COLORS.get(urgency, QColor("#212121")))
            font = QFont()
            if urgency == "critical":
                font.setBold(True)
            urg_item.setFont(font)
            self._table.setItem(row, 3, urg_item)

            enabled = r.get("enabled", True)
            en_item = QTableWidgetItem(_CHECK if enabled else _CROSS)
            en_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            en_item.setForeground(QColor("#4caf50") if enabled else QColor("#f44336"))
            self._table.setItem(row, 4, en_item)

        # Restore selection
        if selected_name:
            self._select_by_name(selected_name)

        self._update_action_states()

    def _refresh_status(self, daemon_running: Optional[bool] = None) -> None:
        if daemon_running is None:
            daemon_running = PID_FILE.exists()
        state = "Running" if daemon_running else "Stopped"
        n = len(self._reminders)
        self._statusbar.showMessage(
            f"Daemon: {state}   ·   {n} reminder{'s' if n != 1 else ''}   ·   kim v{VERSION}"
        )

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _selected_row(self) -> int:
        rows = self._table.selectedItems()
        if not rows:
            return -1
        return self._table.row(rows[0])

    def _selected_reminder(self) -> Optional[Dict]:
        row = self._selected_row()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_name(self) -> Optional[str]:
        r = self._selected_reminder()
        return r.get("name") if r else None

    def _select_by_name(self, name: str) -> None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.text() == name:
                self._table.selectRow(row)
                return

    def _update_action_states(self) -> None:
        has_sel = self._selected_row() >= 0
        r = self._selected_reminder()
        self._act_edit.setEnabled(has_sel)
        self._act_remove.setEnabled(has_sel)
        self._act_enable.setEnabled(
            has_sel and r is not None and not r.get("enabled", True)
        )
        self._act_disable.setEnabled(
            has_sel and r is not None and r.get("enabled", True)
        )

    # ------------------------------------------------------------------
    # Actions
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
