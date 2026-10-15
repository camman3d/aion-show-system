"""Project-relative locations for config, data and logs.

Everything lives under the project root (the directory holding ``pyproject.toml``
and ``config.json``) so a checkout is self-contained and the config next to the
code is the config that gets read.
"""

from __future__ import annotations

from pathlib import Path

# paths.py -> aion_show_system -> src -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """Directory for ``config.json`` and show files: the project root."""
    return PROJECT_ROOT


def data_dir() -> Path:
    """Directory for application data (caches of assets, indexes, ...)."""
    return _ensure(PROJECT_ROOT / "data")


def log_dir() -> Path:
    """Directory for log files."""
    return _ensure(PROJECT_ROOT / "logs")
