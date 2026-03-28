# Development

## Building from Source

### Prerequisites

- Python 3.7+
- Git

### Clone Repository

```bash
git clone https://github.com/pratikwayal01/kim.git
cd kim
```

### Run Directly

```bash
python kim.py start
```

### Build Binaries

Install PyInstaller:

```bash
pip install pyinstaller
```

Build for current platform:

```bash
pyinstaller --onefile --name kim kim.py
```

The binary will be in `dist/`.

### Cross-Platform Builds

The GitHub Actions workflow (`.github/workflows/build.yml`) builds for:
- Linux x86_64
- Linux ARM64
- macOS ARM64
- Windows x86_64

## Project Structure

```
kim/
├── kim.py              # Entry point (thin wrapper)
├── kim_old.py          # Backup of original monolithic file
├── test_kim_memory.py  # Memory scale tests
├── install.sh          # Linux/macOS installer
├── install.ps1         # Windows installer
├── .github/
│   └── workflows/
│       ├── test.yml    # CI tests
│       └── build.yml   # Binary builds
├── kim/                # Package
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py          # CLI argument parsing
│   ├── core.py         # Config, paths, logging
│   ├── notifications.py # Notification backends
│   ├── sound.py        # Sound playback
│   ├── scheduler.py    # Heapq scheduler
│   ├── interactive.py  # Interactive TUI
│   ├── selfupdate.py   # Self-update/uninstall
│   ├── utils.py        # Cross-platform utilities
│   └── commands/       # Command implementations
│       ├── config.py
│       ├── daemon.py
│       ├── management.py
│       └── misc.py
├── tests/              # Unit tests
│   └── test_basic.py
└── docs/               # Documentation
    ├── index.md
    ├── installation.md
    ├── configuration.md
    ├── commands.md
    ├── sound.md
    ├── slack.md
    ├── development.md
    └── changelog.md
```

## Testing

### Run Unit Tests

```bash
python -m unittest discover -s tests -v
```

### Run Memory Tests

```bash
python test_kim_memory.py
```

Requires `psutil` for RSS measurements (optional).

### CI Testing

Tests run automatically on push/PR via GitHub Actions (`.github/workflows/test.yml`).

## Code Style

- Follow PEP 8
- Use type hints where practical
- Keep functions focused and small
- Document public functions with docstrings

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Commit Messages

Use conventional commits:
- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation changes
- `style:` formatting
- `refactor:` code refactoring
- `test:` adding tests
- `chore:` maintenance tasks

## Architecture Notes

### Scheduler

The scheduler uses a single `heapq` thread instead of one thread per reminder. This reduces memory usage from ~1.6 MB per thread to ~0.02 MB per reminder.

### Platform Abstraction

Platform-specific code is isolated in:
- `notifications.py` — Notification backends
- `sound.py` — Sound playback
- `utils.py` — Cross-platform symbols

### Command Pattern

Each command is implemented in a separate function in `commands/` subpackage. The CLI dispatcher in `cli.py` maps command names to functions.

## License

MIT License — see [LICENSE](../LICENSE) for details.