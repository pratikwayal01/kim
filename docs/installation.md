# Installation

## pip (Recommended — all platforms)

[![PyPI](https://img.shields.io/pypi/v/kim-reminder)](https://pypi.org/project/kim-reminder/)

```bash
pip install kim-reminder
```

Then run `kim start` to launch the daemon. That's all.

> pip installs the `kim` command globally. Autostart (systemd / launchd / Task Scheduler)
> is set up the first time you run `kim start`.

## Automatic Installation (binary + autostart)

### Linux / macOS

Run the install script (curl):

```bash
curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/install.sh | bash
```

The script will:
1. Download the latest binary for your platform
2. Install to `~/.local/bin/kim` (or `/usr/local/bin/kim` if writable)
3. Set up autostart (systemd user service on Linux, launchd agent on macOS)
4. Start the daemon

### Windows (PowerShell as Admin)

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/pratikwayal01/kim/main/install.ps1 | iex"
```

The script will:
1. Download the latest Windows executable
2. Install to `AppData\Local\Programs\kim\kim.exe`
3. Add to PATH
4. Set up Task Scheduler for autostart
5. Start the daemon

## Manual Installation

### From Source

1. Clone the repository:
   ```bash
   git clone https://github.com/pratikwayal01/kim.git
   cd kim
   ```

2. No dependencies required — pure Python stdlib.

3. Run directly:
   ```bash
   python kim.py start
   ```

4. Optionally install globally:
   ```bash
   python kim.py  # ensure it's executable
   cp kim.py /usr/local/bin/kim
   chmod +x /usr/local/bin/kim
   ```

### Prebuilt Binaries

Download the latest binary for your platform from [GitHub Releases](https://github.com/pratikwayal01/kim/releases).

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
- Remove systemd/launchd/Task Scheduler entries
- Delete configuration and log files
- Remove the binary

## Troubleshooting

### Permission Issues

- On Linux/macOS, ensure `~/.local/bin` is in your PATH
- On Windows, run PowerShell as Administrator for installation

### Daemon Not Starting

Check the logs:
```bash
kim logs
```

Ensure the config file is valid:
```bash
kim validate
```