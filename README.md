# AION Show System

Automated show playback for DMX lighting rigs. The system runs on Windows, macOS, Linux and Raspberry Pi, playing audio or video while driving DMX over Art‑Net or sACN (E1.31). Triggered by a schedule, a websocket cue, the command line or a chained show.

## Features

* **Full‑fledged DMX output** – dry run, Art‑Net or sACN, with custom universe, host and port.
* **High‑precision timing** – a dedicated clock runs on a monotonic timer, synchronised to `QMediaPlayer` reports. DMX frames are sent at a fixed 40 Hz in a dedicated thread.
* **Show files** – JSON describing media, DMX tracks, keyframes, looping and chaining (`next_show`).
* **Triggers** – wall‑clock schedule, WebSocket cue, command‑line `aion-show-system-cli --trigger`, or a chain from a previous show.
* **No hardware dependencies** – tested with headless Qt and without a lighting rig.
* **Extensible** – replace‑able output backends, add fixture profiles, add cue authoring UI.

## Installation

```bash
# Clone the repo
git clone https://github.com/<org>/aion-show-system
cd aion-show-system

# Create a virtual environment and install the package (editable for dev)
pip install -e ".[dev]"
```

Dependencies are pure Python with `PySide6`. On Linux/Raspberry Pi you may need the system packages for GStreamer:

```bash
sudo apt install libgstreamer1.0-0 gstreamer1.0-plugins-base \
                 gstreamer1.0-plugins-good gstreamer1.0-alsa
```

## Running

```bash
# GUI + console entry point
python -m aion_show_system    # or `aion-show-system`

# CLI only (launches the GUI in the background)
aion-show-system-cli [--trigger "ShowName"]
```

If you want to start the system with a specific show or config:

```bash
python -m aion_show_system /path/to/myshow.show.json
python -m aion_show_system --config /etc/aion/config.json
```

## Configuration

`config.json` (optional) is read from the project root (`paths.config_dir()`).
It can specify DMX parameters, a websocket endpoint and a wall‑clock schedule.

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

Missing fields are silently ignored; an empty `config.json` is a valid start‑up.

## Show files

A show is a JSON object containing media information, a collection of DMX tracks and optional metadata. The full schema is documented in `docs/show-file-format.md`.

```json
{
  "name": "Act One",
  "media": { "path": "music.wav", "start_ms": 0 },
  "duration_ms": 60000,
  "loop": false,
  "allow_override": true,
  "next_show": "Act Two",
  "tracks": [
    { "name": "Wash", "universe": 1, "keyframes": [
      { "time_ms": 0, "values": { "1": 0 } },
      { "time_ms": 2500, "values": { "1": 255 } }
    ]}
  ]
}
```

Keyframes drive linear interpolation per channel. Multiple tracks inside the same universe use a **highest‑takes‑precedence** merge.

## Triggers

- **Clock** – configured in `clock_triggers`.
- **WebSocket** – a persistent client sending show names.
- **Poll** – a URL polled at an interval; it returns `{"show": "name", "inc": N}` and the show starts when `inc` increases.
- **Command line** – `aion-show-system-cli --trigger "Name"`.
- **Chaining** – `next_show` in a finished show.

Triggers obey an *override policy*: if the currently playing show has
`allow_override: false` the trigger is rejected.

## Development

Running the test suite:

```bash
pytest
ruff check .
```

The tests run Qt off‑screen and do not require a DMX rig.

## Contribution

We welcome pull requests!  Please ensure tests pass and the `ruff check`
linting passes.

---

© AION 2023–2026, licensed under the MIT licence.
