"""sACN (ANSI E1.31) output.

E1.31 multicasts to a well-known address derived from the universe number, so a
receiver joins the universes it cares about and no configuration of node
addresses is needed. Unicast is supported by passing an explicit ``host``.
"""

from __future__ import annotations

import logging
import socket
import struct
import uuid

from .output import DMX_UNIVERSE_SIZE, DmxOutput

log = logging.getLogger(__name__)

SACN_PORT = 5568
DEFAULT_PRIORITY = 100

_ACN_PACKET_IDENTIFIER = b"ASC-E1.17\x00\x00\x00"
_VECTOR_ROOT_E131_DATA = 0x00000004
_VECTOR_E131_DATA_PACKET = 0x00000002
_VECTOR_DMP_SET_PROPERTY = 0x02
_ADDRESS_AND_DATA_TYPE = 0xA1
_SLOT_COUNT = DMX_UNIVERSE_SIZE + 1  # start code + 512 channels
_PACKET_SIZE = 638


def check_universe(universe: int) -> int:
    """Validate an E1.31 universe number.

    Unlike Art-Net, sACN has no universe 0. Catching it here turns a silently
    dark rig into an error the operator can actually see.
    """
    if not 1 <= universe <= 63999:
        raise ValueError(f"sACN universe {universe} out of range 1-63999 (0 is Art-Net only)")
    return universe


def multicast_host(universe: int) -> str:
    """The E1.31 multicast group for a universe: 239.255.<hi>.<lo>."""
    return f"239.255.{(check_universe(universe) >> 8) & 0xFF}.{universe & 0xFF}"


class SacnOutput(DmxOutput):
    """Send E1.31 data packets.

    Args:
        host: Unicast destination. Defaults to the universe's multicast group.
        source_name: Shown by receivers to identify this sender.
        priority: 0-200; higher wins when several sources drive one universe.
        cid: Stable component identifier. A show system should persist this so
            receivers see the same source across restarts.
        ttl: Multicast hop limit; 1 keeps traffic on the local segment.
    """

    def __init__(
        self,
        host: str | None = None,
        *,
        source_name: str = "AION Show System",
        priority: int = DEFAULT_PRIORITY,
        cid: bytes | None = None,
        ttl: int = 1,
    ) -> None:
        self.host = host
        self.source_name = source_name
        self.priority = max(0, min(200, int(priority)))
        self.cid = cid or uuid.uuid4().bytes
        if len(self.cid) != 16:
            raise ValueError("sACN CID must be 16 bytes")

        self._sequence: dict[int, int] = {}
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(ttl))
        log.info("sACN output to %s", host or "multicast")

    def build_packet(self, universe: int, data: bytes) -> bytes:
        """Build one E1.31 data packet (638 bytes). Exposed for tests."""
        check_universe(universe)
        payload = self._fit(data)
        sequence = self._sequence.get(universe, 0)

        packet = bytearray()
        # Root layer
        packet += struct.pack(">HH", 0x0010, 0x0000)  # preamble / postamble size
        packet += _ACN_PACKET_IDENTIFIER
        packet += struct.pack(">H", 0x7000 | (_PACKET_SIZE - 16))
        packet += struct.pack(">I", _VECTOR_ROOT_E131_DATA)
        packet += self.cid
        # Framing layer
        packet += struct.pack(">H", 0x7000 | (_PACKET_SIZE - 38))
        packet += struct.pack(">I", _VECTOR_E131_DATA_PACKET)
        packet += self.source_name.encode("utf-8")[:63].ljust(64, b"\x00")
        packet += bytes([self.priority])
        packet += struct.pack(">H", 0)  # synchronisation address: unsynchronised
        packet += bytes([sequence, 0])  # sequence number, options
        packet += struct.pack(">H", universe)
        # DMP layer
        packet += struct.pack(">H", 0x7000 | (_PACKET_SIZE - 115))
        packet += bytes([_VECTOR_DMP_SET_PROPERTY, _ADDRESS_AND_DATA_TYPE])
        packet += struct.pack(">HHH", 0x0000, 0x0001, _SLOT_COUNT)
        packet += b"\x00"  # DMX start code
        packet += payload
        return bytes(packet)

    def send(self, universe: int, data: bytes) -> None:
        packet = self.build_packet(universe, data)
        self._sequence[universe] = (self._sequence.get(universe, 0) + 1) % 256
        self._socket.sendto(packet, (self.host or multicast_host(universe), SACN_PORT))

    def close(self) -> None:
        self._socket.close()

    def __str__(self) -> str:
        destination = self.host or "multicast"
        return f"sACN -> {destination}"
