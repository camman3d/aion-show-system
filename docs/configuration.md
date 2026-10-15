# Configuration

The app reads one optional JSON file, **once at startup**. Every section and
field is optional; a missing file is a valid configuration (dry-run DMX, no
WebSocket, no clock triggers). An unreadable or malformed file is logged and
treated as absent so an unattended machine still boots.

## Locations

| Item | Location |
| --- | --- |
| Config file (default) | `<project>/config.json` |
| Shows directory (default) | `<project>/shows/` |
| Log file | `<project>/logs/aion-show-system.log` (1 MB × 3 rotating) |

`<project>` is the repository root (the directory containing `pyproject.toml`).
Override the config file with `--config PATH`.

## Full example

```json
{
  "shows_dir": "/opt/aion/shows",

  "dmx": {
    "protocol": "artnet",
    "host": "10.0.0.20",
    "port": 6454,
    "universe": 1
  },

  "websocket": {
    "host": "10.0.0.5",
    "port": 8765,
    "path": "/cues",
    "reconnect_seconds": 5
  },

  "poll": {
    "url": "http://10.0.0.5/cue.json",
    "interval_seconds": 5,
    "timeout_seconds": 5
  },

  "clock_triggers": [
    { "time": "10:00 PM", "show": "Nightly" },
    { "time": "14:30", "show": "Matinee", "days": ["sat", "sun"] }
  ]
}
```

A copy is in `config.example.json`.

## `shows_dir`

String. Directory that trigger references resolve against (see
[triggers.md](triggers.md#how-a-show-is-resolved)). `~` is expanded. Default:
`<project>/shows`.

## `dmx`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `protocol` | string | `"none"` | `artnet` (`art-net`, `art_net`), `sacn` (`e1.31`, `e131`), or `none` (`null`, `dry`, empty) = dry run. Anything else is an error (see note below) |
| `host` | string | none | Destination address. Art-Net: node or broadcast (blank → `255.255.255.255`). sACN: unicast address; blank = multicast `239.255.x.y` |
| `port` | int | `6454` | See [limitations](#limitations) |
| `universe` | int | `1` | Initial value of the panel's universe spinner |
| `fps` | float | `40.0` | See [limitations](#limitations) |
| `auto_start` | bool | auto | `true`/`false` forces whether the output goes live at startup. Omitted → live iff `protocol` is `artnet`/`sacn` |

> An unknown `protocol` raises `ValueError` inside `AppConfig.from_dict`, which
> is **not** caught there (only clock-trigger entries are). It will propagate
> out of `AppConfig.load`. Use one of the accepted values.

On startup `MainWindow` copies protocol/host/universe into the *DMX output*
panel and, if `enabled`, presses **Go live**.

## `websocket`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `host` | string | none | Server host |
| `port` | int | none | Server port |
| `path` | string | `/` | URL path (a leading `/` is added if missing) |
| `secure` | bool | `false` | `wss://` instead of `ws://` |
| `reconnect_seconds` | float | `5.0` | Retry interval (minimum 1 s) |

The client only connects when **both** `host` and `port` are set; otherwise the
panel shows "not configured" (not an error).

## `poll`

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `url` | string | none | URL to GET. Polling is off when absent |
| `interval_seconds` | float | `5.0` | Time between polls (minimum 0.25) |
| `timeout_seconds` | float | `5.0` | Per-request timeout |
| `delay_seconds` (or `delay`) | float | `0` | Seconds to wait after a poll cue before the show starts |

The response must be `{"show": "name", "inc": N}`; a show starts when `inc`
increases. See [triggers.md](triggers.md#poll).

## `clock_triggers`

A list of objects:

| Key | Required | Meaning |
| --- | --- | --- |
| `time` | yes | `HH:MM`, `HH:MM:SS`, `H:MM AM/PM`, `H AM/PM` (case/space-insensitive) |
| `show` | yes | Show reference (name, file name or path) |
| `days` | no | List (or single string) of weekdays: `mon`/`monday`, `tue`/`tues`, `wed`, `thu`/`thur`/`thurs`, `fri`, `sat`, `sun`. Empty/omitted = every day |
| `name` | no | Label for logs |

An invalid entry is logged and skipped; the others still load. Times are local
system time at minute granularity.

## Command line

```
aion-show-system [file] [--trigger SHOW] [--config PATH] [--socket NAME] [--version]
```

| Argument | Effect |
| --- | --- |
| `file` | Show file (`.json`) to load on launch (loaded, not auto-played) |
| `--trigger SHOW` | Send SHOW (name or path) to the already-running instance and exit. Exit code 0 if accepted, 1 otherwise; the reply is printed to stdout/stderr. No GUI is created. |
| `--config PATH` | Use this config instead of the default |
| `--socket NAME` | IPC endpoint name (default `aion-show-system`) |
| `--version` | Print version |

Both console scripts (`aion-show-system`, `aion-show-system-cli`) map to the
same `main()`.

## Limitations

- `dmx.fps` and `dmx.port` are parsed but not currently applied (the engine
  runs at 40 Hz and Art-Net uses port 6454); `DmxConfig.create_output()` is not
  used by the GUI. Details in [architecture.md](architecture.md#known-gaps--inconsistencies-in-the-current-code).
- Config is not reloaded at runtime; restart to apply changes.
