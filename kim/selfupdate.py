"""
Self-update and uninstall commands for kim.
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


def cmd_selfupdate(args):
    print(f"Current version: {VERSION}")
    print("Checking for updates...")

    try:
        url = "https://api.github.com/repos/pratikwayal01/kim/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "kim"})

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            latest_version = data.get("tag_name", "").lstrip("v")

            if latest_version == VERSION:
                print(f"You're running the latest version ({VERSION}).")
                return

            print(f"New version available: {latest_version}")

            if not args.force:
                confirm = input("Update? (y/N): ").strip().lower()
                if confirm != "y":
                    print("Update cancelled.")
                    return

            system = platform.system().lower()
            arch = platform.machine()

            if system == "linux":
                arch_map = {
                    "x86_64": "x86_64",
                    "amd64": "x86_64",
                    "aarch64": "arm64",
                    "arm64": "arm64",
                }
                arch = arch_map.get(arch, "x86_64")
                asset_name = f"kim-linux-{arch}"
            elif system == "darwin":
                arch_map = {
                    "x86_64": "x86_64",
                    "amd64": "x86_64",
                    "aarch64": "arm64",
                    "arm64": "arm64",
                }
                arch = arch_map.get(arch, "x86_64")
                asset_name = f"kim-macos-{arch}"
            elif system == "windows":
                asset_name = "kim-windows-x86_64.exe"
            else:
                print(f"Unsupported platform: {system}")
                sys.exit(1)

            asset_url = None
            for a in data.get("assets", []):
                if asset_name in a.get("name", ""):
                    asset_url = a.get("browser_download_url")
                    break

            if not asset_url:
                print(f"No prebuilt binary for {system}-{arch}")
                print("Please update manually from GitHub releases.")
                return

            kim_in_path = shutil.which("kim")
            if kim_in_path:
                kim_path = Path(kim_in_path).resolve()
            else:
                if platform.system() == "Windows":
                    kim_path = (
                        Path.home()
                        / "AppData"
                        / "Local"
                        / "Programs"
                        / "kim"
                        / "kim.exe"
                    )
                elif platform.system() == "Darwin":
                    # Prefer Homebrew prefix if available, otherwise ~/.local/bin
                    brew_bin = Path("/opt/homebrew/bin/kim")
                    kim_path = (
                        brew_bin
                        if brew_bin.parent.exists()
                        else Path.home() / ".local" / "bin" / "kim"
                    )
                else:
                    kim_path = Path.home() / ".local" / "bin" / "kim"
                kim_path.parent.mkdir(parents=True, exist_ok=True)

            # ── Resolve the correct target path ───────────────────────────
            # If shutil.which returned a .py script (user is running the
            # source directly), do NOT overwrite it with a compiled exe —
            # that would put a PE binary where Python expects a script.
            # In that case, fall back to a platform-appropriate install dir.
            if (
                kim_in_path
                and system == "windows"
                and kim_path.suffix.lower() not in (".exe", "")
            ):
                kim_path = (
                    Path.home() / "AppData" / "Local" / "Programs" / "kim" / "kim.exe"
                )
                kim_path.parent.mkdir(parents=True, exist_ok=True)

            tmp_path = kim_path.with_suffix(".new")

            # ── Download with proper headers + streaming ──────────────────
            print(f"Downloading {asset_url}...")
            req = urllib.request.Request(
                asset_url,
                headers={"User-Agent": f"kim/{VERSION}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    if resp.status != 200:
                        print(f"Download failed: HTTP {resp.status}")
                        return
                    with open(tmp_path, "wb") as fout:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            fout.write(chunk)
            except Exception as e:
                tmp_path.unlink(missing_ok=True)
                print(f"Download error: {e}")
                return

            # ── Verify the downloaded file is what we expect ─────────────
            # GitHub CDN sometimes serves HTML redirect/error pages instead
            # of the binary when User-Agent or auth is wrong.  A PE exe
            # always starts with the two-byte magic "MZ"; a Python script
            # always starts with "#!".  HTML would start with "<" or spaces.
            try:
                with open(tmp_path, "rb") as fcheck:
                    magic = fcheck.read(4)
            except Exception:
                magic = b""

            if system == "windows" and kim_path.suffix.lower() == ".exe":
                if not magic.startswith(b"MZ"):
                    tmp_path.unlink(missing_ok=True)
                    print(
                        "Download integrity check failed: not a valid Windows executable."
                    )
                    print("The release asset may not exist yet. Check:")
                    print(
                        f"  https://github.com/pratikwayal01/kim/releases/tag/v{latest_version}"
                    )
                    return
            else:
                # Unix binary or Python script — must not be HTML
                if magic.startswith(b"<") or magic.startswith(b"\xff\xfe<"):
                    tmp_path.unlink(missing_ok=True)
                    print(
                        "Download integrity check failed: received HTML instead of binary."
                    )
                    print(
                        f"  https://github.com/pratikwayal01/kim/releases/tag/v{latest_version}"
                    )
                    return

            if platform.system() != "Windows":
                os.chmod(tmp_path, 0o755)
            try:
                tmp_path.replace(kim_path)
            except PermissionError:
                tmp_path.unlink(missing_ok=True)
                print("Could not replace binary — the file is in use.")
                print(f"  New binary is at: {tmp_path}")
                print(f"  Manually replace: {kim_path}")
                return

            print(f"\n✓ Updated to version {latest_version}")
            print("Run 'kim --version' to verify.")

    except urllib.error.URLError as e:
        print(f"Network error: {e}")
    except Exception as e:
        print(f"Update failed: {e}")
        if args.force:
            raise


def cmd_uninstall(args):
    print("\033[1;31m=== Uninstall kim ===\033[0m\n")

    if PID_FILE.exists():
        print("kim is running. Stop it first with 'kim stop'")
        sys.exit(1)

    confirm = (
        input("This will remove kim data and the binary. Continue? (Y/N): ")
        .strip()
        .lower()
    )
    if confirm != "y":
        print("Uninstall cancelled.")
        return

    system = platform.system()

    if system == "Linux":
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "kim.service"],
            capture_output=True,
        )
        service_path = Path.home() / ".config/systemd/user/kim.service"
        if service_path.exists():
            service_path.unlink()
            print("Removed systemd service.")
    elif system == "Darwin":
        plist = Path.home() / "Library/LaunchAgents/io.kim.reminder.plist"
        if plist.exists():
            subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
            plist.unlink()
            print("Removed launchd plist.")
    elif system == "Windows":
        # Must invoke via powershell.exe, NOT shell=True (cmd.exe).
        # shell=True routes through cmd.exe which cannot parse $false or
        # PowerShell cmdlets, causing output to leak even with capture_output.
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

    # Release the log file handle before wiping KIM_DIR.
    # On Windows, open file handles prevent deletion (WinError 32).
    # logging.shutdown() flushes and closes every handler registered
    # with the root logger, including the FileHandler on kim.log.
    logging.shutdown()

    # Collect binary locations to clean up beyond KIM_DIR
    _system = platform.system()
    binary_candidates = [Path.home() / ".local" / "bin" / "kim"]
    if _system == "Darwin":
        binary_candidates += [
            Path("/usr/local/bin/kim"),
            Path("/opt/homebrew/bin/kim"),
        ]
    elif _system == "Windows":
        binary_candidates += [
            Path.home() / "AppData" / "Local" / "Programs" / "kim" / "kim.exe",
        ]
    # Also add whatever shutil.which finds (covers pip entry-point wrappers)
    _which = shutil.which("kim")
    if _which:
        binary_candidates.append(Path(_which).resolve())
    for path in [KIM_DIR] + list(dict.fromkeys(binary_candidates)):  # dedup
        if path.exists():
            if path.is_dir():
                try:
                    shutil.rmtree(path)
                except PermissionError as e:
                    print(f"Could not remove {path}: {e}")
                    print(
                        "  Close any programs using files in that folder, then delete it manually."
                    )
                    continue
            else:
                try:
                    path.unlink()
                except PermissionError as e:
                    print(f"Could not remove {path}: {e}")
                    continue
            print(f"Removed {path}")

    print("\n✓ kim has been uninstalled.")
    print("Thank you for using kim!")
