# Triggers

A *trigger* means "stop what is playing, load this show, start it". Five things
can cause one; they all produce a `TriggerEvent(show, source, detail)` and are
handled by one policy in `TriggerManager` so they behave identically.

| Source | `source` | Where the show name comes from |
| --- | --- | --- |
| Clock | `clock` | `clock_triggers` in config |
| WebSocket | `websocket` | Text frames from the configured server |
| Poll | `poll` | `show` in the JSON returned by a polled URL |
| Command line | `command` | `aion-show-system --trigger SHOW` |
| Chain | `chain` | `next_show` of the show that just finished |
| (Manual) | `manual` | constant defined for UI use |

## Policy (`TriggerManager.handle`)

1. Resolve the reference with `ShowLibrary.load`. No match / unreadable →
   **rejected** (`no show named '…'`).
2. If a show is currently *playing*, is a different show object, and has
   `allow_override: false` → **rejected** (`'X' does not allow being overridden`).
3. Otherwise `engine.load_show(show)` then `engine.play()`; emits `triggered`.

A `rejected` result is logged, shown in the Triggers panel/status bar, and
reported back to a waiting command-line caller. Note that a trigger naming the
show that is already loaded and playing is reloaded from disk and restarted
(the "current is not show" check compares object identity, and the library
returns a fresh object each time).

## How a show is resolved

`ShowLibrary.find(reference)` tries, in order:

1. The reference as a file path (absolute or relative to the working directory).
2. In each library directory (`shows_dir`): `reference`, `reference.show.json`,
   `reference.json`.
3. A case-insensitive match against file stem/name, then against the `"name"`
   field inside each show file.

The directory is re-read on every lookup, so shows may be dropped in while the
system runs. The scan is **not recursive** and files are visited in sorted
order; first match wins.

## Message formats (WebSocket and command line)

Parsed by `parse_trigger_message`. Either:

- a bare string: `Nightly`
- a JSON object: `{"show": "Nightly"}` (`trigger` or `name` also accepted as
  the key). Optional `"command"` must be `trigger`, `show`, `play` or empty;
  other commands are ignored.

Anything that names no show is ignored with a warning.

## Clock triggers

`ClockTriggerSource` polls the system clock at 1 Hz (robust against NTP steps,
DST and sleep). A trigger matches when the current hour/minute equal its time
and (if `days` is set) the weekday is listed. It fires **at most once per
minute per day**, and on `start()` it claims the current minute so relaunching
the app at 10:00 PM doesn't immediately re-fire the 10:00 PM show.

## Poll

`PollTriggerSource` does an HTTP GET on `poll.url` every
`poll.interval_seconds` (default 5, minimum 0.25) and expects JSON:

```json
{"show": "Nightly", "inc": 7}
```

`inc` is a counter the server bumps whenever it wants a show started. The
source remembers the last `inc` and fires `show` only when `inc` **increases**:

- `inc` of 0, or a blank/missing `show`, never starts anything.
- The **first successful response after startup is a baseline** and never
  fires, so restarting the machine doesn't replay the last cue.
- If `inc` goes down (server reset), it becomes the new baseline; the next
  increase fires.
- Unchanged `inc` does nothing, so the same answer polled repeatedly is safe.
- Network errors, timeouts (`timeout_seconds`, default 5), non-JSON bodies and
  non-object JSON are logged and ignored; polling continues. Requests don't
  overlap: a slow response delays the next poll rather than stacking up.

Panel status shows e.g. `polling http://host/cue.json (inc 7)`, `error: …` or
`bad response`. With no `url` it reads "not configured".

## WebSocket

`WebSocketTriggerSource` is a **client**: it dials out to
`ws[s]://host:port/path` and relays each text message as a cue. It reconnects
forever every `reconnect_seconds` (≥ 1 s) after a disconnect or error. With no
host+port configured it stays idle ("not configured").

Quick test with any WebSocket server that broadcasts, sending `Nightly` or
`{"show":"Nightly"}`.

## Command line (local IPC)

`CommandTriggerSource` runs a `QLocalServer` (named pipe on Windows, socket file
elsewhere) named `aion-show-system` (override with `--socket`). Protocol: one
UTF-8 line in, one line out:

- `OK triggered <show name>`
- `ERR no show in message`
- `ERR no show named '<ref>'`
- `ERR '<current>' does not allow being overridden`

Client side: `send_trigger(message, socket_name=…, timeout_ms=2000)` returns
`(accepted, reply)`; failures include `ERR no running instance on <name>` and
`ERR no reply from the running instance`.

```bash
aion-show-system --trigger "Nightly"; echo $?
```

The client uses a `QCoreApplication` (no display needed), so it works over SSH.
If the server socket can't be opened, the panel reports "unavailable: …"; a
stale endpoint from a crash is removed on start.

## Chaining

When `show_finished` fires and the show has `next_show`, a `chain` trigger for
that name goes through the same policy. A looping show never finishes, so it
never chains. If the next show is missing or refuses override, the chain stops.

## Trigger panel

The UI's *Triggers* box shows one status line per source (e.g. "3 clock
triggers armed", "connected to ws://…", "reconnecting in 5s", "listening on
aion-show-system") and the last trigger, accepted or refused.
