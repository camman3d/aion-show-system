"""Art-Net (ArtDMX) output.

Art-Net is plain UDP on port 6454. Unicast to a node's address is preferable on
a show network; broadcast works when you do not know the node's address.
"""

from __future__ import annotations

import logging
import socket
import struct

from .output import DMX_UNIVERSE_SIZE, DmxOutput

log = logging.getLogger(__name__)

ARTNET_PORT = 6454
_ARTNET_ID = b"Art-Net\x00"
_OP_DMX = 0x5000
_PROTOCOL_VERSION = 14


class ArtNetOutput(DmxOutput):
    """Send ArtDMX packets to one node.

    Args:
        host: Node address, or a broadcast address such as ``255.255.255.255``.
        port: Art-Net port; the spec fixes this at 6454.
        universe: Base universe, mapped onto Art-Net's Net/SubUni fields. The
            ``universe`` passed to :meth:`send` overrides it.
    """

    def __init__(self, host: str, port: int = ARTNET_PORT, universe: int = 0) -> None:
        self.host = host
        self.port = int(port)
        self.universe = int(universe)
        self._sequence = 1
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        log.info("Art-Net output to %s:%d", self.host, self.port)

    def build_packet(self, universe: int, data: bytes) -> bytes:
        """Build one ArtDMX packet. Exposed so it can be asserted on in tests."""
        payload = self._fit(data)
        packet = bytearray(_ARTNET_ID)
        packet += struct.pack("<H", _OP_DMX)  # OpCode is little-endian
        packet += struct.pack(">H", _PROTOCOL_VERSION)
        packet += bytes([self._sequence, 0])  # sequence, physical
        packet += bytes([universe & 0xFF, (universe >> 8) & 0xFF])  # SubUni, Net
        packet += struct.pack(">H", DMX_UNIVERSE_SIZE)
        packet += payload
        return bytes(packet)

    def send(self, universe: int, data: bytes) -> None:
        packet = self.build_packet(universe, data)
        # Sequence wraps 1-255; 0 means "sequencing disabled", so skip it.
        self._sequence = self._sequence % 255 + 1
        self._socket.sendto(packet, (self.host, self.port))

    def close(self) -> None:
        self._socket.close()

    def __str__(self) -> str:
        return f"Art-Net → {self.host}:{self.port}"
