"""One policy for every trigger, whatever asked for it.

Triggering means: stop what is playing, put the new show in its place, and
start it. The only question is whether the show that is currently running is
willing to be replaced - ``Show.allow_override`` - and that question is asked
here rather than in each source, so a clock trigger, a WebSocket frame and a
command line all behave identically.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from ..config import AppConfig
from ..show import Show, ShowEngine
from ..show.library import ShowLibrary
from .base import CHAIN, TriggerEvent, TriggerSource
from .clock_source import ClockTriggerSource
from .command_source import CommandTriggerSource
from .websocket_source import WebSocketTriggerSource

log = logging.getLogger(__name__)


class TriggerManager(QObject):
    """Owns the trigger sources and turns their events into playback."""

    triggered = Signal(object)  # TriggerEvent that started a show
    rejected = Signal(object, str)  # TriggerEvent, reason

    def __init__(
        self,
        engine: ShowEngine,
        library: ShowLibrary | None = None,
        config: AppConfig | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self.config = config or AppConfig()
        self.library = library or ShowLibrary([self.config.shows_path])
        self.sources: list[TriggerSource] = []
        self.command_source: CommandTriggerSource | None = None

        # A show naming ``next_show`` is a trigger like any other; it just
        # fires when the show ends rather than when a clock or a socket says so.
        self.engine.show_finished.connect(self._on_show_finished)

    # -- sources -----------------------------------------------------------
    def add_source(self, source: TriggerSource) -> TriggerSource:
        source.setParent(self)
        source.triggered.connect(self.handle)
        self.sources.append(source)
        return source

    def build_default_sources(self) -> None:
        """Create the three configured trigger sources: clock, socket, CLI."""
        self.add_source(ClockTriggerSource(self.config.clock_triggers))
        self.add_source(WebSocketTriggerSource(self.config.websocket))
        self.command_source = self.add_source(CommandTriggerSource())

    def start(self) -> None:
        for source in self.sources:
            source.start()

    def stop(self) -> None:
        for source in self.sources:
            source.stop()

    # -- policy ------------------------------------------------------------
    def handle(self, event: TriggerEvent) -> bool:
        """Apply a trigger. Returns whether the show was started."""
        show = self.library.load(event.show)
        if show is None:
            return self._reject(event, f"no show named {event.show!r}")

        current = self.engine.show
        if (
            current is not None
            and self.engine.is_playing
            and not current.allow_override
            and current is not show
        ):
            return self._reject(event, f"{current.name!r} does not allow being overridden")

        log.info("Triggered %r from %s", show.name, event.detail or event.source)
        self.play(show)
        self._report(f"OK triggered {show.name}")
        self.triggered.emit(event)
        return True

    def play(self, show: Show) -> None:
        """Replace whatever is loaded with ``show`` and start it immediately."""
        self.engine.load_show(show)
        self.engine.play()

    # -- internals ---------------------------------------------------------
    def _on_show_finished(self, show: Show) -> None:
        if show is None or not show.next_show:
            return
        log.info("Show %r chains to %r", show.name, show.next_show)
        self.handle(TriggerEvent(show=show.next_show, source=CHAIN, detail=f"after {show.name}"))

    def _reject(self, event: TriggerEvent, reason: str) -> bool:
        log.warning("Trigger %s refused: %s", event, reason)
        self._report(f"ERR {reason}")
        self.rejected.emit(event, reason)
        return False

    def _report(self, message: str) -> None:
        """Pass the outcome back to a command-line caller that is still waiting."""
        if self.command_source is not None:
            self.command_source.report_result(message)
