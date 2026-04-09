"""
OneShotDialog — QDialog for scheduling a one-shot reminder.

Mirrors `kim remind <message> in <delay>` / `kim remind <message> at <time>`.

Fields
------
  Message       QLineEdit
  Title         QLineEdit  (optional)
  When          QButtonGroup — "In (delay)" / "At (date+time)"
  Delay         QLineEdit  e.g. "10m", "1h", "2h 30m"
  Date          QDateEdit  (for absolute time)
  Time          QTimeEdit  with AM/PM
  Timezone      QComboBox  (only shown in At mode)
  Urgency       QComboBox  low / normal / critical

On Accept: result_args is a namespace-like object that can be passed
           directly to cmd_remind(), or callers can read .fire_time (Unix
           timestamp) and .message / .title / .urgency directly.
"""

from __future__ import annotations

import subprocess
import sys
import time as _time
from typing import Optional

from PySide6.QtCore import QDate, QDateTime, QTime, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

_COMMON_ZONES = [
    "(local system timezone)",
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Moscow",
    "Asia/Kolkata",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Australia/Sydney",
    "Pacific/Auckland",
]


class OneShotDialog(QDialog):
    """
    Schedule a one-shot reminder.

    After accept(), check ``result_fire_time`` (Unix timestamp) and
    ``result_message``, ``result_title``, ``result_urgency`` to fire via
    cmd_remind or directly via the subprocess path.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Add One-Shot Reminder")
        self.setMinimumWidth(440)

        self.result_fire_time: Optional[float] = None
        self.result_message: str = ""
        self.result_title: str = "Reminder"
        self.result_urgency: str = "normal"
        self.result_timezone: Optional[str] = None

        self._build_ui()
        self._update_when_visibility()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Message
        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText("e.g. Take medication")
        form.addRow("Message:", self._message_edit)

        # Title
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Reminder (default)")
        form.addRow("Title:", self._title_edit)

        # Urgency
        self._urgency_combo = QComboBox()
        self._urgency_combo.addItems(["low", "normal", "critical"])
        self._urgency_combo.setCurrentText("normal")
        form.addRow("Urgency:", self._urgency_combo)

        # When group
        when_box = QGroupBox("When")
        when_layout = QVBoxLayout(when_box)

        self._radio_delay = QRadioButton("In … (relative delay)")
        self._radio_at = QRadioButton("At … (specific date & time)")
        self._radio_delay.setChecked(True)

        self._when_group = QButtonGroup(self)
        self._when_group.addButton(self._radio_delay, 0)
        self._when_group.addButton(self._radio_at, 1)
        self._when_group.buttonClicked.connect(self._update_when_visibility)

        when_layout.addWidget(self._radio_delay)

        # Delay row
        self._delay_row = QWidget()
        delay_layout = QHBoxLayout(self._delay_row)
        delay_layout.setContentsMargins(0, 0, 0, 0)
        self._delay_edit = QLineEdit()
        self._delay_edit.setPlaceholderText("e.g.  10m   1h   2h 30m   90s")
        self._delay_edit.setMinimumWidth(200)
        delay_layout.addWidget(self._delay_edit)
        delay_layout.addWidget(QLabel("(s / m / h)"))
        delay_layout.addStretch()
        when_layout.addWidget(self._delay_row)

        when_layout.addWidget(self._radio_at)

        # At row
        self._at_row = QWidget()
        at_layout = QHBoxLayout(self._at_row)
        at_layout.setContentsMargins(0, 0, 0, 0)

        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        at_layout.addWidget(self._date_edit)

        self._time_edit = QTimeEdit()
        self._time_edit.setDisplayFormat("hh:mm AP")
        self._time_edit.setTime(QTime(9, 0))
        at_layout.addWidget(self._time_edit)

        at_layout.addWidget(QLabel("TZ:"))
        self._tz_combo = QComboBox()
        self._tz_combo.setEditable(True)
        self._tz_combo.addItems(_COMMON_ZONES)
        self._tz_combo.setCurrentIndex(0)
        self._tz_combo.setMinimumWidth(160)
        at_layout.addWidget(self._tz_combo)
        at_layout.addStretch()
        when_layout.addWidget(self._at_row)

        form.addRow(when_box)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # Visibility
    # ------------------------------------------------------------------

    def _update_when_visibility(self) -> None:
        at_mode = self._radio_at.isChecked()
        self._delay_row.setVisible(not at_mode)
        self._at_row.setVisible(at_mode)

    # ------------------------------------------------------------------
    # Validation & accept
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        message = self._message_edit.text().strip()
        if not message:
            QMessageBox.warning(self, "Validation", "Message is required.")
            return

        title = self._title_edit.text().strip() or "Reminder"
        urgency = self._urgency_combo.currentText()

        if self._radio_delay.isChecked():
            delay_str = self._delay_edit.text().strip()
            if not delay_str:
                QMessageBox.warning(self, "Validation", "Delay is required.")
                return
            fire_time = _parse_delay(delay_str)
            if fire_time is None:
                QMessageBox.warning(
                    self,
                    "Validation",
                    f"Invalid delay '{delay_str}'.\n"
                    "Use formats like: 10m  1h  2h 30m  90s  1d",
                )
                return
            tz_name = None
        else:
            d = self._date_edit.date()
            t = self._time_edit.time()
            tz_text = self._tz_combo.currentText().strip()
            tz_name = None if tz_text.startswith("(local") else tz_text or None

            # Build a fire timestamp via parse_datetime
            time_str = f"{t.hour():02d}:{t.minute():02d}"
            date_str = f"{d.year():04d}-{d.month():02d}-{d.day():02d}"
            try:
                from kim.core import parse_datetime

                fire_time = parse_datetime(
                    ["at", f"{date_str} {time_str}"], tz_name=tz_name
                )
            except ValueError as e:
                QMessageBox.warning(self, "Validation", str(e))
                return

            if fire_time <= _time.time():
                QMessageBox.warning(
                    self,
                    "Validation",
                    "The scheduled time is in the past. Choose a future time.",
                )
                return

        self.result_fire_time = fire_time
        self.result_message = message
        self.result_title = title
        self.result_urgency = urgency
        self.result_timezone = tz_name
        self.accept()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_delay(text: str) -> Optional[float]:
    """
    Parse a human delay string into a Unix fire timestamp.

    Supports: 10m, 1h, 90s, 1d, 2h 30m, 2h30m, plain number (minutes).
    Returns None if unparseable or non-positive.
    """
    import re

    text = text.strip().lower()
    if not text:
        return None

    total_seconds = 0.0
    # Match sequences like "2h", "30m", "90s", "1d"
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*([smhd]?)")
    found_any = False
    remainder = text
    for m in pattern.finditer(text):
        val_str, unit = m.group(1), m.group(2)
        val = float(val_str)
        if val <= 0:
            continue
        if unit == "s":
            total_seconds += val
        elif unit == "h":
            total_seconds += val * 3600
        elif unit == "d":
            total_seconds += val * 86400
        else:
            # "m" or no unit → minutes
            total_seconds += val * 60
        found_any = True
        remainder = remainder.replace(m.group(0), "", 1)

    # Reject if there's leftover non-whitespace (garbage in the string)
    if remainder.strip():
        return None
    if not found_any or total_seconds <= 0:
        return None
    if total_seconds > 365 * 24 * 3600:
        return None

    return _time.time() + total_seconds
