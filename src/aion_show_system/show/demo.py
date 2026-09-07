"""A generated show, used to prove out the timeline and a real DMX rig.

This is a stand-in for the cue editor: it produces a real :class:`Show` with
real keyframes, so sync, fades and output can be exercised end to end before
any authoring UI exists.
"""

from __future__ import annotations

from .timeline import DmxKeyframe, DmxTrack, MediaCue, Show


def build_chase(
    duration_ms: int,
    channels: int = 8,
    step_ms: int = 500,
    universe: int = 1,
    name: str = "Chase",
) -> DmxTrack:
    """A looping chase: each channel fades up, then down, in turn."""
    track = DmxTrack(name=name, universe=universe)
    step = 0
    while step * step_ms < duration_ms:
        time_ms = step * step_ms
        channel = step % channels + 1
        previous = (step - 1) % channels + 1
        track.add(DmxKeyframe(time_ms, {channel: 255, previous: 0}))
        step += 1
    if track.keyframes:
        track.add(DmxKeyframe(duration_ms, dict.fromkeys(range(1, channels + 1), 0)))
    return track


def build_swell(
    duration_ms: int,
    channel: int = 16,
    universe: int = 1,
    name: str = "Swell",
) -> DmxTrack:
    """A single slow up-and-down fade across the whole show, for drift checks.

    Because it is one long interpolation, any stutter in the timeline clock is
    visible on the rig as a step in the level.
    """
    return DmxTrack(
        name=name,
        universe=universe,
        keyframes=[
            DmxKeyframe(0, {channel: 0}),
            DmxKeyframe(duration_ms // 2, {channel: 255}),
            DmxKeyframe(duration_ms, {channel: 0}),
        ],
    )


def build_demo_show(
    duration_ms: int = 30_000,
    media_path: str | None = None,
    universe: int = 1,
) -> Show:
    """A complete demo show: a chase plus a swell, optionally against media."""
    duration_ms = max(1000, int(duration_ms))
    return Show(
        name="Demo Sequence",
        media=MediaCue(path=media_path) if media_path else None,
        tracks=[
            build_chase(duration_ms, universe=universe),
            build_swell(duration_ms, universe=universe),
        ],
        duration_ms=duration_ms,
    )
