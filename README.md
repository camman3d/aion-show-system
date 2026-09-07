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
python -m aion_show_system path/to/cue.wav   # open media on launch
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

## Layout

```
src/aion_show_system/
├── __main__.py        entry point (console + gui scripts)
├── app.py             QApplication bootstrap
├── paths.py           per-OS config/data/log directories (via QStandardPaths)
├── logging_setup.py   console + rotating file logging
├── media/
│   ├── devices.py     audio output device enumeration
│   └── player.py      MediaPlayer: audio or video, load/play/seek/route
├── show/
│   ├── clock.py       ShowClock: the interpolating timeline clock
│   ├── timeline.py    Show / DmxTrack / DmxKeyframe, JSON persistence
│   ├── engine.py      ShowEngine: media + clock + DMX as one unit
│   └── demo.py        generated chase/swell show for rig checkout
├── dmx/
│   ├── output.py      DmxOutput interface, NullOutput for dry runs
│   ├── artnet.py      Art-Net (ArtDMX) packets
│   ├── sacn.py        sACN / E1.31 packets, multicast addressing
│   └── sender.py      fixed-rate output thread
└── ui/
    ├── main_window.py transport, timeline and output
    ├── video_widget.py black video surface, full screen on any display
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

## Next steps

There is no cue authoring UI yet — `show/demo.py` stands in for it. The natural
next pieces are a cue list editor writing the same JSON, fixture profiles so
cues address fixtures rather than raw channels, and Art-Net node discovery
(ArtPoll) so outputs can be picked from a list instead of typed.
