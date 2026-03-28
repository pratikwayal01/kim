# kim Wiki Update

## Latest Changes (v2.1.0 -> Refactoring)

### Modular Package Structure

The codebase has been refactored from two monolithic Python files (`kim.py` and `kim_scheduler.py`) into a modular package structure with multiple folders:

```
kim/
├── __init__.py
├── __main__.py
├── cli.py              # CLI argument parsing and command dispatch
├── core.py             # Config, paths, logging, constants
├── notifications.py    # Platform-specific notifications and Slack
├── sound.py            # Sound playback and validation
├── scheduler.py        # Heapq scheduler (moved from kim_scheduler.py)
├── interactive.py      # Interactive mode with TUI
├── selfupdate.py       # Self-update and uninstall commands
├── utils.py            # Cross-platform symbols and utilities
└── commands/
    ├── config.py       # Config-related commands
    ├── daemon.py       # Daemon management
    ├── management.py   # Reminder management
    └── misc.py         # Miscellaneous commands
```

### Key Improvements

1. **Cross-Platform Compatibility**: Added ASCII fallbacks for Unicode symbols on Windows (✓→OK, ●→*, ○→o, etc.)
2. **Testing**: Added unit tests and GitHub Actions CI/CD pipeline that runs tests on Windows, macOS, and Linux
3. **Documentation**: Comprehensive documentation in `docs/` folder, deployable to GitHub Pages
4. **Build Process**: Updated build workflow to run tests before building binaries

### New Features

- **Interactive Mode**: Text-based UI for managing reminders (`kim interactive` or `kim -i`)
- **One-shot Reminders**: `kim remind "standup" in 10m`
- **Self-update**: `kim self-update` checks GitHub releases
- **Export/Import**: JSON and CSV support
- **Config Validation**: `kim validate`
- **Slack Integration**: Webhook and bot token support
- **Custom Sound Files**: wav, mp3, ogg, flac, aiff, m4a

### Installation

Same as before:

**Linux / macOS**
```bash
curl -fsSL https://raw.githubusercontent.com/pratikwayal01/kim/main/install.sh | bash
```

**Windows** (PowerShell as Admin)
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/pratikwayal01/kim/main/install.ps1 | iex"
```

### Configuration

Configuration remains in `~/.kim/config.json`. Example:

```json
{
  "reminders": [
    {
      "name": "eye-break",
      "interval_minutes": "30m",
      "title": "👁️ Eye Break",
      "message": "Look 20 feet away for 20 seconds. Blink slowly.",
      "urgency": "critical",
      "enabled": true
    }
  ],
  "sound": true,
  "slack": {
    "enabled": false,
    "webhook_url": "",
    "bot_token": "",
    "channel": "#general"
  }
}
```

### Documentation

Full documentation is available in the `docs/` folder and can be viewed as a website via GitHub Pages:

- [Home](docs/index.md)
- [Installation](docs/installation.md)
- [Configuration](docs/configuration.md)
- [Commands](docs/commands.md)
- [Sound](docs/sound.md)
- [Slack](docs/slack.md)
- [Development](docs/development.md)
- [Changelog](docs/changelog.md)

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes
4. Run tests: `python -m unittest discover -s tests -v`
5. Submit a pull request

### Links

- [GitHub Repository](https://github.com/pratikwayal01/kim)
- [Issue Tracker](https://github.com/pratikwayal01/kim/issues)
- [Documentation](https://pratikwayal01.github.io/kim/)

---

*To update the wiki, copy the relevant sections above into the appropriate wiki pages.*