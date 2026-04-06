"""
KimTrayIcon — system tray icon with right-click context menu.

Menu layout:
  ● Daemon: Running / Stopped   (status label, not clickable)
  ─────────────────────────────
  Open Manager
  ─────────────────────────────
  Start Daemon
  Stop Daemon
  ─────────────────────────────
  Add Reminder…
  ─────────────────────────────
  Quit

Double-clicking the tray icon opens the main manager window.
The daemon status dot updates every time ConfigWatcher emits
daemon_status_changed.
"""

import subprocess
import sys

from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def _make_dot_icon(color: str, size: int = 22) -> QIcon:
    """
    Generate a simple filled-circle icon in `color`.
    Used for the tray icon so we don't need bundled image files.
    """
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))  # transparent background
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor(color).darker(130))
    margin = 3
    painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.end()
    return QIcon(pix)


# Icons are built lazily on first use so that QApplication exists by the time
# QPixmap is constructed.  Module-level QPixmap creation crashes with:
#   "QPixmap: Must construct a QGuiApplication before a QPixmap"
_ICON_GREEN: "QIcon | None" = None
_ICON_RED: "QIcon | None" = None
_ICON_GREY: "QIcon | None" = None


def _get_icon(color: str) -> "QIcon":
    """Return (and cache) a dot icon, building it on first call."""
    global _ICON_GREEN, _ICON_RED, _ICON_GREY
    if color == "#4caf50":
        if _ICON_GREEN is None:
            _ICON_GREEN = _make_dot_icon(color)
        return _ICON_GREEN
    if color == "#f44336":
        if _ICON_RED is None:
            _ICON_RED = _make_dot_icon(color)
        return _ICON_RED
    if _ICON_GREY is None:
        _ICON_GREY = _make_dot_icon(color)
    return _ICON_GREY


class KimTrayIcon(QSystemTrayIcon):
    """
    System tray icon for kim.

    Parameters
    ----------
    open_manager_cb:
        Callable with no arguments — called when the user clicks
        "Open Manager" or double-clicks the tray icon.
    add_reminder_cb:
        Callable with no arguments — opens the add-reminder dialog.
    quit_cb:
        Callable with no arguments — exits the application.
    """

    def __init__(self, open_manager_cb, add_reminder_cb, quit_cb, parent=None):
        super().__init__(_get_icon("#9e9e9e"), parent)

        self._open_manager_cb = open_manager_cb
        self._add_reminder_cb = add_reminder_cb
        self._quit_cb = quit_cb

        self._daemon_running: bool = False

        self._build_menu()
        self.activated.connect(self._on_activated)
        self.setToolTip("kim — keep in mind")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_daemon_status(self, running: bool) -> None:
        """Update the icon and status label to reflect daemon state."""
        self._daemon_running = running
        if running:
            self.setIcon(_get_icon("#4caf50"))
            self._status_action.setText("● Daemon: Running")
            self._start_action.setEnabled(False)
            self._stop_action.setEnabled(True)
        else:
            self.setIcon(_get_icon("#f44336"))
            self._status_action.setText("○ Daemon: Stopped")
            self._start_action.setEnabled(True)
            self._stop_action.setEnabled(False)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu()

        # Status label (disabled — display only)
        self._status_action = menu.addAction("○ Daemon: Stopped")
        self._status_action.setEnabled(False)

        menu.addSeparator()
        menu.addAction("Open Manager", self._open_manager_cb)
        menu.addSeparator()

        self._start_action = menu.addAction("Start Daemon", self._start_daemon)
        self._stop_action = menu.addAction("Stop Daemon", self._stop_daemon)
        self._stop_action.setEnabled(False)

        menu.addSeparator()
        menu.addAction("Add Reminder…", self._add_reminder_cb)
        menu.addSeparator()
        menu.addAction("Quit", self._quit_cb)

        self.setContextMenu(menu)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._open_manager_cb()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Single left-click on some platforms
            self._open_manager_cb()

    def _start_daemon(self) -> None:
        try:
            subprocess.Popen(
                [sys.executable, "-m", "kim", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

    def _stop_daemon(self) -> None:
        try:
            subprocess.Popen(
                [sys.executable, "-m", "kim", "stop"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass
