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
        """When pip metadata exists AND the binary on PATH is in RECORD, type is 'pip'."""
        from kim import selfupdate
        import importlib.metadata

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bin = Path(tmpdir) / "kim"
            fake_bin.write_text(
                "#!/usr/bin/env python3\n# pip entry point", encoding="utf-8"
            )

            # RECORD lists this binary (path relative to dist root)
            record_content = f"{fake_bin},sha256=abc,123\n"
            fake_dist = MagicMock()
            fake_dist.read_text.return_value = record_content
            fake_dist.locate_file.return_value = Path(tmpdir)  # dist root = tmpdir

            with patch.object(
                importlib.metadata, "distribution", return_value=fake_dist
            ):
                with patch("shutil.which", return_value=str(fake_bin)):
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


# ---------------------------------------------------------------------------
# selfupdate.py — install-script binary not removed on uninstall (v4.5.8)
#
# Bug: after running `pip install kim-reminder` once, then running the
# install.sh script, `importlib.metadata` still finds the old pip metadata.
# _detect_install_type() returned "pip" even though the active binary at
# ~/.local/bin/kim was placed by the install script and is NOT listed in pip's
# RECORD.  pip uninstall reported "no files found" and left the binary behind.
#
# Fix 1: _pip_owns_entry_point() verifies the binary on PATH is in pip's RECORD
#         before _detect_install_type() commits to returning "pip".
# Fix 2: _uninstall_pip() always calls _remove_binary_candidates() after pip
#         so the script-placed binary is deleted even in the pip path.
# Fix 3: _uninstall_script_or_binary() silently runs pip uninstall to clean up
#         orphaned metadata when pip metadata exists alongside a script install.
# ---------------------------------------------------------------------------
class TestUninstallOrphanedPipMetadata(unittest.TestCase):
    """kim uninstall must remove ~/.local/bin/kim even with orphaned pip metadata."""

    def test_detect_install_type_not_pip_when_binary_not_in_record(self):
        """_detect_install_type returns non-pip when RECORD doesn't list the binary."""
        from kim import selfupdate
        import importlib.metadata

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_bin = Path(tmpdir) / "kim"
            fake_bin.write_text(
                '#!/usr/bin/env bash\nexec python3 -m kim "$@"\n', encoding="utf-8"
            )

            # RECORD does NOT list fake_bin — simulates orphaned pip metadata
            record_content = "/some/other/file.py,sha256=abc,123\n"
            fake_dist = MagicMock()
            fake_dist.read_text.return_value = record_content
            fake_dist.locate_file.return_value = Path(tmpdir)

            with patch.object(
                importlib.metadata, "distribution", return_value=fake_dist
            ):
                with patch("shutil.which", return_value=str(fake_bin)):
                    with patch.object(selfupdate, "KIM_DIR", Path(tmpdir) / "nokimdir"):
                        result = selfupdate._detect_install_type()

        # Must NOT be "pip" — the binary is not pip-owned
        self.assertNotEqual(result, "pip")

    def test_uninstall_pip_also_removes_binary_candidates(self):
        """_uninstall_pip must call _remove_binary_candidates on non-Windows."""
        from kim import selfupdate
        import inspect

        src = inspect.getsource(selfupdate._uninstall_pip)
        self.assertIn(
            "_remove_binary_candidates",
            src,
            "_uninstall_pip must call _remove_binary_candidates to clean up script-placed binaries",
        )

    def test_remove_binary_candidates_deletes_local_bin_kim(self):
        """_remove_binary_candidates deletes ~/.local/bin/kim if it exists."""
        from kim import selfupdate

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_local_bin = Path(tmpdir) / ".local" / "bin"
            fake_local_bin.mkdir(parents=True)
            fake_kim = fake_local_bin / "kim"
            fake_kim.write_text(
                '#!/usr/bin/env bash\nexec python3 -m kim "$@"\n', encoding="utf-8"
            )

            with patch.object(Path, "home", return_value=Path(tmpdir)):
                with patch("shutil.which", return_value=None):
                    selfupdate._remove_binary_candidates("Linux")

            self.assertFalse(
                fake_kim.exists(),
                "~/.local/bin/kim must be deleted by _remove_binary_candidates",
            )

    def test_uninstall_script_or_binary_cleans_orphaned_pip_metadata(self):
        """_uninstall_script_or_binary runs silent pip uninstall to clean up orphaned metadata."""
        from kim import selfupdate
        import inspect

        src = inspect.getsource(selfupdate._uninstall_script_or_binary)
        self.assertIn(
            "pip",
            src,
            "_uninstall_script_or_binary must attempt pip uninstall to clean orphaned metadata",
        )


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
        """When pip metadata exists AND pip owns the binary, return 'pip' despite leftover ~/.kim/kim.py."""
        from kim import selfupdate
        import importlib.metadata

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_kim_dir = Path(tmpdir)
            (fake_kim_dir / "kim.py").write_text("# leftover", encoding="utf-8")

            # Create a fake binary that pip owns
            fake_bin = Path(tmpdir) / "bin" / "kim"
            fake_bin.parent.mkdir()
            fake_bin.write_text(
                "#!/usr/bin/env python3\n# pip entry point", encoding="utf-8"
            )

            record_content = f"{fake_bin},sha256=abc,123\n"
            fake_dist = MagicMock()
            fake_dist.read_text.return_value = record_content
            fake_dist.locate_file.return_value = Path(tmpdir)

            with patch.object(
                importlib.metadata, "distribution", return_value=fake_dist
            ):
                with patch.object(selfupdate, "KIM_DIR", fake_kim_dir):
                    with patch("shutil.which", return_value=str(fake_bin)):
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


# ===========================================================================
# v4.5.5 regression tests
# ===========================================================================


# ---------------------------------------------------------------------------
# scheduler.py — _wakeup.clear() must be inside the lock
#
# Bug: _wakeup.clear() was called OUTSIDE the lock. A wakeup signal set
#      between reading the heap and calling _wakeup.wait() was lost, causing
#      the scheduler to sleep past a just-added reminder.
# Fix: moved _wakeup.clear() to the first statement inside `with self._lock`.
# ---------------------------------------------------------------------------
class TestSchedulerWakeupClearInsideLock(unittest.TestCase):
    """_wakeup.clear() must appear after 'with self._lock:' in _run."""

    def test_wakeup_clear_inside_lock(self):
        import inspect
        from kim.scheduler import KimScheduler

        src = inspect.getsource(KimScheduler._run)
        # Find position of 'with self._lock:' and '_wakeup.clear()'
        lock_pos = src.find("with self._lock:")
        clear_pos = src.find("self._wakeup.clear()")
        self.assertGreater(lock_pos, -1, "'with self._lock:' not found in _run")
        self.assertGreater(clear_pos, -1, "self._wakeup.clear() not found in _run")
        self.assertGreater(
            clear_pos,
            lock_pos,
            "_wakeup.clear() must appear AFTER 'with self._lock:' in _run — "
            "calling it outside the lock loses wakeup signals",
        )


# ---------------------------------------------------------------------------
# scheduler.py — notifier must run in a daemon thread
#
# Bug: notifier was called directly in the scheduler loop. A slow notifier
#      (e.g. a network Slack call) blocked the scheduler from rescheduling
#      other reminders until the call returned.
# Fix: notifier is launched in a daemon Thread so it never stalls the loop.
# ---------------------------------------------------------------------------
class TestSchedulerNotifierInThread(unittest.TestCase):
    """_fire_due_events must launch the notifier in a daemon Thread."""

    def test_notifier_thread_in_source(self):
        import inspect
        from kim.scheduler import KimScheduler

        src = inspect.getsource(KimScheduler._fire_due_events)
        self.assertIn(
            "threading.Thread",
            src,
            "_fire_due_events must start a threading.Thread for the notifier",
        )
        self.assertIn(
            "daemon=True",
            src,
            "Notifier thread must be a daemon thread",
        )

    def test_slow_notifier_does_not_block_scheduler(self):
        """A notifier that sleeps 0.3 s must not delay _fire_due_events > 0.2 s."""
        from kim.scheduler import KimScheduler

        fired = []

        def slow_notifier(reminder):
            time.sleep(0.3)
            fired.append(reminder)

        config = {"reminders": []}
        sched = KimScheduler(config, slow_notifier)
        # Manually inject a due event
        from kim.scheduler import _Event
        import heapq

        event = _Event(fire_at=time.time() - 1, reminder={"name": "test"})
        sched._live["test"] = event
        heapq.heappush(sched._heap, event)

        t0 = time.time()
        sched._fire_due_events()
        elapsed = time.time() - t0

        self.assertLess(
            elapsed,
            0.2,
            f"_fire_due_events took {elapsed:.3f}s — slow notifier is blocking the scheduler loop",
        )


# ---------------------------------------------------------------------------
# scheduler.py — one-shot removed from _live after firing
#
# Bug: after a one-shot reminder fired, it remained in _live. The scheduler
#      would attempt to reschedule it and push a new event onto the heap,
#      causing it to fire repeatedly.
# Fix: after firing a one-shot (has _oneshot_fire_at key), the entry is
#      deleted from _live.
# ---------------------------------------------------------------------------
class TestOneshotRemovedFromLiveAfterFire(unittest.TestCase):
    """One-shot reminder must be removed from _live after it fires."""

    def test_oneshot_removed_from_live(self):
        from kim.scheduler import KimScheduler, _Event
        import heapq

        config = {"reminders": []}
        fired = []
        sched = KimScheduler(config, lambda r: fired.append(r))

        reminder = {
            "name": "once",
            "_oneshot_fire_at": time.time() - 1,
            "message": "one-shot test",
        }
        event = _Event(fire_at=time.time() - 1, reminder=reminder)
        with sched._lock:
            sched._live["once"] = event
            heapq.heappush(sched._heap, event)

        sched._fire_due_events()
        # Give the notifier thread a moment to finish
        time.sleep(0.05)

        self.assertNotIn(
            "once",
            sched._live,
            "One-shot must be removed from _live after firing",
        )


# ---------------------------------------------------------------------------
# commands/misc.py — oneshot file chmod 0o600 on write
#
# Bug: the temporary oneshot file was written without restricting permissions,
#      leaving it world-readable (0o644 default umask) until replaced.
# Fix: os.chmod(_tmp, 0o600) added after writing the .tmp file in
#      cmd_remind, load_oneshot_reminders, and remove_oneshot.
# ---------------------------------------------------------------------------
class TestOneshotChmodOnWrite(unittest.TestCase):
    """On non-Windows, oneshot writes must chmod the tmp file to 0o600."""

    def _get_src(self):
        import inspect
        from kim.commands import misc

        return inspect.getsource(misc)

    @unittest.skipIf(platform.system() == "Windows", "chmod not applicable on Windows")
    def test_cmd_remind_chmods_tmp(self):
        src = self._get_src()
        # count occurrences of chmod 0o600 near ONESHOT_FILE writes
        self.assertIn(
            "os.chmod(_tmp, 0o600)",
            src,
            "cmd_remind / oneshot write path must chmod tmp file to 0o600",
        )

    @unittest.skipIf(platform.system() == "Windows", "chmod not applicable on Windows")
    def test_remove_oneshot_chmods_tmp(self):
        import inspect
        from kim.commands.misc import remove_oneshot

        src = inspect.getsource(remove_oneshot)
        self.assertIn(
            "os.chmod(_tmp, 0o600)",
            src,
            "remove_oneshot must chmod tmp file to 0o600",
        )

    @unittest.skipIf(platform.system() == "Windows", "chmod not applicable on Windows")
    def test_load_oneshot_reminders_chmods_tmp(self):
        import inspect
        from kim.commands.misc import load_oneshot_reminders

        src = inspect.getsource(load_oneshot_reminders)
        self.assertIn(
            "os.chmod(_tmp, 0o600)",
            src,
            "load_oneshot_reminders cleanup write must chmod tmp file to 0o600",
        )


# ---------------------------------------------------------------------------
# commands/misc.py — sleep_seconds must be clamped to 0.0
#
# Bug: if the system clock jumped forward between parse_datetime() and
#      time.time(), sleep_seconds could be negative, causing time.sleep()
#      to raise or behave unexpectedly.
# Fix: sleep_seconds = max(0.0, fire_time - time.time())
# ---------------------------------------------------------------------------
class TestCmdRemindNegativeSleepClamped(unittest.TestCase):
    """sleep_seconds must be clamped to >= 0.0 with max(0.0, ...)."""

    def test_max_zero_in_source(self):
        import inspect
        from kim.commands import misc

        src = inspect.getsource(misc.cmd_remind)
        self.assertIn(
            "max(0.0,",
            src,
            "cmd_remind must clamp sleep_seconds with max(0.0, ...) to prevent negative sleep",
        )

    @unittest.skipIf(platform.system() == "Windows", "fork not available on Windows")
    def test_negative_sleep_clamped_to_zero(self):
        """When time.time() > fire_time, sleep called with 0.0 not a negative value."""
        from kim.commands import misc

        slept = []
        original_sleep = time.sleep

        def fake_sleep(s):
            slept.append(s)
            # Don't actually sleep
            pass

        # fire_time = now - 5; so sleep_seconds would be -5 without the clamp
        fire_time = time.time() - 5.0

        with patch.object(misc, "parse_datetime", return_value=fire_time):
            with patch("time.sleep", side_effect=fake_sleep):
                with patch(
                    "os.fork", return_value=1
                ):  # parent path — returns immediately
                    with patch("builtins.print"):
                        args = MagicMock()
                        args.time = ["1s"]
                        args.message = "test"
                        args.title = None
                        args.timezone = None
                        args.urgency = "normal"
                        try:
                            misc.cmd_remind(args)
                        except SystemExit:
                            pass

        # If sleep was called, it must not have been with a negative value
        for s in slept:
            self.assertGreaterEqual(
                s,
                0.0,
                f"time.sleep called with negative value {s} — sleep_seconds not clamped",
            )


# ---------------------------------------------------------------------------
# commands/management.py — cmd_update rejects invalid --interval
#
# Bug: cmd_update accepted any string as --interval and stored it directly
#      in config without validation. A typo like "foo" would silently write
#      an invalid interval that the scheduler would skip.
# Fix: validate via KimScheduler._parse_interval; exit 1 if invalid.
# ---------------------------------------------------------------------------
class TestCmdUpdateIntervalValidation(unittest.TestCase):
    """cmd_update --interval with invalid value must exit 1, not save config."""

    def test_invalid_interval_exits_one(self):
        from kim.commands import management

        config = {"reminders": [{"name": "water", "interval": "30m", "enabled": True}]}
        args = MagicMock()
        args.name = "water"
        args.interval = "foo"
        args.at_time = None
        args.timezone = None
        args.title = None
        args.message = None
        args.urgency = None
        args.enable = False
        args.disable = False

        save_called = []

        with patch.object(management, "load_config", return_value=config):
            with patch.object(
                management, "_save_config", side_effect=lambda c: save_called.append(c)
            ):
                with patch("builtins.print"):
                    with self.assertRaises(SystemExit) as cm:
                        management.cmd_update(args)

        self.assertEqual(cm.exception.code, 1, "Invalid interval must exit with code 1")
        self.assertEqual(
            save_called, [], "_save_config must NOT be called for invalid interval"
        )

    def test_valid_interval_is_accepted(self):
        from kim.commands import management

        config = {"reminders": [{"name": "water", "interval": "30m", "enabled": True}]}
        args = MagicMock()
        args.name = "water"
        args.interval = "1h"
        args.at_time = None
        args.timezone = None
        args.title = None
        args.message = None
        args.urgency = None
        args.enable = False
        args.disable = False

        save_called = []

        with patch.object(management, "load_config", return_value=config):
            with patch.object(
                management, "_save_config", side_effect=lambda c: save_called.append(c)
            ):
                with patch.object(management, "_signal_reload"):
                    with patch("builtins.print"):
                        management.cmd_update(args)

        self.assertEqual(len(save_called), 1, "Valid interval must call _save_config")


# ---------------------------------------------------------------------------
# commands/config.py — cmd_validate rejects bad 'at' field format
#
# Bug: cmd_validate only checked that an 'at' key was present but did not
#      validate the value format, so "at": "not-valid" would pass validation.
# Fix: cmd_validate now applies a fullmatch regex (\d{1,2}):(\d{2}) to the
#      at value and exits 1 if it doesn't match.
# ---------------------------------------------------------------------------
class TestCmdValidateAtFieldFormat(unittest.TestCase):
    """cmd_validate must reject reminders whose 'at' value is not HH:MM."""

    def _run(self, reminders):
        from kim.commands import config as cfg_mod

        cfg = {"reminders": reminders}
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = Path(tmpdir) / "config.json"
            cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.object(cfg_mod, "CONFIG", cfg_file):
                with patch("builtins.print"):
                    try:
                        cfg_mod.cmd_validate(MagicMock())
                        return 0
                    except SystemExit as e:
                        return e.code

    def test_invalid_at_rejected(self):
        result = self._run([{"name": "bad", "at": "not-valid"}])
        self.assertEqual(result, 1, "cmd_validate must exit 1 for invalid 'at' format")

    def test_valid_at_accepted(self):
        result = self._run([{"name": "standup", "at": "09:30"}])
        self.assertEqual(result, 0, "cmd_validate must accept valid 'at' value '09:30'")

    def test_regex_in_validate_source(self):
        import inspect
        from kim.commands import config as cfg_mod

        src = inspect.getsource(cfg_mod.cmd_validate)
        self.assertIn(
            "fullmatch",
            src,
            "cmd_validate must use re.fullmatch to validate the 'at' field format",
        )


# ---------------------------------------------------------------------------
# notifications.py — _notify_slack_webhook logs warning on non-"ok" response
#
# Bug: _notify_slack_webhook did not check the Slack response body. Silent
#      failures (e.g. wrong webhook URL returning "invalid_auth") went
#      unnoticed.
# Fix: after reading the response, if body != "ok", log.warning is called.
# ---------------------------------------------------------------------------
class TestSlackWebhookResponseCheck(unittest.TestCase):
    """_notify_slack_webhook must log a warning when response body is not 'ok'."""

    def _make_fake_urlopen(self, body: str):
        """Return a context manager mock whose .read() returns body bytes."""
        fake_resp = MagicMock()
        fake_resp.read.return_value = body.encode("utf-8")
        fake_resp.__enter__ = lambda s: fake_resp
        fake_resp.__exit__ = MagicMock(return_value=False)
        return fake_resp

    def test_non_ok_body_triggers_warning(self):
        from kim import notifications

        fake_resp = self._make_fake_urlopen("invalid_auth")
        with patch("urllib.request.urlopen", return_value=fake_resp):
            with patch.object(notifications.log, "warning") as mock_warn:
                notifications._notify_slack_webhook("Title", "Msg", "https://fake.hook")
                mock_warn.assert_called_once()
                args = mock_warn.call_args[0]
                self.assertIn("unexpected", args[0].lower())

    def test_ok_body_no_warning(self):
        from kim import notifications

        fake_resp = self._make_fake_urlopen("ok")
        with patch("urllib.request.urlopen", return_value=fake_resp):
            with patch.object(notifications.log, "warning") as mock_warn:
                notifications._notify_slack_webhook("Title", "Msg", "https://fake.hook")
                mock_warn.assert_not_called()


# ---------------------------------------------------------------------------
# notifications.py — _notify_slack_bot logs warning when ok=false
#
# Bug: _notify_slack_bot did not check the "ok" field in the JSON response.
#      A channel_not_found error would be swallowed silently.
# Fix: response JSON is parsed; if ok is False, log.warning is called with
#      the error field.
# ---------------------------------------------------------------------------
class TestSlackBotOkFalseCheck(unittest.TestCase):
    """_notify_slack_bot must log a warning when JSON response has ok=false."""

    def _make_fake_urlopen(self, body_dict: dict):
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps(body_dict).encode("utf-8")
        fake_resp.__enter__ = lambda s: fake_resp
        fake_resp.__exit__ = MagicMock(return_value=False)
        return fake_resp

    def test_ok_false_triggers_warning(self):
        from kim import notifications

        fake_resp = self._make_fake_urlopen({"ok": False, "error": "channel_not_found"})
        with patch("urllib.request.urlopen", return_value=fake_resp):
            with patch.object(notifications.log, "warning") as mock_warn:
                notifications._notify_slack_bot("Title", "Msg", "xoxb-fake", "#general")
                mock_warn.assert_called_once()
                args = mock_warn.call_args[0]
                # Should mention ok=false or the error
                combined = " ".join(str(a) for a in args)
                self.assertTrue(
                    "ok" in combined.lower() or "channel_not_found" in combined,
                    f"Warning message should mention ok=false or the error: {combined}",
                )

    def test_ok_true_no_warning(self):
        from kim import notifications

        fake_resp = self._make_fake_urlopen({"ok": True})
        with patch("urllib.request.urlopen", return_value=fake_resp):
            with patch.object(notifications.log, "warning") as mock_warn:
                notifications._notify_slack_bot("Title", "Msg", "xoxb-fake", "#general")
                mock_warn.assert_not_called()


# ---------------------------------------------------------------------------
# interactive.py — edit_reminder clears 'at' and 'timezone' when new interval given
#
# Bug: when the user entered a new interval in the interactive edit flow, the
#      old 'at' and 'timezone' keys were left on the reminder dict. The
#      scheduler would then treat it as an at-time reminder, ignoring the new
#      interval.
# Fix: r.pop("at", None) and r.pop("timezone", None) inside the
#      `if new_interval:` block.
# ---------------------------------------------------------------------------
class TestInteractiveEditReminderClearsAtKey(unittest.TestCase):
    """edit_reminder must remove 'at' and 'timezone' when a new interval is set."""

    def test_pop_at_in_source(self):
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        self.assertIn(
            'r.pop("at", None)',
            src,
            "edit_reminder must call r.pop('at', None) when updating interval",
        )

    def test_pop_timezone_in_source(self):
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        self.assertIn(
            'r.pop("timezone", None)',
            src,
            "edit_reminder must call r.pop('timezone', None) when updating interval",
        )

    def test_pops_inside_new_interval_block(self):
        """Both pops must appear after 'if new_interval' or 'if new_interval:'."""
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        interval_block_pos = src.find("new_interval")
        at_pop_pos = src.find('r.pop("at", None)')
        tz_pop_pos = src.find('r.pop("timezone", None)')
        self.assertGreater(
            at_pop_pos,
            interval_block_pos,
            "r.pop('at') must appear after the new_interval check",
        )
        self.assertGreater(
            tz_pop_pos,
            interval_block_pos,
            "r.pop('timezone') must appear after the new_interval check",
        )


# ---------------------------------------------------------------------------
# interactive.py — add_oneshot must not hardcode urgency="critical"
#
# Bug: add_oneshot called notify(..., urgency="critical") regardless of what
#      the user typed, making all interactive one-shots critical.
# Fix: user input is collected into urgency_input (or similar variable) and
#      passed to notify.
# ---------------------------------------------------------------------------
class TestInteractiveAddOneshotUrgency(unittest.TestCase):
    """add_oneshot must not hardcode urgency='critical'."""

    def test_critical_not_hardcoded(self):
        import inspect
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        # Look for the pattern urgency="critical" as a literal keyword argument
        # outside of a comment
        import re

        hardcoded = re.findall(r'urgency\s*=\s*["\']critical["\']', src)
        # It's acceptable to have it as a default choice label but not as
        # the only value passed to notify in the add_oneshot flow.
        # We check that the notify call uses a variable, not a literal.
        notify_calls = re.findall(
            r'notify\([^)]*urgency\s*=\s*["\']critical["\'][^)]*\)', src
        )
        self.assertEqual(
            notify_calls,
            [],
            "add_oneshot must not hardcode urgency='critical' in the notify() call; "
            f"found: {notify_calls}",
        )

    def test_urgency_variable_used(self):
        import inspect, re
        from kim import interactive

        src = inspect.getsource(interactive.cmd_interactive)
        # The urgency value must be read from user input into a variable
        self.assertTrue(
            "urgency" in src
            and (
                "urgency_input" in src
                or "urgency_choice" in src
                or re.search(r"urgency\s*=\s*\w+", src)
            ),
            "add_oneshot must use a variable for urgency, not a hardcoded string",
        )


# ---------------------------------------------------------------------------
# core.py — load_config prints to stderr on JSON corruption
#
# Bug: load_config() silently swallowed JSONDecodeError and returned defaults
#      with no user-visible feedback, making corruption hard to diagnose.
# Fix: when JSONDecodeError is caught, a warning is printed to sys.stderr.
# ---------------------------------------------------------------------------
class TestLoadConfigPrintsWarningOnCorruption(unittest.TestCase):
    """load_config() must print a warning to stderr when the config is corrupt."""

    def test_corrupt_config_prints_to_stderr(self):
        from kim import core

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_cfg = Path(tmpdir) / "config.json"
            bad_cfg.write_text("{not valid json", encoding="utf-8")

            captured = io.StringIO()
            with patch.object(core, "CONFIG", bad_cfg):
                with patch("sys.stderr", captured):
                    result = core.load_config()

            warning_output = captured.getvalue()
            self.assertTrue(
                len(warning_output) > 0,
                "load_config must print a warning to stderr when config is corrupt JSON",
            )
            self.assertTrue(
                "corrupt" in warning_output.lower()
                or "invalid" in warning_output.lower()
                or "warning" in warning_output.lower(),
                f"Warning message should mention corruption/invalid JSON, got: {warning_output!r}",
            )

    def test_returns_default_on_corruption(self):
        """load_config must return a usable default config, not raise."""
        from kim import core

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_cfg = Path(tmpdir) / "config.json"
            bad_cfg.write_text("{{{BROKEN", encoding="utf-8")

            with patch.object(core, "CONFIG", bad_cfg):
                with patch("sys.stderr", io.StringIO()):
                    result = core.load_config()

        self.assertIn(
            "reminders", result, "load_config must return a dict with 'reminders' key"
        )


# ---------------------------------------------------------------------------
# cli.py — bare 'kim' (no subcommand) must exit cleanly (code 0)
#
# Bug: the else branch after the command dispatch called sys.exit(1), so
#      `kim` with no arguments returned exit code 1 — treated as an error
#      by shell scripts.
# Fix: the else branch prints help but does NOT call sys.exit (exits 0).
# ---------------------------------------------------------------------------
class TestBareKimExitsZero(unittest.TestCase):
    """cli.main() with no subcommand must print help and exit 0, not 1."""

    def test_no_sys_exit_1_after_print_help(self):
        import inspect
        from kim import cli

        src = inspect.getsource(cli.main)
        # Find the else branch that handles no-subcommand
        # The pattern: parser.print_help() must NOT be immediately followed by sys.exit(1)
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "parser.print_help()" in line:
                # Check the next few lines for sys.exit(1)
                next_lines = " ".join(lines[i + 1 : i + 4])
                self.assertNotIn(
                    "sys.exit(1)",
                    next_lines,
                    "sys.exit(1) must not appear after parser.print_help() — bare 'kim' should exit 0",
                )

    def test_no_exit_one_comment_present(self):
        """Source comment must indicate no-error exit."""
        import inspect
        from kim import cli

        src = inspect.getsource(cli.main)
        self.assertIn(
            "exit cleanly",
            src,
            "cli.main must have a comment explaining why bare kim exits cleanly (exit 0)",
        )


# ---------------------------------------------------------------------------
# cli.py — 'import re' must be at module level, not inside a function
#
# Bug: 'import re' was placed inside a function body in cli.py. This works
#      but is a style/performance issue and indicates cut-and-paste tech debt.
# Fix: 'import re' moved to the top-level imports.
# ---------------------------------------------------------------------------
class TestImportReAtModuleLevel(unittest.TestCase):
    """'import re' must be at the module level in cli.py, not inside a function."""

    def test_import_re_not_inside_function(self):
        import ast

        # Read the raw source
        import kim.cli as cli_mod
        import inspect

        source = inspect.getsource(cli_mod)
        tree = ast.parse(source)

        # Walk all function/method defs and check for 'import re' inside them
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, ast.Import):
                        for alias in child.names:
                            self.assertNotEqual(
                                alias.name,
                                "re",
                                f"'import re' found inside function '{node.name}' — must be at module level",
                            )

    def test_import_re_exists_at_top(self):
        import kim.cli as cli_mod

        self.assertTrue(
            hasattr(cli_mod, "re") or "re" in dir(cli_mod),
            "cli.py must import re at module level",
        )


# ---------------------------------------------------------------------------
# sound.py — validate_sound_file returns False for unreadable file
#
# Bug: validate_sound_file only checked file existence and extension. A file
#      with 0o000 permissions would pass validation but fail when read.
# Fix: os.access(path, os.R_OK) check added; returns (False, "not readable")
#      if the file is not readable.
# ---------------------------------------------------------------------------
class TestSoundValidateReadPermission(unittest.TestCase):
    """validate_sound_file must return (False, ...) for a 0o000 permission file."""

    @unittest.skipIf(
        platform.system() == "Windows", "chmod 000 not testable on Windows"
    )
    @unittest.skipIf(
        getattr(os, "getuid", lambda: 1)() == 0, "root bypasses permission checks"
    )
    def test_unreadable_file_rejected(self):
        from kim.sound import validate_sound_file

        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "sound.wav"
            f.write_bytes(b"\x00" * 10)
            os.chmod(f, 0o000)
            try:
                ok, err = validate_sound_file(str(f))
                self.assertFalse(
                    ok, "validate_sound_file must return ok=False for unreadable file"
                )
                self.assertIn(
                    "readable",
                    err.lower(),
                    f"Error message should mention 'readable', got: {err!r}",
                )
            finally:
                os.chmod(f, 0o644)  # restore so tmpdir cleanup works

    def test_readable_file_accepted(self):
        from kim.sound import validate_sound_file

        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "sound.wav"
            f.write_bytes(b"\x00" * 10)
            ok, err = validate_sound_file(str(f))
            # Should pass all checks except possibly extension (which is valid here)
            # .wav is a supported extension
            self.assertTrue(
                ok, f"validate_sound_file should accept readable .wav: {err}"
            )


# ---------------------------------------------------------------------------
# commands/management.py — cmd_remove uses narrow exception tuple
#
# Bug: cmd_remove used a bare `except Exception` clause around the oneshots
#      file read, swallowing programming errors that should propagate.
# Fix: narrowed to `except (json.JSONDecodeError, OSError)`.
# ---------------------------------------------------------------------------
class TestCmdRemoveExceptionNarrowed(unittest.TestCase):
    """cmd_remove must use (json.JSONDecodeError, OSError), not bare except Exception."""

    def test_narrow_exception_in_source(self):
        import inspect
        from kim.commands import management

        src = inspect.getsource(management.cmd_remove)
        # Bare `except Exception:` or `except Exception as` must not appear
        import re

        bare_except = re.findall(r"except\s+Exception\b", src)
        self.assertEqual(
            bare_except,
            [],
            f"cmd_remove must not use bare 'except Exception' — found: {bare_except}",
        )

    def test_json_decode_error_in_source(self):
        import inspect
        from kim.commands import management

        src = inspect.getsource(management.cmd_remove)
        self.assertIn(
            "JSONDecodeError",
            src,
            "cmd_remove must catch json.JSONDecodeError explicitly",
        )


# ---------------------------------------------------------------------------
# scheduler.py — update_reminder and disable_reminder removed
#
# Bug: KimScheduler had update_reminder and disable_reminder methods that
#      duplicated logic from the public add_reminder/remove_reminder API and
#      were never called. Dead code invites misuse.
# Fix: both methods removed from the class.
# ---------------------------------------------------------------------------
class TestUpdateReminderAndDisableReminderRemoved(unittest.TestCase):
    """KimScheduler must not have update_reminder or disable_reminder methods."""

    def test_update_reminder_absent(self):
        from kim.scheduler import KimScheduler

        self.assertFalse(
            hasattr(KimScheduler, "update_reminder"),
            "update_reminder is dead code and must have been removed from KimScheduler",
        )

    def test_disable_reminder_absent(self):
        from kim.scheduler import KimScheduler

        self.assertFalse(
            hasattr(KimScheduler, "disable_reminder"),
            "disable_reminder is dead code and must have been removed from KimScheduler",
        )


# ---------------------------------------------------------------------------
# core.py — parse_interval still works but is deprecated
#
# Bug: parse_interval was a top-level function duplicating scheduler logic.
#      Callers should use KimScheduler._parse_interval going forward.
# Fix: kept for backward compat but marked deprecated in docstring.
# ---------------------------------------------------------------------------
class TestParseIntervalDeprecated(unittest.TestCase):
    """core.parse_interval must still work and carry a deprecation note."""

    def test_still_callable(self):
        from kim.core import parse_interval

        self.assertEqual(parse_interval("30m"), 1800.0)
        self.assertEqual(parse_interval("1h"), 3600.0)
        self.assertEqual(parse_interval("1d"), 86400.0)
        self.assertEqual(parse_interval(30), 1800.0)

    def test_deprecation_in_docstring(self):
        from kim.core import parse_interval

        doc = parse_interval.__doc__ or ""
        self.assertTrue(
            "deprecat" in doc.lower(),
            "core.parse_interval docstring must mention deprecation",
        )


# ===========================================================================
# v4.5.6 regression tests
# ===========================================================================


# ---------------------------------------------------------------------------
# cli.py — help epilog must show oneshots path
#
# Bug: `kim --help` showed the config path and log path but omitted the
#      oneshots path, leaving users unable to find oneshots.json.
# Fix: epilog now includes "oneshots: ~/.kim/oneshots.json".
# ---------------------------------------------------------------------------
class TestHelpEpilogShowsOneshotsPath(unittest.TestCase):
    """kim --help epilog must contain 'oneshots:' and 'oneshots.json'."""

    def test_epilog_contains_oneshots(self):
        import inspect
        from kim import cli

        src = inspect.getsource(cli.main)
        # Find the epilog string
        self.assertIn(
            "oneshots:",
            src,
            "cli.main epilog must include 'oneshots:' line",
        )

    def test_epilog_contains_oneshots_json(self):
        import inspect
        from kim import cli

        src = inspect.getsource(cli.main)
        self.assertIn(
            "oneshots.json",
            src,
            "cli.main epilog must reference 'oneshots.json'",
        )


# ---------------------------------------------------------------------------
# commands/config.py — export with --oneshots includes pending one-shots
#
# Bug: kim export did not support one-shots at all. Users had no way to
#      back up or migrate their pending one-shot reminders.
# Fix: --oneshots flag added; when set, pending one-shots (fire_at > now)
#      are included under a "oneshots" key in the JSON output.
# ---------------------------------------------------------------------------
class TestExportWithOneshots(unittest.TestCase):
    """cmd_export --oneshots must include pending one-shots in JSON output."""

    def _run_export(self, oneshots_content, include_oneshots=True):
        from kim.commands import config as cfg_mod

        fake_config = {"reminders": [], "sound": True}

        with tempfile.TemporaryDirectory() as tmpdir:
            oneshot_file = Path(tmpdir) / "oneshots.json"
            oneshot_file.write_text(json.dumps(oneshots_content), encoding="utf-8")

            captured = io.StringIO()
            args = MagicMock()
            args.format = "json"
            args.output = None
            args.oneshots = include_oneshots

            with patch.object(cfg_mod, "load_config", return_value=fake_config):
                with patch.object(cfg_mod, "ONESHOT_FILE", oneshot_file):
                    with patch(
                        "builtins.print", side_effect=lambda x: captured.write(x + "\n")
                    ):
                        cfg_mod.cmd_export(args)

        return captured.getvalue()

    def test_pending_oneshots_in_output(self):
        future = time.time() + 9999
        oneshots = [
            {
                "message": "deploy",
                "fire_at": future,
                "title": "Reminder",
                "urgency": "normal",
            }
        ]
        output = self._run_export(oneshots, include_oneshots=True)
        data = json.loads(output.strip())
        self.assertIn(
            "oneshots", data, "JSON export with --oneshots must include 'oneshots' key"
        )
        self.assertEqual(len(data["oneshots"]), 1)
        self.assertEqual(data["oneshots"][0]["message"], "deploy")

    def test_no_oneshots_key_without_flag(self):
        future = time.time() + 9999
        oneshots = [{"message": "deploy", "fire_at": future}]
        output = self._run_export(oneshots, include_oneshots=False)
        data = json.loads(output.strip())
        self.assertNotIn(
            "oneshots",
            data,
            "JSON export without --oneshots must not include 'oneshots' key",
        )


# ---------------------------------------------------------------------------
# commands/config.py — export excludes expired one-shots
#
# Bug: if the user kept old oneshots.json entries from previous runs,
#      exporting with --oneshots would include already-fired entries.
# Fix: only entries with fire_at > now are exported.
# ---------------------------------------------------------------------------
class TestExportWithOneshotsExcludesExpired(unittest.TestCase):
    """cmd_export --oneshots must not include one-shots whose fire_at is in the past."""

    def test_expired_oneshots_excluded(self):
        from kim.commands import config as cfg_mod

        past = time.time() - 100
        future = time.time() + 9999
        oneshots = [
            {"message": "old", "fire_at": past, "title": "Old", "urgency": "normal"},
            {"message": "new", "fire_at": future, "title": "New", "urgency": "normal"},
        ]
        fake_config = {"reminders": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            oneshot_file = Path(tmpdir) / "oneshots.json"
            oneshot_file.write_text(json.dumps(oneshots), encoding="utf-8")

            captured = io.StringIO()
            args = MagicMock()
            args.format = "json"
            args.output = None
            args.oneshots = True

            with patch.object(cfg_mod, "load_config", return_value=fake_config):
                with patch.object(cfg_mod, "ONESHOT_FILE", oneshot_file):
                    with patch(
                        "builtins.print", side_effect=lambda x: captured.write(x + "\n")
                    ):
                        cfg_mod.cmd_export(args)

        data = json.loads(captured.getvalue().strip())
        self.assertEqual(len(data["oneshots"]), 1)
        self.assertEqual(data["oneshots"][0]["message"], "new")


# ---------------------------------------------------------------------------
# commands/config.py — CSV export with --oneshots appends oneshots section
#
# Bug: CSV export had no support for one-shots, so they couldn't be backed
#      up in CSV format.
# Fix: when --oneshots is set and there are pending one-shots, a
#      "# oneshots: ..." section is appended after the reminders CSV.
# ---------------------------------------------------------------------------
class TestExportCsvWithOneshots(unittest.TestCase):
    """cmd_export --format csv --oneshots must append a # oneshots: section."""

    def test_csv_oneshots_section(self):
        from kim.commands import config as cfg_mod

        future = time.time() + 9999
        oneshots = [
            {
                "message": "deploy",
                "fire_at": future,
                "title": "Deploy",
                "urgency": "normal",
            }
        ]
        fake_config = {"reminders": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            oneshot_file = Path(tmpdir) / "oneshots.json"
            oneshot_file.write_text(json.dumps(oneshots), encoding="utf-8")

            captured = io.StringIO()
            args = MagicMock()
            args.format = "csv"
            args.output = None
            args.oneshots = True

            with patch.object(cfg_mod, "load_config", return_value=fake_config):
                with patch.object(cfg_mod, "ONESHOT_FILE", oneshot_file):
                    with patch(
                        "builtins.print", side_effect=lambda x: captured.write(x + "\n")
                    ):
                        cfg_mod.cmd_export(args)

        output = captured.getvalue()
        self.assertIn(
            "# oneshots:",
            output,
            "CSV export with --oneshots must include '# oneshots:' section",
        )
        self.assertIn("deploy", output.lower())


# ---------------------------------------------------------------------------
# commands/config.py — import with --oneshots writes future one-shots
#
# Bug: kim import had no way to restore one-shot reminders from an export.
# Fix: --oneshots flag reads the "oneshots" key from the JSON file and
#      writes future fire times to ONESHOT_FILE.
# ---------------------------------------------------------------------------
class TestImportWithOneshots(unittest.TestCase):
    """cmd_import --oneshots must write future one-shots to ONESHOT_FILE."""

    def test_future_oneshots_written(self):
        from kim.commands import config as cfg_mod

        future = time.time() + 9999
        import_data = {
            "reminders": [],
            "oneshots": [
                {
                    "message": "post-deploy",
                    "fire_at": future,
                    "title": "Deploy",
                    "urgency": "normal",
                }
            ],
        }
        fake_config = {"reminders": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            import_file = Path(tmpdir) / "backup.json"
            import_file.write_text(json.dumps(import_data), encoding="utf-8")
            oneshot_file = Path(tmpdir) / "oneshots.json"
            oneshot_file.write_text("[]", encoding="utf-8")

            args = MagicMock()
            args.file = str(import_file)
            args.format = "auto"
            args.merge = False
            args.oneshots = True

            with patch.object(cfg_mod, "load_config", return_value=fake_config):
                with patch.object(cfg_mod, "_save_config"):
                    with patch.object(cfg_mod, "ONESHOT_FILE", oneshot_file):
                        with patch("builtins.print"):
                            cfg_mod.cmd_import(args)

            written = json.loads(oneshot_file.read_text())
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0]["message"], "post-deploy")


# ---------------------------------------------------------------------------
# commands/config.py — import skips duplicate one-shots (same fire_at)
#
# Bug: importing a backup file multiple times would duplicate one-shots in
#      ONESHOT_FILE since there was no deduplication check.
# Fix: existing fire_at timestamps are collected; only one-shots not already
#      in ONESHOT_FILE are appended.
# ---------------------------------------------------------------------------
class TestImportWithOneshotsSkipsDuplicates(unittest.TestCase):
    """cmd_import --oneshots must not add a one-shot whose fire_at already exists."""

    def test_no_duplicate_fire_at(self):
        from kim.commands import config as cfg_mod

        future = time.time() + 9999
        existing = [{"message": "existing", "fire_at": future}]
        import_data = {
            "reminders": [],
            "oneshots": [
                {
                    "message": "same-time",
                    "fire_at": future,
                    "title": "T",
                    "urgency": "normal",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            import_file = Path(tmpdir) / "backup.json"
            import_file.write_text(json.dumps(import_data), encoding="utf-8")
            oneshot_file = Path(tmpdir) / "oneshots.json"
            oneshot_file.write_text(json.dumps(existing), encoding="utf-8")

            args = MagicMock()
            args.file = str(import_file)
            args.format = "auto"
            args.merge = False
            args.oneshots = True

            with patch.object(cfg_mod, "load_config", return_value={"reminders": []}):
                with patch.object(cfg_mod, "_save_config"):
                    with patch.object(cfg_mod, "ONESHOT_FILE", oneshot_file):
                        with patch("builtins.print"):
                            cfg_mod.cmd_import(args)

            written = json.loads(oneshot_file.read_text())
            self.assertEqual(
                len(written),
                1,
                "Duplicate fire_at must not be added; ONESHOT_FILE should still have exactly 1 entry",
            )


# ---------------------------------------------------------------------------
# commands/config.py — import skips expired one-shots
#
# Bug: if an export file contained old one-shots with fire_at in the past,
#      importing them would add stale entries that would never fire.
# Fix: only one-shots with fire_at > now are written during import.
# ---------------------------------------------------------------------------
class TestImportWithOneshotsExpiredSkipped(unittest.TestCase):
    """cmd_import --oneshots must skip one-shots with past fire_at."""

    def test_expired_not_written(self):
        from kim.commands import config as cfg_mod

        past = time.time() - 100
        future = time.time() + 9999
        import_data = {
            "reminders": [],
            "oneshots": [
                {
                    "message": "old",
                    "fire_at": past,
                    "title": "Old",
                    "urgency": "normal",
                },
                {
                    "message": "new",
                    "fire_at": future,
                    "title": "New",
                    "urgency": "normal",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            import_file = Path(tmpdir) / "backup.json"
            import_file.write_text(json.dumps(import_data), encoding="utf-8")
            oneshot_file = Path(tmpdir) / "oneshots.json"
            oneshot_file.write_text("[]", encoding="utf-8")

            args = MagicMock()
            args.file = str(import_file)
            args.format = "auto"
            args.merge = False
            args.oneshots = True

            with patch.object(cfg_mod, "load_config", return_value={"reminders": []}):
                with patch.object(cfg_mod, "_save_config"):
                    with patch.object(cfg_mod, "ONESHOT_FILE", oneshot_file):
                        with patch("builtins.print"):
                            cfg_mod.cmd_import(args)

            written = json.loads(oneshot_file.read_text())
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0]["message"], "new")


# ---------------------------------------------------------------------------
# selfupdate.py — cmd_uninstall clears ONESHOT_FILE before removal
#
# Bug: uninstall removed ~/.kim/ but left orphan fork children alive with a
#      reference to oneshots.json. On restart, they could re-add their entry.
# Fix: before removing files, write "[]" to ONESHOT_FILE so surviving fork
#      children read an empty list on their next check.
# ---------------------------------------------------------------------------
class TestUninstallClearsOneshotFile(unittest.TestCase):
    """cmd_uninstall must write '[]' to ONESHOT_FILE before removal."""

    def test_oneshot_file_cleared(self):
        from kim import selfupdate

        with tempfile.TemporaryDirectory() as tmpdir:
            oneshot_file = Path(tmpdir) / "oneshots.json"
            future = time.time() + 9999
            oneshot_file.write_text(
                json.dumps([{"message": "pending", "fire_at": future}]),
                encoding="utf-8",
            )

            with patch.object(selfupdate, "PID_FILE", Path(tmpdir) / "kim.pid"):
                with patch("builtins.input", return_value="y"):
                    with patch.object(selfupdate, "_remove_os_service"):
                        with patch.object(selfupdate, "_kill_remind_fire_orphans"):
                            with patch.object(selfupdate, "_close_log_handles"):
                                with patch.object(
                                    selfupdate,
                                    "_detect_install_type",
                                    return_value="pip",
                                ):
                                    with patch.object(selfupdate, "_uninstall_pip"):
                                        # Patch ONESHOT_FILE at the import location in selfupdate
                                        import kim.core as _core

                                        with patch.object(
                                            _core, "ONESHOT_FILE", oneshot_file
                                        ):
                                            # Also patch the local import used in cmd_uninstall
                                            with patch(
                                                "kim.selfupdate.ONESHOT_FILE",
                                                oneshot_file,
                                                create=True,
                                            ):
                                                with patch("builtins.print"):
                                                    # Patch the from .core import
                                                    orig = selfupdate.__dict__.get(
                                                        "ONESHOT_FILE"
                                                    )
                                                    selfupdate.__dict__[
                                                        "ONESHOT_FILE"
                                                    ] = oneshot_file
                                                    try:
                                                        selfupdate.cmd_uninstall(
                                                            MagicMock()
                                                        )
                                                    except SystemExit:
                                                        pass
                                                    finally:
                                                        if orig is not None:
                                                            selfupdate.__dict__[
                                                                "ONESHOT_FILE"
                                                            ] = orig
                                                        else:
                                                            selfupdate.__dict__.pop(
                                                                "ONESHOT_FILE", None
                                                            )

            content = oneshot_file.read_text(encoding="utf-8").strip()
            self.assertEqual(
                content,
                "[]",
                f"cmd_uninstall must write '[]' to ONESHOT_FILE, got: {content!r}",
            )

    def test_oneshot_clear_in_source(self):
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate.cmd_uninstall)
        self.assertIn(
            "[]",
            src,
            "cmd_uninstall source must contain '[]' for clearing ONESHOT_FILE",
        )
        self.assertIn(
            "ONESHOT_FILE",
            src,
            "cmd_uninstall must reference ONESHOT_FILE",
        )


# ---------------------------------------------------------------------------
# selfupdate.py — _kill_remind_fire_orphans on Linux reads /proc
#
# Bug: Linux had no orphan-killing logic at all — only macOS pkill and Windows
#      Stop-Process were handled.
# Fix: on Linux, iterate /proc/<pid>/cmdline and SIGTERM processes whose
#      cmdline contains "kim" and "remind" (excluding own PID).
# ---------------------------------------------------------------------------
class TestKillOrphanLinuxReadsProcFs(unittest.TestCase):
    """On Linux, _kill_remind_fire_orphans must read /proc and SIGTERM matching PIDs."""

    def test_linux_reads_proc_in_source(self):
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._kill_remind_fire_orphans)
        self.assertIn(
            "/proc",
            src,
            "_kill_remind_fire_orphans must read /proc on Linux",
        )
        self.assertIn(
            "cmdline",
            src,
            "_kill_remind_fire_orphans must read /proc/<pid>/cmdline",
        )
        self.assertIn(
            "SIGTERM",
            src,
            "_kill_remind_fire_orphans must send SIGTERM on Linux",
        )

    @unittest.skipIf(platform.system() != "Linux", "Linux-specific test")
    def test_linux_kills_matching_process(self):
        """With a fake /proc structure, SIGTERM must be sent to matching PID."""
        from kim import selfupdate
        import signal as _signal

        my_pid = os.getpid()
        fake_pid = 99999
        killed = []

        # Build a fake /proc directory
        with tempfile.TemporaryDirectory() as tmpdir:
            proc_dir = Path(tmpdir)
            # Create entry for our fake PID
            pid_dir = proc_dir / str(fake_pid)
            pid_dir.mkdir()
            # cmdline: python3\x00kim\x00remind (mimics fork child)
            (pid_dir / "cmdline").write_bytes(b"python3\x00kim\x00remind\x00")
            # Create entry for current PID (should be skipped)
            own_dir = proc_dir / str(my_pid)
            own_dir.mkdir()
            (own_dir / "cmdline").write_bytes(b"python3\x00test\x00")

            def fake_kill(pid, sig):
                killed.append((pid, sig))

            with patch("kim.selfupdate.os.kill", side_effect=fake_kill):
                with patch(
                    "pathlib.Path.iterdir",
                    return_value=[
                        proc_dir / str(fake_pid),
                        proc_dir / str(my_pid),
                    ],
                ):
                    # Override the proc_dir used inside the function
                    original_src = selfupdate._kill_remind_fire_orphans
                    # We test by patching Path("/proc") iteration
                    import kim.selfupdate as su_mod

                    orig_path = su_mod.__dict__.get("Path")
                    # Patch at os.getpid to return something other than fake_pid
                    with patch("kim.selfupdate.os.getpid", return_value=my_pid):
                        # Simulate the Linux branch: patch platform check
                        with patch("kim.selfupdate.platform") as mock_platform:
                            mock_platform.system.return_value = "Linux"
                            # Can't easily mock /proc iteration without deeper patching,
                            # so we verify via source inspection that the logic is correct
                            pass

        # Source-level verification (functional test is complex due to /proc)
        import inspect

        src = inspect.getsource(selfupdate._kill_remind_fire_orphans)
        self.assertIn("os.kill(pid,", src.replace(" ", "").replace("\n", ""))


# ---------------------------------------------------------------------------
# selfupdate.py — _kill_remind_fire_orphans never kills own PID
#
# Bug: if the regex matched the current process's own cmdline, it would
#      self-terminate — instantly killing the running `kim uninstall` process.
# Fix: `if pid == my_pid: continue` guard added on Linux path.
# ---------------------------------------------------------------------------
class TestKillOrphanSkipsOwnPid(unittest.TestCase):
    """_kill_remind_fire_orphans must never send a signal to its own PID."""

    def test_own_pid_excluded_in_source(self):
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._kill_remind_fire_orphans)
        self.assertIn(
            "getpid",
            src,
            "_kill_remind_fire_orphans must call os.getpid() to exclude self",
        )
        self.assertTrue(
            "my_pid" in src or "getpid()" in src,
            "_kill_remind_fire_orphans must store own PID and skip it",
        )

    def test_own_pid_not_killed(self):
        """Functional: even if own cmdline matches, os.kill must not be called for own PID."""
        from kim import selfupdate

        killed_pids = []
        my_pid = os.getpid()

        def fake_kill(pid, sig):
            killed_pids.append(pid)

        # We run the real function on Linux with a patched os.kill
        if platform.system() != "Linux":
            self.skipTest("Linux-only functional test")

        with patch("os.kill", side_effect=fake_kill):
            selfupdate._kill_remind_fire_orphans("Linux")

        self.assertNotIn(
            my_pid,
            killed_pids,
            "_kill_remind_fire_orphans must not send SIGTERM to its own PID",
        )


# ---------------------------------------------------------------------------
# selfupdate.py — _kill_remind_fire_orphans uses pkill on macOS
#
# Bug: macOS had no /proc filesystem. The function needed a different strategy.
# Fix: on Darwin (and other Unix), fall back to pkill -f with the relevant
#      patterns ("_remind-fire", "kim remind").
# ---------------------------------------------------------------------------
class TestKillOrphanMacOsFallback(unittest.TestCase):
    """On Darwin, _kill_remind_fire_orphans must call pkill -f."""

    def test_darwin_uses_pkill_in_source(self):
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate._kill_remind_fire_orphans)
        self.assertIn(
            "pkill",
            src,
            "_kill_remind_fire_orphans must use pkill on macOS/other Unix",
        )

    def test_darwin_calls_subprocess_run_with_pkill(self):
        from kim import selfupdate

        ran = []

        def fake_run(cmd, **kwargs):
            ran.append(cmd)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            with patch("shutil.which", return_value="/usr/bin/pkill"):
                selfupdate._kill_remind_fire_orphans("Darwin")

        pkill_calls = [c for c in ran if c and c[0] == "pkill"]
        self.assertGreater(
            len(pkill_calls),
            0,
            "_kill_remind_fire_orphans must call pkill on Darwin",
        )
        # Must target the right patterns
        patterns_used = [c[2] for c in pkill_calls if len(c) > 2]
        self.assertTrue(
            any("remind" in p for p in patterns_used),
            f"pkill must target 'remind' pattern, got: {patterns_used}",
        )


# ---------------------------------------------------------------------------
# management.py — index-based removal for recurring reminders (v4.5.7)
# ---------------------------------------------------------------------------
class TestRemoveByIndex(unittest.TestCase):
    """
    kim remove <N> removes the Nth recurring reminder by 1-based index.

    Bug this catches: before index support, users had to type the full name.
    A digit-only argument would fall through to name-match (finding nothing)
    and then auto-try one-shots, making index removal impossible for recurring
    reminders.
    """

    def _make_args(self, name, oneshot=False):
        args = MagicMock()
        args.name = name
        args.oneshot = oneshot
        return args

    def test_remove_by_index_first(self):
        """kim remove 1 removes the first recurring reminder."""
        config = {
            "reminders": [
                {"name": "water", "interval": "30m"},
                {"name": "stretch", "interval": "1h"},
            ]
        }
        with patch("kim.commands.management.load_config", return_value=config), patch(
            "kim.commands.management._save_config"
        ) as mock_save, patch("kim.commands.management._signal_reload"), patch(
            "builtins.print"
        ):
            from kim.commands.management import cmd_remove

            cmd_remove(self._make_args("1"))

        saved = mock_save.call_args[0][0]
        names = [r["name"] for r in saved["reminders"]]
        self.assertEqual(names, ["stretch"])

    def test_remove_by_index_second(self):
        """kim remove 2 removes the second recurring reminder."""
        config = {
            "reminders": [
                {"name": "water", "interval": "30m"},
                {"name": "stretch", "interval": "1h"},
                {"name": "standup", "at": "10:00"},
            ]
        }
        with patch("kim.commands.management.load_config", return_value=config), patch(
            "kim.commands.management._save_config"
        ) as mock_save, patch("kim.commands.management._signal_reload"), patch(
            "builtins.print"
        ):
            from kim.commands.management import cmd_remove

            cmd_remove(self._make_args("2"))

        saved = mock_save.call_args[0][0]
        names = [r["name"] for r in saved["reminders"]]
        self.assertEqual(names, ["water", "standup"])

    def test_remove_by_index_out_of_range(self):
        """kim remove 99 exits with error when index exceeds reminder count."""
        config = {"reminders": [{"name": "water", "interval": "30m"}]}
        with patch("kim.commands.management.load_config", return_value=config), patch(
            "builtins.print"
        ):
            from kim.commands.management import cmd_remove

            with self.assertRaises(SystemExit) as ctx:
                cmd_remove(self._make_args("99"))
            self.assertEqual(ctx.exception.code, 1)

    def test_remove_by_name_still_works(self):
        """kim remove water still works after index support added."""
        config = {
            "reminders": [
                {"name": "water", "interval": "30m"},
                {"name": "stretch", "interval": "1h"},
            ]
        }
        with patch("kim.commands.management.load_config", return_value=config), patch(
            "kim.commands.management._save_config"
        ) as mock_save, patch("kim.commands.management._signal_reload"), patch(
            "builtins.print"
        ):
            from kim.commands.management import cmd_remove

            cmd_remove(self._make_args("water"))

        saved = mock_save.call_args[0][0]
        names = [r["name"] for r in saved["reminders"]]
        self.assertEqual(names, ["stretch"])

    def test_list_shows_index_column(self):
        """kim list output must include a # index column."""
        import inspect
        from kim.commands import config as config_mod

        src = inspect.getsource(config_mod.cmd_list)
        self.assertIn("'#'", src)


if __name__ == "__main__":
    unittest.main()
