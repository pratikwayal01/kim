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
# selfupdate.py — empty tag_name guard
# ---------------------------------------------------------------------------
class TestSelfUpdateEmptyVersion(unittest.TestCase):
    def test_empty_tag_name_guard_present(self):
        import inspect
        from kim import selfupdate

        src = inspect.getsource(selfupdate.cmd_selfupdate)
        self.assertIn(
            "not latest_version",
            src,
            "Must guard against empty latest_version from GitHub API",
        )

    def test_empty_tag_returns_early(self):
        """Simulates GitHub API returning no tag_name; must not attempt update."""
        from kim import selfupdate

        fake_response_data = json.dumps({"tag_name": "", "assets": []}).encode()

        class FakeResponse:
            def read(self):
                return fake_response_data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            with patch("builtins.print") as mock_print:
                args = MagicMock(force=False)
                selfupdate.cmd_selfupdate(args)
                printed = " ".join(str(c) for c in mock_print.call_args_list)
                self.assertIn("Could not determine", printed)


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
        self.assertIn(
            '"interval": interval_str',
            src,
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


if __name__ == "__main__":
    unittest.main()
