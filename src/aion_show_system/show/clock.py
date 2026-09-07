"""The show's master timeline clock.

Qt's media transport only reports its position about every 90 ms, and
``QMediaPlayer.position()`` does not interpolate between those reports — polling
it faster just returns the same staircase value. DMX needs a new frame every
25 ms, so reading the player directly would quantise every cue to ~93 ms.

``ShowClock`` solves that by running a free monotonic clock anchored to the
media transport: it interpolates between the media's reports, and when the next
report arrives it corrects by *slewing the rate* rather than jumping the
position. The media file stays the authority on drift, the timeline never runs
backwards, and cue times resolve to sub-millisecond precision.

The clock is thread-safe: the DMX output thread reads ``position_ms()`` while
the Qt GUI thread calls ``sync()``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)


class ShowClock:
    """A monotonic timeline position in milliseconds.

    Args:
        hard_resync_ms: An error at least this large is treated as a seek or a
            stall and corrected by jumping. Below it, the clock slews.
        slew_window_ms: Time over which a small error is absorbed by rate
            adjustment. Larger is smoother and slower to converge.
        max_slew: Ceiling on the rate adjustment, as a fraction (0.05 = ±5%).
            Keeps audible/visible pitch and timing artefacts out of the show.
        time_fn: Monotonic wall-clock source, in seconds. Injectable for tests.
    """

    def __init__(
        self,
        *,
        hard_resync_ms: float = 250.0,
        slew_window_ms: float = 1000.0,
        max_slew: float = 0.05,
        time_fn: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._hard_resync_ms = float(hard_resync_ms)
        self._slew_window_ms = float(slew_window_ms)
        self._max_slew = float(max_slew)
        self._time_fn = time_fn

        self._lock = threading.RLock()
        self._running = False
        self._anchor_media_ms = 0.0
        self._anchor_wall_s = time_fn()
        self._rate = 1.0
        self._needs_anchor = True

    # -- state -------------------------------------------------------------
    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def rate(self) -> float:
        """Current slew rate; 1.0 means the clock is tracking exactly."""
        with self._lock:
            return self._rate

    def position_ms(self) -> float:
        """The interpolated timeline position. Safe to call from any thread."""
        with self._lock:
            if not self._running:
                return self._anchor_media_ms
            elapsed_s = self._time_fn() - self._anchor_wall_s
            return self._anchor_media_ms + elapsed_s * 1000.0 * self._rate

    # -- transport ---------------------------------------------------------
    def start(self, at_ms: float | None = None) -> None:
        """Run the clock, optionally from a specific position.

        The position a transport reports at the moment it starts is already up
        to one report interval stale, so the first ``sync()`` after starting is
        taken as gospel rather than slewed - otherwise a show opens up to 90 ms
        out and takes seconds to pull in.
        """
        with self._lock:
            if at_ms is not None:
                self._anchor_media_ms = float(at_ms)
            self._anchor_wall_s = self._time_fn()
            self._rate = 1.0
            self._running = True
            self._needs_anchor = True

    def pause(self) -> None:
        """Freeze at the current interpolated position."""
        with self._lock:
            self._anchor_media_ms = self.position_ms()
            self._anchor_wall_s = self._time_fn()
            self._running = False

    def stop(self) -> None:
        """Freeze and return to zero."""
        with self._lock:
            self._running = False
            self._anchor_media_ms = 0.0
            self._anchor_wall_s = self._time_fn()
            self._rate = 1.0

    def seek(self, position_ms: float) -> None:
        """Jump the timeline; keeps running if it was running."""
        with self._lock:
            self._anchor_media_ms = max(0.0, float(position_ms))
            self._anchor_wall_s = self._time_fn()
            self._rate = 1.0
            self._needs_anchor = True

    # -- synchronisation ---------------------------------------------------
    def sync(self, media_ms: float) -> float:
        """Correct against a fresh media transport position.

        Call this from the media player's ``position_changed`` signal. Returns
        the error in milliseconds (media minus clock) before correction, which
        is worth logging or displaying: a persistently large value means the
        machine cannot keep up with the show.
        """
        with self._lock:
            if not self._running:
                self._anchor_media_ms = float(media_ms)
                self._anchor_wall_s = self._time_fn()
                return 0.0

            predicted = self.position_ms()
            error = float(media_ms) - predicted

            if self._needs_anchor or abs(error) >= self._hard_resync_ms:
                # A seek, a stall, or a decoder hiccup: jumping is correct here.
                self._anchor_media_ms = float(media_ms)
                self._anchor_wall_s = self._time_fn()
                self._rate = 1.0
                self._needs_anchor = False
                log.debug("Hard resync, error %.1f ms", error)
                return error

            # Re-anchor at where we already believe we are, so the timeline
            # never steps backwards, then nudge the rate to close the gap.
            self._anchor_media_ms = predicted
            self._anchor_wall_s = self._time_fn()
            adjustment = error / self._slew_window_ms
            self._rate = 1.0 + max(-self._max_slew, min(self._max_slew, adjustment))
            return error
