"""Resolving the show a trigger asked for.

A trigger arrives carrying a string - from a config file, a WebSocket frame, a
command line, or another show's ``next_show``. All four go through here, so
they all accept the same references and fail the same way:

* a path, absolute or relative to the working directory;
* a file name inside the shows directory, with or without its extension;
* the ``name`` written inside a show file, matched case-insensitively.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from .timeline import Show

log = logging.getLogger(__name__)

SHOW_SUFFIXES = (".show.json", ".json")


class ShowLibrary:
    """The set of shows a trigger can name.

    The directory is re-read on every lookup rather than cached: shows are
    dropped onto these machines while they are running, and a stale index that
    needs a restart to clear would be a worse bug than a directory scan.
    """

    def __init__(self, directories: Iterable[str | Path] = ()) -> None:
        self.directories = [Path(d).expanduser() for d in directories]

    def add_directory(self, directory: str | Path) -> None:
        path = Path(directory).expanduser()
        if path not in self.directories:
            self.directories.append(path)

    def files(self) -> list[Path]:
        """Every show file in the library, de-duplicated, in directory order."""
        found: list[Path] = []
        seen: set[Path] = set()
        for directory in self.directories:
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if path.is_file() and path.name.lower().endswith(SHOW_SUFFIXES):
                    resolved = path.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        found.append(path)
        return found

    def find(self, reference: str) -> Path | None:
        """The file a reference names, or ``None`` if nothing matches."""
        reference = str(reference).strip()
        if not reference:
            return None

        direct = Path(reference).expanduser()
        if direct.is_file():
            return direct

        candidates = [reference, *(f"{reference}{suffix}" for suffix in SHOW_SUFFIXES)]
        for directory in self.directories:
            for candidate in candidates:
                path = directory / candidate
                if path.is_file():
                    return path

        # Last resort: the name written inside the file, which is what an
        # operator sees in the UI and the most natural thing to type.
        wanted = reference.casefold()
        for path in self.files():
            if path.stem.casefold() == wanted or path.name.casefold() == wanted:
                return path
            if self._show_name(path).casefold() == wanted:
                return path
        return None

    def load(self, reference: str) -> Show | None:
        """Load the show a reference names. Unreadable files are logged, not raised."""
        path = self.find(reference)
        if path is None:
            log.error("No show matches %r in %s", reference, self.directories or "(no directories)")
            return None
        try:
            return Show.load(path)
        except (OSError, ValueError, KeyError) as error:
            log.error("Could not load show %s: %s", path, error)
            return None

    def names(self) -> list[str]:
        """Show names for display, one per file in the library."""
        return [self._show_name(path) or path.stem for path in self.files()]

    @staticmethod
    def _show_name(path: Path) -> str:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        return str(data.get("name", "")) if isinstance(data, dict) else ""
