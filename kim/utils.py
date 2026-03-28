"""
Utility functions and constants for kim.
"""

import platform

# Platform-specific symbols for cross-platform compatibility
if platform.system() == "Windows":
    CHECK = "OK"
    CROSS = "ERROR"
    BULLET = "-"
    EM_DASH = "--"
    WARNING = "!"
    CIRCLE_OPEN = "o"
    CIRCLE_FILLED = "*"
    MIDDOT = "."
    ARROW = ">"
    HLINE = "-"
else:
    CHECK = "\u2713"  # ✓
    CROSS = "\u2717"  # ✗
    BULLET = "\u2022"  # •
    EM_DASH = "\u2014"  # —
    WARNING = "\u26a0"  # ⚠
    CIRCLE_OPEN = "\u25cb"  # ○
    CIRCLE_FILLED = "\u25cf"  # ●
    MIDDOT = "\u00b7"  # ·
    ARROW = "\u25ba"  # ►
    HLINE = "\u2501"  # ━
