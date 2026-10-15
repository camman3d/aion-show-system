"""Poll triggers: ask a URL, at an interval, whether there is a new cue.

The URL answers with a small JSON object::

    {"show": "Nightly", "inc": 7}

``inc`` is a counter the server bumps each time it wants a show started. The
source remembers the last value it saw and fires ``show`` only when ``inc``
goes *up*, so a server that keeps answering with the same cue does not restart
the show every few seconds. ``inc`` of 0 or a blank ``show`` means "nothing to
start".

The first answer after startup is taken as the baseline and never fires:
otherwise a show machine rebooted at 4pm would replay whatever the server's
counter last said.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..config import PollConfig
from .base import POLL, TriggerSource

log = logging.getLogger(__name__)


def parse_poll_response(body: bytes | str) -> tuple[str, int] | None:
    """``(show, inc)`` from a poll response, or ``None`` if it is not one.

    A missing or non-numeric ``inc`` counts as 0, and a missing ``show`` as
    blank, so a half-formed answer is simply "nothing to start".
    """
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    show = data.get("show")
    show = show.strip() if isinstance(show, str) else ""
    try:
        inc = int(data.get("inc", 0))
    except (ValueError, TypeError):
        inc = 0
    return show, inc


class PollTriggerSource(TriggerSource):
    """Fetch the configured URL every ``interval_seconds`` and fire on a new ``inc``."""

    source_name = POLL

    def __init__(self, config: PollConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._manager = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._last_inc: int | None = None
        self._failing = False
        self._pending: set[QTimer] = set()

        self._timer = QTimer(self)
        self._timer.setInterval(max(250, int(config.interval_seconds * 1000)))
        self._timer.timeout.connect(self.poll)

    def start(self) -> None:
        if not self.config.enabled:
            log.info("No poll URL configured; not polling")
            self.set_status("not configured")
            return
        self._timer.start()
        self.set_status(f"polling {self.config.url}")
        log.info("Polling %s every %.1fs", self.config.url, self._timer.interval() / 1000)
        self.poll()

    def stop(self) -> None:
        self._timer.stop()
        for timer in self._pending:
            timer.stop()
            timer.deleteLater()
        self._pending.clear()
        if self._reply is not None:
            self._reply.abort()
        self.set_status("stopped")

    def poll(self) -> None:
        """Issue one request, unless the previous one is still outstanding."""
        if self._reply is not None or not self.config.enabled:
            return
        request = QNetworkRequest(QUrl(self.config.url))
        request.setTransferTimeout(max(1, int(self.config.timeout_seconds * 1000)))
        reply = self._manager.get(request)
        self._reply = reply
        reply.finished.connect(lambda: self._on_finished(reply))

    def handle_response(self, body: bytes | str) -> None:
        """Apply one response body. Separate from the network so it is testable."""
        parsed = parse_poll_response(body)
        if parsed is None:
            log.warning("Poll response is not a JSON object: %r", str(body)[:120])
            self.set_status("bad response")
            return
        show, inc = parsed
        self.set_status(f"polling {self.config.url} (inc {inc})")

        previous, self._last_inc = self._last_inc, inc
        if previous is None:
            return  # baseline
        if inc > previous and inc > 0 and show:
            self._fire_after_delay(show, f"poll inc {inc}")

    # -- internals ---------------------------------------------------------
    def _fire_after_delay(self, show: str, detail: str) -> None:
        delay = self.config.delay_seconds
        if delay <= 0:
            self.fire(show, detail=detail)
            return
        log.info("poll trigger: %s will start in %.1fs", show, delay)
        timer = QTimer(self)
        timer.setSingleShot(True)
        self._pending.add(timer)

        def done() -> None:
            self._pending.discard(timer)
            timer.deleteLater()
            self.fire(show, detail=detail)

        timer.timeout.connect(done)
        timer.start(int(delay * 1000))

    def _on_finished(self, reply: QNetworkReply) -> None:
        self._reply = None
        try:
            error = reply.error()
            if error != QNetworkReply.NetworkError.NoError:
                if error != QNetworkReply.NetworkError.OperationCanceledError:
                    if not self._failing:
                        log.warning("Poll of %s failed: %s", self.config.url, reply.errorString())
                    self._failing = True
                    self.set_status(f"error: {reply.errorString()}")
                return
            self._failing = False
            self.handle_response(bytes(reply.readAll().data()))
        finally:
            reply.deleteLater()
