"""The show engine: media transport, timeline clock and DMX output as one unit.

The wiring that matters:

    MediaPlayer.position_changed  ->  ShowClock.sync()      (~11 Hz, coarse)
    ShowClock.position_ms()       ->  Show.render()         (40 Hz, interpolated)
    Show.render()                 ->  DmxSender             (40 Hz, own thread)

The media file is the authority on where the show is; the clock turns its
coarse reports into a smooth, monotonic timeline; DMX frames are rendered from
the clock, never from the player. A show with no media cue still runs - the
clock free-runs and DMX plays back on its own.

The same split decides how a show ends. With media, the transport says when:
the end of the file is the end of the show, and a looping show loops in the
media backend so the seam is gapless. Without media there is nothing to ask, so
the engine watches the clock against the show's own duration.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal

from ..dmx import DmxOutput, DmxSender
from ..media import MediaPlayer, PlaybackState
from .clock import ShowClock
from .timeline import Show

log = logging.getLogger(__name__)

COMPLETION_POLL_MS = 50


class ShowEngine(QObject):
    """Plays a :class:`Show`: media, timeline and lighting together."""

    show_changed = Signal(object)  # Show | None
    sync_error_changed = Signal(float)  # ms, media position minus clock
    show_finished = Signal(object)  # Show that just ran to its end
    looped = Signal(object)  # Show that just wrapped back to the top

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
        self._finishing = False
        self._play_pending = False  # play() asked, media still loading
        self._awaiting_audio = False  # player says playing, position not moving yet
        self._audio_start_ms: int | None = None

        self.player.ready.connect(self._on_media_ready)
        self.player.position_changed.connect(self._on_media_position)
        self.player.state_changed.connect(self._on_media_state)
        self.player.end_of_media.connect(self._on_end_of_media)

        # Only timeline-only shows need this: a show with media ends when its
        # file does. It runs on the Qt thread and touches no DMX state.
        self._completion_timer = QTimer(self)
        self._completion_timer.setInterval(COMPLETION_POLL_MS)
        self._completion_timer.timeout.connect(self._check_completion)

    # -- show --------------------------------------------------------------
    @property
    def show(self) -> Show | None:
        return self._show

    def load_show(self, show: Show) -> None:
        """Load a show and its media cue, without starting playback."""
        self.stop()
        self._show = show
        self._finishing = False
        self.player.set_looping(bool(show.loop))
        if show.media:
            try:
                self.player.load(show.media.path)
            except FileNotFoundError:
                log.error("Show media missing: %s", show.media.path)
                self.player.error_occurred.emit(f"Show media not found: {show.media.path}")
        log.info(
            "Loaded show %r: %d track(s), universes %s%s",
            show.name,
            len(show.tracks),
            show.universes or "none",
            ", looping" if show.loop else "",
        )
        self.show_changed.emit(show)

    def set_loop(self, looping: bool) -> None:
        """Turn looping on or off on the loaded show, mid-playback if need be."""
        if self._show is None:
            return
        self._show.loop = bool(looping)
        self.player.set_looping(bool(looping))
        log.info("Looping %s for show %r", "on" if looping else "off", self._show.name)

    # -- output ------------------------------------------------------------
    def add_output(self, output: DmxOutput) -> None:
        self.sender.add_output(output)

    def clear_outputs(self) -> None:
        self.sender.clear_outputs()

    # -- transport ---------------------------------------------------------
    def play(self) -> None:
        """Start the DMX loop first, so lighting is live before sound starts."""
        self._finishing = False
        if self._show and self._show.media:
            if not self.player.is_ready:
                # Starting before the decoder is up makes the audio lag the
                # clock and the show jump back to catch it. Wait instead.
                self._play_pending = True
                log.info("Waiting for media to load before starting")
                return
            self._start_media()
        else:
            self.sender.start()
            self.clock.start()
        self._completion_timer.start()

    def _start_media(self) -> None:
        self._play_pending = False
        self.sender.start()
        self._awaiting_audio = True
        self._audio_start_ms = None
        self.player.play()  # the clock starts once the audio is really moving
        self._completion_timer.start()

    def _on_media_ready(self) -> None:
        if self._play_pending:
            self._start_media()

    def pause(self) -> None:
        self._play_pending = False
        if self._show and self._show.media:
            self.player.pause()
        self.clock.pause()
        self._completion_timer.stop()

    def stop(self) -> None:
        """Stop everything and black out the rig before dropping the output."""
        self._play_pending = False
        self._awaiting_audio = False
        self._audio_start_ms = None
        self._completion_timer.stop()
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

    @property
    def state(self) -> PlaybackState:
        """Transport state of the show, media-backed or not."""
        if self._show and self._show.media:
            return self.player.state
        if self.clock.running:
            return PlaybackState.PLAYING
        return PlaybackState.PAUSED if self.position_ms > 0 else PlaybackState.STOPPED

    @property
    def is_playing(self) -> bool:
        return self.state is PlaybackState.PLAYING

    @property
    def duration_ms(self) -> int:
        """How long the show runs: its own duration, else the media's."""
        show = self._show
        if show is None:
            return 0
        return show.effective_duration_ms or self.player.duration or 0

    # -- internals ---------------------------------------------------------
    def _render_frame(self) -> dict[int, bytes]:
        """Called on the DMX sender thread; touches no Qt widgets."""
        show = self._show
        if show is None:
            return {}
        return show.render(self.clock.position_ms())

    def _on_media_position(self, position_ms: int) -> None:
        if self._awaiting_audio:
            # The player reports "playing" before the audio device has started,
            # and the position sits still until it has. Start the clock on the
            # first report that has actually moved.
            start = self._audio_start_ms
            if start is None:
                self._audio_start_ms = position_ms
                return
            if position_ms == start:
                return
            self._awaiting_audio = False
            self._audio_start_ms = None
            self.clock.start(float(position_ms))
            return
        error = self.clock.sync(float(position_ms))
        self.sync_error_changed.emit(error)

    def _on_media_state(self, state: PlaybackState) -> None:
        if state is PlaybackState.PLAYING:
            if not self.clock.running and not self._awaiting_audio:
                self.clock.start(self.player.position)
        elif state is PlaybackState.PAUSED:
            self.clock.pause()
        else:
            self.clock.stop()

    def _on_end_of_media(self) -> None:
        """The file ran out. A looping show never gets here - Qt wraps it."""
        if self._show and self._show.media:
            self._complete()

    def _check_completion(self) -> None:
        """Wrap or finish a show that has no media to end it."""
        show = self._show
        if show is None or show.media or not self.clock.running:
            return
        duration = show.effective_duration_ms
        if duration <= 0 or self.position_ms < duration:
            return
        if show.loop:
            self.clock.seek(0.0)
            log.debug("Looped show %r", show.name)
            self.looped.emit(show)
        else:
            self._complete()

    def _complete(self) -> None:
        """Run the show down and announce it, exactly once per run.

        The guard matters because a trigger chained off ``show_finished`` loads
        the next show synchronously, and Qt can still deliver a trailing state
        change from the show that just ended.
        """
        show = self._show
        if show is None or self._finishing:
            return
        self._finishing = True
        log.info("Show %r finished", show.name)
        self.stop()
        self.show_finished.emit(show)
