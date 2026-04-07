"""
Self-update and uninstall commands for kim.

Install-type detection
----------------------
kim can be installed in three ways; we detect which one is active and
update accordingly:

1. pip / editable install
   `importlib.metadata` can find the "kim-reminder" distribution.
   Update path: `pip install --upgrade kim-reminder`

2. Single-file / script install  (`~/.kim/kim.py` + a BAT/shell wrapper)
   `shutil.which("kim")` resolves to a .BAT or shell script that calls
   a `kim.py` inside ~/.kim/.  We download the new `kim.py` asset from
   the GitHub release and atomically replace ~/.kim/kim.py.

3. Standalone binary install  (compiled PyInstaller exe on PATH)
   `shutil.which("kim")` resolves to a `.exe` (Windows) or a file with
   no extension whose first bytes are ELF/Mach-O magic (Unix).
   We download the matching platform binary and atomically replace it.
"""

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .core import KIM_DIR, PID_FILE, VERSION, log
from .utils import CHECK


# ---------------------------------------------------------------------------
# Install-type detection
# ---------------------------------------------------------------------------


def _pip_owns_entry_point():
    """Return True only if pip's RECORD lists the current 'kim' binary on PATH.

    If importlib.metadata finds the package but the binary on PATH is NOT in
    pip's RECORD (e.g. orphaned metadata from a previous pip install while the
    active binary was placed by the install script), we should NOT treat this
    as a pip install — doing so causes pip uninstall to say "no files found"
    and leave the binary behind.
    """
    try:
        import importlib.metadata

        dist = importlib.metadata.distribution("kim-reminder")
        kim_bin = shutil.which("kim")
        if kim_bin is None:
            # Metadata exists but no binary — let pip clean up the metadata.
            return True
        kim_real = str(Path(kim_bin).resolve())
        # Walk RECORD entries; each is a path relative to the dist root.
        try:
            record = dist.read_text("RECORD") or ""
        except Exception:
            record = ""
        if record:
            # RECORD lines: path,hash,size — path may be relative or absolute
            dist_loc = str(Path(dist.locate_file("")).resolve())
            for line in record.splitlines():
                entry_path = line.split(",")[0].strip()
                if not entry_path:
                    continue
                resolved = str((Path(dist_loc) / entry_path).resolve())
                if resolved == kim_real:
                    return True
            # Binary not found in RECORD — pip doesn't own this entry point.
            return False
        # No RECORD (editable / legacy install) — trust metadata.
        return True
    except Exception:
        return False


def _detect_install_type():
    """
    Returns one of: "pip", "script", "binary", "unknown"

    "pip"    — installed as a Python package (importlib.metadata finds it AND
               pip's RECORD lists the kim binary on PATH)
    "script" — ~/.kim/kim.py exists and the kim wrapper calls it, OR pip
               metadata exists but the binary is not pip-owned (install-script
               placed the binary after a prior pip install left orphaned metadata)
    "binary" — kim on PATH is a compiled standalone exe / ELF binary
    "unknown"— cannot determine; fall back to pip-upgrade attempt

    Priority: pip (only if it owns the entry point) > binary > script.
    """
    # 1. pip / editable install — only if pip actually owns the binary.
    try:
        import importlib.metadata

        importlib.metadata.distribution("kim-reminder")
        if _pip_owns_entry_point():
            return "pip"
        # Metadata exists but binary not pip-owned — fall through to binary/script checks.
    except Exception:
        pass

    # 2. Binary install — kim on PATH is a compiled standalone exe / ELF binary.
    #    Check this before the script heuristic because a binary install does not
    #    leave ~/.kim/kim.py, but a prior script install might have.
    kim_bin = shutil.which("kim")
    if kim_bin:
        p = Path(kim_bin).resolve()
        if p.suffix.lower() == ".exe":
            return "binary"
        if p.suffix == "":
            try:
                magic = p.read_bytes()[:4]
                if (
                    magic[:2] == b"MZ"
                    or magic[:4] == b"\x7fELF"
                    or magic[:4]
                    in (
                        b"\xfe\xed\xfa\xce",
                        b"\xfe\xed\xfa\xcf",
                        b"\xce\xfa\xed\xfe",
                        b"\xcf\xfa\xed\xfe",
                    )
                ):
                    return "binary"
            except OSError:
                pass

    # 3. Script install — ~/.kim/kim.py exists (last resort)
    script_path = KIM_DIR / "kim.py"
    if script_path.exists():
        return "script"

    return "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_latest_release():
    """Return the parsed JSON of the latest GitHub release, or raise."""
    url = "https://api.github.com/repos/pratikwayal01/kim/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": f"kim/{VERSION}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _parse_version(v: str) -> tuple:
    """
    Parse a 'X.Y.Z' version string into a comparable integer tuple.
    Non-numeric parts are treated as 0 so pre-release suffixes don't crash.
    """
    parts = []
    for segment in v.strip().lstrip("v").split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _find_asset(assets: list, name: str):
    """Return browser_download_url for the asset whose name contains `name`."""
    for a in assets:
        if name in a.get("name", ""):
            return a.get("browser_download_url")
    return None


def _download_to(url, dest: Path, show_progress=True):
    """
    Stream-download `url` to `dest` (a Path).
    Raises on HTTP error or if the downloaded content looks like an HTML
    error page rather than a real binary/script.
    Returns the first 4 bytes (for magic-byte verification by the caller).
    """
    req = urllib.request.Request(url, headers={"User-Agent": f"kim/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} downloading {url}")
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" in content_type:
                raise RuntimeError(
                    f"Received HTML instead of binary (Content-Type: {content_type})"
                )
            if show_progress:
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(dest, "wb") as fout:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        fout.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            print(
                                f"\r  {pct:3d}%  {downloaded // 1024} / {total // 1024} KB",
                                end="",
                                flush=True,
                            )
                if total:
                    print()  # newline after progress
            else:
                with open(dest, "wb") as fout:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        fout.write(chunk)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {e.reason} downloading {url}") from e

    # Read magic bytes for caller to verify
    try:
        return dest.read_bytes()[:4]
    except OSError:
        return b""


def _atomic_replace(src: Path, dst: Path):
    """Replace dst with src atomically.  Raises PermissionError if in use."""
    try:
        src.replace(dst)
    except PermissionError as e:
        src.unlink(missing_ok=True)
        raise PermissionError(
            f"Could not replace {dst} — file may be in use.\n  Run: mv {src} {dst}"
        ) from e


# ---------------------------------------------------------------------------
# Per-install-type update implementations
# ---------------------------------------------------------------------------


def _update_via_pip(latest_version: str, force: bool):
    """
    Run `pip install --upgrade kim-reminder==<version>` in a subprocess.
    This correctly updates the Python package regardless of where pip put it.
    """
    print(f"Upgrading pip package kim-reminder to {latest_version}...")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--break-system-packages",
                "--upgrade",
                f"kim-reminder=={latest_version}",
            ],
            timeout=120,
        )
        if result.returncode != 0:
            # Retry without pinned version (lets pip pick latest)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--break-system-packages",
                    "--upgrade",
                    "kim-reminder",
                ],
                timeout=120,
            )
        if result.returncode == 0:
            print(f"\n{CHECK} Updated to {latest_version}")
            print("Restart your terminal or run 'kim --version' to verify.")
        else:
            print("\nPip upgrade failed. Try manually:")
            print(f"  pip install --break-system-packages --upgrade kim-reminder")
    except FileNotFoundError:
        print("pip not found. Try manually:")
        print(f"  pip install --break-system-packages --upgrade kim-reminder")
    except subprocess.TimeoutExpired:
        print("pip upgrade timed out. Try manually:")
        print(f"  pip install --break-system-packages --upgrade kim-reminder")


def _update_script(assets: list, latest_version: str):
    """
    Script install: download the kim.py asset and replace ~/.kim/kim.py.
    Also replaces the entire kim/ package directory from the source tarball
    if available — but as a minimum the kim.py stub is updated.
    """
    script_path = KIM_DIR / "kim.py"

    # Look for kim.py asset first
    asset_url = _find_asset(assets, "kim.py")
    if not asset_url:
        # Fall back to pip upgrade which will also work if the package is on PyPI
        print("No kim.py asset found in release — attempting pip upgrade instead.")
        _update_via_pip(latest_version, force=True)
        return

    tmp = script_path.with_suffix(".new")
    print(f"Downloading kim.py...")
    try:
        magic = _download_to(asset_url, tmp)
    except RuntimeError as e:
        tmp.unlink(missing_ok=True)
        print(f"Download error: {e}")
        return

    # Verify it looks like a Python script (starts with # or from)
    if magic and not (
        magic.startswith(b"#")
        or magic.startswith(b"fr")
        or magic.startswith(b"im")
        or magic.startswith(b"\xef\xbb\xbf#")
    ):
        tmp.unlink(missing_ok=True)
        print(
            "Integrity check failed: downloaded file does not look like a Python script."
        )
        return

    try:
        _atomic_replace(tmp, script_path)
    except PermissionError as e:
        print(str(e))
        return

    if platform.system() != "Windows":
        try:
            os.chmod(script_path, 0o755)
        except OSError:
            pass

    print(f"\n{CHECK} Updated kim.py to {latest_version}")
    print("Run 'kim --version' to verify.")


def _update_binary(assets: list, latest_version: str):
    """
    Binary install: download the matching platform executable and replace it.
    """
    system = platform.system().lower()
    arch = platform.machine()

    if system == "linux":
        arch = {
            "x86_64": "x86_64",
            "amd64": "x86_64",
            "aarch64": "arm64",
            "arm64": "arm64",
        }.get(arch, "x86_64")
        asset_name = f"kim-linux-{arch}"
    elif system == "darwin":
        arch = {
            "x86_64": "x86_64",
            "amd64": "x86_64",
            "aarch64": "arm64",
            "arm64": "arm64",
        }.get(arch, "x86_64")
        asset_name = f"kim-macos-{arch}"
    elif system == "windows":
        asset_name = "kim-windows-x86_64.exe"
    else:
        print(f"Unsupported platform: {system}")
        sys.exit(1)

    asset_url = _find_asset(assets, asset_name)
    if not asset_url:
        print(f"No prebuilt binary found for {system}-{arch} in the release.")
        print(f"  Available assets: {[a.get('name') for a in assets]}")
        print("Please update manually from:")
        print(f"  https://github.com/pratikwayal01/kim/releases/tag/v{latest_version}")
        return

    # Locate the binary to replace
    kim_bin = shutil.which("kim")
    if kim_bin:
        kim_path = Path(kim_bin).resolve()
        # If on Windows and what's on PATH is not an .exe (e.g. a .BAT shim),
        # look for the actual exe the shim is wrapping, or fall back to default
        if system == "windows" and kim_path.suffix.lower() not in (".exe", ""):
            # Try to parse the BAT to find the exe path
            try:
                bat_content = kim_path.read_text(encoding="utf-8", errors="ignore")
                # BAT line: @"C:\...\kim.exe" %*
                for line in bat_content.splitlines():
                    line = line.strip()
                    if ".exe" in line.lower():
                        import re

                        m = re.search(r'"([^"]+\.exe)"', line, re.IGNORECASE)
                        if m:
                            kim_path = Path(m.group(1))
                            break
            except OSError:
                pass
            if kim_path.suffix.lower() != ".exe":
                kim_path = (
                    Path.home() / "AppData" / "Local" / "Programs" / "kim" / "kim.exe"
                )
                kim_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        if system == "windows":
            kim_path = (
                Path.home() / "AppData" / "Local" / "Programs" / "kim" / "kim.exe"
            )
        elif system == "darwin":
            brew_bin = Path("/opt/homebrew/bin/kim")
            kim_path = (
                brew_bin
                if brew_bin.parent.exists()
                else Path.home() / ".local" / "bin" / "kim"
            )
        else:
            kim_path = Path.home() / ".local" / "bin" / "kim"
        kim_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = kim_path.with_suffix(".new")
    print(f"Downloading {asset_name}...")
    try:
        magic = _download_to(asset_url, tmp_path)
    except RuntimeError as e:
        tmp_path.unlink(missing_ok=True)
        print(f"Download error: {e}")
        return

    # Integrity: Windows exe must start with MZ; Unix must not be HTML
    if system == "windows" and kim_path.suffix.lower() == ".exe":
        if not magic.startswith(b"MZ"):
            tmp_path.unlink(missing_ok=True)
            print("Integrity check failed: not a valid Windows executable.")
            print(
                f"  https://github.com/pratikwayal01/kim/releases/tag/v{latest_version}"
            )
            return
    else:
        if magic.startswith(b"<") or magic.startswith(b"\xff\xfe<"):
            tmp_path.unlink(missing_ok=True)
            print("Integrity check failed: received HTML instead of binary.")
            print(
                f"  https://github.com/pratikwayal01/kim/releases/tag/v{latest_version}"
            )
            return

    if platform.system() != "Windows":
        try:
            os.chmod(tmp_path, 0o755)
        except OSError:
            pass

    try:
        _atomic_replace(tmp_path, kim_path)
    except PermissionError as e:
        print(str(e))
        return

    print(f"\n{CHECK} Updated to {latest_version}: {kim_path}")
    print("Run 'kim --version' to verify.")


# ---------------------------------------------------------------------------
# Public command
# ---------------------------------------------------------------------------


def cmd_selfupdate(args):
    install_type = _detect_install_type()
    print(f"Current version : {VERSION}")
    print(f"Install type    : {install_type}")
    print("Checking for updates...")

    try:
        data = _fetch_latest_release()
    except urllib.error.URLError as e:
        print(f"Network error: {e.reason}")
        return
    except Exception as e:
        print(f"Could not reach GitHub API: {e}")
        return

    latest_version = data.get("tag_name", "").lstrip("v")
    if not latest_version:
        print("Could not determine latest version from GitHub API.")
        return

    current_tuple = _parse_version(VERSION)
    latest_tuple = _parse_version(latest_version)

    if latest_tuple == current_tuple:
        print(f"Already up to date ({VERSION}).")
        return

    if latest_tuple < current_tuple:
        print(
            f"Already up to date ({VERSION}). "
            f"(Latest GitHub release is {latest_version} — "
            "a newer version may not have been released to GitHub yet.)"
        )
        return

    print(f"New version available: {latest_version}  (you have {VERSION})")

    if not args.force:
        try:
            confirm = input("Update? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nUpdate cancelled.")
            return
        if confirm != "y":
            print("Update cancelled.")
            return

    assets = data.get("assets", [])

    if install_type == "pip":
        _update_via_pip(latest_version, args.force)
    elif install_type == "script":
        _update_script(assets, latest_version)
    elif install_type == "binary":
        _update_binary(assets, latest_version)
    else:
        # Unknown — try pip first (most common), then script fallback
        print("Install type unknown — attempting pip upgrade.")
        _update_via_pip(latest_version, args.force)

    log.info(
        "self-update attempted: %s -> %s (install_type=%s)",
        VERSION,
        latest_version,
        install_type,
    )


# ---------------------------------------------------------------------------
# Uninstall helpers
# ---------------------------------------------------------------------------


def _remove_os_service(system):
    """Remove the OS-level autostart service/task if present."""
    if system == "Linux":
        try:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "kim.service"],
                capture_output=True,
            )
        except FileNotFoundError:
            pass
        service_path = Path.home() / ".config/systemd/user/kim.service"
        if service_path.exists():
            service_path.unlink()
            print("Removed systemd service.")
    elif system == "Darwin":
        plist = Path.home() / "Library/LaunchAgents/io.kim.reminder.plist"
        if plist.exists():
            try:
                subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            except FileNotFoundError:
                pass
            plist.unlink()
            print("Removed launchd plist.")
    elif system == "Windows":
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Unregister-ScheduledTask -TaskName KimReminder -Confirm:$false"
                    " -ErrorAction SilentlyContinue",
                ],
                capture_output=True,
            )
            if result.returncode == 0:
                print("Removed scheduled task.")
            else:
                print("No scheduled task found (or already removed).")
        except FileNotFoundError:
            print("No scheduled task found (or already removed).")


def _kill_remind_fire_orphans(system):
    """Kill lingering one-shot fire subprocesses before removing files.

    On Windows: kill processes whose command line contains '_remind-fire'.
    On Unix: the fork children from 'kim remind' sleep until their fire time.
    They inherit sys.argv, so their cmdline always contains 'kim remind'.
    We kill them via /proc (Linux) or 'pkill -f' fallback (macOS/others).
    Our own PID is excluded to avoid self-kill.
    Best-effort — failures are silently ignored.
    """
    try:
        if system == "Windows":
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "Get-WmiObject Win32_Process | "
                    "Where-Object { $_.CommandLine -like '*_remind-fire*' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
                ],
                capture_output=True,
                timeout=10,
            )
        elif system == "Linux":
            # Read /proc/<pid>/cmdline for each process and SIGTERM matching ones.
            import signal as _sig

            my_pid = os.getpid()
            proc_dir = Path("/proc")
            for entry in proc_dir.iterdir():
                if not entry.name.isdigit():
                    continue
                pid = int(entry.name)
                if pid == my_pid:
                    continue
                try:
                    cmdline = (
                        (entry / "cmdline")
                        .read_bytes()
                        .replace(b"\x00", b" ")
                        .decode("utf-8", errors="replace")
                    )
                    if (
                        "kim" in cmdline
                        and "remind" in cmdline
                        and "_remind-fire" not in cmdline
                    ):
                        os.kill(pid, _sig.SIGTERM)
                    elif "_remind-fire" in cmdline:
                        os.kill(pid, _sig.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass  # process already gone
        else:
            # macOS / other Unix: fall back to pkill -f
            import shutil as _shutil

            if _shutil.which("pkill"):
                for pattern in ("_remind-fire", "kim remind"):
                    subprocess.run(
                        ["pkill", "-f", pattern],
                        capture_output=True,
                        timeout=10,
                    )
    except Exception:
        pass


def _close_log_handles():
    """Close all Python-level log file handles held by this process.

    On Windows the OS-level file lock is not released until the process fully
    exits, but closing the handler flushes pending writes and is good practice.
    """
    for logger_name in ("kim", ""):
        _lg = logging.getLogger(logger_name)
        for handler in _lg.handlers[:]:
            try:
                handler.close()
            except Exception:
                pass
            _lg.removeHandler(handler)
    logging.shutdown()
    try:
        import kim.core as _core

        if hasattr(_core, "_handler") and _core._handler is not None:
            try:
                _core._handler.close()
            except Exception:
                pass
            _core._handler = None
    except Exception:
        pass


def _spawn_deferred_ps(ps_script: str):
    """Spawn a hidden, detached PowerShell process to run ps_script after we exit."""
    try:
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                ps_script,
            ],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass  # non-fatal


def _remove_kimdir_deferred_windows():
    """Spawn a hidden PowerShell process to remove KIM_DIR after this process exits.

    On Windows, kim.log is locked by the RotatingFileHandler for the lifetime of
    this process.  The deferred script waits for the process to exit, retries
    deleting kim.log (up to 10 times, 1 s apart), then removes the now-empty
    ~/.kim directory (up to 5 retries).
    """
    d = str(KIM_DIR).replace("'", "''")
    log_file = str(KIM_DIR / "kim.log").replace("'", "''")
    ps_script = "; ".join(
        [
            "Start-Sleep 3",
            # Step 1: delete kim.log once the process releases the handle.
            f"for($j=0;$j -lt 10;$j++){{"
            f"if(Test-Path '{log_file}'){{"
            f"Remove-Item '{log_file}' -Force -ErrorAction SilentlyContinue;"
            f"if(-not(Test-Path '{log_file}')){{break}};Start-Sleep 1}}else{{break}}}}",
            # Step 2: remove the now-empty directory.
            f"for($i=0;$i -lt 5;$i++){{"
            f"if(Test-Path '{d}'){{"
            f"Remove-Item '{d}' -Recurse -Force -ErrorAction SilentlyContinue;"
            f"if(-not(Test-Path '{d}')){{break}};Start-Sleep 1}}else{{break}}}}",
        ]
    )
    _spawn_deferred_ps(ps_script)


def _remove_kimdir(system):
    """Remove ~/.kim user-data directory.

    On Windows, kim.log is OS-locked for the lifetime of this process, so the
    actual deletion is deferred to a background PowerShell subprocess that runs
    after we exit.  On other platforms we can delete immediately.
    """
    if not KIM_DIR.exists():
        return
    if system == "Windows":
        _remove_kimdir_deferred_windows()
    else:
        try:
            shutil.rmtree(KIM_DIR)
            print(f"Removed {KIM_DIR}")
        except PermissionError as e:
            print(f"Could not remove {KIM_DIR}: {e}")
            print(
                "  Close any programs using files in that folder, then delete it manually."
            )


def _uninstall_pip(system):
    """Remove a pip-installed kim-reminder package.

    On non-Windows: run `pip uninstall kim-reminder -y` synchronously, then
    remove ~/.kim/ user data.

    On Windows: kim.exe is the currently-executing process.  Windows will not
    allow any process (including pip) to rename or delete a running .exe
    (WinError 32).  The only solution is to exit first and delete after.  We
    spawn a hidden background PowerShell script that:
      1. Waits for this process to exit (polls until kim.exe is unlocked).
      2. Runs `pip uninstall kim-reminder -y` via the same python.exe.
      3. Removes ~/.kim/ user data (retrying kim.log then the directory).
    """
    if system != "Windows":
        # Non-Windows: pip can remove the entry point cleanly right now.
        print("Detected pip install — running: pip uninstall kim-reminder -y")
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "uninstall",
                    "--break-system-packages",
                    "kim-reminder",
                    "-y",
                ],
                timeout=120,
            )
            if result.returncode == 0:
                print(f"{CHECK} pip uninstall succeeded.")
            else:
                print(
                    "pip uninstall returned a non-zero exit code.\n"
                    "You can finish manually with:  pip uninstall --break-system-packages kim-reminder -y"
                )
        except FileNotFoundError:
            print(
                "pip not found.  Finish manually with:  pip uninstall --break-system-packages kim-reminder -y"
            )
        except subprocess.TimeoutExpired:
            print(
                "pip uninstall timed out.  Finish manually with:  pip uninstall --break-system-packages kim-reminder -y"
            )
        # Also sweep known binary locations — pip may not have owned the entry
        # point (e.g. install-script placed it after a prior pip install left
        # orphaned metadata).
        _remove_binary_candidates(system)
        _remove_kimdir(system)
        return

    # Windows path — everything must happen after this process exits.
    # Build the deferred PowerShell script.
    py = str(sys.executable).replace("'", "''")
    d = str(KIM_DIR).replace("'", "''")
    log_file = str(KIM_DIR / "kim.log").replace("'", "''")

    ps_lines = [
        # Give this process time to fully exit and release all file handles.
        "Start-Sleep 3",
        # Run pip uninstall via the same Python interpreter.
        f"& '{py}' -m pip uninstall --break-system-packages kim-reminder -y",
        # Remove kim.log (retry up to 10 times in case handles linger).
        f"for($j=0;$j -lt 10;$j++){{"
        f"if(Test-Path '{log_file}'){{"
        f"Remove-Item '{log_file}' -Force -ErrorAction SilentlyContinue;"
        f"if(-not(Test-Path '{log_file}')){{break}};Start-Sleep 1}}else{{break}}}}",
        # Remove ~/.kim/ directory (retry up to 5 times).
        f"for($i=0;$i -lt 5;$i++){{"
        f"if(Test-Path '{d}'){{"
        f"Remove-Item '{d}' -Recurse -Force -ErrorAction SilentlyContinue;"
        f"if(-not(Test-Path '{d}')){{break}};Start-Sleep 1}}else{{break}}}}",
    ]
    _spawn_deferred_ps("; ".join(ps_lines))
    print(
        "pip uninstall and data removal scheduled — will complete after this process exits."
    )


def _remove_binary_candidates(system):
    """Delete the kim binary/wrapper from well-known install locations.

    Used by both the pip and script/binary uninstall paths so that any
    binary placed by the install script is always cleaned up regardless of
    which uninstall path was taken.  Windows deferred deletion is handled
    separately by _uninstall_script_or_binary; this function is a no-op on
    Windows.
    """
    if system == "Windows":
        return
    candidates = [Path.home() / ".local" / "bin" / "kim"]
    if system == "Darwin":
        candidates += [
            Path("/usr/local/bin/kim"),
            Path("/opt/homebrew/bin/kim"),
        ]
    _which = shutil.which("kim")
    if _which:
        candidates.append(Path(_which).resolve())
    for path in list(dict.fromkeys(candidates)):
        if path.exists():
            if path.is_dir():
                try:
                    shutil.rmtree(path)
                except PermissionError as e:
                    print(f"Could not remove {path}: {e}")
                    continue
            else:
                try:
                    path.unlink()
                except PermissionError as e:
                    print(f"Could not remove {path}: {e}")
                    continue
            print(f"Removed {path}")


def _uninstall_script_or_binary(system):
    """Remove a script or standalone-binary install of kim.

    Handles direct file deletion with Windows deferred-deletion where needed.
    """
    if system != "Windows":
        _remove_binary_candidates(system)
        # Clean up any orphaned pip metadata left by a prior pip install.
        try:
            import importlib.metadata

            importlib.metadata.distribution("kim-reminder")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "uninstall",
                    "--break-system-packages",
                    "kim-reminder",
                    "-y",
                ],
                timeout=120,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        _remove_kimdir(system)
        return

    # Windows: all binaries are deferred — direct deletion of kim.bat
    # while cmd.exe is still executing it causes "The batch file cannot be
    # found." on exit, and kim.exe may still be the running process.

    deferred_bat = None
    deferred_exe = None
    _which = shutil.which("kim")
    if _which:
        which_path = Path(_which).resolve()
        if which_path.suffix.lower() == ".bat":
            deferred_bat = which_path
        elif which_path.suffix.lower() == ".exe":
            deferred_exe = which_path

    if deferred_bat is None:
        _fallback_bat = Path.home() / ".local" / "bin" / "kim.bat"
        if _fallback_bat.exists():
            deferred_bat = _fallback_bat
    exe_candidates = [
        Path(sys.executable).parent / "Scripts" / "kim.exe",
        Path(sys.executable).parent.parent / "Scripts" / "kim.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "kim" / "kim.exe",
    ]
    for _exe in exe_candidates:
        if _exe.exists() and _exe != deferred_exe:
            deferred_exe = _exe
            break

    _remove_kimdir(system)

    # Deferred deletion for Windows bat/exe files.
    deferred_files = [p for p in (deferred_bat, deferred_exe) if p and p.exists()]
    if deferred_files:
        d = str(KIM_DIR).replace("'", "''") if KIM_DIR.exists() else None
        log_file = str(KIM_DIR / "kim.log").replace("'", "''")
        ps_lines = ["Start-Sleep 3"]
        if d:
            ps_lines += [
                f"for($j=0;$j -lt 10;$j++){{"
                f"if(Test-Path '{log_file}'){{"
                f"Remove-Item '{log_file}' -Force -ErrorAction SilentlyContinue;"
                f"if(-not(Test-Path '{log_file}')){{break}};Start-Sleep 1}}else{{break}}}}",
                f"for($i=0;$i -lt 5;$i++){{"
                f"if(Test-Path '{d}'){{"
                f"Remove-Item '{d}' -Recurse -Force -ErrorAction SilentlyContinue;"
                f"if(-not(Test-Path '{d}')){{break}};Start-Sleep 1}}else{{break}}}}",
            ]
        for p in deferred_files:
            ps = str(p).replace("'", "''")
            ps_lines.append(f"Remove-Item '{ps}' -Force -ErrorAction SilentlyContinue")
        ps_script = "; ".join(ps_lines)
        try:
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-WindowStyle",
                    "Hidden",
                    "-Command",
                    ps_script,
                ],
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Uninstall — public command
# ---------------------------------------------------------------------------


def cmd_uninstall(args):
    print("\033[1;31m=== Uninstall kim ===\033[0m\n")

    if PID_FILE.exists():
        print("kim is running. Stop it first with 'kim stop'")
        sys.exit(1)

    try:
        confirm = (
            input("This will remove kim and its data. Continue? (Y/N): ")
            .strip()
            .lower()
        )
    except (EOFError, KeyboardInterrupt):
        print("\nUninstall cancelled.")
        return

    if confirm != "y":
        print("Uninstall cancelled.")
        return

    system = platform.system()
    install_type = _detect_install_type()

    # 1. Remove OS autostart service/task.
    _remove_os_service(system)

    # 2. Kill orphaned one-shot fire subprocesses.
    _kill_remind_fire_orphans(system)

    # 3. Clear oneshots.json so any surviving fork children cannot re-schedule
    #    their reminders on a future kim start.
    from .core import ONESHOT_FILE

    try:
        if ONESHOT_FILE.exists():
            ONESHOT_FILE.write_text("[]", encoding="utf-8")
    except OSError:
        pass

    # 4. Close this process's log file handles (best-effort flush).
    _close_log_handles()

    # 5. Remove binaries and ~/.kim/ user data.
    if install_type == "pip":
        _uninstall_pip(system)
    else:
        _uninstall_script_or_binary(system)

    print(f"\n{CHECK} kim has been uninstalled.")
    print("Thank you for using kim!")
    if system == "Windows":
        print("  (Open a new terminal for the change to take effect.)")
