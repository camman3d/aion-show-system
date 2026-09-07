"""The config file: absent, malformed and complete."""

import json
from datetime import datetime

import pytest

from aion_show_system.config import (
    AppConfig,
    ClockTrigger,
    DmxConfig,
    WebSocketConfig,
    parse_clock_time,
    parse_days,
)
from aion_show_system.dmx import ArtNetOutput, NullOutput, SacnOutput


def write_config(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# -- times and days --------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("22:00", (22, 0)),
        ("10:00 PM", (22, 0)),
        ("10:00PM", (22, 0)),
        ("9 AM", (9, 0)),
        ("07:30:00", (7, 30)),
    ],
)
def test_clock_times_parse_in_both_notations(text, expected):
    parsed = parse_clock_time(text)
    assert (parsed.hour, parsed.minute) == expected


def test_unparseable_clock_time_raises():
    with pytest.raises(ValueError):
        parse_clock_time("half past nine")


def test_days_parse_to_weekday_numbers():
    assert parse_days(["mon", "Friday"]) == frozenset({0, 4})
    assert parse_days(None) == frozenset()  # empty means every day


# -- clock triggers --------------------------------------------------------
def test_clock_trigger_matches_its_minute_on_any_day():
    trigger = ClockTrigger(at=parse_clock_time("10:00 PM"), show="Nightly")
    assert trigger.matches(datetime(2026, 9, 7, 22, 0, 0))
    assert trigger.matches(datetime(2026, 9, 7, 22, 0, 59))  # anywhere in the minute
    assert not trigger.matches(datetime(2026, 9, 7, 22, 1, 0))
    assert not trigger.matches(datetime(2026, 9, 7, 21, 59, 59))


def test_clock_trigger_honours_its_day_filter():
    # 2026-09-07 is a Monday, 2026-09-11 a Friday.
    trigger = ClockTrigger(at=parse_clock_time("22:00"), show="Weekend", days=parse_days(["fri"]))
    assert not trigger.matches(datetime(2026, 9, 7, 22, 0))
    assert trigger.matches(datetime(2026, 9, 11, 22, 0))


def test_a_clock_trigger_without_a_show_is_dropped_not_fatal(tmp_path):
    path = write_config(
        tmp_path,
        {
            "clock_triggers": [
                {"time": "22:00"},  # no show
                {"time": "nonsense", "show": "Bad"},
                {"time": "23:15", "show": "Good"},
            ]
        },
    )
    config = AppConfig.load(path)
    assert [t.show for t in config.clock_triggers] == ["Good"]


# -- DMX -------------------------------------------------------------------
def test_dmx_config_builds_each_transport():
    artnet = DmxConfig(protocol="artnet", host="127.0.0.1", universe=3).create_output()
    assert isinstance(artnet, ArtNetOutput) and artnet.universe == 3
    artnet.close()

    sacn = DmxConfig(protocol="sacn").create_output()
    assert isinstance(sacn, SacnOutput)
    sacn.close()

    assert isinstance(DmxConfig().create_output(), NullOutput)


def test_dmx_protocol_aliases_are_accepted():
    assert DmxConfig.from_dict({"protocol": "Art-Net"}).protocol == "artnet"
    assert DmxConfig.from_dict({"protocol": "E1.31"}).protocol == "sacn"
    with pytest.raises(ValueError):
        DmxConfig.from_dict({"protocol": "midi"})


def test_a_real_protocol_goes_live_on_its_own_and_a_dry_run_does_not():
    assert DmxConfig(protocol="artnet").enabled
    assert not DmxConfig(protocol="none").enabled
    # An explicit auto_start always wins over the inference.
    assert not DmxConfig(protocol="artnet", auto_start=False).enabled
    assert DmxConfig(protocol="none", auto_start=True).enabled


# -- WebSocket -------------------------------------------------------------
def test_websocket_needs_both_host_and_port_to_connect():
    assert not WebSocketConfig().enabled
    assert not WebSocketConfig(host="10.0.0.5").enabled
    assert not WebSocketConfig(port=8765).enabled
    assert WebSocketConfig(host="10.0.0.5", port=8765).enabled


def test_websocket_url_is_built_from_the_parts():
    assert WebSocketConfig(host="h", port=80, path="cues").url == "ws://h:80/cues"
    assert WebSocketConfig(host="h", port=443, secure=True).url == "wss://h:443/"


# -- the file as a whole ---------------------------------------------------
def test_a_missing_config_file_is_a_valid_configuration(tmp_path):
    config = AppConfig.load(tmp_path / "nothing-here.json")
    assert not config.websocket.enabled  # so it does not connect
    assert not config.dmx.enabled
    assert config.clock_triggers == ()


def test_a_malformed_config_file_does_not_stop_the_system(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    config = AppConfig.load(path)
    assert not config.websocket.enabled


def test_a_complete_config_file_round_trips(tmp_path):
    path = write_config(
        tmp_path,
        {
            "shows_dir": str(tmp_path / "shows"),
            "dmx": {"protocol": "sacn", "universe": 4},
            "websocket": {"host": "10.0.0.5", "port": 8765, "path": "/cues"},
            "clock_triggers": [{"time": "10:00 PM", "show": "Nightly", "days": ["sat", "sun"]}],
        },
    )
    config = AppConfig.load(path)

    assert config.dmx.protocol == "sacn"
    assert config.dmx.universe == 4
    assert config.websocket.url == "ws://10.0.0.5:8765/cues"
    assert config.shows_path == tmp_path / "shows"

    trigger = config.clock_triggers[0]
    assert (trigger.at.hour, trigger.show) == (22, "Nightly")
    assert trigger.days == frozenset({5, 6})
