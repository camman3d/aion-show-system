# DMX Output

All transports implement `DmxOutput` (`dmx/output.py`):

```python
class DmxOutput(ABC):
    def send(self, universe: int, data: bytes) -> None: ...   # data padded/truncated to 512
    def close(self) -> None: ...
```

`DmxSender` calls `send` for every universe in the frame, every tick (40 Hz by
default). DMX is continuously refreshed: receivers expect frames even when
nothing changes.

## Transports

| Class | Protocol | Port | Destination |
| --- | --- | --- | --- |
| `NullOutput` | none (dry run) | – | Records last frame per universe and a `sent` counter; used for tests and dry runs |
| `ArtNetOutput(host, port=6454, universe=0)` | Art-Net ArtDMX (UDP) | 6454 | Unicast to a node, or a broadcast address (UI default `255.255.255.255`) |
| `SacnOutput(host=None, source_name, priority=100, cid, ttl=1)` | sACN / E1.31 (UDP) | 5568 | Multicast `239.255.<hi>.<lo>` for the universe when `host` is blank, else unicast |

### Art-Net details
- Packet: `Art-Net\0`, OpCode 0x5000 (little-endian), protocol version 14,
  sequence (1–255, wrapping, never 0), physical 0, SubUni/Net from the universe
  number, length 512, then data.
- `SO_BROADCAST` is enabled on the socket.
- The per-call `universe` argument is what is written; the constructor's
  `universe` is not used when sending.

### sACN details
- 638-byte E1.31 data packet: root layer, framing layer (source name ≤ 63
  bytes, priority 0–200, sequence per universe), DMP layer, start code 0.
- Universes must be **1–63999**; 0 raises `ValueError` (`check_universe`).
- `cid` defaults to a random UUID each run; pass a stable one so receivers see
  the same source across restarts (not currently configurable from the config
  file).
- `ttl=1` keeps multicast on the local segment.

## `DmxSender` behaviour

- Own daemon thread (`dmx-sender`), absolute-time scheduling (`perf_counter`).
  When a frame overruns, `late_frames` is incremented and the schedule resets.
- `frame_source()` is `ShowEngine._render_frame` → `Show.render(clock.position_ms())`;
  it returns `{}` when no show is loaded (nothing is sent).
- Errors: `OSError`/`ValueError` from an output are logged **once per output**
  and that output keeps being tried but is not re-logged. Any other exception in
  a frame is logged with a traceback and the loop continues.
- `blackout(universes)` sends an all-zero frame to each universe on each output.
- Stats: `frames_sent`, `late_frames`, `failed_outputs`, `last_frame` (copied
  by the UI monitor).

## Rendering model (summary)

For each universe the show touches, a 512-byte frame is built by merging every
track's levels with **HTP**. Channels are 1-based; levels clamp to 0–255;
before a track's first keyframe it is dark, after its last it holds. Keyframes
fade linearly between each other; two keyframes at the same time make a snap.
Optional `wide` groups (e.g. 16-bit pan/tilt) interpolate as one number so the
fine byte never wraps mid-fade. Full spec: [show-file-format.md](show-file-format.md).

## Going live from the UI

Select protocol, host, universe in **DMX output** and press **Go live**. The
panel builds the output, replaces the engine's outputs with it and starts the
sender so the rig is refreshed before Play. **Go offline** blacks out the loaded
show's universes and closes the output. Construction errors (bad address,
sACN universe 0) show as `Failed: …` in the panel.

## Adding a transport

1. Subclass `DmxOutput`, implement `send` (use `self._fit(data)` to normalise
   to 512 bytes) and `close`; give it a useful `__str__` (shown in the panel).
2. Add it to `dmx/__init__.py`.
3. Wire it into `DmxPanel.build_output` and/or `DmxConfig.create_output`.
4. Expose a `build_packet`-style method for byte-level tests (see
   `tests/test_dmx.py`).
