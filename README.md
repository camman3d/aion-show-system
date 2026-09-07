# AION Show System

Automated show playback: preprogrammed DMX lighting sequences synchronised to
audio or video. Python + Qt (PySide6), running on Windows, macOS, Linux and
Raspberry Pi, with DMX over Art-Net or sACN (E1.31).

## Requirements

- Python 3.10 or newer
- A desktop session (or `QT_QPA_PLATFORM=offscreen` for headless testing)

## Setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux / Raspberry Pi
source .venv/bin/activate

pip install -e ".[dev]"
```

## Run

```bash
aion-show-system            # console script
python -m aion_show_system  # equivalent
python -m aion_show_system path/to/cue.wav        # open media on launch
python -m aion_show_system path/to/act.show.json  # open a show on launch
python -m aion_show_system --config /etc/aion/config.json
```

Cue the copy that is **already running** from another terminal (see
[Triggers](#triggers)):

```bash
aion-show-system-cli --trigger "Nightly"
```

**File → Build Demo Sequence** generates a real chase-and-swell show over the
loaded media's duration, so a rig can be verified before any cues are authored.
Set the DMX panel to *Dry run* to exercise the timeline with no network at all.

## Test

```bash
pytest
ruff check .
```

Tests force the Qt `offscreen` platform, so they run without a display or a
lighting rig.

## How synchronisation works

This is the load-bearing design decision, and it is not obvious:

**Qt's media transport is too coarse to drive DMX from.** `QMediaPlayer` reports
its position roughly every **93 ms**, and `position()` does not interpolate
between those reports — polling it faster just returns the same staircase value.
DMX wants a frame every 25 ms. Reading cue times off the player directly would
quantise every fade and every hit to ~93 ms.

So the timeline runs on its own clock:

```
MediaPlayer.position_changed  ->  ShowClock.sync()    (~11 Hz, coarse, authoritative)
ShowClock.position_ms()       ->  Show.render()       (interpolated, sub-ms)
Show.render()                 ->  DmxSender           (40 Hz, dedicated thread)
```

`ShowClock` free-runs on a monotonic clock anchored to the media transport. When
a media report arrives it corrects by **slewing the rate** (capped at ±5%)
rather than jumping the position, so:

- the timeline never runs backwards and never re-fires a cue;
- the media file remains the authority on drift;
- cue times resolve to sub-millisecond precision.

The exception is a discontinuity — a seek, a stall, or the first report after
starting — where the clock hard-anchors instead. That first report matters: the
position a transport reports at the instant it starts is already up to one
interval stale, so slewing it off would open a show up to 90 ms out.

DMX output runs on its own thread, not a Qt timer, because the GUI thread on a
loaded Raspberry Pi will not hold a 25 ms cadence. Watch `late_frames` in the
DMX panel — that is the number that tells you the machine is struggling.

## Config file

One JSON file, read at startup. It lives beside the show files in
`paths.config_dir()` — `%APPDATA%\AION\AION Show System\config.json` on Windows,
`~/.config/AION Show System/config.json` on Linux and Raspberry Pi OS — or
wherever `--config` points.

```json
{
  "shows_dir": "/opt/aion/shows",
  "dmx": {
    "protocol": "artnet",
    "host": "10.0.0.20",
    "universe": 1
  },
  "websocket": {
    "host": "10.0.0.5",
    "port": 8765,
    "path": "/cues"
  },
  "clock_triggers": [
    { "time": "10:00 PM", "show": "Nightly" },
    { "time": "14:30", "show": "Matinee", "days": ["sat", "sun"] }
  ]
}
```

**Every section is optional, and a missing file is a valid configuration.** A
machine with no config file comes up with no network DMX, no WebSocket and no
schedule — which is what a unit being set up for the first time should do. A
config file that will not parse is logged and treated as absent rather than
being fatal: a show machine that boots unattended has to come up regardless.

`dmx.protocol` is `artnet`, `sacn` or `none` (a dry run). Naming a real
protocol goes live at startup without anyone clicking *Go live*; set
`"auto_start": false` to override that, or `true` to arm a dry run.

`websocket` needs **both** a host and a port. Either one missing, or the whole
section absent, means this machine does not connect at all.

`clock_triggers` take `"22:00"` or `"10:00 PM"`, and an optional `days` filter
(`mon`–`sun`, or full names). Without `days` a trigger fires daily.

## Triggers

A trigger stops whatever is playing, loads the named show, and starts it. Four
things can raise one:

| Source | How |
| --- | --- |
| **Clock** | `clock_triggers` in the config file |
| **WebSocket** | a message from the configured server |
| **Command line** | `aion-show-system-cli --trigger "Nightly"` |
| **Another show** | `next_show` in a show file, when that show ends |

All four resolve the show the same way — a path, a file name in `shows_dir`
with or without its extension, or the `name` written inside a show file — and
all four go through one policy, so they behave identically.

**The show that is playing decides whether it can be replaced.** A show with
`"allow_override": false` refuses triggers while it is actually playing; the
trigger is logged, reported in the UI, and returned to the caller. Once it
finishes, or is stopped, triggers land again. A show that says nothing is
overridable, so existing show files keep working.

### WebSocket

The whole system connects out to one server, so a cue sent there reaches every
machine. This end is a client — show machines sit behind whatever network the
venue has, and dialling out is the half that reliably works. It reconnects on
its own, indefinitely.

Messages are either a bare show name or a JSON object:

```
Nightly
{"show": "Nightly"}
```

### Command line

The show system is already running and holding a rig live, so `--trigger` must
not start a second copy. It hands the message to the running instance over a
local IPC endpoint (a named pipe on Windows, a socket file elsewhere) and prints
what came back:

```console
$ aion-show-system-cli --trigger "Nightly"
OK triggered Nightly

$ aion-show-system-cli --trigger "Ghost"
ERR no show named 'Ghost'
```

It exits non-zero when the show did not start — nothing listening, no such
show, or a running show that refused to be overridden — so it can be scripted
against. The reply says which.

## Layout

```
src/aion_show_system/
├── __main__.py        entry point (console + gui scripts)
├── app.py             argument parsing, QApplication bootstrap, --trigger
├── config.py          the config file: DMX, WebSocket, clock triggers
├── paths.py           per-OS config/data/log directories (via QStandardPaths)
├── logging_setup.py   console + rotating file logging
├── media/
│   ├── devices.py     audio output device enumeration
│   └── player.py      MediaPlayer: audio or video, load/play/seek/loop/route
├── show/
│   ├── clock.py       ShowClock: the interpolating timeline clock
│   ├── timeline.py    Show / DmxTrack / DmxKeyframe, JSON persistence
│   ├── engine.py      ShowEngine: media + clock + DMX as one unit
│   ├── library.py     resolving the show a trigger named
│   └── demo.py        generated chase/swell show for rig checkout
├── triggers/
│   ├── base.py        TriggerEvent, TriggerSource, message parsing
│   ├── clock_source.py     wall-clock schedule
│   ├── websocket_source.py the show system's WebSocket client
│   ├── command_source.py   local IPC server + the --trigger client
│   └── manager.py     one override policy for every source
├── dmx/
│   ├── output.py      DmxOutput interface, NullOutput for dry runs
│   ├── artnet.py      Art-Net (ArtDMX) packets
│   ├── sacn.py        sACN / E1.31 packets, multicast addressing
│   └── sender.py      fixed-rate output thread
└── ui/
    ├── main_window.py show, transport, timeline and output
    ├── video_widget.py black video surface, full screen on any display
    ├── trigger_panel.py per-source trigger status and the last trigger
    ├── dmx_panel.py   protocol/host/universe, go live
    └── dmx_monitor.py live 512-channel level grid
tests/                 pytest suite (offscreen Qt, no hardware needed)
```

## Show files

A show is JSON: a media cue plus time-indexed DMX tracks, saved by default under
`paths.config_dir()`.

```json
{
  "version": 1,
  "name": "Act One",
  "media": { "path": "music.wav", "start_ms": 0 },
  "duration_ms": 60000,
  "loop": false,
  "allow_override": true,
  "next_show": "Act Two",
  "tracks": [
    {
      "name": "Wash",
      "universe": 1,
      "keyframes": [
        { "time_ms": 0,    "values": { "1": 0 } },
        { "time_ms": 2500, "values": { "1": 255 } }
      ]
    }
  ]
}
```

Channels are 1-based. Levels interpolate linearly between keyframes, so a pair
of keyframes is a fade and two at the same time is a snap. A channel holds its
last value until another keyframe touches it. Tracks sharing a universe merge
**highest-takes-precedence**, as on a lighting desk.

Three fields decide how the show behaves in a running system. `loop` restarts
it at the end instead of finishing. `allow_override` (default `true`) is
whether a trigger may replace it mid-show. `next_show` names the show to
trigger when this one ends, which is how shows are chained without anything
outside the show files knowing the running order.

## How a show ends

The media file is the authority on where a show is, so it is also the authority
on when it is over: the end of the file ends the show, and a looping show loops
**in the media backend**, which wraps without tearing down the decoder and
leaves no audio gap at the seam. Hand-rolling that as a seek-on-end would open
a hole at every loop point and make the timeline, not the transport, the thing
deciding where the show is.

A show with no media has nothing to ask, so there the engine watches the clock
against the show's own `duration_ms` and wraps or finishes itself.

Either way the show ends exactly once, which matters because `next_show` loads
the following show synchronously and Qt can still deliver a trailing state
change from the show that just ended.

## Platform notes

**DMX universes.** Art-Net universes start at 0; sACN universes start at 1.
Tracks default to universe **1** so a show is valid on either protocol. Sending
universe 0 over sACN raises rather than failing silently.

**Media backend.** Playback goes through Qt Multimedia, which since Qt 6.5 uses
a bundled FFmpeg backend on all four targets — so container and codec support is
consistent everywhere (H.264/H.265/MPEG4 video; MP3/AAC/FLAC/WAV audio). Video
attaches to any `QVideoWidget`, video item or `QVideoSink`.

The full `PySide6` metapackage is a dependency rather than `PySide6-Essentials`
because QtMultimedia ships in the `PySide6-Addons` half.

**Linux / Raspberry Pi.** Install the GStreamer plugins Qt falls back to:

```bash
sudo apt install libgstreamer1.0-0 gstreamer1.0-plugins-base \
                 gstreamer1.0-plugins-good gstreamer1.0-alsa
```

If `pip install PySide6` has no wheel for your Pi (32-bit Raspberry Pi OS in
particular), use the distro build and create the venv with access to it:

```bash
sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtmultimedia
python -m venv --system-site-packages .venv
```

Video decodes in **software** on the Pi. 1080p H.264 is generally fine on a Pi 4
or 5, but it competes with the DMX thread for CPU, and the Pi 5 has no H.264
hardware decoder at all. Pre-transcode show video to the exact playback
resolution and check `late_frames` on the real unit before committing to it.

**macOS.** The first launch that opens an audio device may prompt for audio
permission depending on the OS version; allow it once.

## Verified

Measured on Windows 11 with a real Art-Net receiver on loopback:

- 40 Hz DMX output, inter-packet interval 24–26 ms, **0 late frames**
- Art-Net and sACN packets validated byte-for-byte against the specs
- Sync error settles to single-digit milliseconds after the first media report
- Blackout sent on stop

All four trigger paths run end to end against a real running instance:

- **Clock** — armed from the config file, fired within 400 ms of the minute
- **WebSocket** — dialled out to a live server, connected, cued from a JSON frame
- **Command line** — `--trigger` from a second process, with the outcome
  returned to the caller and reflected in its exit code
- **Chaining** — a show finishing and triggering the one its file names

Refusals were checked the same way: a playing show with
`"allow_override": false` rejected a command-line trigger, and a show name
nothing matches was reported rather than silently dropped.

## Next steps

There is no cue authoring UI yet — `show/demo.py` stands in for it. The natural
next pieces are a cue list editor writing the same JSON, fixture profiles so
cues address fixtures rather than raw channels, and Art-Net node discovery
(ArtPoll) so outputs can be picked from a list instead of typed.

On the trigger side, the WebSocket client currently only receives. Sending
state back to the server — what is playing, how far in, whether the last
trigger landed — would let one operator see a wall of machines at once.
