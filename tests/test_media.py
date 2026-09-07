import pytest

from aion_show_system.media import MediaPlayer, PlaybackState, list_output_devices


def test_new_player_is_stopped_and_empty(app):
    player = MediaPlayer()
    assert player.state is PlaybackState.STOPPED
    assert player.source is None


def test_volume_is_clamped(app):
    player = MediaPlayer()
    player.volume = 2.5
    assert player.volume == pytest.approx(1.0)
    player.volume = -1.0
    assert player.volume == pytest.approx(0.0)


def test_load_missing_file_raises(app, tmp_path):
    player = MediaPlayer()
    with pytest.raises(FileNotFoundError):
        player.load(tmp_path / "nope.wav")


def test_load_sets_source(app, tmp_path):
    path = tmp_path / "cue.wav"
    path.write_bytes(b"RIFF")  # not decodable, but load() only resolves the path
    player = MediaPlayer()
    player.load(path)
    assert player.source == path.resolve()


def test_output_devices_are_enumerable(app):
    for device in list_output_devices():
        assert device.name


def test_new_player_has_no_video(app):
    assert MediaPlayer().has_video is False


def test_set_video_output_accepts_none(app):
    MediaPlayer().set_video_output(None)  # detaching must not raise
