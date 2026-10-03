"""What every trigger source has in common.

A trigger is just "start this show, and here is who asked". Sources differ only
in where the string comes from - a schedule, a socket, a command line, the show
that just finished - so they all emit the same event and the manager applies
one policy to all of them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

CLOCK = "clock"
WEBSOCKET = "websocket"
COMMAND = "command"
POLL = "poll"
CHAIN = "chain"
MANUAL = "manual"


@dataclass(frozen=True)
class TriggerEvent:
    """A request to start ``show``, tagged with where it came from."""

    show: str
    source: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.show} ({self.detail or self.source})"


class TriggerSource(QObject):
    """Base class: start listening, emit :class:`TriggerEvent`, stop cleanly.

    ``status_changed`` carries a short line for the UI - "connected",
    "reconnecting in 5s" - because on an unattended machine the only way to
    tell a silent trigger path from a working one is to show it.
    """

    triggered = Signal(object)  # TriggerEvent
    status_changed = Signal(str)

    #: Name used in log lines and in the emitted events.
    source_name = "trigger"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._status = "idle"

    @property
    def status(self) -> str:
        return self._status

    def set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self.status_changed.emit(status)

    def start(self) -> None:
        """Begin listening. Must be safe to call twice."""

    def stop(self) -> None:
        """Stop listening and release anything held. Must be safe to call twice."""

    def fire(self, show: str, detail: str = "") -> None:
        """Emit a trigger for ``show``. For use by subclasses."""
        show = str(show).strip()
        if not show:
            log.warning("%s trigger with no show name; ignored", self.source_name)
            return
        log.info("%s trigger: %s", self.source_name, show)
        self.triggered.emit(TriggerEvent(show=show, source=self.source_name, detail=detail))


def parse_trigger_message(text: str) -> str | None:
    """Pull a show reference out of a WebSocket frame or a command-line message.

    Both wire formats are accepted because both are natural to send by hand:

    * a bare show name or path - ``Nightly``
    * a JSON object - ``{"show": "Nightly"}``, or ``trigger``/``name`` instead
      of ``show``, so a sender does not have to guess the key

    Returns ``None`` for anything that names no show, which the caller reports
    rather than treating as a trigger.
    """
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            log.warning("Trigger message looked like JSON but did not parse: %r", text[:120])
            return None
        if not isinstance(data, dict):
            return None
        command = str(data.get("command", "trigger")).strip().lower()
        if command not in ("trigger", "show", "play", ""):
            log.warning("Unsupported trigger command %r", command)
            return None
        for key in ("show", "trigger", "name"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    return text
