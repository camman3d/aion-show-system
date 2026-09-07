"""The WebSocket trigger client.

The whole show system - every machine in it - connects out to one WebSocket
server, so a cue sent there reaches all of them. This is a client, not a
server: show machines sit on the far side of whatever network the venue has,
and dialling out is the half of that connection that reliably works.

Without a host and a port in the config file there is nothing to dial, and the
client stays down. That is the specified behaviour, so it is logged at info and
reported in the UI rather than treated as a fault.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from ..config import WebSocketConfig
from .base import WEBSOCKET, TriggerSource, parse_trigger_message

log = logging.getLogger(__name__)


class WebSocketTriggerSource(TriggerSource):
    """Hold a connection to the show system's WebSocket server and relay cues.

    The connection reconnects on its own, forever: a show machine that loses
    the server at 4pm has to be triggerable again at 8pm without anyone logging
    into it.
    """

    source_name = WEBSOCKET

    def __init__(self, config: WebSocketConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._socket = QWebSocket()
        self._socket.setParent(self)
        self._wanted = False

        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_text_message)
        self._socket.errorOccurred.connect(self._on_error)

        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.setInterval(max(1000, int(config.reconnect_seconds * 1000)))
        self._retry.timeout.connect(self._connect)

    @property
    def connected(self) -> bool:
        return self._socket.state() == QAbstractSocket.SocketState.ConnectedState

    def start(self) -> None:
        if not self.config.enabled:
            log.info("No WebSocket host/port configured; not connecting")
            self.set_status("not configured")
            return
        self._wanted = True
        self._connect()

    def stop(self) -> None:
        self._wanted = False
        self._retry.stop()
        self._socket.close()
        self.set_status("stopped")

    # -- internals ---------------------------------------------------------
    def _connect(self) -> None:
        if not self._wanted:
            return
        url = self.config.url
        log.info("Connecting to WebSocket %s", url)
        self.set_status(f"connecting to {url}")
        self._socket.open(QUrl(url))

    def _schedule_retry(self) -> None:
        if not self._wanted or self._retry.isActive():
            return
        seconds = self._retry.interval() / 1000
        self.set_status(f"reconnecting in {seconds:.0f}s")
        self._retry.start()

    def _on_connected(self) -> None:
        log.info("WebSocket connected to %s", self.config.url)
        self.set_status(f"connected to {self.config.url}")

    def _on_disconnected(self) -> None:
        if self._wanted:
            log.warning("WebSocket disconnected from %s", self.config.url)
            self._schedule_retry()

    def _on_error(self, _error) -> None:
        log.warning("WebSocket error: %s", self._socket.errorString())
        self._schedule_retry()

    def _on_text_message(self, text: str) -> None:
        show = parse_trigger_message(text)
        if show is None:
            log.warning("Ignoring WebSocket message with no show: %r", text[:120])
            return
        self.fire(show, detail="websocket")
