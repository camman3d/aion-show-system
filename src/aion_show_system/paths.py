"""Platform-correct locations for config, data and logs.

Qt already knows the right directory on every target (AppData on Windows,
~/Library on macOS, XDG dirs on Linux and Raspberry Pi OS), so we defer to it
rather than hard-coding per-OS paths.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths


def _standard_dir(location: QStandardPaths.StandardLocation) -> Path:
    path = Path(QStandardPaths.writableLocation(location))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """Directory for user settings and show files."""
    return _standard_dir(QStandardPaths.StandardLocation.AppConfigLocation)


def data_dir() -> Path:
    """Directory for application data (caches of assets, indexes, ...)."""
    return _standard_dir(QStandardPaths.StandardLocation.AppDataLocation)


def log_dir() -> Path:
    """Directory for log files."""
    return _standard_dir(QStandardPaths.StandardLocation.AppDataLocation) / "logs"
