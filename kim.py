#!/usr/bin/env python3
"""
kim — keep in mind
Lightweight cross-platform reminder daemon for developers.

This is the entry point script that imports from the kim package.
"""

import sys

# Add the current directory to sys.path to ensure local package is found
# (for development). In installed versions, the package is in site-packages.
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kim.cli import main

if __name__ == "__main__":
    main()
