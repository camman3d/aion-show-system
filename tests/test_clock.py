"""The clock is the piece the whole show hangs off, so it is tested hardest."""

import pytest

from aion_show_system.show import ShowClock


class FakeTime:
    """A controllable monotonic source, in seconds.

    Time is accumulated in milliseconds so repeated small steps do not drift in
    binary floating point and turn an exact assertion into a flaky one.
    """

    def __init__(self) -> None:
        self.elapsed_ms = 0.0

    def __call__(self) -> float:
        return 1000.0 + self.elapsed_ms / 1000.0

    def advance_ms(self, milliseconds: float) -> None:
        self.elapsed_ms += milliseconds


def make_clock(**kwargs) -> tuple[ShowClock, FakeTime]:
    fake = FakeTime()
    return ShowClock(time_fn=fake, **kwargs), fake


def running_clock(**kwargs) -> tuple[ShowClock, FakeTime]:
    """A clock that is started and has already taken its first media report.

    The first sync after start() deliberately hard-anchors, so tests about
    slewing have to get past it first.
    """
    clock, fake = make_clock(**kwargs)
    clock.start()
    clock.sync(0.0)
    return clock, fake


def test_stopped_clock_does_not_advance():
    clock, fake = make_clock()
    fake.advance_ms(500)
    assert clock.position_ms() == 0.0


def test_interpolates_between_media_reports():
    """The whole point: sub-93 ms resolution the media player cannot give."""
    clock, fake = make_clock()
    clock.start()
    fake.advance_ms(25)
    assert clock.position_ms() == pytest.approx(25.0)
    fake.advance_ms(1)
    assert clock.position_ms() == pytest.approx(26.0)


def test_pause_freezes_and_resume_continues():
    clock, fake = make_clock()
    clock.start()
    fake.advance_ms(400)
    clock.pause()
    fake.advance_ms(5000)
    assert clock.position_ms() == pytest.approx(400.0)
    clock.start()
    fake.advance_ms(100)
    assert clock.position_ms() == pytest.approx(500.0)


def test_small_error_slews_instead_of_jumping():
    clock, fake = running_clock(slew_window_ms=1000.0, max_slew=0.05)
    fake.advance_ms(1000)  # clock believes 1000
    error = clock.sync(1040)  # media says 1040: 40 ms ahead

    assert error == 40.0
    # No jump: position stays where the timeline already was.
    assert clock.position_ms() == pytest.approx(1000.0)
    # Rate nudged up to close the gap over the slew window.
    assert clock.rate == pytest.approx(1.04)

    fake.advance_ms(1000)
    assert clock.position_ms() == pytest.approx(2040.0)  # gap absorbed, no discontinuity


def test_slew_is_capped():
    clock, fake = running_clock(slew_window_ms=100.0, max_slew=0.05, hard_resync_ms=1000.0)
    fake.advance_ms(1000)
    clock.sync(1200)  # a 200 ms error over a 100 ms window would be rate 3.0
    assert clock.rate == pytest.approx(1.05)


def test_timeline_never_runs_backwards_when_media_lags():
    """A media report behind the clock must not rewind cues already fired."""
    clock, fake = running_clock()
    fake.advance_ms(1000)
    before = clock.position_ms()
    clock.sync(960)  # media reports 40 ms behind
    assert clock.position_ms() == before
    assert clock.rate < 1.0  # slowing down to let media catch up

    fake.advance_ms(10)
    assert clock.position_ms() > before  # still monotonic


def test_large_error_hard_resyncs():
    clock, fake = running_clock(hard_resync_ms=250.0)
    fake.advance_ms(1000)
    error = clock.sync(5000)  # a seek
    assert error == 4000.0
    assert clock.position_ms() == pytest.approx(5000.0)
    assert clock.rate == 1.0


def test_seek_and_stop():
    clock, fake = make_clock()
    clock.start()
    fake.advance_ms(1000)
    clock.seek(250)
    assert clock.position_ms() == pytest.approx(250.0)
    fake.advance_ms(100)
    assert clock.position_ms() == pytest.approx(350.0)  # seek keeps it running
    clock.stop()
    assert clock.position_ms() == 0.0
    assert not clock.running


def test_sync_while_stopped_anchors_without_running():
    clock, _ = make_clock()
    assert clock.sync(700) == 0.0
    assert clock.position_ms() == pytest.approx(700.0)
    assert not clock.running


def test_real_time_source_advances():
    """Guards against the default time source being wired up wrong."""
    import time

    clock = ShowClock()
    clock.start()
    time.sleep(0.05)
    assert 25.0 < clock.position_ms() < 200.0


def test_first_sync_after_start_anchors_hard():
    """A transport's position at start is already stale; do not slew it off."""
    clock, fake = make_clock()
    clock.start(at_ms=0)
    fake.advance_ms(100)
    clock.sync(35)  # the true position was behind what we assumed

    assert clock.position_ms() == pytest.approx(35.0)  # jumped, not slewed
    assert clock.rate == 1.0


def test_first_sync_after_seek_anchors_hard():
    clock, fake = running_clock()
    fake.advance_ms(1000)
    clock.seek(4000)
    fake.advance_ms(50)
    clock.sync(4010)  # the decoder landed slightly past the requested point

    assert clock.position_ms() == pytest.approx(4010.0)
    assert clock.rate == 1.0
