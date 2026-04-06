"""
app.py — entry point for the kim Qt GUI.

Call run() to start the application.  This is what `kim ui` invokes.

Architecture
------------
  QApplication
    ├── KimTrayIcon          (lives in the system tray)
    ├── KimMainWindow        (shown/hidden on demand)
    └── ConfigWatcher        (QThread, polls config every 3 s)

The window is hidden by default; the tray icon is the persistent presence.
Closing the window hides it rather than quitting — the tray icon stays.
Quitting via the tray menu (or last-window-closed if the tray is not
supported) exits cleanly.
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from kim.core import CONFIG, PID_FILE

from .config_watcher import ConfigWatcher
from .main_window import KimMainWindow
from .tray import KimTrayIcon


def run() -> None:
    """Launch the kim Qt GUI.  Blocks until the user quits."""

    # High-DPI scaling — let Qt handle it automatically on all platforms
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("kim")
    app.setApplicationDisplayName("kim — keep in mind")
    app.setQuitOnLastWindowClosed(False)  # tray keeps us alive

    # Warn if no system tray is available (e.g. some minimal Linux WMs)
    if not KimTrayIcon.isSystemTrayAvailable():
        QMessageBox.warning(
            None,
            "kim — no system tray",
            "Your desktop environment does not appear to support a system tray.\n\n"
            "The management window will open directly instead.\n"
            "Close the window to quit.",
        )
        app.setQuitOnLastWindowClosed(True)

    # Config watcher — background thread
    watcher = ConfigWatcher(CONFIG, PID_FILE)

    # Main window — hidden by default
    window = KimMainWindow(watcher)
    window.setWindowFlag(Qt.WindowType.Window)

    # Closing the window hides it (tray stays alive)
    window.closeEvent = lambda event: (event.ignore(), window.hide())

    # Tray icon
    def _show_window():
        window.show()
        window.raise_()
        window.activateWindow()

    def _add_reminder():
        window.show()
        window.raise_()
        window.activateWindow()
        window._add_reminder()

    def _quit():
        watcher.stop()
        watcher.wait(3000)
        app.quit()

    tray = KimTrayIcon(
        open_manager_cb=_show_window,
        add_reminder_cb=_add_reminder,
        quit_cb=_quit,
    )
    tray.show()

    # Wire daemon status into tray icon
    watcher.daemon_status_changed.connect(tray.set_daemon_status)

    # Seed the initial daemon status before the first poll
    tray.set_daemon_status(PID_FILE.exists())

    # Start watcher thread after everything is wired
    watcher.start()

    # If no system tray, show the window immediately
    if not KimTrayIcon.isSystemTrayAvailable():
        _show_window()

    sys.exit(app.exec())
