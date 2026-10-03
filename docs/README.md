# AION Show System — Documentation

Automated show playback for DMX lighting: plays audio/video, drives DMX over
Art-Net or sACN in sync, and is cued by a schedule, WebSocket, command line or
a chained show.

| Document | Read it to… |
| --- | --- |
| [user-guide.md](user-guide.md) | Install, run, operate the UI, workflows and troubleshooting |
| [configuration.md](configuration.md) | Every `config.json` option and command-line argument |
| [show-file-format.md](show-file-format.md) | Write or generate show files (normative spec, for authoring tools) |
| [triggers.md](triggers.md) | Clock, WebSocket, CLI and chained triggers; override policy; wire formats |
| [dmx-output.md](dmx-output.md) | Art-Net / sACN output, sender thread, adding transports |
| [architecture.md](architecture.md) | Module map, threading, clock sync, engine design, known gaps |
| [development.md](development.md) | Tests, lint, conventions, extension points |
| [project-status-report.md](project-status-report.md) | Project status |

Source of truth: where a document and the code disagree, the code is right —
especially `src/aion_show_system/show/timeline.py` for the show format.
