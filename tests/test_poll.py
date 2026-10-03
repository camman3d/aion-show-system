"""Poll trigger: fire when a URL's ``inc`` counter goes up."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PySide6.QtCore import QCoreApplication

from aion_show_system.config import AppConfig, PollConfig
from aion_show_system.triggers import PollTriggerSource
from aion_show_system.triggers.poll_source import parse_poll_response


def make_source(app):
    source = PollTriggerSource(PollConfig(url="http://example.invalid/cue"))
    fired = []
    source.triggered.connect(fired.append)
    return source, fired


def feed(source, show, inc):
    source.handle_response(json.dumps({"show": show, "inc": inc}))


def test_poll_config_defaults_and_parsing():
    assert not PollConfig().enabled
    config = AppConfig.from_dict({"poll": {"url": "http://h/x", "interval_seconds": 2}})
    assert config.poll.enabled and config.poll.interval_seconds == 2
    assert not AppConfig.from_dict({}).poll.enabled


def test_parse_poll_response():
    assert parse_poll_response('{"show": " A ", "inc": 3}') == ("A", 3)
    assert parse_poll_response('{"show": "A"}') == ("A", 0)
    assert parse_poll_response('{"show": "A", "inc": "x"}') == ("A", 0)
    assert parse_poll_response("nope") is None
    assert parse_poll_response("[1]") is None


def test_not_configured_does_not_poll(app):
    source = PollTriggerSource(PollConfig())
    source.start()
    assert source.status == "not configured"


def test_first_response_is_a_baseline_and_never_fires(app):
    source, fired = make_source(app)
    feed(source, "Nightly", 5)
    assert fired == []


def test_fires_when_inc_increments_once(app):
    source, fired = make_source(app)
    feed(source, "A", 1)
    feed(source, "A", 1)
    feed(source, "B", 2)
    feed(source, "B", 2)
    assert [(e.show, e.source) for e in fired] == [("B", "poll")]


def test_blank_show_or_zero_inc_does_not_fire(app):
    source, fired = make_source(app)
    feed(source, "A", 0)
    feed(source, "", 1)
    feed(source, "A", 0)
    feed(source, "A", 0)
    assert fired == []


def test_decrease_rebaselines_then_next_increment_fires(app):
    source, fired = make_source(app)
    feed(source, "A", 5)
    feed(source, "A", 0)  # server reset
    feed(source, "A", 1)
    assert [e.show for e in fired] == ["A"]


def test_bad_response_is_ignored(app):
    source, fired = make_source(app)
    feed(source, "A", 1)
    source.handle_response("<html>")
    feed(source, "A", 2)
    assert [e.show for e in fired] == ["A"]


@pytest.fixture
def server():
    state = {"body": {"show": "", "inc": 0}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps(state["body"]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield state, f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


def wait_for(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_polls_a_real_url(app, server):
    state, url = server
    source = PollTriggerSource(PollConfig(url=url, interval_seconds=0.25))
    fired = []
    source.triggered.connect(fired.append)
    source.start()
    try:
        assert wait_for(lambda: "inc 0" in source.status)
        state["body"] = {"show": "Live", "inc": 1}
        assert wait_for(lambda: fired)
        assert fired[0].show == "Live"
        time.sleep(0.6)
        QCoreApplication.processEvents()
        assert len(fired) == 1  # same inc again does not refire
    finally:
        source.stop()
