"""
SettingsDialog — QDialog with tabs for Sound, Slack, and Daemon controls.

Tabs
----
  Sound   — enabled toggle, custom sound file path + browse, test button
  Slack   — webhook URL or bot token + channel, test button
  Daemon  — start/stop/restart buttons, last 30 lines of kim.log
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class SettingsDialog(QDialog):
    """
    Global settings: Sound, Slack integration, Daemon controls.

    Parameters
    ----------
    config:
        The current loaded config dict (will be written back on accept).
    save_config_fn:
        Callable ``(config: dict) -> None`` — the _save_config from
        commands.misc or commands.config.  Injected so the dialog does
        not import from a specific module.
    log_path:
        Path to kim.log for the Daemon tab log viewer.
    parent:
        Parent widget.
    """

    def __init__(
        self,
        config: Dict,
        save_config_fn,
        log_path: Path,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._config = config
        self._save_config = save_config_fn
        self._log_path = log_path

        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.setMinimumHeight(380)
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        tabs.addTab(self._build_sound_tab(), "Sound")
        tabs.addTab(self._build_slack_tab(), "Slack")
        tabs.addTab(self._build_daemon_tab(), "Daemon")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # -- Sound tab ---------------------------------------------------------

    def _build_sound_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._sound_enabled = QCheckBox("Enable notification sound")
        layout.addWidget(self._sound_enabled)

        file_group = QGroupBox("Custom sound file")
        fg_layout = QHBoxLayout(file_group)
        self._sound_file_edit = QLineEdit()
        self._sound_file_edit.setPlaceholderText("Leave blank for system default")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_sound)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self._sound_file_edit.clear())
        fg_layout.addWidget(self._sound_file_edit)
        fg_layout.addWidget(browse_btn)
        fg_layout.addWidget(clear_btn)
        layout.addWidget(file_group)

        test_btn = QPushButton("Test sound now")
        test_btn.clicked.connect(self._test_sound)
        layout.addWidget(test_btn)

        layout.addStretch()
        return w

    def _browse_sound(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select sound file",
            str(Path.home()),
            "Audio files (*.wav *.mp3 *.ogg *.flac *.aiff *.aif *.m4a *.aac *.oga)",
        )
        if path:
            self._sound_file_edit.setText(path)

    def _test_sound(self) -> None:
        """Fire a test notification via the CLI to exercise the real notify path."""
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "kim",
                    "_remind-fire",
                    "--message",
                    "Sound test",
                    "--title",
                    "kim sound test",
                    "--urgency",
                    "normal",
                    "--seconds",
                    "0",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            QMessageBox.warning(self, "Test sound", f"Could not launch test: {e}")

    # -- Slack tab ---------------------------------------------------------

    def _build_slack_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._slack_enabled = QCheckBox("Enable Slack notifications")
        layout.addWidget(self._slack_enabled)

        form = QFormLayout()

        webhook_group = QGroupBox("Incoming Webhook (simpler)")
        wh_layout = QVBoxLayout(webhook_group)
        self._webhook_edit = QLineEdit()
        self._webhook_edit.setPlaceholderText("https://hooks.slack.com/services/…")
        self._webhook_edit.setEchoMode(QLineEdit.EchoMode.Password)
        wh_layout.addWidget(self._webhook_edit)
        show_wh = QCheckBox("Show webhook URL")
        show_wh.toggled.connect(
            lambda v: self._webhook_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password
            )
        )
        wh_layout.addWidget(show_wh)
        layout.addWidget(webhook_group)

        bot_group = QGroupBox("Bot Token (supports urgency emoji)")
        bt_layout = QFormLayout(bot_group)
        self._bot_token_edit = QLineEdit()
        self._bot_token_edit.setPlaceholderText("xoxb-…")
        self._bot_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        show_tok = QCheckBox("Show token")
        show_tok.toggled.connect(
            lambda v: self._bot_token_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password
            )
        )
        self._channel_edit = QLineEdit()
        self._channel_edit.setPlaceholderText("#general")
        bt_layout.addRow("Bot token:", self._bot_token_edit)
        bt_layout.addRow("", show_tok)
        bt_layout.addRow("Channel:", self._channel_edit)
        layout.addWidget(bot_group)

        test_slack_btn = QPushButton("Send test Slack notification")
        test_slack_btn.clicked.connect(self._test_slack)
        layout.addWidget(test_slack_btn)

        layout.addStretch()
        return w

    def _test_slack(self) -> None:
        try:
            subprocess.Popen(
                [sys.executable, "-m", "kim", "slack", "--test"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            QMessageBox.warning(self, "Test Slack", f"Could not launch test: {e}")

    # -- Daemon tab --------------------------------------------------------

    def _build_daemon_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        btn_row = QHBoxLayout()
        start_btn = QPushButton("Start Daemon")
        stop_btn = QPushButton("Stop Daemon")
        restart_btn = QPushButton("Restart Daemon")
        start_btn.clicked.connect(lambda: self._daemon_cmd("start"))
        stop_btn.clicked.connect(lambda: self._daemon_cmd("stop"))
        restart_btn.clicked.connect(self._restart_daemon)
        btn_row.addWidget(start_btn)
        btn_row.addWidget(stop_btn)
        btn_row.addWidget(restart_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Recent log (last 30 lines):"))
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = self._log_view.font()
        font.setFamily("monospace")
        self._log_view.setFont(font)
        layout.addWidget(self._log_view)

        refresh_btn = QPushButton("Refresh log")
        refresh_btn.clicked.connect(self._refresh_log)
        layout.addWidget(refresh_btn)

        self._refresh_log()
        return w

    def _daemon_cmd(self, cmd: str) -> None:
        try:
            subprocess.Popen(
                [sys.executable, "-m", "kim", cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            QMessageBox.warning(self, "Daemon", f"Could not run 'kim {cmd}': {e}")

    def _restart_daemon(self) -> None:
        self._daemon_cmd("stop")
        import time

        time.sleep(1)
        self._daemon_cmd("start")

    def _refresh_log(self) -> None:
        try:
            lines = self._log_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            self._log_view.setPlainText("\n".join(lines[-30:]))
            # Scroll to bottom
            sb = self._log_view.verticalScrollBar()
            sb.setValue(sb.maximum())
        except OSError:
            self._log_view.setPlainText("(log file not found)")

    # ------------------------------------------------------------------
    # Population & save
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        self._sound_enabled.setChecked(self._config.get("sound", True))
        self._sound_file_edit.setText(self._config.get("sound_file") or "")

        slack = self._config.get("slack", {})
        self._slack_enabled.setChecked(bool(slack.get("enabled", False)))
        self._webhook_edit.setText(slack.get("webhook_url", ""))
        self._bot_token_edit.setText(slack.get("bot_token", ""))
        self._channel_edit.setText(slack.get("channel", "#general"))

    def _on_save(self) -> None:
        self._config["sound"] = self._sound_enabled.isChecked()
        sf = self._sound_file_edit.text().strip()
        self._config["sound_file"] = sf if sf else None

        self._config["slack"] = {
            "enabled": self._slack_enabled.isChecked(),
            "webhook_url": self._webhook_edit.text().strip(),
            "bot_token": self._bot_token_edit.text().strip(),
            "channel": self._channel_edit.text().strip() or "#general",
        }

        try:
            self._save_config(self._config)
        except SystemExit:
            QMessageBox.critical(self, "Error", "Could not write config file.")
            return

        self.accept()
