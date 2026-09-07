"""The show engine: media transport, timeline clock and DMX output as one unit.

The wiring that matters:

    MediaPlayer.position_changed  ->  ShowClock.sync()      (~11 Hz, coarse)
    ShowClock.position_ms()       ->  Show.render()         (40 Hz, interpolated)
    Show.render()                 ->  DmxSender             (40 Hz, own thread)

The media file is the authority on where the show is; the clock turns its
coarse reports into a smooth, monotonic timeline; DMX frames are rendered from
the clock, never from the player. A show with no media cue still runs - the
clock free-runs and DMX plays back on its own.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from ..dmx import DmxOutput, DmxSender
from ..media import MediaPlayer, PlaybackState
from .clock import ShowClock
from .timeline import Show

log = logging.getLogger(__name__)


class ShowEngine(QObject):
    """Plays a :class:`Show`: media, timeline and lighting together."""

    show_changed = Signal(object)  # Show | None
    sync_error_changed = Signal(float)  # ms, media position minus clock

    def __init__(
        self,
        player: MediaPlayer | None = None,
        clock: ShowClock | None = None,
        fps: float = 40.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.player = player or MediaPlayer(self)
        self.clock = clock or ShowClock()
        self.sender = DmxSender(self._render_frame, fps=fps)
        self._show: Show | None = None

        self.player.position_changed.connect(self._on_media_position)
        self.player.state_changed.connect(self._on_media_state)

    # -- show --------------------------------------------------------------
    @property
    def show(self) -> Show | None:
        return self._show

    def load_show(self, show: Show) -> None:
        """Load a show and its media cue, without starting playback."""
        self.stop()
        self._show = show
        if show.media:
            try:
                self.player.load(show.media.path)
            except FileNotFoundError:
                log.error("Show media missing: %s", show.media.path)
                self.player.error_occurred.emit(f"Show media not found: {show.media.path}")
        log.info(
            "Loaded show %r: %d track(s), universes %s",
            show.name,
            len(show.tracks),
            show.universes or "none",
        )
        self.show_changed.emit(show)

    # -- output ------------------------------------------------------------
    def add_output(self, output: DmxOutput) -> None:
        self.sender.add_output(output)

    def clear_outputs(self) -> None:
        self.sender.clear_outputs()

    # -- transport ---------------------------------------------------------
    def play(self) -> None:
        """Start the DMX loop first, so lighting is live before sound starts."""
        self.sender.start()
        if self._show and self._show.media:
            self.player.play()  # the clock starts when the player reports playing
        else:
            self.clock.start()

    def pause(self) -> None:
        if self._show and self._show.media:
            self.player.pause()
        self.clock.pause()

    def stop(self) -> None:
        """Stop everything and black out the rig before dropping the output."""
        self.player.stop()
        self.clock.stop()
        if self._show:
            self.sender.blackout(self._show.universes)
        self.sender.stop()

    def seek(self, position_ms: float) -> None:
        self.player.seek(int(position_ms))
        self.clock.seek(position_ms)

    @property
    def position_ms(self) -> float:
        """Where the show is now, interpolated. This is the timeline position."""
        return self.clock.position_ms()

    # -- internals ---------------------------------------------------------
    def _render_frame(self) -> dict[int, bytes]:
        """Called on the DMX sender thread; touches no Qt widgets."""
        show = self._show
        if show is None:
            return {}
        return show.render(self.clock.position_ms())

    def _on_media_position(self, position_ms: int) -> None:
        error = self.clock.sync(float(position_ms))
        self.sync_error_changed.emit(error)

    def _on_media_state(self, state: PlaybackState) -> None:
        if state is PlaybackState.PLAYING:
            if not self.clock.running:
                self.clock.start(self.player.position)
        elif state is PlaybackState.PAUSED:
            self.clock.pause()
        else:
            self.clock.stop()
