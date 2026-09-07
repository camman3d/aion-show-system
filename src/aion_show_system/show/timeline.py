"""The cue data model: a show is media plus time-indexed DMX tracks.

Everything here is plain data with no Qt dependency, so it can be built,
rendered and tested without a GUI, a display or a lighting rig.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DMX_UNIVERSE_SIZE = 512
MIN_CHANNEL = 1
MAX_CHANNEL = DMX_UNIVERSE_SIZE


def _clamp_level(value: int) -> int:
    return max(0, min(255, int(round(value))))


@dataclass(frozen=True)
class DmxKeyframe:
    """Target levels for a set of channels at a point in the show.

    Channels are 1-based, as they are on every console and fixture manual.
    Levels between keyframes are interpolated, so a pair of keyframes is a fade
    and two keyframes at the same time is a snap.
    """

    time_ms: int
    values: dict[int, int]

    def __post_init__(self) -> None:
        for channel in self.values:
            if not MIN_CHANNEL <= channel <= MAX_CHANNEL:
                raise ValueError(f"DMX channel {channel} out of range 1-{MAX_CHANNEL}")
        object.__setattr__(self, "time_ms", int(self.time_ms))
        object.__setattr__(
            self, "values", {int(c): _clamp_level(v) for c, v in self.values.items()}
        )

    def to_dict(self) -> dict[str, Any]:
        return {"time_ms": self.time_ms, "values": {str(c): v for c, v in self.values.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DmxKeyframe:
        return cls(
            time_ms=int(data["time_ms"]),
            values={int(c): int(v) for c, v in data.get("values", {}).items()},
        )


@dataclass
class DmxTrack:
    """An ordered sequence of keyframes rendering into one universe."""

    name: str = "Track"
    # Universe 1, not 0: Art-Net allows 0 but sACN universes start at 1, so
    # defaulting to 1 keeps a show valid on either protocol.
    universe: int = 1
    keyframes: list[DmxKeyframe] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.keyframes = sorted(self.keyframes, key=lambda kf: kf.time_ms)

    @property
    def duration_ms(self) -> int:
        return self.keyframes[-1].time_ms if self.keyframes else 0

    def add(self, keyframe: DmxKeyframe) -> None:
        """Insert a keyframe, keeping the track ordered."""
        self.keyframes.append(keyframe)
        self.keyframes.sort(key=lambda kf: kf.time_ms)

    def levels_at(self, time_ms: float) -> dict[int, int]:
        """Interpolated channel levels at ``time_ms``.

        Channels hold their last set value until another keyframe touches them,
        and fade linearly toward the next keyframe that names them. Before the
        first keyframe the track is dark; after the last it holds.
        """
        state: dict[int, int] = {}
        index = 0
        previous: DmxKeyframe | None = None
        for keyframe in self.keyframes:
            if keyframe.time_ms > time_ms:
                break
            state.update(keyframe.values)
            previous = keyframe
            index += 1

        following = self.keyframes[index] if index < len(self.keyframes) else None
        if following is None or previous is None:
            return state

        span = following.time_ms - previous.time_ms
        if span <= 0:
            return state

        fraction = (time_ms - previous.time_ms) / span
        levels = dict(state)
        for channel, target in following.values.items():
            start = state.get(channel, 0)
            levels[channel] = _clamp_level(start + (target - start) * fraction)
        return levels

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "universe": self.universe,
            "keyframes": [kf.to_dict() for kf in self.keyframes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DmxTrack:
        return cls(
            name=data.get("name", "Track"),
            universe=int(data.get("universe", 1)),
            keyframes=[DmxKeyframe.from_dict(kf) for kf in data.get("keyframes", [])],
        )


@dataclass
class MediaCue:
    """The audio or video file the show runs against."""

    path: str
    start_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "start_ms": self.start_ms}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MediaCue:
        return cls(path=str(data["path"]), start_ms=int(data.get("start_ms", 0)))


@dataclass
class Show:
    """A media cue plus the DMX tracks synchronised to it.

    Three fields shape how a show behaves in an unattended running system:

    ``loop``
        Restart from the top instead of finishing.
    ``allow_override``
        Whether a trigger arriving mid-show may replace this one. A show that
        must not be interrupted - a scheduled announcement, say - sets this
        false and triggers are refused until it finishes.
    ``next_show``
        The show to trigger when this one completes, which is how a sequence of
        shows is chained without anything outside the show files knowing about it.
    """

    name: str = "Untitled Show"
    media: MediaCue | None = None
    tracks: list[DmxTrack] = field(default_factory=list)
    duration_ms: int = 0
    loop: bool = False
    allow_override: bool = True
    next_show: str | None = None

    @property
    def universes(self) -> list[int]:
        return sorted({track.universe for track in self.tracks})

    @property
    def effective_duration_ms(self) -> int:
        """Explicit duration if set, otherwise the last keyframe in any track."""
        if self.duration_ms:
            return self.duration_ms
        return max((track.duration_ms for track in self.tracks), default=0)

    def render(self, time_ms: float) -> dict[int, bytes]:
        """Flatten every track into one 512-byte frame per universe.

        Tracks sharing a universe are merged highest-takes-precedence, the
        convention every lighting desk uses for stacked playbacks.
        """
        frames = {universe: bytearray(DMX_UNIVERSE_SIZE) for universe in self.universes}
        for track in self.tracks:
            frame = frames[track.universe]
            for channel, level in track.levels_at(time_ms).items():
                index = channel - 1
                if level > frame[index]:
                    frame[index] = level
        return {universe: bytes(frame) for universe, frame in frames.items()}

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "name": self.name,
            "media": self.media.to_dict() if self.media else None,
            "duration_ms": self.duration_ms,
            "loop": self.loop,
            "allow_override": self.allow_override,
            "next_show": self.next_show,
            "tracks": [track.to_dict() for track in self.tracks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Show:
        media = data.get("media")
        next_show = data.get("next_show") or None
        return cls(
            name=data.get("name", "Untitled Show"),
            media=MediaCue.from_dict(media) if media else None,
            tracks=[DmxTrack.from_dict(t) for t in data.get("tracks", [])],
            duration_ms=int(data.get("duration_ms", 0)),
            loop=bool(data.get("loop", False)),
            # Default true: a show that says nothing is interruptible, so
            # triggers keep working on show files written before this existed.
            allow_override=bool(data.get("allow_override", True)),
            next_show=str(next_show) if next_show else None,
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> Show:
        return cls.from_dict(json.loads(Path(path).expanduser().read_text(encoding="utf-8")))
