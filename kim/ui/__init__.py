"""
kim graphical UI — requires PySide6.

Install with:  pip install kim-reminder[ui]
               pip install PySide6

This package is intentionally isolated from the rest of kim so that the
daemon and CLI continue to work with zero dependencies even when PySide6
is not installed.  Every module in this package imports PySide6 at the top
level; the guard here lets callers detect availability cleanly.
"""

try:
    import PySide6  # noqa: F401

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


def require_pyside6() -> None:
    """Raise SystemExit with a helpful message if PySide6 is not installed."""
    if not PYSIDE6_AVAILABLE:
        import sys

        print(
            "The kim UI requires PySide6, which is not installed.\n"
            "\n"
            "Install it with:\n"
            "  pip install kim-reminder[ui]\n"
            "  # or\n"
            "  pip install PySide6\n",
            file=sys.stderr,
        )
        sys.exit(1)
