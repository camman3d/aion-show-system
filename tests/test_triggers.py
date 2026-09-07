"""Triggers: the four ways a show starts without anyone at the keyboard."""

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from aion_show_system.config import AppConfig, ClockTrigger, WebSocketConfig, parse_clock_time
from aion_show_system.show import Show, ShowClock, ShowEngine, ShowLibrary
from aion_show_system.show.demo import build_demo_show
from aion_show_system.triggers import (
    ClockTriggerSource,
    CommandTriggerSource,
    TriggerEvent,
    TriggerManager,
    WebSocketTriggerSource,
    send_trigger,
)
from aion_show_system.triggers.base import parse_trigger_message

from .test_clock import FakeTime


def write_show(directory, name, **fields):
    directory.mkdir(parents=True, exist_ok=True)
    show = build_demo_show(duration_ms=5000)
    show.name = name
    for key, value in fields.items():
        setattr(show, key, value)
    return show.save(directory / f"{name}.show.json")


class MovableClock:
    """A wall clock the test steps forward, for the schedule poller."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


# -- message parsing -------------------------------------------------------
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Nightly", "Nightly"),
        ("  Nightly  ", "Nightly"),
        ('{"show": "Nightly"}', "Nightly"),
        ('{"trigger": "Nightly"}', "Nightly"),
        ('{"name": "Nightly"}', "Nightly"),
        ('{"command": "trigger", "show": "Nightly"}', "Nightly"),
        ("D:/shows/Nightly.show.json", "D:/shows/Nightly.show.json"),
    ],
)
def test_trigger_messages_parse_in_both_wire_formats(message, expected):
    assert parse_trigger_message(message) == expected


@pytest.mark.parametrize(
    "message",
    ["", "   ", "{}", '{"show": ""}', "{broken json", '{"command": "blackout", "show": "X"}'],
)
def test_messages_that_name_no_show_are_rejected(message):
    assert parse_trigger_message(message) is None


# -- the library triggers resolve against ----------------------------------
def test_library_resolves_paths_names_and_stems(tmp_path):
    path = write_show(tmp_path / "shows", "Nightly")
    library = ShowLibrary([tmp_path / "shows"])

    assert library.find(str(path)) == path  # a full path
    assert library.find("Nightly") == path  # the file stem
    assert library.find("Nightly.show.json") == path  # the file name
    assert library.find("nightly") == path  # case-insensitive
    assert library.find("Missing") is None


def test_library_matches_the_name_written_inside_the_file(tmp_path):
    directory = tmp_path / "shows"
    directory.mkdir()
    show = build_demo_show(duration_ms=1000)
    show.name = "Act One"
    show.save(directory / "act-one.show.json")

    library = ShowLibrary([directory])
    assert library.find("Act One") is not None
    assert library.load("Act One").name == "Act One"


def test_library_survives_an_unreadable_show_file(tmp_path):
    directory = tmp_path / "shows"
    directory.mkdir()
    (directory / "broken.show.json").write_text("{not json", encoding="utf-8")
    assert ShowLibrary([directory]).load("broken") is None


# -- clock triggers --------------------------------------------------------
def test_clock_trigger_fires_once_when_its_minute_arrives(app):
    clock = MovableClock(datetime(2026, 9, 7, 21, 59, 30))
    source = ClockTriggerSource(
        [ClockTrigger(at=parse_clock_time("10:00 PM"), show="Nightly")], now_fn=clock
    )
    fired = []
    source.triggered.connect(fired.append)

    source.poll()
    assert fired == []  # not yet 22:00

    clock.advance(seconds=30)
    source.poll()
    assert [event.show for event in fired] == ["Nightly"]

    clock.advance(seconds=20)  # still inside the same minute
    source.poll()
    assert len(fired) == 1  # and it must not fire again


def test_clock_trigger_fires_again_the_next_day(app):
    clock = MovableClock(datetime(2026, 9, 7, 22, 0, 0))
    source = ClockTriggerSource(
        [ClockTrigger(at=parse_clock_time("22:00"), show="Nightly")], now_fn=clock
    )
    fired = []
    source.triggered.connect(fired.append)

    source.poll()
    clock.advance(days=1)
    source.poll()
    assert len(fired) == 2


def test_starting_at_the_trigger_minute_does_not_re_fire(app):
    """Relaunching the app at 22:00 must not replay the 22:00 show."""
    clock = MovableClock(datetime(2026, 9, 7, 22, 0, 10))
    source = ClockTriggerSource(
        [ClockTrigger(at=parse_clock_time("22:00"), show="Nightly")], now_fn=clock
    )
    fired = []
    source.triggered.connect(fired.append)

    source.start()
    source.poll()
    assert fired == []
    source.stop()


# -- websocket -------------------------------------------------------------
def test_websocket_does_not_connect_without_a_host_and_port(app):
    source = WebSocketTriggerSource(WebSocketConfig())
    source.start()
    assert not source.connected
    assert source.status == "not configured"


def test_websocket_message_becomes_a_trigger(app):
    source = WebSocketTriggerSource(WebSocketConfig(host="h", port=1))
    fired = []
    source.triggered.connect(fired.append)
    source._on_text_message('{"show": "Nightly"}')
    assert [(e.show, e.source) for e in fired] == [("Nightly", "websocket")]


def test_websocket_junk_is_ignored_rather_than_fired(app):
    source = WebSocketTriggerSource(WebSocketConfig(host="h", port=1))
    fired = []
    source.triggered.connect(fired.append)
    source._on_text_message("{}")
    assert fired == []


# -- command line ----------------------------------------------------------
CLIENT_SCRIPT = """
import sys
sys.path.insert(0, {src!r})
from PySide6.QtCore import QCoreApplication
from aion_show_system.triggers import send_trigger
QCoreApplication([])
accepted, reply = send_trigger({message!r}, socket_name={socket!r})
print("ACCEPTED" if accepted else "REFUSED")
print(reply)
"""


def send_trigger_from_another_process(message, socket_name, timeout=25.0):
    """Trigger the way an operator actually does: a second invocation.

    This has to be a real process. A Windows named pipe is driven by the Qt
    event dispatcher of the thread that owns the socket, and a bare Python
    thread has none - so an in-process client never gets its bytes out, while
    the shipping command line (its own process, its own ``QCoreApplication``)
    works. Testing it any other way would be testing something we do not ship.
    """
    src = str(Path(__file__).resolve().parents[1] / "src")
    script = CLIENT_SCRIPT.format(src=src, message=message, socket=socket_name)
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Pump this process's event loop: it is the show system the client dials.
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    out, err = process.communicate(timeout=10)
    lines = out.strip().splitlines()
    assert lines, f"trigger client produced no output; stderr:\n{err}"
    return lines[0] == "ACCEPTED", "\n".join(lines[1:])


def make_command_source(engine, library, socket_name):
    manager = TriggerManager(engine, library)
    source = CommandTriggerSource(socket_name=socket_name)
    manager.command_source = source
    manager.add_source(source)
    source.start()
    return manager, source


def test_command_line_triggers_the_running_instance(app, tmp_path):
    """The end-to-end hop: a second invocation cues the one already running."""
    engine = ShowEngine()
    write_show(tmp_path / "shows", "Nightly")
    _, source = make_command_source(engine, ShowLibrary([tmp_path / "shows"]), "aion-test-trigger")
    assert source.listening

    try:
        accepted, reply = send_trigger_from_another_process("Nightly", "aion-test-trigger")
    finally:
        source.stop()
        engine.stop()

    assert accepted, reply
    assert engine.show is not None and engine.show.name == "Nightly"


def test_command_line_reports_a_show_that_does_not_exist(app, tmp_path):
    """The caller learns *why* it failed, not just that something did."""
    engine = ShowEngine()
    _, source = make_command_source(engine, ShowLibrary([tmp_path / "shows"]), "aion-test-missing")

    try:
        accepted, reply = send_trigger_from_another_process("Ghost", "aion-test-missing")
    finally:
        source.stop()

    assert not accepted
    assert "Ghost" in reply


def test_command_line_is_refused_by_a_show_that_forbids_override(app, tmp_path):
    engine = ShowEngine(clock=ShowClock(time_fn=FakeTime()))
    write_show(tmp_path / "shows", "Nightly")
    _, source = make_command_source(engine, ShowLibrary([tmp_path / "shows"]), "aion-test-locked")

    protected = build_demo_show(duration_ms=10_000)
    protected.name = "Announcement"
    protected.allow_override = False
    engine.load_show(protected)
    engine.play()

    try:
        accepted, reply = send_trigger_from_another_process("Nightly", "aion-test-locked")
    finally:
        source.stop()
        engine.stop()

    assert not accepted
    assert "overridden" in reply
    assert engine.show.name == "Announcement"


def test_triggering_with_nothing_running_fails_cleanly(app):
    accepted, reply = send_trigger("Nightly", socket_name="aion-not-listening", timeout_ms=200)
    assert not accepted
    assert "no running instance" in reply


# -- the policy every trigger goes through ---------------------------------
def make_manager(tmp_path, app):
    engine = ShowEngine(clock=ShowClock(time_fn=FakeTime()))
    return engine, TriggerManager(engine, ShowLibrary([tmp_path / "shows"]), AppConfig())


def test_a_trigger_replaces_the_show_and_starts_it(app, tmp_path):
    write_show(tmp_path / "shows", "Nightly")
    engine, manager = make_manager(tmp_path, app)
    engine.load_show(build_demo_show(duration_ms=1000))

    assert manager.handle(TriggerEvent(show="Nightly", source="test"))
    assert engine.show.name == "Nightly"
    assert engine.clock.running  # "automatically start playing"
    engine.stop()


def test_a_trigger_for_a_show_that_does_not_exist_is_refused(app, tmp_path):
    engine, manager = make_manager(tmp_path, app)
    refusals = []
    manager.rejected.connect(lambda event, reason: refusals.append(reason))

    assert not manager.handle(TriggerEvent(show="Ghost", source="test"))
    assert refusals and "Ghost" in refusals[0]


def test_a_show_that_forbids_being_overridden_blocks_a_trigger(app, tmp_path):
    write_show(tmp_path / "shows", "Nightly")
    engine, manager = make_manager(tmp_path, app)

    protected = build_demo_show(duration_ms=10_000)
    protected.name = "Announcement"
    protected.allow_override = False
    engine.load_show(protected)
    engine.play()

    assert not manager.handle(TriggerEvent(show="Nightly", source="test"))
    assert engine.show.name == "Announcement"
    engine.stop()


def test_a_protected_show_stops_blocking_once_it_is_no_longer_playing(app, tmp_path):
    write_show(tmp_path / "shows", "Nightly")
    engine, manager = make_manager(tmp_path, app)

    protected = build_demo_show(duration_ms=10_000)
    protected.allow_override = False
    engine.load_show(protected)  # loaded, but never started

    assert manager.handle(TriggerEvent(show="Nightly", source="test"))
    engine.stop()


def test_an_overridable_show_is_replaced_mid_playback(app, tmp_path):
    write_show(tmp_path / "shows", "Nightly")
    engine, manager = make_manager(tmp_path, app)

    running = build_demo_show(duration_ms=10_000)
    running.name = "Ambient"
    running.allow_override = True
    engine.load_show(running)
    engine.play()

    assert manager.handle(TriggerEvent(show="Nightly", source="test"))
    assert engine.show.name == "Nightly"
    engine.stop()


# -- one show triggering the next ------------------------------------------
def test_a_finished_show_triggers_the_show_it_names(app, tmp_path):
    write_show(tmp_path / "shows", "Second")
    engine, manager = make_manager(tmp_path, app)

    first = build_demo_show(duration_ms=1000)
    first.name = "First"
    first.next_show = "Second"
    engine.load_show(first)
    engine.play()

    engine._complete()  # the show runs out

    assert engine.show.name == "Second"
    assert engine.clock.running
    engine.stop()


def test_a_finished_show_with_no_next_show_just_stops(app, tmp_path):
    engine, manager = make_manager(tmp_path, app)
    show = build_demo_show(duration_ms=1000)
    engine.load_show(show)
    engine.play()

    finished = []
    engine.show_finished.connect(finished.append)
    engine._complete()

    assert finished == [show]
    assert not engine.clock.running
    assert engine.show is show  # the show stays loaded and visible in the UI


def test_the_chain_survives_a_missing_next_show(app, tmp_path):
    engine, manager = make_manager(tmp_path, app)
    show = build_demo_show(duration_ms=1000)
    show.next_show = "Ghost"
    engine.load_show(show)
    engine.play()

    refusals = []
    manager.rejected.connect(lambda event, reason: refusals.append(reason))
    engine._complete()

    assert refusals  # reported, not raised
    assert not engine.clock.running


def test_next_show_and_override_policy_survive_a_save_and_load(tmp_path):
    show = build_demo_show(duration_ms=1000)
    show.name = "Act One"
    show.loop = True
    show.allow_override = False
    show.next_show = "Act Two"
    path = show.save(tmp_path / "act-one.show.json")

    loaded = Show.load(path)
    assert loaded.loop is True
    assert loaded.allow_override is False
    assert loaded.next_show == "Act Two"


def test_a_show_file_that_says_nothing_is_overridable_and_does_not_loop(tmp_path):
    path = tmp_path / "plain.show.json"
    path.write_text(json.dumps({"name": "Plain", "tracks": []}), encoding="utf-8")
    show = Show.load(path)
    assert show.allow_override is True
    assert show.loop is False
    assert show.next_show is None
