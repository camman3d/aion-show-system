import pytest

from aion_show_system.show import DmxKeyframe, DmxTrack, MediaCue, Show
from aion_show_system.show.demo import build_demo_show


def test_keyframe_rejects_out_of_range_channel():
    with pytest.raises(ValueError):
        DmxKeyframe(0, {513: 255})
    with pytest.raises(ValueError):
        DmxKeyframe(0, {0: 255})


def test_keyframe_clamps_levels():
    keyframe = DmxKeyframe(0, {1: 300, 2: -20})
    assert keyframe.values == {1: 255, 2: 0}


def test_track_sorts_keyframes():
    track = DmxTrack(keyframes=[DmxKeyframe(500, {1: 255}), DmxKeyframe(0, {1: 0})])
    assert [kf.time_ms for kf in track.keyframes] == [0, 500]


def test_levels_interpolate_between_keyframes():
    track = DmxTrack(keyframes=[DmxKeyframe(0, {1: 0}), DmxKeyframe(1000, {1: 200})])
    assert track.levels_at(0) == {1: 0}
    assert track.levels_at(500) == {1: 100}
    assert track.levels_at(1000) == {1: 200}


def test_levels_hold_after_last_keyframe():
    track = DmxTrack(keyframes=[DmxKeyframe(0, {1: 128})])
    assert track.levels_at(99_999) == {1: 128}


def test_levels_before_first_keyframe_are_dark():
    track = DmxTrack(keyframes=[DmxKeyframe(1000, {1: 255})])
    assert track.levels_at(0) == {}


def test_untouched_channels_hold_their_value():
    track = DmxTrack(
        keyframes=[
            DmxKeyframe(0, {1: 255, 2: 100}),
            DmxKeyframe(1000, {1: 0}),  # channel 2 untouched
        ]
    )
    levels = track.levels_at(500)
    assert levels[1] == 128  # fading down
    assert levels[2] == 100  # held


def test_render_produces_512_byte_frames():
    show = Show(tracks=[DmxTrack(universe=3, keyframes=[DmxKeyframe(0, {1: 255, 512: 10})])])
    frames = show.render(0)
    assert set(frames) == {3}
    assert len(frames[3]) == 512
    assert frames[3][0] == 255
    assert frames[3][511] == 10


def test_tracks_merge_highest_takes_precedence():
    show = Show(
        tracks=[
            DmxTrack(name="a", keyframes=[DmxKeyframe(0, {1: 100})]),
            DmxTrack(name="b", keyframes=[DmxKeyframe(0, {1: 200})]),
        ]
    )
    assert show.render(0)[1][0] == 200


def test_tracks_default_to_universe_one():
    """Universe 0 is valid Art-Net but illegal sACN, so it is not the default."""
    assert DmxTrack().universe == 1


def test_show_round_trips_through_json(tmp_path):
    show = Show(
        name="Act One",
        media=MediaCue(path="music.wav", start_ms=250),
        tracks=[DmxTrack(name="Wash", universe=2, keyframes=[DmxKeyframe(1500, {5: 77})])],
        duration_ms=60_000,
    )
    path = show.save(tmp_path / "act.show.json")
    loaded = Show.load(path)

    assert loaded.name == "Act One"
    assert loaded.media.path == "music.wav"
    assert loaded.media.start_ms == 250
    assert loaded.duration_ms == 60_000
    assert loaded.tracks[0].universe == 2
    assert loaded.tracks[0].keyframes[0].values == {5: 77}
    assert loaded.render(1500) == show.render(1500)


def test_effective_duration_falls_back_to_last_keyframe():
    show = Show(tracks=[DmxTrack(keyframes=[DmxKeyframe(4200, {1: 1})])])
    assert show.effective_duration_ms == 4200


def test_demo_show_renders_across_its_duration():
    show = build_demo_show(duration_ms=10_000)
    assert show.universes == [1]
    assert show.effective_duration_ms == 10_000
    # The swell must actually be mid-fade halfway through.
    assert show.render(5000)[1][15] == 255
    assert show.render(0)[1][15] == 0
