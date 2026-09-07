"""Packet-level tests: a malformed header is silently ignored by real hardware,
so the bytes are asserted against the Art-Net and E1.31 specs directly."""

import struct
import time

import pytest

from aion_show_system.dmx import ArtNetOutput, DmxSender, NullOutput, SacnOutput
from aion_show_system.dmx.sacn import check_universe, multicast_host


# -- Art-Net ---------------------------------------------------------------
def test_artnet_packet_header():
    output = ArtNetOutput("127.0.0.1")
    packet = output.build_packet(universe=0, data=bytes([1, 2, 3]))
    try:
        assert packet[:8] == b"Art-Net\x00"
        assert struct.unpack("<H", packet[8:10])[0] == 0x5000  # OpDmx, little-endian
        assert struct.unpack(">H", packet[10:12])[0] == 14  # protocol version
        assert struct.unpack(">H", packet[16:18])[0] == 512  # length, big-endian
        assert len(packet) == 18 + 512
        assert packet[18:21] == bytes([1, 2, 3])
        assert packet[21:] == bytes(509)  # short data is zero-padded
    finally:
        output.close()


def test_artnet_universe_splits_into_subuni_and_net():
    output = ArtNetOutput("127.0.0.1")
    try:
        packet = output.build_packet(universe=0x0102, data=b"")
        assert packet[14] == 0x02  # SubUni
        assert packet[15] == 0x01  # Net
    finally:
        output.close()


def test_artnet_sequence_wraps_and_skips_zero():
    output = ArtNetOutput("127.0.0.1")
    try:
        output._sequence = 255
        output.send(0, bytes(512))
        assert output._sequence == 1  # 0 means "sequencing disabled"
    finally:
        output.close()


def test_artnet_truncates_oversized_data():
    output = ArtNetOutput("127.0.0.1")
    try:
        assert len(output.build_packet(0, bytes(900))) == 18 + 512
    finally:
        output.close()


# -- sACN ------------------------------------------------------------------
def test_sacn_packet_layout():
    output = SacnOutput(cid=bytes(range(16)), source_name="Test Source")
    try:
        packet = output.build_packet(universe=1, data=bytes([9]))
        assert len(packet) == 638
        assert packet[4:16] == b"ASC-E1.17\x00\x00\x00"
        assert struct.unpack(">I", packet[18:22])[0] == 0x04  # root vector
        assert packet[22:38] == bytes(range(16))  # CID
        assert struct.unpack(">I", packet[40:44])[0] == 0x02  # framing vector
        assert packet[44:55] == b"Test Source"
        assert packet[108] == 100  # default priority
        assert struct.unpack(">H", packet[113:115])[0] == 1  # universe
        assert packet[117] == 0x02  # DMP vector
        assert packet[118] == 0xA1  # address and data type
        assert struct.unpack(">H", packet[123:125])[0] == 513  # slot count
        assert packet[125] == 0  # DMX start code
        assert packet[126] == 9  # channel 1
    finally:
        output.close()


def test_sacn_pdu_lengths_have_the_flag_nibble():
    output = SacnOutput(cid=bytes(16))
    try:
        packet = output.build_packet(1, bytes(512))
        assert struct.unpack(">H", packet[16:18])[0] == 0x7000 | 622
        assert struct.unpack(">H", packet[38:40])[0] == 0x7000 | 600
        assert struct.unpack(">H", packet[115:117])[0] == 0x7000 | 523
    finally:
        output.close()


def test_sacn_sequence_is_per_universe():
    output = SacnOutput(host="127.0.0.1", cid=bytes(16))
    try:
        output.send(1, bytes(512))
        output.send(1, bytes(512))
        output.send(2, bytes(512))
        assert output._sequence == {1: 2, 2: 1}
    finally:
        output.close()


def test_sacn_multicast_addresses():
    assert multicast_host(1) == "239.255.0.1"
    assert multicast_host(256) == "239.255.1.0"


def test_sacn_rejects_universe_zero_even_when_unicast():
    """Universe 0 is legal Art-Net but not sACN; it must not fail silently."""
    output = SacnOutput(host="127.0.0.1", cid=bytes(16))
    try:
        with pytest.raises(ValueError, match="out of range"):
            output.build_packet(0, bytes(512))
    finally:
        output.close()
    with pytest.raises(ValueError):
        check_universe(64000)


def test_sacn_rejects_bad_cid():
    with pytest.raises(ValueError):
        SacnOutput(cid=b"short")


# -- Sender ----------------------------------------------------------------
def test_sender_sends_one_frame_per_universe():
    output = NullOutput()
    frame = {0: bytes([255] + [0] * 511), 1: bytes(512)}
    sender = DmxSender(lambda: frame, [output])

    sender.send_once()
    assert output.sent == 2
    assert output.frames[0][0] == 255
    assert sender.frames_sent == 1
    assert sender.last_frame == frame


def test_sender_runs_at_the_requested_rate():
    output = NullOutput()
    sender = DmxSender(lambda: {0: bytes(512)}, [output], fps=50)
    sender.start()
    try:
        assert sender.running
        time.sleep(0.4)
    finally:
        sender.stop()

    assert not sender.running
    # 50 Hz for 0.4 s is 20 frames; allow wide slack for a loaded CI machine.
    assert 8 <= sender.frames_sent <= 40


def test_sender_survives_a_failing_frame_source():
    """A bad cue must never take the output thread down mid-show."""
    calls = []

    def source():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("bad cue")
        return {0: bytes(512)}

    sender = DmxSender(source, [NullOutput()], fps=100)
    sender.start()
    try:
        time.sleep(0.2)
        assert sender.running
    finally:
        sender.stop()
    assert len(calls) > 3


def test_blackout_zeroes_every_universe():
    output = NullOutput()
    sender = DmxSender(lambda: {}, [output])
    sender.blackout([0, 1])
    assert output.frames[0] == bytes(512)
    assert output.frames[1] == bytes(512)


def test_clear_outputs_closes_them():
    output = NullOutput()
    sender = DmxSender(lambda: {}, [output])
    sender.clear_outputs()
    assert sender.outputs == []


def test_one_failing_output_does_not_stop_the_others():
    """A misconfigured transport must never take the rest of the rig dark."""

    class BrokenOutput(NullOutput):
        def send(self, universe, data):
            raise OSError("network went away")

    good = NullOutput()
    sender = DmxSender(lambda: {1: bytes(512)}, [BrokenOutput(), good])
    for _ in range(3):
        sender.send_once()

    assert good.sent == 3
    assert sender.failed_outputs == 1  # logged once, not once per frame


def test_blackout_survives_a_failing_output():
    class BrokenOutput(NullOutput):
        def send(self, universe, data):
            raise OSError("gone")

    DmxSender(lambda: {}, [BrokenOutput()]).blackout([1])  # must not raise
