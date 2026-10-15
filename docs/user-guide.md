# User Guide

## Install

Requires Python ≥ 3.10 and PySide6 ≥ 6.7 (the full package: audio lives in
PySide6-Addons).

```bash
git clone <repo-url> aion-show-system
cd aion-show-system
pip install -e ".[dev]"      # or: uv sync
```

Raspberry Pi / Linux may need GStreamer for Qt Multimedia:

```bash
sudo apt install libgstreamer1.0-0 gstreamer1.0-plugins-base \
                 gstreamer1.0-plugins-good gstreamer1.0-alsa
```

## Start

```bash
python -m aion_show_system                       # or: aion-show-system
python -m aion_show_system my.show.json          # preload a show
python -m aion_show_system --config /etc/aion/config.json
```

Logs go to stderr and to `<project>/logs/aion-show-system.log`.

## The window

Top to bottom:

| Area | Purpose |
| --- | --- |
| Video surface | Hidden until the loaded media has a video stream. **F11** (View ▸ Video Full Screen) toggles full screen; **Esc** leaves it |
| Show label | Loaded show name, track count and flags (looping, not overridable, `then <next_show>`) |
| Media path | File currently loaded |
| Position slider + time | Driven by the show clock, can outlast the media if the show's `duration_ms` is longer. Drag to seek |
| `clock ±x.xx%` | Slew applied to the timeline clock to track the media. Near 0 is healthy; a persistently large value means the machine can't keep up |
| Transport | **Open Show…**, **Play/Pause** (Space), **Stop**, **Loop**, volume |
| Audio output | Choose the output device (default listed first) |
| Triggers | Status of the clock, WebSocket and command-line sources; last trigger and whether it was accepted |
| DMX output | Protocol (Art-Net / sACN / Dry run), host, universe, **Go live**. Shows measured Hz and a late-frame count when live |
| Levels | 32×16 live grid of one universe (channel 1 top-left); pick the universe |

Menu: **File** ▸ Open Show (Ctrl+O), Build Demo Sequence, Exit; **View** ▸ Video
Full Screen; **Help** ▸ About.

## Typical workflows

### Test the rig with the demo sequence
1. (Optional) File ▸ Open Show… and load a show that has media, or just use the
   demo on its own.
2. File ▸ **Build Demo Sequence**: generates an 8-channel chase plus a slow
   "swell" on channel 16 across the media's duration (30 s if no media), in
   universe 1.
3. Set protocol/host in *DMX output*, click **Go live**, then **Play**. The swell
   is one long fade, so any clock stutter shows as a step on the rig.

### Run an unattended show machine
1. Put `.show.json` files in `shows_dir`.
2. Write `config.json` with `dmx` (live protocol), optional `websocket` and
   `clock_triggers` — see [configuration.md](configuration.md).
3. Launch the app at boot. With a real protocol configured it goes live on its
   own; triggers arm automatically.
4. Cue shows with a schedule, the WebSocket, a polled URL, or
   `aion-show-system --trigger "Show Name"` — see [triggers.md](triggers.md).

### Chain / loop shows
- `"loop": true` repeats a show indefinitely (gapless for media shows). The
  **Loop** checkbox toggles it on the loaded show at runtime (not saved to disk).
- `"next_show": "Act Two"` starts that show when this one finishes.
- `"allow_override": false` protects a show from triggers until it ends.

## Behaviours to know

- **Play** starts DMX first, then audio/video. **Stop** blacks out every
  universe the show uses, then stops sending.
- **Go live** begins refreshing DMX even before Play (so fixtures hold their
  state); **Go offline** blacks out the loaded show's universes.
- A show with no media runs on the clock alone, using `duration_ms` (or its last
  keyframe) as its length.
- If a show's media file is missing, a warning dialog appears; the show still
  loads and its DMX can run.
- Multiple tracks on one universe merge **highest value wins** per channel.
- Triggers replace whatever is playing unless it has `allow_override: false`.
- Config changes require a restart.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Rig dark, panel says Offline | Click **Go live**, or set `protocol` in config |
| sACN "universe out of range" | sACN universes are 1–63999; use 1, not 0 |
| Trigger "no show named …" | File in `shows_dir`? Name matches filename or the show's `"name"`? Not in a subfolder (scan is flat) |
| Trigger "does not allow being overridden" | Playing show has `allow_override: false`; wait or stop it |
| `ERR no running instance` from `--trigger` | App isn't running, or `--socket` names a different endpoint |
| WebSocket stuck "reconnecting" | Host/port/path/`secure` correct? Server reachable? Check the log |
| Many "late" frames | Machine is overloaded (common on Pi); close other apps, reduce video load |
| Silent / no devices | "No audio output found" means Qt sees no device; on Linux check GStreamer packages |
| Config ignored | A malformed JSON file is logged and skipped — check the log for "Could not read config" |
