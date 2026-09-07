"""End-to-end wiring: media reports feed the clock, the clock renders DMX."""

from aion_show_system.dmx import NullOutput
from aion_show_system.show import MediaCue, Show, ShowClock, ShowEngine
from aion_show_system.show.demo import build_demo_show

from .test_clock import FakeTime


def make_engine(app, show=None):
    fake = FakeTime()
    engine = ShowEngine(clock=ShowClock(time_fn=fake))
    engine.load_show(show or build_demo_show(duration_ms=10_000))
    return engine, fake


def test_engine_renders_from_the_clock_not_the_player(app):
    engine, fake = make_engine(app)
    engine.clock.start()
    fake.advance_ms(5000)

    frame = engine._render_frame()
    assert frame[1][15] == 255  # swell peaks halfway through the demo show


def test_media_position_syncs_the_clock(app):
    engine, fake = make_engine(app)
    engine.clock.start()

    # The first report after start is authoritative: the show snaps to it.
    fake.advance_ms(100)
    engine._on_media_position(40)
    assert engine.position_ms == 40.0

    # Later reports slew instead, so the timeline never jumps mid-show.
    fake.advance_ms(1000)
    engine._on_media_position(1070)
    assert engine.clock.rate > 1.0
    assert engine.position_ms == 1040.0


def test_engine_with_no_show_renders_nothing(app):
    engine = ShowEngine()
    assert engine._render_frame() == {}


def test_stop_blacks_out_the_rig(app):
    engine, _ = make_engine(app)
    output = NullOutput()
    engine.add_output(output)
    engine.clock.start()
    engine.sender.send_once()
    engine.stop()
    assert output.frames[1] == bytes(512)


def test_load_show_reports_missing_media(app, tmp_path):
    engine = ShowEngine()
    errors = []
    engine.player.error_occurred.connect(errors.append)
    show = Show(name="Broken", media=MediaCue(path=str(tmp_path / "gone.wav")))
    engine.load_show(show)
    assert errors and "not found" in errors[0]
