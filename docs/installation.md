# Installation

## Automatic Installation (Recommended)

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/install.sh | bash
```

The script will:
1. Check / install Python 3
2. Install `kim-reminder` via pip
3. Add `~/.local/bin` to PATH if needed
4. Set up autostart (systemd user service on Linux, launchd agent on macOS)
5. Start the daemon

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/pratikwayal01/kim/main/install.ps1 | iex"
```

The script will:
1. Check / install Python 3
2. Install `kim-reminder` via pip
3. Add the pip Scripts directory to your user PATH automatically
4. Set up Task Scheduler for autostart
5. Start the daemon

---

## pip (manual — all platforms)

[![PyPI](https://img.shields.io/pypi/v/kim-reminder)](https://pypi.org/project/kim-reminder/)

```bash
pip install kim-reminder
```

Then run `kim start` to launch the daemon.

> **Windows note:** pip installs the `kim.exe` script into a user Scripts directory
> that is often **not on PATH** by default. If `kim` is not found after install,
> run the following once in PowerShell to fix it:
>
> ```powershell
> $p = python -c "import sysconfig; print(sysconfig.get_path('scripts','nt_user'))"
> [Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";" + $p, "User")
> $env:PATH += ";$p"
> ```
>
> Open a new terminal window and `kim --version` should work.

---

## Manual Installation

### From Source

1. Clone the repository:
   ```bash
   git clone https://github.com/pratikwayal01/kim.git
   cd kim
   ```

2. No dependencies required — pure Python stdlib.

3. Install in editable mode:
   ```bash
   pip install -e .
   ```

### Prebuilt Binaries

Download the latest binary for your platform from [GitHub Releases](https://github.com/pratikwayal01/kim/releases).

---

## Post-Installation

After installation, kim starts automatically on login. You can manage it with:

```bash
kim start      # Start the daemon
kim stop       # Stop the daemon
kim status     # Show status
```

## Updating

### Automatic

```bash
kim self-update
```

### Via pip

```bash
pip install --upgrade kim-reminder
```

### Manual

Re-run the installation script or download the latest binary.

## Uninstallation

```bash
kim uninstall
```

This will:
- Stop the daemon
- Remove systemd / launchd / Task Scheduler entries
- Delete configuration and log files
- Remove the binary

## Troubleshooting

### `kim` not found after `pip install` (Windows)

pip installs `kim.exe` to a user Scripts directory that may not be on PATH.
Run this once in PowerShell:

```powershell
$p = python -c "import sysconfig; print(sysconfig.get_path('scripts','nt_user'))"
[Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";" + $p, "User")
$env:PATH += ";$p"
```

Open a new terminal — `kim --version` should now work.

### `kim` not found after `pip install` (Linux / macOS)

Ensure `~/.local/bin` is in your PATH. Add this to your shell config (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Daemon Not Starting

Check the logs:
```bash
kim logs
```

Ensure the config file is valid:
```bash
kim validate
```