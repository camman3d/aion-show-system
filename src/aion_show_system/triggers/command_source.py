"""Command-line triggers: a second invocation cues the one that is running.

    aion-show-system-cli --trigger "Nightly"

The show system is already up and holding a rig live, so the command line must
not start a second copy of it. It connects to a local IPC endpoint the running
instance listens on - a named pipe on Windows, a socket file elsewhere, both
via ``QLocalSocket`` - hands over one line, and reads back whether it landed.

The protocol is one UTF-8 line each way, so ``--trigger`` is debuggable by hand
and the reply can say *why* a trigger was refused rather than just exiting 1.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .base import COMMAND, TriggerSource, parse_trigger_message

log = logging.getLogger(__name__)

#: Endpoint name. Per-user on Windows named pipes and in the user's runtime
#: directory elsewhere, so two accounts on one machine do not collide.
SOCKET_NAME = "aion-show-system"

CONNECT_TIMEOUT_MS = 2000
REPLY_TIMEOUT_MS = 5000

OK = "OK"
ERROR = "ERR"


class CommandTriggerSource(TriggerSource):
    """Listen for trigger messages from other invocations of the program."""

    source_name = COMMAND

    def __init__(self, socket_name: str = SOCKET_NAME, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.socket_name = socket_name
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._result: str | None = None

    @property
    def listening(self) -> bool:
        return self._server.isListening()

    def start(self) -> None:
        if self._server.isListening():
            return
        # A crash leaves the endpoint behind on Unix and every later listen()
        # fails with "address in use" until it is cleared.
        QLocalServer.removeServer(self.socket_name)
        if not self._server.listen(self.socket_name):
            log.error(
                "Command triggers unavailable: %s (%s)",
                self._server.errorString(),
                self.socket_name,
            )
            self.set_status(f"unavailable: {self._server.errorString()}")
            return
        log.info("Listening for command triggers on %s", self.socket_name)
        self.set_status(f"listening on {self.socket_name}")

    def stop(self) -> None:
        if self._server.isListening():
            self._server.close()
        self.set_status("stopped")

    def report_result(self, message: str) -> None:
        """Set the reply the *current* trigger will send back to the CLI.

        The manager calls this while handling ``triggered``, which - because Qt
        delivers a direct connection synchronously - is still inside the socket
        read below. So the caller finds out whether its show actually started,
        instead of only that the bytes arrived.
        """
        self._result = message

    # -- internals ---------------------------------------------------------
    def _on_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda: self._on_ready_read(socket))
        socket.disconnected.connect(socket.deleteLater)

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        text = bytes(socket.readAll().data()).decode("utf-8", errors="replace").strip()
        if not text:
            return
        show = parse_trigger_message(text)
        if show is None:
            self._reply(socket, f"{ERROR} no show in message")
            return
        self._result = None
        self.fire(show, detail="command line")
        self._reply(socket, self._result or f"{OK} triggered {show}")

    def _reply(self, socket: QLocalSocket, message: str) -> None:
        socket.write(f"{message}\n".encode())
        socket.flush()
        socket.waitForBytesWritten(REPLY_TIMEOUT_MS)
        socket.disconnectFromServer()


def send_trigger(
    message: str,
    *,
    socket_name: str = SOCKET_NAME,
    timeout_ms: int = CONNECT_TIMEOUT_MS,
) -> tuple[bool, str]:
    """Send a trigger to the running show system.

    Returns ``(accepted, reply)``. ``accepted`` is false both when nothing is
    listening and when the running instance refused the trigger - a show that
    does not exist, or one that declined to be overridden - and ``reply`` says
    which, so the caller can print something an operator can act on.
    """
    socket = QLocalSocket()
    socket.connectToServer(socket_name)
    if not socket.waitForConnected(timeout_ms):
        return False, f"{ERROR} no running instance on {socket_name}"

    socket.write(f"{message}\n".encode())
    socket.flush()
    # Best effort only: on a Windows named pipe this reports false even when
    # the bytes went out, so the reply - not this call - is the confirmation.
    socket.waitForBytesWritten(timeout_ms)

    if not socket.waitForReadyRead(REPLY_TIMEOUT_MS):
        return False, f"{ERROR} no reply from the running instance"

    reply = bytes(socket.readAll().data()).decode("utf-8", errors="replace").strip()
    socket.disconnectFromServer()
    return reply.startswith(OK), reply
