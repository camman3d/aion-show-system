"""The fixed-rate DMX output loop.

DMX is a continuously refreshed protocol: receivers expect frames whether or
not anything changed. This runs on its own thread rather than a Qt timer,
because the GUI thread on a loaded Raspberry Pi will not hold a 25 ms cadence.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable

from .output import DMX_UNIVERSE_SIZE, DmxOutput

log = logging.getLogger(__name__)

DEFAULT_FPS = 40.0

FrameSource = Callable[[], dict[int, bytes]]


class DmxSender:
    """Pull frames from a source at a fixed rate and push them to outputs.

    Args:
        frame_source: Called once per frame; returns ``{universe: 512 bytes}``.
            It runs on the sender thread, so it must not touch Qt widgets.
        outputs: Transports to send every frame to.
        fps: Refresh rate. 40 Hz roughly matches a full DMX512 line.
    """

    def __init__(
        self,
        frame_source: FrameSource,
        outputs: Iterable[DmxOutput] = (),
        fps: float = DEFAULT_FPS,
    ) -> None:
        self.frame_source = frame_source
        self.fps = float(fps)
        self._outputs: list[DmxOutput] = list(outputs)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frames_sent = 0
        self._last_frame: dict[int, bytes] = {}
        self._late_frames = 0
        self._failed_outputs: set[int] = set()

    # -- outputs -----------------------------------------------------------
    @property
    def outputs(self) -> list[DmxOutput]:
        with self._lock:
            return list(self._outputs)

    def add_output(self, output: DmxOutput) -> None:
        with self._lock:
            self._outputs.append(output)

    def clear_outputs(self, *, close: bool = True) -> None:
        with self._lock:
            outputs, self._outputs = self._outputs, []
        if close:
            for output in outputs:
                output.close()

    # -- stats -------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def frames_sent(self) -> int:
        return self._frames_sent

    @property
    def late_frames(self) -> int:
        """Frames that missed their slot - the number to watch on a Pi."""
        return self._late_frames

    @property
    def last_frame(self) -> dict[int, bytes]:
        """The most recent rendered frame, for the UI channel monitor."""
        return dict(self._last_frame)

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dmx-sender", daemon=True)
        self._thread.start()
        log.info("DMX sender started at %.1f Hz", self.fps)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)
        log.info(
            "DMX sender stopped after %d frames (%d late)", self._frames_sent, self._late_frames
        )

    def send_once(self) -> dict[int, bytes]:
        """Render and send a single frame on the calling thread.

        A transport that throws (a misconfigured universe, a socket that went
        away with the network) is logged once and then skipped quietly: one bad
        output must not stop the others from lighting the show.
        """
        frame = self.frame_source() or {}
        self._last_frame = frame
        for output in self.outputs:
            try:
                for universe, data in frame.items():
                    output.send(universe, data)
            except (OSError, ValueError) as error:
                if id(output) not in self._failed_outputs:
                    self._failed_outputs.add(id(output))
                    log.error("Output %s failed, skipping it: %s", output, error)
        self._frames_sent += 1
        return frame

    @property
    def failed_outputs(self) -> int:
        """How many transports have thrown at least once this run."""
        return len(self._failed_outputs)

    def blackout(self, universes: Iterable[int]) -> None:
        """Send all-zero frames - always do this when stopping a show."""
        dark = bytes(DMX_UNIVERSE_SIZE)
        for output in self.outputs:
            for universe in universes:
                try:
                    output.send(universe, dark)
                except (OSError, ValueError) as error:
                    log.error("Blackout failed on %s universe %d: %s", output, universe, error)

    # -- loop --------------------------------------------------------------
    def _run(self) -> None:
        period = 1.0 / self.fps
        next_frame = time.perf_counter()
        while not self._stop.is_set():
            try:
                self.send_once()
            except Exception:  # a bad cue must not kill the output thread
                log.exception("DMX frame failed")

            # Absolute scheduling, so a slow frame does not accumulate drift.
            next_frame += period
            delay = next_frame - time.perf_counter()
            if delay > 0:
                self._stop.wait(delay)
            else:
                self._late_frames += 1
                next_frame = time.perf_counter()
