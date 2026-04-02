# AGENTS.md — kim codebase guide

kim is a cross-platform Python reminder daemon. It runs on Linux, macOS, and
Windows using only the Python standard library (no third-party runtime deps).

---

## Build / install

```bash
# Editable install (preferred for local dev)
pip install -e .

# Build a distribution wheel
pip install build
python -m build

# Install dev extras (build, twine, pytest)
pip install -e ".[dev]"
```

---

## Running tests

```bash
# Run the full test suite
python -m unittest discover -s tests -v

# Run a single test class
python -m unittest tests.test_basic.TestCore -v

# Run a single test method
python -m unittest tests.test_basic.TestCore.test_parse_interval -v

# Run via pytest (if installed)
pytest tests/ -v

# Run a single test with pytest
pytest tests/test_basic.py::TestCore::test_parse_interval -v
```

All tests are in `tests/test_basic.py`. There is no separate lint step; the
project has no linting configuration. CI runs on ubuntu-latest, macos-latest,
and windows-latest via `.github/workflows/test.yml`.

---

## Project layout

```
kim/
  core.py            # Paths, VERSION, logging setup, load_config(), parse_interval()
  cli.py             # argparse entry point — main() function
  scheduler.py       # KimScheduler (heapq, single background thread)
  notifications.py   # notify(), _notify_slack_*(), platform-specific dispatch
  sound.py           # play_sound_file(), validate_sound_file()
  interactive.py     # TUI interactive mode, _enable_windows_ansi()
  selfupdate.py      # cmd_selfupdate(), cmd_uninstall()
  utils.py           # Platform-safe Unicode symbols (CHECK, CROSS, EM_DASH, …)
  commands/
    daemon.py        # cmd_start(), cmd_stop(), cmd_status()
    management.py    # cmd_add(), cmd_remove(), cmd_enable(), cmd_disable(), cmd_update()
    config.py        # cmd_edit(), cmd_list(), cmd_logs(), cmd_validate(), cmd_export(), cmd_import()
    misc.py          # cmd_remind(), cmd_remind_fire(), cmd_slack(), cmd_sound(), cmd_completion()
tests/
  test_basic.py      # All tests: TestCore, TestScheduler, TestUtils, TestSound, TestEntryPoint
kim.py               # Root entry point for direct execution (python kim.py) and installers
pyproject.toml       # Build config; package name is "kim-reminder", entry point is kim.cli:main
```

Runtime data lives in `~/.kim/`:
- `config.json` — reminder config
- `kim.log` — rotating log (5 MB × 3 backups)
- `kim.pid` — PID of running daemon
- `oneshots.json` — persisted one-shot reminders

---

## Code style

### Language and compatibility
- Python 3.8+ only. No walrus operator (`:=`) unless 3.8 compatible. No
  `match` statements.
- **Zero runtime dependencies.** Never add a `pip install` dependency to
  `[project.dependencies]`. Use only the standard library.
- `tuple[bool, str]` return-type syntax requires Python 3.9+; use
  `Tuple[bool, str]` from `typing` when annotating code that must run on 3.8.

### Formatting
- 4-space indentation; no tabs.
- Max line length ~88 characters (Black-style), but no formatter is enforced.
- Module docstring at the top of every file: `"""One-line description."""`
- Blank line between top-level functions/classes; two blank lines before a
  class definition at module scope.

### Imports
Ordered in three groups, separated by blank lines:
1. Standard library
2. (no third-party runtime deps exist)
3. Local package imports (`from .core import …` or `from ..core import …`)

Never use wildcard imports (`from x import *`).

### Naming
- `snake_case` for functions, variables, and module-level constants.
- `CamelCase` for classes.
- Private helpers prefixed with a single underscore: `_is_process_running()`.
- Constants in `UPPER_SNAKE_CASE`: `VERSION`, `KIM_DIR`, `DEFAULT_CONFIG`.
- Command handlers named `cmd_<subcommand>`: `cmd_start`, `cmd_remind`, etc.

### Type hints
Use type hints on public function signatures. Internal/private helpers may
omit them. Import from `typing` for Python 3.8 compatibility:
```python
from typing import Callable, Dict, List, Optional
```

### Error handling
- Catch specific exceptions; never use a bare `except:`. Catching `Exception`
  is acceptable only when intentionally suppressing all errors (log a warning).
- File I/O: always catch `OSError`. JSON parsing: always catch
  `json.JSONDecodeError`. Subprocess not found: catch `FileNotFoundError`.
- Use `log.warning()` / `log.error()` / `log.exception()` — never `print()`
  inside library code. `print()` is only for user-facing CLI output in command
  handlers.
- For subprocess commands that may not exist on all platforms, check with
  `shutil.which()` before calling, and catch `FileNotFoundError`.

### Logging
Use the shared logger from `core.py`:
```python
from .core import log   # within kim/
from ..core import log  # within kim/commands/
```
Levels:
- `log.debug()` — internal tracing (scheduler events, file operations)
- `log.info()` — lifecycle events (daemon start/stop, reminder fired, config changes)
- `log.warning()` — recoverable problems (stale PID, bad sound file, etc.)
- `log.error()` — non-fatal failures
- `log.exception()` — caught exceptions where the traceback is useful

### Platform handling
- Check `platform.system()` for `"Windows"`, `"Darwin"`, or `"Linux"`.
- File permissions (`os.chmod`) must be guarded: `if platform.system() != "Windows"`.
- Windows does not support `os.fork()`, `os.setsid()`, or SIGTERM across
  processes. Use the existing `_terminate_process()` helper in `commands/daemon.py`
  for cross-platform process termination.
- All user-visible symbols (check marks, arrows, etc.) must come from
  `kim/utils.py` — it provides ASCII fallbacks for Windows.
- Config and data files are always read/written with `encoding="utf-8"`.

### Config writes
Always write config atomically to avoid corruption:
```python
with open(CONFIG, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
if platform.system() != "Windows":
    os.chmod(CONFIG, 0o600)
```
Use `json.dump(..., indent=2)` (2-space indent) consistently.

### Scheduler
- The `KimScheduler` in `scheduler.py` is the single source of truth for
  timing. Do not add `threading.Timer` or `time.sleep` loops for recurring
  notifications.
- One-shot reminders use `_oneshot_add()`. They require the `_oneshot_fire_at`
  key in the reminder dict and must never be rescheduled after firing.
- All mutations to `_heap` and `_live` must be done inside `self._lock`.
  Calling `self._wakeup.set()` after mutations wakes the scheduler thread.

### Security
- When importing reminder data from untrusted files, run every reminder dict
  through `_sanitize_reminder()` in `commands/config.py`.
- Webhook URLs and bot tokens must never be logged at INFO or below.

---

## Key constants to keep in sync

| Symbol | Location | Current value |
|--------|----------|---------------|
| `VERSION` | `kim/core.py:23` | `"3.0.0"` — must match `pyproject.toml` |
| `version` | `pyproject.toml:7` | `"3.1.5"` |

When bumping a release: update **both** `VERSION` in `core.py` and `version`
in `pyproject.toml` together.

---

## Common pitfalls

- `ONESHOT_FILE` is only read at daemon startup (`cmd_start`). A one-shot
  created while the daemon is running is handled via a detached subprocess
  (`os.fork` on Unix, `subprocess.Popen` with `creationflags=0x08000000` on
  Windows) — the daemon does **not** hot-reload `oneshots.json`.
- `cmd_edit` on Unix uses `os.execvp` (replaces the process); on Windows it
  uses `subprocess.run` (blocks until editor closes).
- The `_remind-fire` subcommand is an internal implementation detail used by
  Windows; do not document it to end users or add it to shell completions for
  interactive use.
- `interactive.py` imports `tty`/`termios` inside a `try/except ImportError`
  because those modules do not exist on Windows.
