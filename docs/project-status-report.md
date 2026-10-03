# AION Show System — Implementation Status Report

**Review date:** 2026-10-02  
**Version:** 0.1.0 (`pyproject.toml`)  
**Baseline:** current working tree, including existing uncommitted changes; latest commit `d069639`.

## 1. Executive summary

AION Show System is a working **playback-focused MVP** for synchronized audio/video and network DMX lighting. The main runtime pieces are present: JSON shows, interpolated lighting timelines, Art-Net and sACN output, a Qt operator interface, scheduled/WebSocket/local-command triggers, looping, and show chaining.

The project is **not yet a complete show-authoring or production-hardened unattended control platform**. Shows must be authored externally or in JSON; there is no fixture patch/editor, playlist interface, or service-mode playback entry point. The most important remaining work is correctness and operational safety, rather than adding another trigger type.

**Overall assessment:** suitable for development and controlled rig trials; resolve configuration, media-failure, and output-lifecycle issues before relying on it unattended. Passing tests establish useful software coverage, but do not establish hardware timing, codec compatibility, or production reliability.

### At a glance

| Area | Status | Assessment |
| --- | --- | --- |
| Show model and rendering | Implemented | Linear fades, HTP merging, multi-universe frames, multi-byte channel interpolation |
| Playback and synchronization | Implemented with gaps | Media-backed and timeline-only transport; media lifecycle/error handling needs hardening |
| DMX transports | Implemented with gaps | Art-Net and sACN packet generation; configuration wiring and shutdown safety need attention |
| Trigger system | Implemented with gaps | All four original trigger paths exist; identity, IPC robustness, and network authorization remain |
| Operator GUI | Implemented | Transport, status, monitoring, audio routing, video fullscreen; not an authoring environment |
| Configuration | Partially integrated | Parser supports more settings than the GUI actually applies |
| Automated quality checks | Mostly healthy | 138 tests pass; Ruff has one violation |
| Deployment/readiness | Incomplete | No checked-in CI workflow, installer/service setup, or documented rig qualification results |

## 2. Review scope and verification

Reviewed `README.md`, `docs/show-file-format.md`, `pyproject.toml`, application bootstrap/configuration, show engine/model/clock/library, DMX transports/sender, trigger sources/policy, GUI components, and test coverage. The original requirements were also consulted from `HEAD:requirements.md`; that file is deleted in the current working tree, so it is historical context rather than a current specification.

Commands run using the existing Windows virtual environment:

| Check | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest` | **138 passed in 2.21s** |
| `.venv/Scripts/ruff.exe check .` | **Failed:** one `E501` at `src/aion_show_system/show/timeline.py:146` (105 characters; configured maximum 100) |

Tests run with Qt's offscreen platform. Coverage includes packet layouts, clock behavior, timeline rendering, GUI wiring, playback completion/looping, trigger policy, and real subprocess-to-local-IPC trigger delivery.

**Not verified in this review:** live fixtures/nodes, network delivery under load, audible/video synchronization, seamless media loops, projector behavior, long-duration stability, Raspberry Pi performance, or macOS/Linux deployment. No coverage percentage was measured. Findings below are based on code inspection unless explicitly backed by the checks above.

## 3. What is already implemented

### 3.1 Show files and lighting rendering

Sources: `src/aion_show_system/show/timeline.py`, `show/library.py`, `show/demo.py`.

- JSON load/save APIs for show name, media reference, duration, looping, override policy, successor show, tracks, and keyframes.
- Flat-directory show discovery with lookup by path, filename, stem, or case-insensitive embedded show name. Lookup rescans files, so new shows do not require an application restart.
- Sorted keyframes, channel-range validation, level clamping, linear interpolation, same-time snaps, and holding channel values after their last cue.
- Full 512-channel frames per referenced universe, with highest-takes-precedence merging between tracks.
- `wide` channel groups for interpolating 16-bit and wider parameters as one value rather than independently fading coarse/fine bytes.
- Explicit duration or duration derived from the last lighting keyframe.
- Programmatic demo chase/swell generation.
- Detailed format/exporter documentation in `docs/show-file-format.md`, including rendering semantics, pitfalls, and reference vectors.

### 3.2 Playback, media, and timing

Sources: `show/engine.py`, `show/clock.py`, `media/player.py`, `media/devices.py`.

- Audio/video playback through `QMediaPlayer`, with play, pause, stop, seek, volume, mute API, and output-device selection.
- Thread-safe monotonic show clock, media-position anchoring, capped slew correction for small drift, and hard resynchronization for large errors/seeks.
- DMX rendering uses the interpolated show clock rather than coarse media position reports.
- Timeline-only playback without media.
- Media-backed completion from end-of-media events; timeline-only completion polled every 50 ms.
- Backend media looping and clock-based timeline looping, with an operator loop toggle.
- Completion notification and `next_show` chaining.
- Explicit blackout attempts on stop and show replacement.

### 3.3 DMX output

Sources: `dmx/output.py`, `dmx/artnet.py`, `dmx/sacn.py`, `dmx/sender.py`.

- Replaceable output interface and dry-run backend recording emitted frames.
- UDP ArtDMX packet generation with unicast/broadcast destinations and sequence handling.
- E1.31/sACN packet generation with multicast/unicast, per-universe sequences, CID, source name, and priority support at the transport API level.
- Dedicated sender thread with absolute frame scheduling; default rate 40 Hz.
- Multi-universe rendering and support for multiple outputs through the sender API, although the GUI selects only one output at a time.
- Frame count, late-frame count, last rendered frame, and failed-output count for diagnostics.
- Frame/output exception handling intended to keep one failing transport from stopping the rest.

### 3.4 Triggers and automation

Sources: `triggers/`, `config.py`, `app.py`.

- Central trigger manager replaces the active show and starts the requested show.
- Override protection while a show is playing; paused/stopped shows can be replaced.
- Wall-clock schedule with weekday filters, accepted 12/24-hour formats, and once-per-matching-minute firing.
- Startup suppression of schedule entries already due in the current minute.
- One outbound WebSocket client, optional `wss`, automatic reconnect, and bare-text/JSON show messages.
- Local command triggers through `QLocalServer`/`QLocalSocket`, with acceptance/refusal replies and CLI exit codes.
- `--trigger` uses `QCoreApplication` and does not launch another GUI; normal invocation starts the GUI.
- Show-finished chaining uses the same resolver and trigger policy as other sources.

### 3.5 Operator interface and application infrastructure

Sources: `ui/`, `app.py`, `paths.py`, `logging_setup.py`, `pyproject.toml`.

- Loaded-show identity, track count, loop/override/chain indicators, progress slider, elapsed/total time, and scrubbing.
- Play/pause, stop, loop, volume, audio output selection, open-show action, and generated demo action.
- Embedded video with F11 fullscreen and an API for selecting a screen; no display-selection UI is wired up.
- DMX go-live/offline controls, destination/protocol selection, frame-rate/late-frame display, and per-universe level monitor.
- Trigger-source status and last accepted/rejected trigger.
- Optional startup config, command-line show loading, and version flag.
- Platform-aware directories and rotating file/console logging.
- Python package metadata, GUI/CLI entry points, development dependencies, and a `uv.lock` in the working tree (currently untracked).

## 4. Original requirement coverage

| Original requirement | Current implementation |
| --- | --- |
| Show which show is loaded | Present in GUI |
| Playback progress and play/pause/stop | Present; timeline-only and media-backed playback supported |
| Looping | Present in show model, engine, backend, and GUI |
| Trigger replaces and starts a show | Present |
| Per-show protection from replacement | Present, but same-show exception has an identity bug described below |
| Clock-time trigger | Present, with weekday filtering |
| One optional configured WebSocket connection | Present; no connection without host and port |
| Command line triggers an existing running instance | Present, including subprocess IPC tests |
| Completion starts another show | Present through `next_show` |
| Config for DMX, WebSocket, and clock triggers | Present, but some DMX properties are not applied by GUI startup |
| No need for DMX levels/config editing in GUI | Both exist as extras; not missing requirements |

The principal requested runtime workflows exist. Remaining work consists of incomplete integration, edge cases, release readiness, and optional expansion—not an absent core playback engine.

## 5. What remains: defects and hardening

Priority definitions: **P0** = address before unattended/live reliance; **P1** = next correctness/reliability milestone; **P2** = usability/documentation/release improvement. These are review recommendations, not an existing project backlog.

### P0 — configuration and safe runtime behavior

1. **Apply the DMX config end to end.** `MainWindow` creates `ShowEngine` without `config.dmx.fps`, so the default GUI path still sends at 40 Hz. `_apply_dmx_config()` populates the panel, whose `build_output()` does not pass the configured Art-Net port. `DmxConfig.create_output()` supports that port but is not used by this startup path. The configured/panel universe also does not remap show universes: packets use each track's universe. Decide and document whether this is a default for authoring, a mapping, or an unnecessary setting; add tests for non-default FPS and port.

2. **Make failed media loading atomic and fail safe.** `ShowEngine.load_show()` installs the new show and catches a missing-file exception without rejecting the load. On a fresh player, playback can remain at zero while DMX continues. After a previous media show, `MediaPlayer.load()` leaves the old source intact when the new path is missing, allowing the new show to play against stale media. Loading a timeline-only show also does not clear old media/video state. Clear/detach obsolete sources and prevent playback/trigger success until required media is usable. Handle asynchronous decoder errors with a defined stop/blackout or fallback policy.

3. **Validate config and show structure before going live.** Config JSON syntax errors fall back to defaults, but invalid section contents can raise out of `AppConfig.from_dict()` and stop startup. Show loaders do not consistently handle wrong-shaped JSON (`[]`, `null`, invalid track/media containers), and some `TypeError`/`AttributeError` failures escape their handlers. Validate positive finite FPS, ports, protocol-specific universes, non-negative finite times/durations, actual boolean types, and supported format versions. Currently `version` is ignored and Art-Net universe values are packed without range validation.

4. **Serialize blackout and sender shutdown.** `ShowEngine.stop()` sends blackout while the sender thread can still render/transmit. It stops the thread only afterward. Output clearing can also close a transport already captured by the sender's output snapshot. Treat this as a concurrency risk requiring tests: ensure a shutdown/replacement cannot transmit a non-black frame after the final blackout or race socket closure. Define intentional pause behavior too: pause currently holds DMX output live.

### P1 — policy, triggering, and operational reliability

5. **Fix same-show override identity.** `TriggerManager.handle()` compares `current is not show`, but `ShowLibrary.load()` creates a new object on each request. A protected playing show therefore rejects a request for itself, despite the documented exception. Use stable resolved file/show identity and test repeated triggers by all aliases.

6. **Clarify/restrict IPC instance ownership.** A listener unconditionally removes the endpoint before listening; there is no explicit single-instance guard. Verify behavior for a second GUI launch on each supported platform and distinguish an active endpoint from a stale one. `--socket` changes the CLI client endpoint, but normal startup does not pass it to the command listener, which always uses the default.

7. **Buffer and bound local IPC messages.** The local server parses each `readyRead` chunk immediately, rather than accumulating through a newline. Fragmented messages can become partial show names. Add framing, length limits, timeout handling, and tests for fragmented/malformed input.

8. **Expose genuine output health.** Failed-output tracking logs only the first failure, but `send_once()` still retries that output every frame; comments claiming it is skipped do not match the loop. The GUI displays rendered-frame rate, not confirmed successful delivery, and does not surface failed-output counts. Add explicit failure/recovery state and honest health labels; UDP transmission alone still cannot prove a fixture received the data.

9. **Harden remote trigger trust.** `wss` transport is supported, but there is no application-level authentication, authorization, show allowlist, replay protection, or message rate limit. Remote triggers can resolve arbitrary local paths. Restrict references and credentials according to the deployment trust model.

10. **Define schedule precision and recovery policy.** Seconds can be parsed but schedule matching uses only hour/minute. Startup skips the current matching minute; missed minutes after downtime are not replayed. Document these choices or add explicit second-level precision, timezone/DST, and missed-trigger policies. Conflicting entries currently execute sequentially, potentially replacing one another immediately.

11. **Qualify runtime timing and lifecycle.** Add actual decoded audio/video tests, end-of-media/chain transition tests, stale Qt-signal tests, network reconnection integration tests, long-run soak tests, and multi-universe load benchmarks. The clock/sender design is sensible, but sub-millisecond cue accuracy and gapless output remain hardware/backend qualification claims rather than results from this review.

### P2 — format completion, usability, and release work

12. **Implement or explicitly reserve `media.start_ms`.** It is parsed and saved but never applied. Documented as reserved already; avoid exposing it as a working trim/offset feature until engine semantics and tests exist.
13. **Resolve zero-duration behavior.** Empty/zero-duration timeline-only shows run indefinitely rather than completing. Decide whether that is an intentional static look, a validation error, or immediate completion.
14. **Finish operator persistence.** No save/export menu is present, despite a working `Show.save()` API. GUI loop edits are in-memory only; output/device choices are not written back to config. No show-library browser is present despite `ShowLibrary.names()`.
15. **Fix lint and establish release gates.** Resolve the existing `E501`, add CI for supported OS/Python combinations, and document dependency/environment setup. Python support is declared as `>=3.10`; that range was not validated here.
16. **Reconcile documentation and packaging.** README's CLI-background-launch description does not accurately distinguish normal invocation from `--trigger`; its WebSocket wording should say incoming cues, not that the client sends show names. The format document mentions a show list and operator save action that are not in this GUI. Replace the placeholder clone URL, add a license file corresponding to the MIT declaration, and qualify platform/codec/gapless claims with tested environments. No checked-in CI workflow or deployment artifacts were found.

## 6. Potential features to add

These are **new feature candidates**, separate from the fixes above. None should be interpreted as already implemented.

| Feature | Benefit | Suggested timing |
| --- | --- | --- |
| Preflight/validation command with machine-readable results | Check media, schema, duplicate names, universes, schedules, and dangling chains before deployment | First expansion |
| Show-library browser with search, recent shows, and manual trigger buttons | Avoid file dialogs and memorized names during operation | First expansion |
| Headless playback/service mode | Run unattended under systemd or Windows service supervision without the operator window | First expansion |
| Emergency blackout and operator lock/arming mode | Provide explicit high-visibility controls separate from normal transport | First expansion; validate safety behavior |
| Playlist/cue-stack interface with Go, Next, queue, and priorities | Replace fragile file-to-file chains for managed running orders | Next milestone |
| Schedule editor and next-trigger preview | Make automation visible and reduce JSON configuration mistakes | Next milestone |
| Display selection and saved projector routing | Use the existing screen-targeting API in an operator workflow | Next milestone |
| Show bundle import/export with media manifest/checksums | Portable deployment without working-directory path traps | Next milestone |
| Multi-output/universe routing and venue profiles | Send different universes to different nodes/interfaces; reuse shows across venues | Next milestone |
| Monitoring dashboard, alerting, and event history | Track trigger outcomes, drift, transport failures, and system health remotely | Next milestone |
| External authoring/export SDK, starting with Unreal Engine integration | Support the intended authoring host using shared validation and test vectors; no plugin exists here | Authoring roadmap |
| Fixture library and patch model | Author pan/tilt/color/intensity instead of raw channel addresses | Authoring roadmap |
| Timeline/cue editor with preview and waveform | Create/edit tracks visually rather than hand-editing JSON | Authoring roadmap |
| Step/easing curves, per-channel LTP/HTP modes, track mute/solo/master | Better control of movement/color and layered looks; requires versioned format changes | Authoring roadmap |
| MIDI, OSC, GPIO, or HTTP trigger adapters | Integrate control desks, sensors, interactive installations, and automation | As deployment requires |
| External timecode and timestamped distributed cues | Synchronize multiple machines more precisely than independent WebSocket receipt | Advanced; requires measured latency/clock design |
| Media preloading, crossfades, and multiple playback voices | Smooth transitions and overlapping audio/video cues | Advanced; engine redesign |
| Backup-controller/failover support | Improve continuity if a show machine fails | Advanced; requires ownership/split-brain safeguards |

## 7. Recommended implementation sequence

1. **Correctness and safe output:** fix DMX config wiring, media source cleanup/failure handling, structural validation, and sender/blackout ordering. Add regression tests before expanding functionality.
2. **Reliable automation:** fix same-show identity and socket configuration, add IPC framing/single-instance checks, surface output faults, and define schedule/network trust policies.
3. **Release qualification:** make lint clean, establish CI, run real media/network/rig tests on target platforms, benchmark Raspberry Pi workloads, and produce deployment/runbook documentation.
4. **Operator improvements:** add preflight tooling, show browser, saved settings, display routing, and headless service startup.
5. **Product expansion:** choose external authoring integration versus a built-in editor, then add playlists, fixtures, richer interpolation, and advanced synchronization as justified by actual installations.

**Bottom line:** most of the original playback requirements are implemented and covered by a useful passing test suite. The highest-value next milestone is a reliable, validated unattended player—not a larger feature surface on top of unresolved media/configuration/output edge cases.
