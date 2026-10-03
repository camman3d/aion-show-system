# Architecture

AION Show System is a Python 3.10+ / PySide6 application that plays an audio or
video file while driving DMX lighting (Art-Net or sACN) from keyframed tracks
kept in sync with that media. It is designed to run unattended on Windows, macOS,
Linux and Raspberry Pi, started by a schedule, a WebSocket cue, a command line or
a chained show.

## Package layout

```
src/aion_show_system/
├── __init__.py          version + APP_NAME / ORG_NAME constants
├── __main__.py          `python -m aion_show_system` / console-script entry
├── app.py               argument parsing, QApplication bootstrap, --trigger client
├── config.py            AppConfig and its sections (DMX, WebSocket, clock triggers)
├── paths.py             platform config/data/log dirs (via QStandardPaths)
├── logging_setup.py     stderr + rotating file log
├── show/                the cue model and playback engine
│   ├── timeline.py      Show, DmxTrack, DmxKeyframe, MediaCue (pure data, no Qt)
│   ├── clock.py         ShowClock - interpolated, slewed master clock
│   ├── engine.py        ShowEngine - media + clock + DMX as one unit
│   ├── library.py       ShowLibrary - resolves a name/path to a show file
│   └── demo.py          generated chase + swell demo show
├── media/
│   ├── player.py        MediaPlayer - QMediaPlayer/QAudioOutput wrapper
│   └── devices.py       audio output device enumeration
├── dmx/
│   ├── output.py        DmxOutput ABC, NullOutput (dry run)
│   ├── artnet.py        ArtNetOutput (UDP 6454)
│   ├── sacn.py          SacnOutput (E1.31, UDP 5568, multicast or unicast)
│   └── sender.py        DmxSender - fixed-rate output thread
├── triggers/
│   ├── base.py          TriggerEvent, TriggerSource, message parsing
│   ├── clock_source.py  wall-clock schedule
│   ├── websocket_source.py  outbound WebSocket client
│   ├── poll_source.py   HTTP poller firing on an incrementing `inc`
│   ├── command_source.py    local IPC server + `send_trigger` client
│   └── manager.py       TriggerManager - the single trigger policy
└── ui/
    ├── main_window.py   MainWindow
    ├── dmx_panel.py     protocol/host/universe + "Go live"
    ├── dmx_monitor.py   custom-painted 512-channel level grid
    ├── trigger_panel.py per-source status + last trigger
    └── video_widget.py  black, full-screen-capable video surface
```

Layering is strictly one-way: `ui` → `triggers` → `show` → `media`/`dmx`.
`show/timeline.py` and `dmx/` have no Qt dependency, so they can be built and
tested without a display.

## Runtime overview

```
                       ┌────────────────────────────────────────────┐
 Clock schedule ──┐    │               TriggerManager                │
 WebSocket cue  ──┤
 URL poll (inc) ──┼──► │  resolve via ShowLibrary → override policy  │
 CLI (--trigger)──┤    │  → engine.load_show() + engine.play()       │
 next_show chain ─┘    └──────────────────────┬─────────────────────┘
                                              ▼
                                       ┌─────────────┐
   MediaPlayer ── position (~11 Hz) ─► │  ShowClock  │  (monotonic, interpolated)
   (QMediaPlayer)                      └──────┬──────┘
                                              │ position_ms() @ any time
                                              ▼
                       DmxSender thread (40 Hz) → Show.render(t) → DmxOutput(s)
                                                                   Art-Net / sACN / Null
```

### Threads

| Thread | Owns | Notes |
| --- | --- | --- |
| Qt GUI thread | widgets, `MediaPlayer`, trigger sources, `ShowEngine` transport calls, 1 Hz clock-trigger poll, 50 ms UI refresh, 50 ms completion poll | All Qt signals/slots |
| `dmx-sender` (daemon `threading.Thread`) | calls `ShowEngine._render_frame` → `Show.render` → `DmxOutput.send` | Must not touch widgets. Reads `ShowClock` (thread-safe via `RLock`) |

DMX deliberately avoids a `QTimer`: the GUI thread on a loaded Raspberry Pi will
not hold a 25 ms cadence.

## Key components

### `ShowClock` (`show/clock.py`)
Qt reports media position only about every 90 ms and does not interpolate, so
reading it directly would quantise every cue to ~93 ms. `ShowClock` free-runs on
`time.perf_counter()` and is *anchored* to the media:

- `position_ms()` = anchor + elapsed wall time × `rate`.
- `sync(media_ms)` is called on each media position report and computes the
  error (media − clock).
  - First sync after `start()`/`seek()`, or an error ≥ `hard_resync_ms` (250 ms):
    **hard resync** – jump to the media position.
  - Otherwise **slew**: re-anchor at the predicted position (so time never goes
    backwards) and set `rate = 1 + clamp(error / slew_window_ms, ±max_slew)`
    (defaults: 1000 ms window, ±5 %).
- The media file stays the authority on drift; the DMX timeline is smooth.

### `Show` / `DmxTrack` / `DmxKeyframe` (`show/timeline.py`)
Plain dataclasses. `Show.render(t)` produces one 512-byte frame per universe:
each track's `levels_at(t)` is computed (hold until next keyframe names the
channel, linear fade toward it, optional 16-bit "wide" channel groups fade as a
single number) and tracks sharing a universe merge **highest-takes-precedence
(HTP)**. See [show-file-format.md](show-file-format.md) for the normative format.

### `ShowEngine` (`show/engine.py`)
Ties player, clock and sender together.

- `play()` starts the DMX sender *first* (lighting is live before sound), then
  the media player; the clock starts when the player reports `PLAYING`. A show
  with no media free-runs the clock instead.
- **End of show**: with media, `end_of_media` completes the show; a looping show
  loops inside the Qt media backend (`Loops.Infinite`) so the seam is gapless.
  Without media a 50 ms timer compares the clock to `effective_duration_ms` and
  either wraps (`clock.seek(0)`, `looped` signal) or completes.
- `_complete()` is guarded by `_finishing` so it fires exactly once per run (a
  chained `next_show` loads synchronously inside `show_finished`).
- `stop()` blacks out all the show's universes, then stops the sender.
- Signals: `show_changed`, `show_finished`, `looped`, `sync_error_changed`.

### `DmxSender` (`dmx/sender.py`)
Fixed-rate loop (default 40 Hz) using absolute scheduling so slow frames don't
accumulate drift; a missed slot increments `late_frames` (the health metric
shown in the UI). A transport that raises `OSError`/`ValueError` is logged once
and then skipped so one bad output can't take down the others. `blackout()`
sends all-zero frames.

### Trigger layer (`triggers/`)
See [triggers.md](triggers.md). Every source emits a `TriggerEvent`;
`TriggerManager.handle` is the single policy point.

### UI (`ui/`)
`MainWindow` composes transport controls, audio device picker, trigger status,
DMX output panel and a live level monitor. Timeline readouts are driven by the
show clock, not the player. Trigger sources are only started if
`start_triggers=True` (tests disable this to avoid a live IPC endpoint).

## Design decisions worth knowing

- **The show file is the whole contract.** No side-car patch files or
  databases; what the authoring tool exports is what plays.
- **Unattended-first.** A missing/malformed config is logged and ignored; shows
  are re-read from disk on every trigger (no stale index); the WebSocket
  reconnects forever; trigger failures show in the UI.
- **Dial out, don't listen.** The WebSocket integration is a client so it works
  from behind venue networks.
- **Single trigger policy.** Source-specific code only produces a show name.

## Known gaps / inconsistencies in the current code

These were observed while writing this documentation and are worth being aware
of (they are not documented elsewhere as features):

1. **`media.start_ms` is ignored** by the engine (reserved field).
2. **`dmx.fps` and `dmx.port` in `config.json` are not applied at runtime.** The
   engine is built with the default 40 Hz, and the GUI builds its output from
   the DMX panel (protocol, host, universe), not from `DmxConfig.create_output()`
   (which is currently unused). The Art-Net port therefore stays 6454.
3. **`DmxConfig.universe` only seeds the panel's universe spinner.** Tracks
   choose their universe (`track.universe`); the Art-Net `universe` constructor
   argument is overridden per `send()` call.
4. **`aion-show-system-cli` is the same entry point as the GUI script** (both map
   to `__main__:main`). Without `--trigger` it opens the GUI; with `--trigger`
   it behaves as a headless client. It does not "launch the GUI in the
   background" as the README states.
5. Opening the same sACN CID/priority settings can't be configured from
   `config.json` (`SacnOutput` defaults: name "AION Show System", priority 100,
   random CID per run).
6. Pause on a media-less show pauses the clock only; the DMX sender keeps
   sending the frame at the frozen position.
