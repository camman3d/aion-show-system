"""A single media playback voice (audio or video) built on Qt Multimedia.

One ``MediaPlayer`` owns one ``QMediaPlayer``/``QAudioOutput`` pair, so several
of them can run concurrently on different output devices — the shape a show
system needs when cues overlap.

Qt reports playback position only about every 90 ms, which is far too coarse to
drive DMX from. Nothing should time off this class directly: feed
``position_changed`` into a :class:`~aion_show_system.show.clock.ShowClock` and
read the timeline position from there.
"""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

from .devices import AudioOutputDevice

log = logging.getLogger(__name__)


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


_QT_STATE_MAP = {
    QMediaPlayer.PlaybackState.StoppedState: PlaybackState.STOPPED,
    QMediaPlayer.PlaybackState.PlayingState: PlaybackState.PLAYING,
    QMediaPlayer.PlaybackState.PausedState: PlaybackState.PAUSED,
}


class MediaPlayer(QObject):
    """Load and play one audio or video file.

    Positions and durations are milliseconds; volume is a linear 0.0-1.0 value.
    """

    position_changed = Signal(int)
    duration_changed = Signal(int)
    state_changed = Signal(PlaybackState)
    source_changed = Signal(object)  # Path | None
    has_video_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source: Path | None = None
        self._output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)

        # Qt emits these as qlonglong; relay through .emit so the Python-side
        # int signals connect regardless of the C++ signature.
        self._player.positionChanged.connect(self.position_changed.emit)
        self._player.durationChanged.connect(self.duration_changed.emit)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.hasVideoChanged.connect(self.has_video_changed.emit)
        self._player.errorOccurred.connect(self._on_error)

    # -- transport ---------------------------------------------------------
    def load(self, path: str | Path) -> None:
        """Point the player at ``path`` (audio or video) without starting playback."""
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        self._source = source
        self._player.setSource(QUrl.fromLocalFile(str(source)))
        log.info("Loaded media source %s", source)
        self.source_changed.emit(source)

    def play(self) -> None:
        if self._source is not None:
            self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def toggle(self) -> None:
        if self.state is PlaybackState.PLAYING:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._player.stop()

    def seek(self, position_ms: int) -> None:
        self._player.setPosition(max(0, int(position_ms)))

    # -- video -------------------------------------------------------------
    def set_video_output(self, sink: QVideoSink | object | None) -> None:
        """Route video frames to a ``QVideoWidget``, video item or ``QVideoSink``.

        Safe to call with ``None`` to detach, and safe to call for audio-only
        sources — Qt simply never delivers a frame.
        """
        self._player.setVideoOutput(sink)

    @property
    def has_video(self) -> bool:
        """True once Qt has determined the loaded source carries a video stream."""
        return self._player.hasVideo()

    # -- properties --------------------------------------------------------
    @property
    def source(self) -> Path | None:
        return self._source

    @property
    def state(self) -> PlaybackState:
        return _QT_STATE_MAP.get(self._player.playbackState(), PlaybackState.STOPPED)

    @property
    def position(self) -> int:
        return self._player.position()

    @property
    def duration(self) -> int:
        return self._player.duration()

    @property
    def volume(self) -> float:
        return float(self._output.volume())

    @volume.setter
    def volume(self, value: float) -> None:
        self._output.setVolume(min(1.0, max(0.0, float(value))))

    @property
    def muted(self) -> bool:
        return self._output.isMuted()

    @muted.setter
    def muted(self, value: bool) -> None:
        self._output.setMuted(bool(value))

    def set_output_device(self, device: AudioOutputDevice) -> None:
        """Route this player to a specific output; playback continues."""
        self._output.setDevice(device.qt_device)
        log.info("Output device set to %s", device.name)

    # -- internals ---------------------------------------------------------
    def _on_state_changed(self, _qt_state: QMediaPlayer.PlaybackState) -> None:
        self.state_changed.emit(self.state)

    def _on_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        text = message or "Unknown media error"
        log.error("Media error: %s", text)
        self.error_occurred.emit(text)
