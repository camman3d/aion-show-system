# Development Guide

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                             # or: uv sync
```

Build backend is hatchling; the wheel packages `src/aion_show_system`.
Dev extras: `pytest`, `pytest-qt`, `ruff`.

## Tests and lint

```bash
pytest          # config in pyproject.toml: testpaths=tests, addopts=-q
ruff check .    # line length 100; rules E, F, I, UP, B
```

`tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen` and provides a
session-scoped `app` fixture, so the suite runs headless with no DMX hardware.

| File | Covers |
| --- | --- |
| `test_clock.py` | `ShowClock`: interpolation, slew, hard resync, pause/seek |
| `test_timeline.py` | keyframe/track/show model, interpolation, HTP merge, wide channels, JSON round-trip |
| `test_dmx.py` | Art-Net and sACN packet bytes, `DmxSender` (rate, failing source/outputs, blackout, clear) |
| `test_config.py` | `AppConfig` parsing: times, days, protocols, WebSocket, defaults |
| `test_engine.py` / `test_playback.py` | `ShowEngine`: render-from-clock, clock sync, blackout on stop, missing media, looping, finish-once, durations |
| `test_media.py` | `MediaPlayer` defaults, volume clamp, load, device enumeration, video output |
| `test_triggers.py` | message parsing, clock/WebSocket/command sources, manager policy |
| `test_ui.py` | `MainWindow` construction, labels/flags, loop checkbox, DMX config, demo sequence, DMX panel and monitor |

## Conventions

- Python 3.10+, `from __future__ import annotations`, type hints throughout.
- Data model and DMX code stay free of Qt so they remain unit-testable.
- Anything running on the DMX thread (`ShowEngine._render_frame`, `Show.render`)
  must not touch widgets or block.
- Inject time sources (`time_fn`, `now_fn`) rather than sleeping in tests.
- Docstrings explain *why* (the failure mode a design avoids), matching the
  existing modules.
- Prefer failing soft and logging for anything an unattended machine can hit
  (bad config, missing media, unreachable server).

## Extending

| Task | Where |
| --- | --- |
| New trigger source | Subclass `TriggerSource` (`triggers/base.py`), call `self.fire(show, detail)`, register in `TriggerManager.build_default_sources`, add a label in `ui/trigger_panel.py` |
| New DMX transport | See [dmx-output.md](dmx-output.md#adding-a-transport) |
| New show-file field | `timeline.py` `to_dict`/`from_dict`, update [show-file-format.md](show-file-format.md) (the code is normative) and bump `version` if incompatible |
| Config option | Add to the relevant dataclass in `config.py` (`from_dict` with a default), update [configuration.md](configuration.md) and `config.example.json` |
| Honour `media.start_ms` | `ShowEngine.load_show`/`play`/`seek` and the clock anchor |

## Release / packaging notes

- Version lives in `src/aion_show_system/__init__.py` and `pyproject.toml`
  (keep both in sync, currently `0.1.0`).
- Entry points: GUI script `aion-show-system`, console script
  `aion-show-system-cli`, both → `aion_show_system.__main__:main`.
- `media/` (large audio) and `*.wav/*.mp3/*.flac` are git-ignored.
