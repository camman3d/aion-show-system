"""The interface every DMX transport implements."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)

DMX_UNIVERSE_SIZE = 512


class DmxOutput(ABC):
    """Sends 512-channel frames to one or more universes."""

    @abstractmethod
    def send(self, universe: int, data: bytes) -> None:
        """Transmit one frame. ``data`` is padded/truncated to 512 bytes."""

    def close(self) -> None:  # noqa: B027 - optional hook, not every transport holds a handle
        """Release sockets or handles. Safe to call more than once."""

    def __enter__(self) -> DmxOutput:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @staticmethod
    def _fit(data: bytes) -> bytes:
        if len(data) == DMX_UNIVERSE_SIZE:
            return data
        return bytes(data[:DMX_UNIVERSE_SIZE]).ljust(DMX_UNIVERSE_SIZE, b"\x00")


class NullOutput(DmxOutput):
    """Discards frames, but records the last one. Used for dry runs and tests."""

    def __init__(self) -> None:
        self.frames: dict[int, bytes] = {}
        self.sent = 0

    def send(self, universe: int, data: bytes) -> None:
        self.frames[universe] = self._fit(data)
        self.sent += 1

    def __str__(self) -> str:
        return "No output (dry run)"
