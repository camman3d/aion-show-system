"""``python -m aion_show_system`` / console-script entry point."""

from __future__ import annotations

import sys

from .app import run


def main() -> int:
    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
