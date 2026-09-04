"""Entry point for `python -m purr` and the `purr` script."""
from __future__ import annotations

import sys

from purr.app import PurrApp


def main() -> int:
    """Launch the purr TUI."""
    try:
        app = PurrApp()
        app.run()
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
