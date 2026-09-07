"""Show playback: looping, finishing, and what the UI says about it."""

from aion_show_system.media import PlaybackState
from aion_show_system.show import MediaCue, Show, ShowClock, ShowEngine
from aion_show_system.show.demo import build_demo_show
from aion_show_system.ui.main_window import MainWindow

from .test_clock import FakeTime


def make_engine(duration_ms=10_000, **fields):
    fake = FakeTime()
    engine = ShowEngine(clock=ShowClock(time_fn=fake))
    show = build_demo_show(duration_ms=duration_ms)
    for key, value in fields.items():
        setattr(show, key, value)
    engine.load_show(show)
    return engine, fake, show


# -- looping ---------------------------------------------------------------
def test_a_looping_show_wraps_instead_of_finishing(app):
    engine, fake, show = make_engine(loop=True)
    finished, looped = [], []
    engine.show_finished.connect(finished.append)
    engine.looped.connect(looped.append)

    engine.play()
    fake.advance_ms(10_500)  # past the end
    engine._check_completion()

    assert looped == [show]
    assert finished == []
    assert engine.position_ms < 100  # back at the top
    assert engine.clock.running  # and still going
    engine.stop()


def test_a_non_looping_show_finishes_at_its_duration(app):
    engine, fake, show = make_engine(loop=False)
    finished = []
    engine.show_finished.connect(finished.append)

    engine.play()
    fake.advance_ms(5000)
    engine._check_completion()
    assert finished == []  # only halfway

    fake.advance_ms(5500)
    engine._check_completion()
    assert finished == [show]
    assert not engine.clock.running


def test_a_show_finishes_only_once(app):
    """The chain must not fire twice off one ending."""
    engine, fake, show = make_engine()
    finished = []
    engine.show_finished.connect(finished.append)

    engine.play()
    fake.advance_ms(11_000)
    engine._check_completion()
    engine._check_completion()
    engine._complete()

    assert finished == [show]


def test_looping_is_handed_to_the_media_backend_when_there_is_media(app, tmp_path):
    """A media-backed loop wraps in Qt, so the seam stays gapless."""
    media = tmp_path / "cue.wav"
    media.write_bytes(b"RIFF")  # not decodable, but loading only resolves the path
    engine = ShowEngine()
    show = Show(name="Looper", loop=True, media=MediaCue(path=str(media)))
    engine.load_show(show)
    assert engine.player.looping

    engine.set_loop(False)
    assert not engine.player.looping
    assert show.loop is False


def test_set_loop_on_a_running_timeline_show(app):
    engine, fake, show = make_engine(loop=False)
    engine.play()
    engine.set_loop(True)
    fake.advance_ms(10_500)
    engine._check_completion()
    assert engine.clock.running  # wrapped rather than stopped
    engine.stop()


def test_a_show_with_no_duration_never_completes_on_its_own(app):
    """Nothing to end against: an empty show must not spin the finish signal."""
    engine = ShowEngine(clock=ShowClock(time_fn=FakeTime()))
    engine.load_show(Show(name="Empty"))
    finished = []
    engine.show_finished.connect(finished.append)
    engine.play()
    engine._check_completion()
    assert finished == []
    engine.stop()


# -- duration and state ----------------------------------------------------
def test_engine_duration_comes_from_the_show(app):
    engine, _, _ = make_engine(duration_ms=7500)
    assert engine.duration_ms == 7500


def test_engine_reports_playing_for_a_timeline_only_show(app):
    engine, _, _ = make_engine()
    assert engine.state is PlaybackState.STOPPED
    engine.play()
    assert engine.is_playing
    engine.pause()
    assert not engine.is_playing
    engine.stop()
    assert engine.state is PlaybackState.STOPPED


# -- the window ------------------------------------------------------------
def make_window():
    return MainWindow(start_triggers=False)


def test_the_window_says_when_no_show_is_loaded(app):
    window = make_window()
    assert window.show_label.text() == "No show loaded"
    assert not window.play_button.isEnabled()
    assert not window.stop_button.isEnabled()


def test_the_window_names_the_loaded_show(app):
    window = make_window()
    show = build_demo_show(duration_ms=20_000)
    show.name = "Act One"
    window.engine.load_show(show)

    assert "Act One" in window.show_label.text()
    assert window.play_button.isEnabled()
    assert window.stop_button.isEnabled()


def test_the_progress_bar_spans_the_show(app):
    window = make_window()
    window.engine.load_show(build_demo_show(duration_ms=45_000))
    assert window.position_slider.maximum() == 45_000


def test_the_window_shows_a_shows_loop_and_override_flags(app):
    window = make_window()
    show = build_demo_show(duration_ms=1000)
    show.name = "Nightly"
    show.loop = True
    show.allow_override = False
    show.next_show = "Closing"
    window.engine.load_show(show)

    text = window.show_label.text()
    assert "looping" in text
    assert "not overridable" in text
    assert "Closing" in text
    assert window.loop_check.isChecked()


def test_the_loop_checkbox_drives_the_show(app):
    window = make_window()
    show = build_demo_show(duration_ms=1000)
    window.engine.load_show(show)
    assert not window.loop_check.isChecked()

    window.loop_check.setChecked(True)
    assert show.loop is True
    window.loop_check.setChecked(False)
    assert show.loop is False


def test_loading_a_show_does_not_echo_the_checkbox_back_into_the_engine(app):
    """Reflecting a file's loop flag must not count as an operator toggling it."""
    window = make_window()
    show = build_demo_show(duration_ms=1000)
    show.loop = True
    window.engine.load_show(show)
    assert show.loop is True  # unchanged by the UI round trip


def test_the_window_reports_a_finished_show(app):
    window = make_window()
    show = build_demo_show(duration_ms=1000)
    show.name = "Act One"
    window.engine.load_show(show)
    window.engine.show_finished.emit(show)
    assert "finished" in window.statusBar().currentMessage()


def test_stop_button_stops_the_engine(app):
    window = make_window()
    window.engine.load_show(build_demo_show(duration_ms=5000))
    window.engine.play()
    window.stop_playback()
    assert not window.engine.is_playing


# -- the window against a config file --------------------------------------
def test_the_window_takes_its_dmx_settings_from_the_config(app):
    from aion_show_system.config import AppConfig, DmxConfig
    from aion_show_system.ui.dmx_panel import ART_NET

    config = AppConfig(dmx=DmxConfig(protocol="artnet", host="10.0.0.20", universe=5))
    window = MainWindow(config=config, start_triggers=False)

    assert window.dmx_panel.protocol_combo.currentText() == ART_NET
    assert window.dmx_panel.host_edit.text() == "10.0.0.20"
    assert window.dmx_panel.universe_spin.value() == 5
    assert window.dmx_panel.live  # a configured protocol goes live unprompted
    window.close()


def test_a_dry_run_config_does_not_open_an_output(app):
    window = make_window()  # default config: no protocol
    assert not window.dmx_panel.live


def test_the_window_resolves_triggers_against_the_configured_shows_dir(app, tmp_path):
    from aion_show_system.config import AppConfig

    shows = tmp_path / "shows"
    shows.mkdir()
    show = build_demo_show(duration_ms=1000)
    show.name = "Nightly"
    show.save(shows / "Nightly.show.json")

    window = MainWindow(config=AppConfig(shows_dir=str(shows)), start_triggers=False)
    assert window.library.find("Nightly") is not None

    from aion_show_system.triggers import TriggerEvent

    assert window.triggers.handle(TriggerEvent(show="Nightly", source="test"))
    assert window.engine.show.name == "Nightly"
    assert "Nightly" in window.trigger_panel.last_label.text()
    window.engine.stop()
