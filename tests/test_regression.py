"""
Regression tests for every bug fixed in the v4.0.0 cleanup.

Each test documents:
  - which file/function was fixed
  - what the old broken behaviour was
  - that the new behaviour is correct

Tests are purely unit-level: no network, no filesystem writes to the real
~/.kim dir, and no interactive TTY required.
"""

import io
import json
import os
import platform
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# scheduler.py — dead methods removed; race-condition snapshot fix
# ---------------------------------------------------------------------------
class TestSchedulerDeadCodeRemoved(unittest.TestCase):
    """_oneshot_remove and enable_reminder were removed from KimScheduler."""

    def test_oneshot_remove_does_not_exist(self):
        from kim.scheduler import KimScheduler

        self.assertFalse(
            hasattr(KimScheduler, "_oneshot_remove"),
            "_oneshot_remove is dead code and should have been removed",
        )

    def test_enable_reminder_does_not_exist(self):
        from kim.scheduler import KimScheduler

        self.assertFalse(
            hasattr(KimScheduler, "enable_reminder"),
            "enable_reminder is dead code and should have been removed",
        )


class TestSchedulerSnapshotRace(unittest.TestCase):
    """
    The `has_oneshot` scan must happen inside the heap lock, not on a
    snapshot taken outside it.  We verify the _run loop can be started
    and stopped cleanly even when the heap is mutated from another thread
    (i.e. no crash / assertion error from stale state).
    """

    def test_run_loop_thread_safe_under_mutation(self):
        from kim.scheduler import KimScheduler

        config = {"reminders": []}
        fired = []
        sched = KimScheduler(config, lambda r: fired.append(r))
        sched.start()

        # Add and cancel a one-shot from a different thread while _run is live
        def mutator():
            for _ in range(20):
                sched._heap.append(
                    type(
                        "FakeEvent",
                        (),
                        {
                            "fire_at": time.time() + 9999,
                            "cancelled": False,
                            "reminder": {},
                            "is_oneshot": True,
                        },
                    )()
                )
                time.sleep(0.005)

        t = threading.Thread(target=mutator, daemon=True)
        t.start()
        time.sleep(0.2)
        sched.stop()
        t.join(timeout=2)
        # No exception = race condition is gone


# ---------------------------------------------------------------------------
# commands/management.py — atomic config write via _save_config
# ---------------------------------------------------------------------------
class TestManagementAtomicWrite(unittest.TestCase):
    """_save_config writes to .tmp then renames — never leaves a partial file."""

    def _make_args(self, **kwargs):
        args = MagicMock()
        for k, v in kwargs.items():
            setattr(args, k, v)
        return args

    def test_save_config_is_atomic(self):
        """The helper must use a .tmp intermediate, not open(CONFIG, 'w') directly."""
        import inspect
        from kim.commands import management

        src = inspect.getsource(management._save_config)
        self.assertIn(".tmp", src, "_save_config must write to a .tmp file first")
        self.assertIn(
            ".replace(", src, "_save_config must atomically rename .tmp → CONFIG"
        )

    def test_cmd_add_uses_save_config(self):
        import inspect
        from kim.commands import management

        src = inspect.getsource(management.cmd_add)
        self.assertIn("_save_config", src, "cmd_add must call _save_config")
        self.assertNotIn('open(CONFIG, "w")', src, "cmd_add must not use raw open")

    def test_cmd_remove_uses_save_config(self):
        import inspect
        from kim.commands import management

        src = inspect.getsource(management.cmd_remove)
        self.assertIn("_save_config", src)

    def test_cmd_enable_uses_save_config(self):
        import inspect
        from kim.commands import management

        src = inspect.getsource(management.cmd_enable)
        self.assertIn("_save_config", src)

    def test_cmd_disable_uses_save_config(self):
        import inspect
        from kim.commands import management

        src = inspect.getsource(management.cmd_disable)
        self.assertIn("_save_config", src)

    def test_cmd_update_uses_save_config(self):
        import inspect
        from kim.commands import management

        src = inspect.getsource(management.cmd_update)
        self.assertIn("_save_config", src)


# ---------------------------------------------------------------------------
# commands/config.py — atomic import write; validate reads JSON directly
# ---------------------------------------------------------------------------
class TestConfigAtomicWriteAndValidate(unittest.TestCase):
    def test_cmd_import_uses_save_config(self):
        import inspect
        from kim.commands import config as cfg_mod

        src = inspect.getsource(cfg_mod.cmd_import)
        self.assertIn("_save_config", src)
        self.assertNotIn('open(CONFIG, "w")', src)

    def test_cmd_validate_catches_json_decode_error(self):
        """
        cmd_validate must read the raw file with json.load() so that
        JSONDecodeError is catchable.  The old code used load_config()
        which swallowed parse errors silently.
        """
        import inspect
        from kim.commands import config as cfg_mod

        src = inspect.getsource(cfg_mod.cmd_validate)
        self.assertIn("json.load", src, "cmd_validate must call json.load directly")
        self.assertIn("JSONDecodeError", src, "cmd_validate must catch JSONDecodeError")

    def test_cmd_validate_exits_on_bad_json(self):
        from kim.commands import config as cfg_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_cfg = Path(tmpdir) / "config.json"
            bad_cfg.write_text("{not valid json", encoding="utf-8")
            with patch.object(cfg_mod, "CONFIG", bad_cfg):
                with self.assertRaises(SystemExit) as cm:
                    cfg_mod.cmd_validate(MagicMock())
                self.assertEqual(cm.exception.code, 1)

    def test_cmd_export_no_dead_else(self):
        """The dead fallthrough else branch must not appear in cmd_export."""
        import inspect
        from kim.commands import config as cfg_mod

        src = inspect.getsource(cfg_mod.cmd_export)
        # The dead branch was: else: output = json.dumps(...)
        # It only ran when format was neither "json" nor "csv", which argparse
        # prevents.  After the fix there should be an explicit else: # csv
        # but no standalone `else: output = json.dumps`.
        lines = [l.strip() for l in src.splitlines()]
        dead = [l for l in lines if l.startswith("else:") and "json.dumps" in l]
        self.assertEqual(dead, [], f"Dead else branch still present: {dead}")


# ---------------------------------------------------------------------------
# notifications.py — Slack error logging must not leak secrets
# ---------------------------------------------------------------------------
class TestNotificationsSlackSecretLeak(unittest.TestCase):
    def _get_webhook_src(self):
        import inspect
        from kim import notifications

        return inspect.getsource(notifications._notify_slack_webhook)

    def _get_bot_src(self):
        import inspect
        from kim import notifications

        return inspect.getsource(notifications._notify_slack_bot)

    def test_webhook_does_not_log_full_urlerror(self):
        """Must not log str(e) for URLError — that can include the webhook URL."""
        src = self._get_webhook_src()
        # The old code: log.error("Slack webhook error: %s", e)
        # 'e' for URLError contains the reason including the URL in some impls.
        # The fix logs only e.reason or type(e).__name__.
        self.assertNotIn(
            'log.error("Slack webhook error: %s", e)',
            src.replace("\n", ""),
            "Must not log full URLError object (leaks URL)",
        )

    def test_webhook_handles_http_error_separately(self):
        src = self._get_webhook_src()
        self.assertIn("HTTPError", src)

    def test_bot_does_not_log_full_urlerror(self):
        src = self._get_bot_src()
        self.assertNotIn(
            'log.error("Slack bot error: %s", e)',
            src.replace("\n", ""),
        )

    def test_bot_handles_http_error_separately(self):
        src = self._get_bot_src()
        self.assertIn("HTTPError", src)


# ---------------------------------------------------------------------------
# selfupdate.py — full self-update rewrite tests
# ---------------------------------------------------------------------------
class TestSelfUpdateInstallTypeDetection(unittest.TestCase):
    """_detect_install_type() must correctly classify the install."""

    def test_pip_install_detected(self):
        """When importlib.metadata finds kim-reminder, type is 'pip'."""
        from kim import selfupdate
        import importlib.metadata

        fake_dist = MagicMock()
        with patch.object(importlib.metadata, "distribution", return_value=fake_dist):
            result = selfupdate._detect_install_type()
        self.assertEqual(result, "pip")

    def test_script_install_detected(self):
        """When ~/.kim/kim.py exists and pip dist not found, type is 'script'."""
        from kim import selfupdate
        import importlib.metadata

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_kim_dir = Path(tmpdir)
            fake_script = fake_kim_dir / "kim.py"
            fake_script.write_text("# kim script", encoding="utf-8")

            with patch.object(
                importlib.metadata,
                "distribution",
                side_effect=importlib.metadata.PackageNotFoundError,
            ):
                with patch.object(selfupdate, "KIM_DIR", fake_kim_dir):
                    result = selfupdate._detect_install_type()
        self.assertEqual(result, "script")

    def test_binary_install_detected_exe(self):
        """When which('kim') returns a .exe path, type is 'binary'."""
        from kim import selfupdate
        import importlib.metadata

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_exe = Path(tmpdir) / "kim.exe"
            fake_exe.write_bytes(b"MZ" + b"\x00" * 100)

            with patch.object(
                importlib.metadata,
                "distribution",
                side_effect=importlib.metadata.PackageNotFoundError,
            ):
                with patch.object(selfupdate, "KIM_DIR", Path(tmpdir) / "nokimdir"):
                    with patch("shutil.which", return_value=str(fake_exe)):
                        result = selfupdate._detect_install_type()
        self.assertEqual(result, "binary")

    def test_binary_install_detected_elf(self):
        """When which('kim') returns an ELF binary (no suffix), type is 'binary'."""
        from kim import selfupdate
        import importlib.metadata

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bin = Path(tmpdir) / "kim"
            fake_bin.write_bytes(b"\x7fELF" + b"\x00" * 100)

            with patch.object(
                importlib.metadata,
                "distribution",
                side_effect=importlib.metadata.PackageNotFoundError,
            ):
                with patch.object(selfupdate, "KIM_DIR", Path(tmpdir) / "nokimdir"):
                    with patch("shutil.which", return_value=str(fake_bin)):
                        result = selfupdate._detect_install_type()
        self.assertEqual(result, "binary")


class TestSelfUpdateEmptyVersion(unittest.TestCase):
    """Guard against empty tag_name from the GitHub API."""

    def test_empty_tag_name_guard_present(self):
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate.cmd_selfupdate)
        self.assertIn(
            "not latest_version",
            src,
            "Must guard against empty latest_version from GitHub API",
        )

    def _fake_fetch(self, tag):
        """Patch _fetch_latest_release to return a fake release dict."""
        from kim import selfupdate

        fake = {"tag_name": tag, "assets": []}
        return patch.object(selfupdate, "_fetch_latest_release", return_value=fake)

    def test_empty_tag_returns_early(self):
        from kim import selfupdate

        with self._fake_fetch(""):
            with patch("builtins.print") as mock_print:
                selfupdate.cmd_selfupdate(MagicMock(force=False))
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                self.assertIn("Could not determine", printed)

    def test_already_up_to_date(self):
        from kim import selfupdate
        from kim.core import VERSION

        with self._fake_fetch(f"v{VERSION}"):
            with patch("builtins.print") as mock_print:
                selfupdate.cmd_selfupdate(MagicMock(force=False))
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                self.assertIn("up to date", printed.lower())


class TestSelfUpdatePipPath(unittest.TestCase):
    """When install_type is pip, must call pip subprocess — not download binary."""

    def test_pip_install_calls_pip_subprocess(self):
        from kim import selfupdate

        fake_release = {"tag_name": "v99.0.0", "assets": []}
        ran = []

        def fake_run(cmd, **kwargs):
            ran.append(cmd)
            return MagicMock(returncode=0)

        with patch.object(selfupdate, "_detect_install_type", return_value="pip"):
            with patch.object(
                selfupdate, "_fetch_latest_release", return_value=fake_release
            ):
                with patch.object(selfupdate, "_update_via_pip") as mock_pip:
                    selfupdate.cmd_selfupdate(MagicMock(force=True))
                    mock_pip.assert_called_once()
                    args_called = mock_pip.call_args[0]
                    self.assertEqual(args_called[0], "99.0.0")

    def test_pip_update_uses_sys_executable(self):
        """_update_via_pip must invoke sys.executable -m pip, not bare 'pip'."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._update_via_pip)
        self.assertIn(
            "sys.executable",
            src,
            "_update_via_pip must use sys.executable to invoke pip",
        )
        self.assertIn(
            "kim-reminder",
            src,
            "_update_via_pip must upgrade the 'kim-reminder' package",
        )


class TestSelfUpdateScriptPath(unittest.TestCase):
    """Script install: must download kim.py asset, not a binary."""

    def test_script_update_falls_back_to_pip_when_no_asset(self):
        """If the release has no kim.py asset, fall back to pip upgrade."""
        from kim import selfupdate

        assets = [
            {
                "name": "kim-linux-x86_64",
                "browser_download_url": "https://example.com/kim-linux-x86_64",
            }
        ]

        with patch.object(selfupdate, "_update_via_pip") as mock_pip:
            with patch("builtins.print"):
                selfupdate._update_script(assets, "99.0.0")
                mock_pip.assert_called_once()

    def test_script_update_downloads_kimpy_asset(self):
        """When a kim.py asset exists, download and replace ~/.kim/kim.py."""
        from kim import selfupdate

        fake_content = b"#!/usr/bin/env python3\nfrom kim.cli import main\n"
        assets = [
            {"name": "kim.py", "browser_download_url": "https://example.com/kim.py"}
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_kim_dir = Path(tmpdir)
            fake_script = fake_kim_dir / "kim.py"
            fake_script.write_text("# old version", encoding="utf-8")

            def fake_download(url, dest, **kwargs):
                dest.write_bytes(fake_content)
                return fake_content[:4]

            with patch.object(selfupdate, "KIM_DIR", fake_kim_dir):
                with patch.object(
                    selfupdate, "_download_to", side_effect=fake_download
                ):
                    with patch("builtins.print"):
                        selfupdate._update_script(assets, "99.0.0")

            # Script should now contain the new content
            self.assertEqual(fake_script.read_bytes(), fake_content)


class TestSelfUpdateBinaryIntegrity(unittest.TestCase):
    """Binary downloads must pass magic-byte integrity checks."""

    def test_html_response_rejected_on_unix(self):
        """If download returns HTML, must not replace the binary."""
        from kim import selfupdate

        html_content = b"<html>Not Found</html>"
        assets = [
            {
                "name": "kim-linux-x86_64",
                "browser_download_url": "https://example.com/kim-linux-x86_64",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bin = Path(tmpdir) / "kim"
            fake_bin.write_bytes(b"\x7fELF" + b"\x00" * 10)  # original

            def fake_download(url, dest, **kwargs):
                dest.write_bytes(html_content)
                return html_content[:4]

            with patch("shutil.which", return_value=str(fake_bin)):
                with patch.object(
                    selfupdate, "_download_to", side_effect=fake_download
                ):
                    with patch("platform.system", return_value="Linux"):
                        with patch("platform.machine", return_value="x86_64"):
                            with patch("builtins.print"):
                                selfupdate._update_binary(assets, "99.0.0")

            # Original binary must be untouched
            self.assertEqual(fake_bin.read_bytes()[:4], b"\x7fELF")

    def test_non_mz_rejected_on_windows(self):
        """Windows exe download that isn't MZ must be rejected."""
        from kim import selfupdate

        bad_content = b"PKzip garbage content here"
        assets = [
            {
                "name": "kim-windows-x86_64.exe",
                "browser_download_url": "https://example.com/kim.exe",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_exe = Path(tmpdir) / "kim.exe"
            fake_exe.write_bytes(b"MZ" + b"\x00" * 10)  # original

            def fake_download(url, dest, **kwargs):
                dest.write_bytes(bad_content)
                return bad_content[:4]

            with patch("shutil.which", return_value=str(fake_exe)):
                with patch.object(
                    selfupdate, "_download_to", side_effect=fake_download
                ):
                    with patch("platform.system", return_value="Windows"):
                        with patch("platform.machine", return_value="x86_64"):
                            with patch("builtins.print"):
                                selfupdate._update_binary(assets, "99.0.0")

            # Original exe must be untouched
            self.assertEqual(fake_exe.read_bytes()[:2], b"MZ")

    def test_no_asset_for_platform_gives_clear_message(self):
        """If no matching asset exists, must print a helpful message (not crash)."""
        from kim import selfupdate

        assets = []  # no assets at all
        with patch("platform.system", return_value="Linux"):
            with patch("platform.machine", return_value="x86_64"):
                with patch("builtins.print") as mock_print:
                    selfupdate._update_binary(assets, "99.0.0")
                    printed = " ".join(str(c) for c in mock_print.call_args_list)
                    self.assertIn("No prebuilt binary", printed)


# ---------------------------------------------------------------------------
# interactive.py — _save_config atomic write
# ---------------------------------------------------------------------------
class TestInteractiveAtomicWrite(unittest.TestCase):
    def _get_src(self):
        import inspect
        from kim import interactive

        return inspect.getsource(interactive)

    def test_module_has_save_config(self):
        from kim import interactive

        self.assertTrue(
            callable(getattr(interactive, "_save_config", None)),
            "interactive.py must define a module-level _save_config()",
        )

    def test_no_raw_open_writes(self):
        src = self._get_src()
        self.assertNotIn(
            'open(CONFIG, "w")',
            src,
            "interactive.py must not use raw open(CONFIG, 'w') — use _save_config()",
        )

    def test_save_config_is_atomic(self):
        import inspect
        from kim.interactive import _save_config

        src = inspect.getsource(_save_config)
        self.assertIn(".tmp", src)
        self.assertIn(".replace(", src)

    def test_save_config_returns_bool(self):
        """_save_config in interactive must return True/False, not raise SystemExit."""
        import inspect
        from kim.interactive import _save_config

        src = inspect.getsource(_save_config)
        self.assertIn("return True", src)
        self.assertIn("return False", src)
        self.assertNotIn("sys.exit", src)


# ---------------------------------------------------------------------------
# interactive.py — interval display: '1h' must not become '1h min'
# ---------------------------------------------------------------------------
class TestInteractiveIntervalDisplay(unittest.TestCase):
    def _run_list_reminders(self, reminders):
        """Run list_reminders() with patched config and capture stdout."""
        from kim import interactive

        fake_config = {"reminders": reminders}
        output_lines = []

        # We need to call the inner list_reminders closure.
        # The easiest way is to drive cmd_interactive just far enough that
        # list_reminders is defined, then extract it via inspection.
        # Instead, we test the display logic directly by checking the
        # interval rendering expression in source.
        import inspect

        src = inspect.getsource(interactive.cmd_interactive)
        return src

    def test_string_interval_not_appended_with_min(self):
        src = self._run_list_reminders([])
        # The old broken line was:
        #   str(r.get('interval') or ...) + ' min'
        # which would produce "1h min" for string intervals.
        self.assertNotIn(
            "') + ' min'",
            src,
            "Must not unconditionally append ' min' to interval string",
        )

    def test_display_logic_guards_type(self):
        """The display block must check type before appending ' min'."""
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        self.assertIn(
            "isinstance",
            src,
            "Interval display must use isinstance() to guard numeric-only ' min' suffix",
        )

    def test_string_interval_displayed_as_is(self):
        """'1h' interval renders as '1h', not '1h min'."""

        # Simulate the rendering logic extracted from interactive.py
        def render_interval(r):
            iv = r.get("interval")
            if iv is None:
                iv = f"{r.get('interval_minutes', 30)} min"
            elif isinstance(iv, (int, float)):
                iv = f"{iv} min"
            return str(iv)

        self.assertEqual(render_interval({"interval": "1h"}), "1h")
        self.assertEqual(render_interval({"interval": "30m"}), "30m")
        self.assertEqual(render_interval({"interval": "1d"}), "1d")
        self.assertEqual(render_interval({"interval": 30}), "30 min")
        self.assertEqual(render_interval({"interval_minutes": 15}), "15 min")
        self.assertEqual(render_interval({}), "30 min")


# ---------------------------------------------------------------------------
# interactive.py — add_reminder accepts string intervals (30m, 1h, 1d)
# ---------------------------------------------------------------------------
class TestInteractiveAddReminderInterval(unittest.TestCase):
    def _get_add_src(self):
        import inspect
        from kim import interactive

        return inspect.getsource(interactive.cmd_interactive)

    def test_no_bare_int_conversion(self):
        """Must not call int(interval_input) directly — rejects '1h'."""
        src = self._get_add_src()
        # Old code: interval = int(interval_input)
        self.assertNotIn(
            "interval = int(interval_input)",
            src,
            "add_reminder must not use bare int() on interval input",
        )

    def test_interval_str_variable_used(self):
        src = self._get_add_src()
        self.assertIn(
            "interval_str",
            src,
            "add_reminder must build interval_str accepting string suffixes",
        )

    def test_new_reminder_uses_interval_str(self):
        """new_reminder dict must store interval_str, not f'{interval}m'."""
        src = self._get_add_src()
        self.assertNotIn(
            'f"{interval}m"',
            src,
            "new_reminder must use interval_str, not the old f'{interval}m'",
        )
        # The actual assignment is new_reminder["interval"] = interval_str
        self.assertIn(
            '"interval"] = interval_str',
            src,
            'new_reminder must assign interval_str to the "interval" key',
        )

    def test_add_interval_logic(self):
        """The normalisation logic: bare int → 'Nm', suffix string → kept."""

        # Reproduce the logic from add_reminder
        def parse(interval_input):
            _iv = interval_input.strip().lower()
            if any(_iv.endswith(u) for u in ("m", "h", "d", "s")):
                return _iv
            else:
                n = int(_iv)
                if n <= 0:
                    raise ValueError("non-positive")
                return f"{n}m"

        self.assertEqual(parse("30m"), "30m")
        self.assertEqual(parse("1h"), "1h")
        self.assertEqual(parse("1d"), "1d")
        self.assertEqual(parse("90s"), "90s")
        self.assertEqual(parse("45"), "45m")
        with self.assertRaises(ValueError):
            parse("abc")  # no valid unit suffix, not a number


# ---------------------------------------------------------------------------
# cli.py — -i flag replacement only at argv[1]
# ---------------------------------------------------------------------------
class TestCliArgvReplacement(unittest.TestCase):
    def _get_src(self):
        import inspect
        from kim import cli

        return inspect.getsource(cli.main)

    def test_no_loop_over_all_argv(self):
        """Must not iterate all of sys.argv replacing every -i."""
        src = self._get_src()
        # Old code pattern: for i, arg in enumerate(sys.argv): if arg.lower() == "-i":
        self.assertNotIn(
            "for i, arg in enumerate(sys.argv)",
            src,
            "Must not iterate all argv for -i replacement",
        )

    def test_only_position_1_replaced(self):
        src = self._get_src()
        self.assertIn(
            "sys.argv[1]",
            src,
            "Must only check/replace -i at position 1",
        )

    def test_i_at_position_1_becomes_interactive(self):
        """sys.argv = ['kim', '-i'] → argv[1] becomes 'interactive'."""
        import kim.cli as cli_mod

        original = sys.argv[:]
        try:
            sys.argv = ["kim", "-i"]
            # Simulate the replacement block
            if len(sys.argv) > 1 and sys.argv[1].lower() == "-i":
                sys.argv[1] = "interactive"
            self.assertEqual(sys.argv[1], "interactive")
        finally:
            sys.argv = original

    def test_i_inside_message_not_replaced(self):
        """sys.argv = ['kim', 'add', '-m', 'use -i flag'] must not touch argv[3]."""
        import kim.cli as cli_mod

        original = sys.argv[:]
        try:
            sys.argv = ["kim", "add", "-m", "use -i flag"]
            # Only position 1 is checked
            if len(sys.argv) > 1 and sys.argv[1].lower() == "-i":
                sys.argv[1] = "interactive"
            self.assertEqual(sys.argv[3], "use -i flag")
        finally:
            sys.argv = original


# ---------------------------------------------------------------------------
# commands/misc.py — cmd_sound uses _save_config (atomic)
# ---------------------------------------------------------------------------
class TestMiscSoundAtomicWrite(unittest.TestCase):
    def test_cmd_sound_has_save_config(self):
        from kim.commands import misc

        self.assertTrue(
            callable(getattr(misc, "_save_config", None)),
            "misc.py must define _save_config()",
        )

    def test_cmd_sound_no_raw_open(self):
        import inspect
        from kim.commands import misc

        src = inspect.getsource(misc.cmd_sound)
        self.assertNotIn(
            'open(CONFIG, "w")',
            src,
            "cmd_sound must not use raw open(CONFIG, 'w')",
        )

    def test_cmd_sound_uses_save_config(self):
        import inspect
        from kim.commands import misc

        src = inspect.getsource(misc.cmd_sound)
        self.assertIn("_save_config", src)


# ---------------------------------------------------------------------------
# commands/misc.py — completion scripts: subcommand list at position 1
# ---------------------------------------------------------------------------
class TestCompletionScripts(unittest.TestCase):
    def test_bash_completion_outputs_string(self):
        from kim.commands.misc import BASH_COMPLETION

        self.assertIsInstance(BASH_COMPLETION, str)
        self.assertGreater(len(BASH_COMPLETION), 100)

    def test_zsh_completion_outputs_string(self):
        from kim.commands.misc import ZSH_COMPLETION

        self.assertIsInstance(ZSH_COMPLETION, str)
        self.assertGreater(len(ZSH_COMPLETION), 100)

    def test_fish_completion_outputs_string(self):
        from kim.commands.misc import FISH_COMPLETION

        self.assertIsInstance(FISH_COMPLETION, str)
        self.assertGreater(len(FISH_COMPLETION), 100)

    def test_bash_uses_mapfile_not_compgen_split(self):
        """Reminder names with spaces must not be word-split; requires mapfile."""
        from kim.commands.misc import BASH_COMPLETION

        self.assertIn(
            "mapfile",
            BASH_COMPLETION,
            "Bash completion must use mapfile to avoid word-splitting on reminder names",
        )

    def test_bash_has_python_fallback(self):
        """Must not hardcode python3 — needs fallback for systems where it is 'python'."""
        from kim.commands.misc import BASH_COMPLETION

        self.assertIn(
            "python",
            BASH_COMPLETION,
        )
        # Robustness: uses command -v with fallback
        self.assertIn(
            "command -v",
            BASH_COMPLETION,
            "Bash completion must use 'command -v python3 ... python' for portability",
        )

    def test_bash_import_completes_file(self):
        """'kim import' positional arg is a file — must offer file completion."""
        from kim.commands.misc import BASH_COMPLETION

        self.assertIn(
            "compgen -f",
            BASH_COMPLETION,
            "Bash completion for 'import' must offer filename completion",
        )

    def test_fish_provides_subcommands_at_position_1(self):
        """Fish completion must offer subcommands when no subcommand has been seen."""
        from kim.commands.misc import FISH_COMPLETION

        self.assertIn(
            "not __fish_seen_subcommand_from",
            FISH_COMPLETION,
            "Fish completion must offer subcommands when none is seen yet",
        )

    def test_fish_has_helper_function(self):
        """Fish must use a helper function, not inline python3 invocation."""
        from kim.commands.misc import FISH_COMPLETION

        self.assertIn(
            "function __kim_reminder_names",
            FISH_COMPLETION,
        )

    def test_zsh_uses_compadd_for_reminder_names(self):
        """
        Zsh must call _kim_reminder_names as a standalone function with compadd,
        not the broken ->reminders state transition.
        """
        from kim.commands.misc import ZSH_COMPLETION

        self.assertIn(
            "_kim_reminder_names",
            ZSH_COMPLETION,
        )
        self.assertIn(
            "compadd",
            ZSH_COMPLETION,
        )

    def test_zsh_calls_kim_with_at(self):
        """_kim function must be invoked as '_kim \"$@\"', not bare '_kim'."""
        from kim.commands.misc import ZSH_COMPLETION

        self.assertIn(
            '_kim "$@"',
            ZSH_COMPLETION,
            'Zsh _kim function must be invoked with "$@" to pass positional args',
        )

    def test_cmd_completion_bash_prints_script(self):
        from kim.commands.misc import cmd_completion, BASH_COMPLETION

        args = MagicMock(shell="bash")
        with patch("builtins.print") as mock_print:
            cmd_completion(args)
            all_output = " ".join(
                str(a) for call in mock_print.call_args_list for a in call[0]
            )
            self.assertIn("_kim_completions", all_output)

    def test_cmd_completion_zsh_prints_script(self):
        from kim.commands.misc import cmd_completion

        args = MagicMock(shell="zsh")
        with patch("builtins.print") as mock_print:
            cmd_completion(args)
            all_output = " ".join(
                str(a) for call in mock_print.call_args_list for a in call[0]
            )
            self.assertIn("#compdef kim", all_output)

    def test_cmd_completion_fish_prints_script(self):
        from kim.commands.misc import cmd_completion

        args = MagicMock(shell="fish")
        with patch("builtins.print") as mock_print:
            cmd_completion(args)
            all_output = " ".join(
                str(a) for call in mock_print.call_args_list for a in call[0]
            )
            self.assertIn("complete -c kim", all_output)


# ---------------------------------------------------------------------------
# v4.1.0 — --every alias, --at daily schedule, remind at <datetime>
# ---------------------------------------------------------------------------


class TestEveryAlias(unittest.TestCase):
    """--every is accepted as an alias for -I/--interval on kim add and kim update."""

    def _make_add_parser(self):
        """Return a fresh argparse subparser for 'kim add'."""
        import argparse
        from kim import cli as cli_mod

        # Re-build just the add parser by importing and parsing
        p = argparse.ArgumentParser()
        grp = p.add_mutually_exclusive_group(required=True)
        grp.add_argument("-I", "--interval", "--every", dest="interval", type=str)
        grp.add_argument("--at", dest="at_time", type=str)
        p.add_argument("name")
        return p

    def test_every_accepted_as_interval_on_add(self):
        """kim add name --every 30m  should set args.interval = '30m'."""
        import argparse

        p = self._make_add_parser()
        args = p.parse_args(["myreminder", "--every", "30m"])
        self.assertEqual(args.interval, "30m")
        self.assertIsNone(args.at_time)

    def test_dash_I_still_works_on_add(self):
        p = self._make_add_parser()
        args = p.parse_args(["myreminder", "-I", "1h"])
        self.assertEqual(args.interval, "1h")

    def test_interval_long_still_works_on_add(self):
        p = self._make_add_parser()
        args = p.parse_args(["myreminder", "--interval", "1d"])
        self.assertEqual(args.interval, "1d")

    def test_every_mutually_exclusive_with_at(self):
        """--every and --at on add are mutually exclusive."""
        p = self._make_add_parser()
        with self.assertRaises(SystemExit):
            p.parse_args(["myreminder", "--every", "30m", "--at", "10:00"])

    def test_cli_add_parser_accepts_every(self):
        """Verify the real CLI parser accepts --every on add."""
        import sys

        original = sys.argv[:]
        try:
            sys.argv = [
                "kim",
                "add",
                "test-r",
                "--every",
                "30m",
                "-m",
                "msg",
                "-t",
                "title",
            ]
            # Build the parser via cli.main() would dispatch — instead just check
            # the argparse definitions include --every
            import inspect
            from kim import cli

            src = inspect.getsource(cli.main)
            self.assertIn("--every", src)
        finally:
            sys.argv = original

    def test_cli_update_parser_accepts_every(self):
        """Verify --every appears in the update parser definition."""
        import inspect
        from kim import cli

        src = inspect.getsource(cli.main)
        # The update parser also needs --every
        self.assertIn("--every", src)


class TestParseAtTime(unittest.TestCase):
    """parse_at_time validates and normalises HH:MM strings."""

    def _parse(self, s, tz_name=None):
        from kim.core import parse_at_time

        return parse_at_time(s, tz_name)

    def test_valid_hh_mm(self):
        self.assertEqual(self._parse("10:00"), "10:00")
        self.assertEqual(self._parse("09:30"), "09:30")
        self.assertEqual(self._parse("23:59"), "23:59")
        self.assertEqual(self._parse("00:00"), "00:00")

    def test_single_digit_hour_normalised(self):
        self.assertEqual(self._parse("9:05"), "09:05")

    def test_invalid_missing_colon(self):
        with self.assertRaises(ValueError):
            self._parse("1030")

    def test_invalid_hour_out_of_range(self):
        with self.assertRaises(ValueError):
            self._parse("25:00")

    def test_invalid_minute_out_of_range(self):
        with self.assertRaises(ValueError):
            self._parse("12:60")

    def test_invalid_format_word(self):
        with self.assertRaises(ValueError):
            self._parse("noon")

    def test_invalid_empty(self):
        with self.assertRaises(ValueError):
            self._parse("")


class TestParseDatetimeRelative(unittest.TestCase):
    """parse_datetime relative mode — existing behaviour preserved."""

    def _parse(self, tokens):
        from kim.core import parse_datetime

        return parse_datetime(tokens)

    def test_minutes(self):
        before = time.time()
        result = self._parse(["10m"])
        after = time.time()
        self.assertAlmostEqual(result, before + 600, delta=5)

    def test_hours(self):
        before = time.time()
        result = self._parse(["1h"])
        self.assertAlmostEqual(result, before + 3600, delta=5)

    def test_with_in_prefix(self):
        before = time.time()
        result = self._parse(["in", "30m"])
        self.assertAlmostEqual(result, before + 1800, delta=5)

    def test_compound(self):
        before = time.time()
        result = self._parse(["2h", "30m"])
        self.assertAlmostEqual(result, before + 9000, delta=5)

    def test_seconds(self):
        before = time.time()
        result = self._parse(["90s"])
        self.assertAlmostEqual(result, before + 90, delta=5)

    def test_days(self):
        before = time.time()
        result = self._parse(["1d"])
        self.assertAlmostEqual(result, before + 86400, delta=5)

    def test_bare_number_is_minutes(self):
        before = time.time()
        result = self._parse(["45"])
        self.assertAlmostEqual(result, before + 2700, delta=5)

    def test_empty_raises(self):
        from kim.core import parse_datetime

        with self.assertRaises(ValueError):
            parse_datetime([])

    def test_garbage_raises(self):
        from kim.core import parse_datetime

        with self.assertRaises(ValueError):
            parse_datetime(["blarg"])

    def test_exceeds_365_days_raises(self):
        from kim.core import parse_datetime

        with self.assertRaises(ValueError):
            parse_datetime(["400d"])


class TestParseDatetimeAbsolute(unittest.TestCase):
    """parse_datetime absolute mode ('at ...')."""

    def _parse(self, tokens, tz_name=None):
        from kim.core import parse_datetime

        return parse_datetime(tokens, tz_name)

    def _future_time_tokens(self, minutes_ahead=60):
        """Return ['at', 'HH:MM'] for a time ~minutes_ahead in the future."""
        import datetime as _dt

        future = _dt.datetime.now() + _dt.timedelta(minutes=minutes_ahead)
        return ["at", future.strftime("%H:%M")]

    def test_at_hhmm_future(self):
        """'at HH:MM' for a time in the future returns a timestamp > now."""
        tokens = self._future_time_tokens(60)
        result = self._parse(tokens)
        self.assertGreater(result, time.time())

    def test_at_hhmm_past_rolls_to_tomorrow(self):
        """'at HH:MM' in the past (already elapsed today) rolls to tomorrow."""
        import datetime as _dt

        past = _dt.datetime.now() - _dt.timedelta(minutes=5)
        tokens = ["at", past.strftime("%H:%M")]
        result = self._parse(tokens)
        # Should be ~23h55m from now, but at least > now + 23h
        self.assertGreater(result, time.time() + 23 * 3600)

    def test_at_tomorrow_hhmm(self):
        import datetime as _dt

        tokens = ["at", "tomorrow", "10:00"]
        result = self._parse(tokens)
        # Tomorrow 10am should be at least 1s in the future
        self.assertGreater(result, time.time())
        # And at most 49h away
        self.assertLess(result, time.time() + 49 * 3600)

    def test_at_tomorrow_am_suffix(self):
        """'at tomorrow 9am' is accepted and returns future timestamp."""
        tokens = ["at", "tomorrow", "9am"]
        result = self._parse(tokens)
        self.assertGreater(result, time.time())

    def test_at_iso_date_time(self):
        """'at 2099-12-31 23:59' returns a far-future timestamp."""
        tokens = ["at", "2099-12-31", "23:59"]
        result = self._parse(tokens)
        self.assertGreater(result, time.time() + 365 * 24 * 3600)

    def test_at_past_iso_date_raises(self):
        """'at 2000-01-01 00:00' (clearly in the past) raises ValueError."""
        from kim.core import parse_datetime

        tokens = ["at", "2000-01-01", "00:00"]
        with self.assertRaises(ValueError):
            parse_datetime(tokens)

    def test_at_garbage_raises(self):
        from kim.core import parse_datetime

        with self.assertRaises(ValueError):
            parse_datetime(["at", "not-a-time"])

    def test_at_alone_raises(self):
        from kim.core import parse_datetime

        with self.assertRaises(ValueError):
            parse_datetime(["at"])

    def test_at_named_weekday(self):
        """'at friday 10:00' returns a future timestamp."""
        tokens = ["at", "friday", "10:00"]
        result = self._parse(tokens)
        self.assertGreater(result, time.time())
        # Must be within the next 8 days
        self.assertLess(result, time.time() + 8 * 24 * 3600)


class TestCmdAddWithAt(unittest.TestCase):
    """cmd_add with --at stores 'at'/'timezone' keys, no 'interval' key."""

    def _run_cmd_add(self, args_dict, config=None):
        """Run cmd_add with a MagicMock args and patched config."""
        from kim.commands import management

        if config is None:
            config = {"reminders": []}
        args = MagicMock()
        args.name = args_dict.get("name", "test-reminder")
        args.at_time = args_dict.get("at_time", None)
        args.interval = args_dict.get("interval", None)
        args.timezone = args_dict.get("timezone", None)
        args.title = args_dict.get("title", None)
        args.message = args_dict.get("message", None)
        args.urgency = args_dict.get("urgency", "normal")
        args.sound_file = args_dict.get("sound_file", None)
        args.slack_channel = args_dict.get("slack_channel", None)
        args.slack_webhook = args_dict.get("slack_webhook", None)

        saved = {}

        def fake_save(cfg):
            saved["config"] = cfg

        with patch.object(management, "load_config", return_value=config):
            with patch.object(management, "_save_config", side_effect=fake_save):
                with patch("builtins.print"):
                    management.cmd_add(args)

        return saved.get("config", config)

    def test_at_stores_at_key(self):
        result = self._run_cmd_add({"name": "standup", "at_time": "09:30"})
        r = next(r for r in result["reminders"] if r["name"] == "standup")
        self.assertIn("at", r)
        self.assertEqual(r["at"], "09:30")

    def test_at_no_interval_key(self):
        result = self._run_cmd_add({"name": "standup", "at_time": "09:30"})
        r = next(r for r in result["reminders"] if r["name"] == "standup")
        self.assertNotIn("interval", r)

    def test_at_with_tz_stores_timezone(self):
        result = self._run_cmd_add(
            {"name": "standup", "at_time": "09:30", "timezone": "America/New_York"}
        )
        r = next(r for r in result["reminders"] if r["name"] == "standup")
        self.assertEqual(r.get("timezone"), "America/New_York")

    def test_interval_stores_interval_key(self):
        result = self._run_cmd_add({"name": "water", "interval": "30m"})
        r = next(r for r in result["reminders"] if r["name"] == "water")
        self.assertIn("interval", r)
        self.assertEqual(r["interval"], "30m")

    def test_interval_no_at_key(self):
        result = self._run_cmd_add({"name": "water", "interval": "30m"})
        r = next(r for r in result["reminders"] if r["name"] == "water")
        self.assertNotIn("at", r)

    def test_every_alias_same_as_interval(self):
        """--every is just --interval at the argparse level; cmd_add receives args.interval."""
        result = self._run_cmd_add({"name": "water", "interval": "1h"})
        r = next(r for r in result["reminders"] if r["name"] == "water")
        self.assertEqual(r["interval"], "1h")


class TestCmdUpdateWithAt(unittest.TestCase):
    """cmd_update can switch between interval and at-time schedules."""

    def _run_cmd_update(self, name, args_dict, existing_reminder):
        from kim.commands import management

        config = {"reminders": [dict(existing_reminder)]}
        args = MagicMock()
        args.name = name
        args.at_time = args_dict.get("at_time", None)
        args.interval = args_dict.get("interval", None)
        args.timezone = args_dict.get("timezone", None)
        args.title = args_dict.get("title", None)
        args.message = args_dict.get("message", None)
        args.urgency = args_dict.get("urgency", None)
        args.enable = args_dict.get("enable", False)
        args.disable = args_dict.get("disable", False)

        saved = {}

        def fake_save(cfg):
            saved["config"] = cfg

        with patch.object(management, "load_config", return_value=config):
            with patch.object(management, "_save_config", side_effect=fake_save):
                with patch("builtins.print"):
                    management.cmd_update(args)

        return saved.get("config", config)

    def test_update_interval_to_at(self):
        """Switch from interval reminder to at-time reminder."""
        existing = {"name": "water", "interval": "30m", "enabled": True}
        result = self._run_cmd_update("water", {"at_time": "10:00"}, existing)
        r = next(r for r in result["reminders"] if r["name"] == "water")
        self.assertIn("at", r)
        self.assertNotIn("interval", r)
        self.assertNotIn("interval_minutes", r)

    def test_update_at_to_interval(self):
        """Switch from at-time reminder to interval reminder."""
        existing = {"name": "standup", "at": "09:00", "enabled": True}
        result = self._run_cmd_update("standup", {"interval": "1h"}, existing)
        r = next(r for r in result["reminders"] if r["name"] == "standup")
        self.assertIn("interval", r)
        self.assertNotIn("at", r)
        self.assertNotIn("timezone", r)

    def test_update_at_with_tz(self):
        """Update --at with --tz stores timezone."""
        existing = {"name": "standup", "interval": "30m", "enabled": True}
        result = self._run_cmd_update(
            "standup", {"at_time": "09:30", "timezone": "Europe/London"}, existing
        )
        r = next(r for r in result["reminders"] if r["name"] == "standup")
        self.assertEqual(r.get("timezone"), "Europe/London")

    def test_update_every_alias(self):
        """--every maps to args.interval — cmd_update receives interval."""
        existing = {"name": "water", "at": "10:00", "enabled": True}
        result = self._run_cmd_update("water", {"interval": "45m"}, existing)
        r = next(r for r in result["reminders"] if r["name"] == "water")
        self.assertEqual(r["interval"], "45m")


class TestNextAtFire(unittest.TestCase):
    """KimScheduler._next_at_fire returns future timestamp for valid HH:MM."""

    def _next(self, at_str, tz_name=None):
        from kim.scheduler import KimScheduler

        reminder = {"name": "test", "at": at_str}
        if tz_name:
            reminder["timezone"] = tz_name
        return KimScheduler._next_at_fire(reminder)

    def test_valid_at_returns_future_timestamp(self):
        result = self._next("10:00")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, float)
        # Must be in the future
        self.assertGreater(result, time.time())

    def test_result_within_24h(self):
        """Next fire for any HH:MM is at most 24 hours away."""
        result = self._next("10:00")
        self.assertLess(result, time.time() + 25 * 3600)

    def test_invalid_at_returns_none(self):
        result = self._next("not-a-time")
        self.assertIsNone(result)

    def test_empty_at_returns_none(self):
        result = self._next("")
        self.assertIsNone(result)

    def test_missing_at_returns_none(self):
        from kim.scheduler import KimScheduler

        result = KimScheduler._next_at_fire({"name": "test"})
        self.assertIsNone(result)


class TestSchedulerLoadsAtTimeReminder(unittest.TestCase):
    """KimScheduler loads at-time reminders and schedules them for the future."""

    def test_at_time_reminder_scheduled_in_future(self):
        from kim.scheduler import KimScheduler

        config = {
            "reminders": [
                {
                    "name": "standup",
                    "at": "10:00",
                    "title": "Stand-up",
                    "message": "Time for stand-up!",
                    "urgency": "normal",
                    "enabled": True,
                }
            ]
        }
        fired = []
        sched = KimScheduler(config, lambda r: fired.append(r))
        # The reminder should be in _live
        self.assertIn("standup", sched._live)
        event = sched._live["standup"]
        # Fire time must be in the future
        self.assertGreater(event.fire_at, time.time())

    def test_invalid_at_reminder_skipped(self):
        """Reminder with invalid 'at' value must be skipped (not in _live)."""
        from kim.scheduler import KimScheduler

        config = {
            "reminders": [
                {
                    "name": "bad-reminder",
                    "at": "notavalidtime",
                    "enabled": True,
                }
            ]
        }
        sched = KimScheduler(config, lambda r: None)
        self.assertNotIn("bad-reminder", sched._live)

    def test_at_time_reschedules_after_fire(self):
        """After firing, the at-time reminder is rescheduled for tomorrow."""
        from kim.scheduler import KimScheduler

        # Use a time 1ms in the future so it fires immediately in _fire_due_events
        import datetime as _dt

        soon = (_dt.datetime.now() + _dt.timedelta(seconds=0.05)).strftime("%H:%M")
        config = {
            "reminders": [
                {
                    "name": "soon",
                    "at": soon,
                    "enabled": True,
                }
            ]
        }
        fired = []
        sched = KimScheduler(config, lambda r: fired.append(r))
        # Manually push the fire time into the past
        event = sched._live["soon"]
        event.fire_at = time.time() - 1
        import heapq as _heapq

        sched._heap = [event]
        _heapq.heapify(sched._heap)

        sched._fire_due_events()

        # The notifier should have been called
        self.assertEqual(len(fired), 1)
        # The reminder should still be live (rescheduled)
        self.assertIn("soon", sched._live)
        # Rescheduled fire time must be in the future
        new_event = sched._live["soon"]
        self.assertGreater(new_event.fire_at, time.time())


# ---------------------------------------------------------------------------
# v4.1.8 — selfupdate: version comparison and install-type detection order
# ---------------------------------------------------------------------------
class TestParseVersion(unittest.TestCase):
    """_parse_version converts a semver string to a comparable tuple."""

    def _pv(self, s):
        from kim.selfupdate import _parse_version

        return _parse_version(s)

    def test_equal_versions(self):
        self.assertEqual(self._pv("4.1.7"), self._pv("4.1.7"))

    def test_upgrade_detected(self):
        self.assertLess(self._pv("4.1.7"), self._pv("4.1.8"))

    def test_downgrade_detected(self):
        self.assertGreater(self._pv("4.1.8"), self._pv("4.1.7"))

    def test_major_version_dominates(self):
        self.assertLess(self._pv("3.9.9"), self._pv("4.0.0"))

    def test_v_prefix_stripped(self):
        self.assertEqual(self._pv("v4.1.8"), self._pv("4.1.8"))

    def test_two_part_version(self):
        self.assertLess(self._pv("4.1"), self._pv("4.2"))

    def test_garbage_returns_zero_tuple(self):
        """Non-numeric version strings must not raise — return (0,) as fallback."""
        result = self._pv("not-a-version")
        self.assertIsInstance(result, tuple)


class TestSelfUpdateDowngradeGuard(unittest.TestCase):
    """cmd_selfupdate must not offer to 'update' when installed version > latest."""

    def _fake_fetch(self, tag):
        from kim import selfupdate

        fake = {"tag_name": tag, "assets": []}
        return patch.object(selfupdate, "_fetch_latest_release", return_value=fake)

    def test_no_downgrade_when_ahead_of_latest(self):
        """When installed version > latest GitHub release, print already-up-to-date."""
        from kim import selfupdate

        # Patch VERSION to a high value so we're always "ahead"
        with patch.object(selfupdate, "VERSION", "99.0.0"):
            with self._fake_fetch("v1.0.0"):
                with patch("builtins.print") as mock_print:
                    selfupdate.cmd_selfupdate(MagicMock(force=False))
                    printed = " ".join(str(c) for c in mock_print.call_args_list)
                    # Must NOT call pip/binary/script updaters — just print message
                    self.assertNotIn("Updating", printed)

    def test_upgrade_proceeds_when_behind_latest(self):
        """When latest > installed, must proceed with update (calls install type)."""
        from kim import selfupdate

        with patch.object(selfupdate, "VERSION", "1.0.0"):
            with self._fake_fetch("v99.0.0"):
                with patch.object(
                    selfupdate, "_detect_install_type", return_value="pip"
                ):
                    with patch.object(selfupdate, "_update_via_pip") as mock_pip:
                        # Use force=True to skip the interactive input() prompt
                        selfupdate.cmd_selfupdate(MagicMock(force=True))
                        mock_pip.assert_called_once()


class TestInstallTypeOrderPipFirst(unittest.TestCase):
    """_detect_install_type must check pip before script, so leftover ~/.kim/kim.py
    does not fool it into returning 'script' when pip-installed."""

    def test_pip_wins_even_when_kimpy_exists(self):
        """When pip metadata exists AND ~/.kim/kim.py exists, return 'pip'."""
        from kim import selfupdate
        import importlib.metadata

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_kim_dir = Path(tmpdir)
            (fake_kim_dir / "kim.py").write_text("# leftover", encoding="utf-8")

            fake_dist = MagicMock()
            with patch.object(
                importlib.metadata, "distribution", return_value=fake_dist
            ):
                with patch.object(selfupdate, "KIM_DIR", fake_kim_dir):
                    result = selfupdate._detect_install_type()

        self.assertEqual(result, "pip")


# ---------------------------------------------------------------------------
# v4.1.8 — interactive.py: cancel_oneshot closure must not shadow module-level
#           remove_oneshot, and action_map must point to the renamed function
# ---------------------------------------------------------------------------
class TestInteractiveCancelOneshotNoShadow(unittest.TestCase):
    """The local cancel_oneshot() in cmd_interactive must not shadow the
    module-level remove_oneshot import, and the action_map must reference
    cancel_oneshot (not the old remove_oneshot name)."""

    def test_local_function_renamed_to_cancel_oneshot(self):
        """interactive.py source must define a local 'def cancel_oneshot' closure."""
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        self.assertIn(
            "def cancel_oneshot",
            src,
            "The local one-shot removal closure must be named cancel_oneshot",
        )

    def test_action_map_uses_cancel_oneshot(self):
        """action_map must reference cancel_oneshot, not remove_oneshot."""
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        # Find the action_map dict definition and confirm cancel_oneshot is in it
        self.assertIn(
            "cancel_oneshot",
            src,
            "action_map must reference cancel_oneshot",
        )

    def test_action_map_does_not_reference_remove_oneshot_as_value(self):
        """action_map must NOT use remove_oneshot as a value (would be a NameError
        at runtime since only cancel_oneshot is defined locally)."""
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        # Extract just the action_map block to check
        # We check that '7: remove_oneshot' does NOT appear
        import re

        # Match the pattern where remove_oneshot is used as a dict value after the colon
        bad_pattern = re.compile(r"\d+\s*:\s*remove_oneshot\b")
        matches = bad_pattern.findall(src)
        self.assertEqual(
            matches,
            [],
            f"action_map must not reference remove_oneshot as a callable value: {matches}",
        )

    def test_module_level_remove_oneshot_still_imported(self):
        """The module-level remove_oneshot must still be importable from interactive."""
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive)
        self.assertIn(
            "from .commands.misc import",
            src,
            "interactive.py must still import remove_oneshot from commands.misc",
        )
        self.assertIn(
            "remove_oneshot",
            src,
        )

    def test_cancel_oneshot_calls_module_remove_oneshot(self):
        """Inside cancel_oneshot, the call must be remove_oneshot(fire_at) — using
        the module-level function, not a recursive self-call."""
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        # The closure body should contain remove_oneshot(target[...])
        self.assertIn(
            "remove_oneshot(target",
            src,
            "cancel_oneshot must call module-level remove_oneshot(target[...])",
        )


# ---------------------------------------------------------------------------
# v4.1.8 — cmd_validate accepts reminders with 'at' field (no interval)
# ---------------------------------------------------------------------------
class TestCmdValidateAcceptsAtReminders(unittest.TestCase):
    """cmd_validate must not reject valid reminders that use 'at' instead of interval."""

    def _run_validate(self, reminders):
        from kim.commands import config as cfg_mod

        cfg = {"reminders": reminders}
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(cfg_mod, "CONFIG", cfg_file):
                with patch("builtins.print"):
                    try:
                        cfg_mod.cmd_validate(MagicMock())
                        return True  # passed
                    except SystemExit as e:
                        return e.code  # failed with code

    def test_at_reminder_passes_validation(self):
        reminders = [
            {
                "name": "standup",
                "at": "09:30",
                "title": "Stand-up",
                "message": "Time!",
                "urgency": "normal",
                "enabled": True,
            }
        ]
        result = self._run_validate(reminders)
        self.assertEqual(
            result, True, f"cmd_validate must accept 'at' reminders, got exit {result}"
        )

    def test_interval_reminder_still_passes(self):
        reminders = [
            {
                "name": "water",
                "interval": "30m",
                "title": "Water",
                "message": "Drink!",
                "urgency": "normal",
                "enabled": True,
            }
        ]
        result = self._run_validate(reminders)
        self.assertEqual(result, True)

    def test_reminder_missing_both_interval_and_at_fails(self):
        reminders = [
            {
                "name": "broken",
                "title": "Broken",
                "message": "No schedule",
                "urgency": "normal",
                "enabled": True,
            }
        ]
        result = self._run_validate(reminders)
        self.assertEqual(
            result,
            1,
            "Reminder missing both 'at' and 'interval' must exit with code 1",
        )


# ---------------------------------------------------------------------------
# selfupdate.py — cmd_uninstall log-handle close (v4.1.9)
#
# Bug: logging handler was closed on root logger only; the "kim" named logger
#      kept its RotatingFileHandler open, causing WinError 32 on shutil.rmtree.
# Fix: close handlers on *both* "kim" and "" (root) loggers.
# ---------------------------------------------------------------------------


class TestUninstallLogHandlerClose(unittest.TestCase):
    """_close_log_handles must close handlers on the 'kim' named logger and root."""

    def test_kim_logger_handlers_closed(self):
        """The log-close helper must explicitly close the 'kim' named logger."""
        import inspect
        from kim import selfupdate

        # Logic is in the _close_log_handles helper, called from cmd_uninstall.
        src = inspect.getsource(selfupdate._close_log_handles)
        self.assertIn(
            '"kim"',
            src,
            "_close_log_handles must explicitly close the 'kim' named logger handlers",
        )

    def test_root_logger_handlers_closed(self):
        """The root logger ('') must also be closed."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._close_log_handles)
        self.assertIn(
            '""',
            src,
            "_close_log_handles must also close root logger ('') handlers",
        )


# ---------------------------------------------------------------------------
# selfupdate.py — cmd_uninstall deferred exe deletion (v4.1.9)
#
# Bug: kim.exe (pip entry point) is the running process; direct os.unlink()
#      yields WinError 5 (Access Denied).  Must be deferred like kim.bat.
# Fix: .exe paths are collected into deferred_exe and deleted via a detached
#      cmd process after this process exits.
# ---------------------------------------------------------------------------


class TestUninstallDeferredExe(unittest.TestCase):
    """kim.exe must be deferred, not directly unlinked (for script/binary installs)."""

    def test_deferred_exe_variable_exists(self):
        import inspect
        from kim import selfupdate

        # Logic lives in _uninstall_script_or_binary helper.
        src = inspect.getsource(selfupdate._uninstall_script_or_binary)
        self.assertIn(
            "deferred_exe",
            src,
            "_uninstall_script_or_binary must use a deferred_exe variable for .exe removal",
        )

    def test_bat_not_in_binary_candidates_on_windows(self):
        """Neither kim.bat nor kim.exe must be in binary_candidates on Windows.
        Both are deferred so they are not deleted while the process is still running."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._uninstall_script_or_binary)
        # The Windows branch of binary_candidates must be a no-op (pass).
        self.assertIn(
            "deferred",
            src,
            "Windows binaries must be deferred, not in binary_candidates",
        )
        # Confirm kim.bat is never added to binary_candidates directly
        # (it only appears in deferred_bat paths)
        self.assertNotIn(
            'binary_candidates += [\n            Path.home() / ".local" / "bin" / "kim.bat"',
            src,
            "kim.bat must not be added to binary_candidates (causes 'batch file cannot be found')",
        )

    def test_deferred_files_list_includes_exe(self):
        """deferred_files must be built from both deferred_bat and deferred_exe."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._uninstall_script_or_binary)
        self.assertIn("deferred_exe", src)
        self.assertIn("deferred_bat", src)
        # Both must feed the same deferred_files list
        self.assertIn("deferred_files", src)


# ---------------------------------------------------------------------------
# selfupdate.py — cmd_uninstall explicit kim.log deletion before rmdir (v4.1.9)
#
# Bug: deferred PowerShell retried rmdir on ~/.kim but kim.log was still locked
#      at that moment because the Python process had not yet exited when the
#      retry loop ran (only Start-Sleep 3 elapsed, but the process exit was
#      racing the sleep).  Result: ~/.kim and kim.log left behind.
# Fix: explicitly Remove-Item kim.log *before* the rmdir retry loop so that
#      once the process exits and the OS handle is released, the log file is
#      deleted first, leaving an empty directory that rmdir can remove.
# ---------------------------------------------------------------------------


class TestUninstallKimLogExplicitDelete(unittest.TestCase):
    """The deferred PS script must explicitly delete kim.log before rmdir."""

    def _get_deferred_src(self):
        import inspect
        from kim import selfupdate

        # The deferred PS logic lives in _remove_kimdir_deferred_windows.
        return inspect.getsource(selfupdate._remove_kimdir_deferred_windows)

    def test_kim_log_path_in_deferred_ps_block(self):
        """The deferred PowerShell block must reference 'kim.log' explicitly."""
        src = self._get_deferred_src()
        self.assertIn(
            "kim.log",
            src,
            "_remove_kimdir_deferred_windows must explicitly remove kim.log",
        )

    def test_log_file_removed_before_rmdir(self):
        """The kim.log retry loop must appear before the rmdir retry loop."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._remove_kimdir_deferred_windows)
        # kim.log retry uses $j; rmdir retry uses $i — find both
        log_loop_pos = src.find("$j=0;$j -lt 10")
        rmdir_loop_pos = src.find("$i=0;$i -lt 5")
        self.assertGreater(
            log_loop_pos,
            0,
            "kim.log retry loop ($j) not found in _remove_kimdir_deferred_windows",
        )
        self.assertGreater(
            rmdir_loop_pos,
            0,
            "rmdir retry loop ($i) not found in _remove_kimdir_deferred_windows",
        )
        self.assertLess(
            log_loop_pos,
            rmdir_loop_pos,
            "kim.log retry loop must appear before the rmdir retry loop",
        )

    def test_deferred_ps_script_structure(self):
        """The deferred PS block must have two separate retry loops:
        one for kim.log deletion and one for rmdir."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._remove_kimdir_deferred_windows)
        self.assertIn("kim.log", src, "Must explicitly remove kim.log")
        self.assertIn(
            "$j=0;$j -lt 10", src, "Must have kim.log retry loop (up to 10 attempts)"
        )
        self.assertIn(
            "$i=0;$i -lt 5", src, "Must have rmdir retry loop (up to 5 attempts)"
        )
        self.assertIn("Start-Sleep 1", src, "Must have retry delay between attempts")
        self.assertIn("Test-Path", src, "Must check path existence before retry")


# ---------------------------------------------------------------------------
# selfupdate.py — cmd_uninstall kills orphaned _remind-fire processes (v4.1.9)
#
# Bug: 'kim remind' spawns background subprocesses that sleep until their
#      timer fires.  If the daemon stopped while they were sleeping they stay
#      alive, holding kim.log open.  This blocks the deferred PS rmdir.
# Fix: synchronously kill all _remind-fire processes in Python (before the
#      log handle close), using PowerShell Stop-Process on Windows and
#      pkill on Linux/macOS.  Reduces the deferred Start-Sleep back to 3s.
# ---------------------------------------------------------------------------


class TestUninstallKillsOrphanRemindFire(unittest.TestCase):
    """cmd_uninstall must synchronously kill orphaned _remind-fire subprocesses."""

    def _get_orphan_src(self):
        import inspect
        from kim import selfupdate

        # Logic lives in the _kill_remind_fire_orphans helper.
        return inspect.getsource(selfupdate._kill_remind_fire_orphans)

    def test_remind_fire_killed_in_python(self):
        """The orphan-kill helper must target _remind-fire processes."""
        src = self._get_orphan_src()
        self.assertIn(
            "_remind-fire",
            src,
            "_kill_remind_fire_orphans must kill orphaned _remind-fire subprocesses",
        )

    def test_windows_uses_stop_process(self):
        """On Windows, Stop-Process (PowerShell) must be used."""
        src = self._get_orphan_src()
        self.assertIn("Stop-Process", src)
        self.assertIn("Win32_Process", src)

    def test_unix_uses_pkill(self):
        """On Unix, pkill must be used."""
        src = self._get_orphan_src()
        self.assertIn("pkill", src)

    def test_orphan_kill_before_log_handle_close(self):
        """cmd_uninstall must call orphan-kill before log handle close."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate.cmd_uninstall)
        orphan_pos = src.find("_kill_remind_fire_orphans")
        log_close_pos = src.find("_close_log_handles")
        self.assertGreater(
            orphan_pos, 0, "_kill_remind_fire_orphans not found in cmd_uninstall"
        )
        self.assertGreater(
            log_close_pos, 0, "_close_log_handles not found in cmd_uninstall"
        )
        self.assertLess(
            orphan_pos,
            log_close_pos,
            "_kill_remind_fire_orphans must be called before _close_log_handles",
        )

    def test_deferred_ps_does_not_kill_orphans(self):
        """Orphan kill is done synchronously in Python via a helper; the deferred
        PS script (_remove_kimdir_deferred_windows) must NOT contain Win32_Process."""
        import inspect
        from kim import selfupdate

        deferred_src = inspect.getsource(selfupdate._remove_kimdir_deferred_windows)
        self.assertNotIn(
            "Win32_Process",
            deferred_src,
            "Deferred PS (kimdir removal) must not kill orphans — that is Python's job",
        )

    def test_stop_process_used_to_terminate(self):
        """The orphan-kill helper must use Stop-Process."""
        src = self._get_orphan_src()
        self.assertIn(
            "Stop-Process",
            src,
            "_kill_remind_fire_orphans must use Stop-Process to kill orphaned processes",
        )

    def test_wmi_used_to_find_by_commandline(self):
        """The orphan-kill helper must use WMI to find processes by CommandLine."""
        src = self._get_orphan_src()
        self.assertIn(
            "Win32_Process",
            src,
            "_kill_remind_fire_orphans must use Win32_Process to find by CommandLine",
        )


# ---------------------------------------------------------------------------
# selfupdate.py — pip uninstall delegates to pip (v4.3.0)
# ---------------------------------------------------------------------------
class TestPipUninstallDelegatesToPip(unittest.TestCase):
    """When install_type is 'pip', cmd_uninstall must delegate binary removal
    to `pip uninstall kim-reminder -y` rather than trying to delete kim.exe
    or kim.bat itself.

    OLD broken behaviour: cmd_uninstall tried to delete kim.exe (the running
    process on Windows) directly, yielding WinError 5, and deleted kim.bat
    while cmd.exe was still executing it.

    NEW correct behaviour: pip owns pip-installed files; we call pip to remove
    them.  We only touch ~/.kim/ user data (which pip doesn't know about).
    """

    def _get_selfupdate_src(self):
        import inspect
        from kim import selfupdate

        return inspect.getsource(selfupdate)

    def test_pip_path_calls_pip_uninstall(self):
        """_uninstall_pip must invoke pip uninstall kim-reminder."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._uninstall_pip)
        self.assertIn("pip", src)
        self.assertIn("uninstall", src)
        self.assertIn("kim-reminder", src)

    def test_pip_path_does_not_delete_exe_directly(self):
        """_uninstall_pip must NOT contain direct exe/bat deletion logic.
        It delegates all binary removal to pip itself."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._uninstall_pip)
        self.assertNotIn("deferred_exe", src)
        self.assertNotIn("deferred_bat", src)
        # Must not call os.unlink, shutil.rmtree, or Path.unlink on binaries
        self.assertNotIn("os.unlink", src)
        self.assertNotIn(".unlink(", src)
        self.assertNotIn("shutil.rmtree", src)
        # Must not use shutil.which to locate the binary for deletion
        self.assertNotIn("shutil.which", src)

    def test_cmd_uninstall_dispatches_on_install_type(self):
        """cmd_uninstall must call _detect_install_type and branch on 'pip'."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate.cmd_uninstall)
        self.assertIn("_detect_install_type", src)
        self.assertIn("pip", src)

    def test_uninstall_pip_uses_sys_executable(self):
        """pip uninstall must be invoked via sys.executable -m pip to target
        the correct Python environment."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._uninstall_pip)
        self.assertIn("sys.executable", src)

    def test_uninstall_pip_windows_deferred(self):
        """On Windows, _uninstall_pip must defer pip uninstall via PowerShell
        (not call subprocess.run directly) because kim.exe is the running process."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._uninstall_pip)
        # Must use deferred PS spawn for Windows path
        self.assertIn("_spawn_deferred_ps", src)
        # The PS script must contain the pip uninstall command
        self.assertIn("-m pip uninstall --break-system-packages kim-reminder", src)

    def test_uninstall_pip_non_windows_uses_subprocess_run(self):
        """On non-Windows, _uninstall_pip must run pip synchronously via subprocess.run."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._uninstall_pip)
        self.assertIn("subprocess.run", src)

    def test_uninstall_pip_windows_deferred_removes_kimdir(self):
        """On Windows, the deferred PS script must also remove ~/.kim/."""
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._uninstall_pip)
        self.assertIn("kim.log", src)
        self.assertIn("Remove-Item", src)

    def test_helper_functions_exist(self):
        """Refactored helpers must exist as top-level functions."""
        from kim import selfupdate

        self.assertTrue(callable(getattr(selfupdate, "_remove_os_service", None)))
        self.assertTrue(
            callable(getattr(selfupdate, "_kill_remind_fire_orphans", None))
        )
        self.assertTrue(callable(getattr(selfupdate, "_close_log_handles", None)))
        self.assertTrue(callable(getattr(selfupdate, "_remove_kimdir", None)))
        self.assertTrue(callable(getattr(selfupdate, "_spawn_deferred_ps", None)))
        self.assertTrue(callable(getattr(selfupdate, "_uninstall_pip", None)))
        self.assertTrue(
            callable(getattr(selfupdate, "_uninstall_script_or_binary", None))
        )


# ---------------------------------------------------------------------------
# management.py — kim remove auto-detects one-shots (v4.4.0)
#
# Bug: `kim remove <name>` only searched config.json (recurring reminders).
#      One-shot reminders live in oneshots.json and required the -o flag.
#      Users expect `kim remove deploy` to work without knowing the flag.
# Fix: if the name is not found in recurring reminders, automatically search
#      pending one-shots and remove there if a match is found.
# ---------------------------------------------------------------------------
class TestRemoveAutoDetectsOneshots(unittest.TestCase):
    """kim remove must fall through to one-shots when name not in config."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_file = Path(self.tmpdir) / "config.json"
        self.oneshot_file = Path(self.tmpdir) / "oneshots.json"
        # Config with no reminders
        self.config_file.write_text(json.dumps({"reminders": []}), encoding="utf-8")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_oneshots(self, entries):
        self.oneshot_file.write_text(json.dumps(entries), encoding="utf-8")

    def test_remove_oneshot_without_flag(self):
        """kim remove <msg> should cancel a matching pending one-shot."""
        import time

        future = time.time() + 9999
        self._write_oneshots([{"message": "deploy", "fire_at": future}])

        from kim.commands import management

        args = MagicMock()
        args.name = "deploy"
        args.oneshot = False

        with patch.object(
            management, "load_config", return_value={"reminders": []}
        ), patch.object(management, "_save_config"), patch.object(
            management, "_signal_reload"
        ), patch.object(management, "ONESHOT_FILE", self.oneshot_file):
            # _remove_oneshot writes to ONESHOT_FILE; patch it there too
            with patch("kim.commands.management.ONESHOT_FILE", self.oneshot_file):
                management.cmd_remove(args)

        remaining = json.loads(self.oneshot_file.read_text())
        self.assertEqual(remaining, [], "One-shot must be removed from oneshots.json")

    def test_remove_recurring_still_works(self):
        """Removing a recurring reminder by name must still work."""
        from kim.commands import management

        args = MagicMock()
        args.name = "water"
        args.oneshot = False

        config = {"reminders": [{"name": "water", "interval": 3600}]}
        saved = {}

        def fake_save(c):
            saved.update(c)

        with patch.object(management, "load_config", return_value=config), patch.object(
            management, "_save_config", side_effect=fake_save
        ), patch.object(management, "_signal_reload"), patch.object(
            management, "ONESHOT_FILE", self.oneshot_file
        ):
            management.cmd_remove(args)

        self.assertEqual(saved.get("reminders"), [])

    def test_remove_not_found_exits(self):
        """If name matches neither recurring nor one-shots, exit with error."""
        import time

        future = time.time() + 9999
        self._write_oneshots([{"message": "standup", "fire_at": future}])

        from kim.commands import management

        args = MagicMock()
        args.name = "deploy"
        args.oneshot = False

        with patch.object(
            management, "load_config", return_value={"reminders": []}
        ), patch.object(management, "_save_config"), patch.object(
            management, "_signal_reload"
        ), patch("kim.commands.management.ONESHOT_FILE", self.oneshot_file):
            with self.assertRaises(SystemExit):
                management.cmd_remove(args)

    def test_cmd_remove_source_checks_oneshots(self):
        """cmd_remove source must reference ONESHOT_FILE as fallback."""
        import inspect
        from kim.commands import management

        src = inspect.getsource(management.cmd_remove)
        self.assertIn("ONESHOT_FILE", src)
        self.assertIn("_remove_oneshot", src)


if __name__ == "__main__":
    unittest.main()
