"""
ConfigWatcher — QThread that polls config.json and oneshots.json every 3 s
and emits a signal whenever either file changes on disk.

This lets the main window and tray icon update automatically when the user
runs a CLI command (e.g. `kim add`, `kim stop`) in another terminal.
"""

import json
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class ConfigWatcher(QThread):
    """
    Background thread that watches ~/.kim/config.json and oneshots.json.

    Signals
    -------
    config_changed(config: dict)
        Emitted whenever config.json changes on disk.  Carries the freshly
        parsed config dict so the receiver never needs to re-read the file.
    daemon_status_changed(running: bool)
        Emitted when the daemon PID file appears or disappears.
    """

    config_changed = Signal(dict)
    daemon_status_changed = Signal(bool)

    # How often (seconds) to poll for file changes
    POLL_INTERVAL = 3.0

    def __init__(self, config_path: Path, pid_path: Path, parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self._pid_path = pid_path
        self._stop_requested = False

        # Track last-seen modification times
        self._config_mtime: float = 0.0
        self._daemon_running: bool = False

    def stop(self) -> None:
        """Request the watcher thread to exit."""
        self._stop_requested = True

    def run(self) -> None:
        """Main polling loop — runs in the background thread."""
        while not self._stop_requested:
            self._check_config()
            self._check_daemon()
            # Sleep in small increments so stop() is responsive
            for _ in range(int(self.POLL_INTERVAL / 0.25)):
                if self._stop_requested:
                    return
                time.sleep(0.25)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_config(self) -> None:
        """Emit config_changed if config.json was modified since last check."""
        try:
            mtime = self._config_path.stat().st_mtime
        except OSError:
            return

        if mtime != self._config_mtime:
            self._config_mtime = mtime
            try:
                with open(self._config_path, encoding="utf-8") as fh:
                    cfg = json.load(fh)
                cfg.setdefault("reminders", [])
                self.config_changed.emit(cfg)
            except (json.JSONDecodeError, OSError):
                pass

    def _check_daemon(self) -> None:
        """Emit daemon_status_changed if the PID file appeared/disappeared."""
        running = self._pid_path.exists()
        if running != self._daemon_running:
            self._daemon_running = running
            self.daemon_status_changed.emit(running)

    def force_refresh(self) -> None:
        """
        Reset the cached mtime so the next poll emits config_changed
        regardless of whether the file actually changed.  Call this after
        the GUI writes a config change itself.
        """
        self._config_mtime = 0.0
