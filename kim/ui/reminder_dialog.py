"""
ReminderDialog — QDialog for adding or editing a single reminder.

Fields
------
  Name            QLineEdit
  Schedule type   QButtonGroup (Interval / Daily at time)
  Interval        QLineEdit  e.g. "30m", "1h", "1d"
  At time         QTimeEdit  HH:MM
  Timezone        QComboBox  (common IANA zones; editable for custom)
  Title           QLineEdit
  Message         QLineEdit
  Urgency         QComboBox  low / normal / critical
  Enabled         QCheckBox

On Accept: returns a validated reminder dict via .result_reminder.
           Caller is responsible for writing config and signalling reload.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
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

# Common IANA timezone names offered in the dropdown.
# Users can type any custom value — the combo is editable.
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


class ReminderDialog(QDialog):
    """
    Add / edit a reminder.

    Parameters
    ----------
    reminder:
        Existing reminder dict when editing; ``None`` when adding.
    existing_names:
        Set of reminder names already in the config — used to prevent
        duplicate names when adding.
    parent:
        Parent widget.
    """

    def __init__(
        self,
        reminder: Optional[Dict] = None,
        existing_names: Optional[set] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._editing = reminder is not None
        self._original = reminder or {}
        self._existing_names = existing_names or set()
        self.result_reminder: Optional[Dict] = None

        self.setWindowTitle("Edit Reminder" if self._editing else "Add Reminder")
        self.setMinimumWidth(420)
        self._build_ui()
        if self._editing:
            self._populate(self._original)
        self._update_schedule_visibility()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Name
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. water")
        if self._editing:
            self._name_edit.setEnabled(False)  # name is the primary key — don't rename
        form.addRow("Name:", self._name_edit)

        # Schedule type toggle
        sched_box = QGroupBox("Schedule")
        sched_layout = QVBoxLayout(sched_box)
        self._radio_interval = QRadioButton("Repeat every interval")
        self._radio_at = QRadioButton("Fire daily at a fixed time")
        self._radio_interval.setChecked(True)
        self._sched_group = QButtonGroup(self)
        self._sched_group.addButton(self._radio_interval, 0)
        self._sched_group.addButton(self._radio_at, 1)
        self._sched_group.buttonClicked.connect(self._update_schedule_visibility)
        sched_layout.addWidget(self._radio_interval)

        # Interval row
        self._interval_row = QWidget()
        iv_layout = QHBoxLayout(self._interval_row)
        iv_layout.setContentsMargins(0, 0, 0, 0)
        self._interval_edit = QLineEdit()
        self._interval_edit.setPlaceholderText("e.g. 30m  1h  1d  45")
        self._interval_edit.setMaximumWidth(160)
        iv_layout.addWidget(self._interval_edit)
        iv_layout.addWidget(QLabel("(s / m / h / d)"))
        iv_layout.addStretch()
        sched_layout.addWidget(self._interval_row)

        sched_layout.addWidget(self._radio_at)

        # At-time row
        self._at_row = QWidget()
        at_layout = QHBoxLayout(self._at_row)
        at_layout.setContentsMargins(0, 0, 0, 0)
        self._at_edit = QTimeEdit()
        self._at_edit.setDisplayFormat("HH:mm")
        self._at_edit.setTime(QTime(9, 0))
        at_layout.addWidget(self._at_edit)

        at_layout.addWidget(QLabel("Timezone:"))
        self._tz_combo = QComboBox()
        self._tz_combo.setEditable(True)
        self._tz_combo.addItems(_COMMON_ZONES)
        self._tz_combo.setCurrentIndex(0)
        self._tz_combo.setMinimumWidth(200)
        at_layout.addWidget(self._tz_combo)
        at_layout.addStretch()
        sched_layout.addWidget(self._at_row)

        form.addRow(sched_box)

        # Title
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Notification title (optional)")
        form.addRow("Title:", self._title_edit)

        # Message
        self._message_edit = QLineEdit()
        self._message_edit.setPlaceholderText("Notification message (optional)")
        form.addRow("Message:", self._message_edit)

        # Urgency
        self._urgency_combo = QComboBox()
        self._urgency_combo.addItems(["low", "normal", "critical"])
        self._urgency_combo.setCurrentText("normal")
        form.addRow("Urgency:", self._urgency_combo)

        # Enabled
        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.setChecked(True)
        form.addRow("", self._enabled_check)

        root.addLayout(form)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------
    # Population & visibility
    # ------------------------------------------------------------------

    def _populate(self, r: dict) -> None:
        """Fill fields from an existing reminder dict."""
        self._name_edit.setText(r.get("name", ""))
        self._title_edit.setText(r.get("title", ""))
        self._message_edit.setText(r.get("message", ""))
        self._urgency_combo.setCurrentText(r.get("urgency", "normal"))
        self._enabled_check.setChecked(r.get("enabled", True))

        if r.get("at"):
            self._radio_at.setChecked(True)
            try:
                h, m = r["at"].split(":")
                self._at_edit.setTime(QTime(int(h), int(m)))
            except (ValueError, AttributeError):
                pass
            tz = r.get("timezone", "")
            if tz and tz in _COMMON_ZONES:
                self._tz_combo.setCurrentText(tz)
            elif tz:
                self._tz_combo.setCurrentText(tz)
            else:
                self._tz_combo.setCurrentIndex(0)
        else:
            self._radio_interval.setChecked(True)
            iv = r.get("interval") or r.get("interval_minutes", "")
            self._interval_edit.setText(str(iv) if iv else "")

    def _update_schedule_visibility(self) -> None:
        at_mode = self._radio_at.isChecked()
        self._interval_row.setVisible(not at_mode)
        self._at_row.setVisible(at_mode)

    # ------------------------------------------------------------------
    # Validation & accept
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Name is required.")
            return
        if not self._editing and name in self._existing_names:
            QMessageBox.warning(
                self,
                "Validation",
                f"A reminder named '{name}' already exists.\nChoose a different name.",
            )
            return

        if self._radio_interval.isChecked():
            interval_str = self._interval_edit.text().strip().lower()
            if not interval_str:
                QMessageBox.warning(self, "Validation", "Interval is required.")
                return
            # Validate via the scheduler's own parser
            try:
                from kim.scheduler import KimScheduler

                if KimScheduler._parse_interval({"interval": interval_str}) is None:
                    raise ValueError
            except Exception:
                QMessageBox.warning(
                    self,
                    "Validation",
                    f"Invalid interval '{interval_str}'.\n"
                    "Use formats like: 30m  1h  1d  (or plain number for minutes)",
                )
                return
            reminder = {
                "name": name,
                "interval": interval_str,
                "title": self._title_edit.text().strip() or f"Reminder: {name}",
                "message": self._message_edit.text().strip() or "Time for a reminder!",
                "urgency": self._urgency_combo.currentText(),
                "enabled": self._enabled_check.isChecked(),
            }
        else:
            t = self._at_edit.time()
            at_str = f"{t.hour():02d}:{t.minute():02d}"
            reminder = {
                "name": name,
                "at": at_str,
                "title": self._title_edit.text().strip() or f"Reminder: {name}",
                "message": self._message_edit.text().strip() or "Time for a reminder!",
                "urgency": self._urgency_combo.currentText(),
                "enabled": self._enabled_check.isChecked(),
            }
            tz_text = self._tz_combo.currentText().strip()
            if tz_text and not tz_text.startswith("(local"):
                reminder["timezone"] = tz_text

        self.result_reminder = reminder
        self.accept()
