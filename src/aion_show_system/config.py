"""The application config file: DMX output, WebSocket server, poll URL and clock triggers.

One JSON file, read once at startup from :func:`default_config_path`. Every
section is optional and every field has a working default, so a missing file is
a valid configuration - it simply means "no network DMX, no WebSocket, no clock
triggers", which is exactly what a machine being set up for the first time
should do.

```json
{
  "shows_dir": "D:/shows",
  "dmx": { "protocol": "artnet", "host": "10.0.0.20", "universe": 1 },
  "websocket": { "host": "10.0.0.5", "port": 8765, "path": "/shows" },
  "poll": { "url": "http://10.0.0.5/cue.json", "interval_seconds": 5 },
  "clock_triggers": [
    { "time": "10:00 PM", "show": "Nightly", "days": ["fri", "sat"] }
  ]
}
```
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from datetime import time as clock_time
from pathlib import Path
from typing import Any

from .dmx import ArtNetOutput, DmxOutput, NullOutput, SacnOutput
from .paths import config_dir

log = logging.getLogger(__name__)

CONFIG_FILENAME = "config.json"

ARTNET = "artnet"
SACN = "sacn"
NO_PROTOCOL = "none"

# "10:00 PM" is what the requirements write and "22:00" is what a config file
# usually holds; both are unambiguous, so accept either.
_TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p")

_DAY_NUMBERS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "weds": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

_PROTOCOL_ALIASES = {
    "art-net": ARTNET, "artnet": ARTNET, "art_net": ARTNET,
    "sacn": SACN, "e1.31": SACN, "e131": SACN,
    "none": NO_PROTOCOL, "null": NO_PROTOCOL, "dry": NO_PROTOCOL, "": NO_PROTOCOL,
}


def default_config_path() -> Path:
    """Where the config file lives on this platform."""
    return config_dir() / CONFIG_FILENAME


def parse_clock_time(text: str) -> clock_time:
    """Parse ``"22:00"`` or ``"10:00 PM"`` into a :class:`datetime.time`."""
    cleaned = " ".join(str(text).strip().upper().split())
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised clock time {text!r}; use '22:00' or '10:00 PM'")


def parse_days(days: Any) -> frozenset[int]:
    """Weekday names to Python weekday numbers; empty means every day."""
    if not days:
        return frozenset()
    if isinstance(days, str):
        days = [days]
    numbers = set()
    for day in days:
        key = str(day).strip().lower()
        if key not in _DAY_NUMBERS:
            raise ValueError(f"Unrecognised day {day!r}")
        numbers.add(_DAY_NUMBERS[key])
    return frozenset(numbers)


@dataclass(frozen=True)
class ClockTrigger:
    """Start a show at a wall-clock time, optionally only on certain days."""

    at: clock_time
    show: str
    days: frozenset[int] = frozenset()
    name: str = ""

    @property
    def label(self) -> str:
        return self.name or f"{self.at.strftime('%H:%M')} {self.show}"

    def matches(self, moment: datetime) -> bool:
        """True when ``moment`` falls in this trigger's minute, on a live day.

        Matching is per-minute rather than per-second: the poll runs at 1 Hz and
        the trigger must still fire if a tick lands a few hundred ms late.
        """
        if self.days and moment.weekday() not in self.days:
            return False
        return (moment.hour, moment.minute) == (self.at.hour, self.at.minute)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClockTrigger:
        show = str(data.get("show") or "").strip()
        if not show:
            raise ValueError("A clock trigger needs a 'show'")
        return cls(
            at=parse_clock_time(data["time"]),
            show=show,
            days=parse_days(data.get("days")),
            name=str(data.get("name", "")),
        )


@dataclass(frozen=True)
class DmxConfig:
    """Where DMX frames go. ``protocol: "none"`` is a dry run."""

    protocol: str = NO_PROTOCOL
    host: str | None = None
    port: int = 6454
    universe: int = 1
    fps: float = 40.0
    # None means "go live iff a real protocol is configured", which is what a
    # show machine wants without having to say so.
    auto_start: bool | None = None

    @property
    def enabled(self) -> bool:
        """Whether to open the output at startup rather than waiting for a click."""
        if self.auto_start is None:
            return self.protocol in (ARTNET, SACN)
        return bool(self.auto_start)

    def create_output(self) -> DmxOutput:
        """Build the configured transport. Raises on an unusable address."""
        if self.protocol == ARTNET:
            return ArtNetOutput(
                self.host or "255.255.255.255", port=self.port, universe=self.universe
            )
        if self.protocol == SACN:
            # Blank host means multicast, the sACN default and usually right.
            return SacnOutput(self.host or None)
        return NullOutput()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DmxConfig:
        raw = str(data.get("protocol", NO_PROTOCOL)).strip().lower()
        protocol = _PROTOCOL_ALIASES.get(raw, raw)
        if protocol not in (ARTNET, SACN, NO_PROTOCOL):
            raise ValueError(f"Unknown DMX protocol {raw!r}")
        host = data.get("host")
        return cls(
            protocol=protocol,
            host=str(host).strip() if host else None,
            port=int(data.get("port", 6454)),
            universe=int(data.get("universe", 1)),
            fps=float(data.get("fps", 40.0)),
            auto_start=None if data.get("auto_start") is None else bool(data["auto_start"]),
        )


@dataclass(frozen=True)
class WebSocketConfig:
    """The single WebSocket server the whole show system listens to.

    Host and port are both required to connect. Either one missing - or the
    whole section absent - means this machine does not connect at all, which is
    the documented behaviour, not an error.
    """

    host: str | None = None
    port: int | None = None
    path: str = "/"
    secure: bool = False
    reconnect_seconds: float = 5.0

    @property
    def enabled(self) -> bool:
        return bool(self.host) and self.port is not None

    @property
    def url(self) -> str:
        scheme = "wss" if self.secure else "ws"
        path = self.path if self.path.startswith("/") else f"/{self.path}"
        return f"{scheme}://{self.host}:{self.port}{path}"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebSocketConfig:
        host = data.get("host")
        port = data.get("port")
        return cls(
            host=str(host).strip() if host else None,
            port=int(port) if port not in (None, "") else None,
            path=str(data.get("path", "/")) or "/",
            secure=bool(data.get("secure", False)),
            reconnect_seconds=float(data.get("reconnect_seconds", 5.0)),
        )


@dataclass(frozen=True)
class PollConfig:
    """A URL polled for cues. Without a ``url`` the poller is off."""

    url: str | None = None
    interval_seconds: float = 5.0
    timeout_seconds: float = 5.0

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PollConfig:
        url = data.get("url")
        return cls(
            url=str(url).strip() if url else None,
            interval_seconds=float(data.get("interval_seconds", 5.0)),
            timeout_seconds=float(data.get("timeout_seconds", 5.0)),
        )


@dataclass(frozen=True)
class AppConfig:
    """Everything the config file can say."""

    dmx: DmxConfig = field(default_factory=DmxConfig)
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    poll: PollConfig = field(default_factory=PollConfig)
    clock_triggers: tuple[ClockTrigger, ...] = ()
    shows_dir: str | None = None
    path: Path | None = None

    @property
    def shows_path(self) -> Path:
        """Directory that triggers resolve show names against."""
        if self.shows_dir:
            return Path(self.shows_dir).expanduser()
        return config_dir() / "shows"

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> AppConfig:
        triggers = []
        for entry in data.get("clock_triggers") or []:
            try:
                triggers.append(ClockTrigger.from_dict(entry))
            except (ValueError, KeyError, TypeError) as error:
                log.error("Ignoring clock trigger %r: %s", entry, error)
        return cls(
            dmx=DmxConfig.from_dict(data.get("dmx") or {}),
            websocket=WebSocketConfig.from_dict(data.get("websocket") or {}),
            poll=PollConfig.from_dict(data.get("poll") or {}),
            clock_triggers=tuple(triggers),
            shows_dir=data.get("shows_dir") or None,
            path=path,
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> AppConfig:
        """Read the config file, falling back to defaults if it is absent.

        A malformed file is logged and treated as absent: a show machine that
        boots unattended must still come up and play, just without the parts it
        could not read.
        """
        target = Path(path).expanduser() if path else default_config_path()
        if not target.is_file():
            log.info("No config file at %s; using defaults", target)
            return cls(path=target)
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log.error("Could not read config %s: %s", target, error)
            return cls(path=target)
        if not isinstance(data, dict):
            log.error("Config %s is not a JSON object; ignoring it", target)
            return cls(path=target)
        log.info("Loaded config from %s", target)
        return cls.from_dict(data, path=target)
