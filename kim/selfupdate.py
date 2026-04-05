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


def _detect_install_type():
    """
    Returns one of: "pip", "script", "binary", "unknown"

    "pip"    — installed as a Python package (importlib.metadata finds it)
    "script" — ~/.kim/kim.py exists and the kim wrapper calls it
    "binary" — kim on PATH is a compiled standalone exe / ELF binary
    "unknown"— cannot determine; fall back to pip-upgrade attempt

    Priority: pip > binary > script.
    The pip check must win even if ~/.kim/kim.py also exists (a leftover from a
    previous script install does not mean the active install is a script).
    """
    # 1. pip / editable install — authoritative: if the package metadata exists,
    #    pip owns this install regardless of what else is on disk.
    try:
        import importlib.metadata

        importlib.metadata.distribution("kim-reminder")
        return "pip"
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
                "--upgrade",
                f"kim-reminder=={latest_version}",
            ],
            timeout=120,
        )
        if result.returncode != 0:
            # Retry without pinned version (lets pip pick latest)
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "kim-reminder"],
                timeout=120,
            )
        if result.returncode == 0:
            print(f"\n{CHECK} Updated to {latest_version}")
            print("Restart your terminal or run 'kim --version' to verify.")
        else:
            print("\nPip upgrade failed. Try manually:")
            print(f"  pip install --upgrade kim-reminder")
    except FileNotFoundError:
        print("pip not found. Try manually:")
        print(f"  pip install --upgrade kim-reminder")
    except subprocess.TimeoutExpired:
        print("pip upgrade timed out. Try manually:")
        print(f"  pip install --upgrade kim-reminder")


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
# Uninstall
# ---------------------------------------------------------------------------


def cmd_uninstall(args):
    print("\033[1;31m=== Uninstall kim ===\033[0m\n")

    if PID_FILE.exists():
        print("kim is running. Stop it first with 'kim stop'")
        sys.exit(1)

    try:
        confirm = (
            input("This will remove kim data and the binary. Continue? (Y/N): ")
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

    # --- Terminate orphaned one-shot reminder subprocesses --------------------
    # 'kim remind' spawns background subprocesses (python kim.py _remind-fire).
    # If the daemon was stopped while they were sleeping they remain alive,
    # holding their own handle on kim.log.  Since the user is uninstalling,
    # these reminders will never fire anyway — kill them now so the log handle
    # is released before we attempt to delete KIM_DIR.
    # Unix processes don't hold file locks after the parent exits, but we
    # terminate them there too for a clean uninstall.
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-WmiObject Win32_Process | "
                "Where-Object { $_.CommandLine -like '*_remind-fire*' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
            ]
            if system == "Windows"
            else [
                "pkill",
                "-f",
                "_remind-fire",
            ],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass
    # --------------------------------------------------------------------------

    # --- Release all log file handles before touching KIM_DIR ----------------
    # Best-effort: close Python-level handlers so they flush; on Windows the OS
    # file lock on kim.log will not be released until this process exits, so
    # KIM_DIR removal is deferred (see below).
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

        if hasattr(_core, "_handler"):
            try:
                _core._handler.close()
            except Exception:
                pass
            _core._handler = None
    except Exception:
        pass
    # --------------------------------------------------------------------------

    binary_candidates = [Path.home() / ".local" / "bin" / "kim"]
    if system == "Darwin":
        binary_candidates += [
            Path("/usr/local/bin/kim"),
            Path("/opt/homebrew/bin/kim"),
        ]
    elif system == "Windows":
        # On Windows all binaries are deferred (bat shim + exe); nothing goes in
        # binary_candidates here — direct deletion of kim.bat while cmd.exe is
        # still executing it causes "The batch file cannot be found." on exit.
        pass

    # On Windows, shutil.which("kim") may resolve to the currently-executing
    # kim.bat.  Deleting it while cmd.exe is running it causes the
    # "The batch file cannot be found." error after the process exits.
    # Similarly, kim.exe (pip-installed entry point) is the running process
    # itself, so os.unlink() on it yields WinError 5 (Access Denied).
    # KIM_DIR itself cannot be removed because kim.log is locked by this process.
    # All three are collected for deferred deletion after process exit.
    deferred_bat = None
    deferred_exe = None
    deferred_kimdir = None
    _which = shutil.which("kim")
    if _which:
        which_path = Path(_which).resolve()
        if system == "Windows" and which_path.suffix.lower() == ".bat":
            deferred_bat = which_path
        elif system == "Windows" and which_path.suffix.lower() == ".exe":
            deferred_exe = which_path
        else:
            binary_candidates.append(which_path)

    # Also check the pip Scripts exe directly — it won't appear via which() when
    # the .bat shim is the PATH entry, but it still needs deferred deletion.
    # Also fall back to the known bat shim path in case which() didn't find it.
    if system == "Windows":
        import sys as _sys

        if deferred_bat is None:
            _fallback_bat = Path.home() / ".local" / "bin" / "kim.bat"
            if _fallback_bat.exists():
                deferred_bat = _fallback_bat

        exe_candidates = [
            Path(_sys.executable).parent / "Scripts" / "kim.exe",
            Path(_sys.executable).parent.parent / "Scripts" / "kim.exe",
            Path.home() / "AppData" / "Local" / "Programs" / "kim" / "kim.exe",
        ]
        for _exe in exe_candidates:
            if _exe.exists() and _exe != deferred_exe:
                deferred_exe = _exe
                break

    for path in list(dict.fromkeys(binary_candidates)):
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

    # Remove KIM_DIR — on non-Windows we can do it now; on Windows the log file
    # handle is held by this process so we must defer it like the binaries.
    if KIM_DIR.exists():
        if system == "Windows":
            deferred_kimdir = KIM_DIR
        else:
            try:
                shutil.rmtree(KIM_DIR)
                print(f"Removed {KIM_DIR}")
            except PermissionError as e:
                print(f"Could not remove {KIM_DIR}: {e}")
                print(
                    "  Close any programs using files in that folder, then delete it manually."
                )

    # Deferred deletion: spawns a hidden cmd that waits ~2 s (ping trick) then
    # removes all locked paths.  By then this process has exited and all file
    # handles are released by the OS.
    deferred_files = [p for p in (deferred_bat, deferred_exe) if p and p.exists()]
    if deferred_files or deferred_kimdir:
        # Use PowerShell for the deferred cleanup — cleaner quoting and retry logic.
        # Start-Sleep 3 gives this process time to fully exit and release kim.log.
        # By this point all _remind-fire orphans have already been killed above,
        # so the only remaining lock on kim.log is this process's own handler.
        ps_lines = ["Start-Sleep 3"]
        if deferred_kimdir:
            d = str(deferred_kimdir).replace("'", "''")
            log_file = str(deferred_kimdir / "kim.log").replace("'", "''")
            # Step 1: retry deleting kim.log up to 10 times with 1s gaps.
            # It is locked by this process's RotatingFileHandler; the handle
            # is released once the Python process fully exits (after the
            # Start-Sleep above).  SilentlyContinue so a still-locked attempt
            # doesn't abort the script.
            ps_lines.append(
                f"for($j=0;$j -lt 10;$j++){{"
                f"if(Test-Path '{log_file}'){{"
                f"Remove-Item '{log_file}' -Force -ErrorAction SilentlyContinue;"
                f"if(-not(Test-Path '{log_file}')){{break}};Start-Sleep 1}}else{{break}}}}"
            )
            # Step 2: now that kim.log is gone, retry rmdir up to 5 times.
            ps_lines.append(
                f"for($i=0;$i -lt 5;$i++){{"
                f"if(Test-Path '{d}'){{"
                f"Remove-Item '{d}' -Recurse -Force -ErrorAction SilentlyContinue;"
                f"if(-not(Test-Path '{d}')){{break}};Start-Sleep 1}}else{{break}}}}"
            )
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
            pass  # non-fatal

    print(f"\n{CHECK} kim has been uninstalled.")
    print("Thank you for using kim!")
    if system == "Windows":
        print("  (Open a new terminal for the change to take effect.)")
