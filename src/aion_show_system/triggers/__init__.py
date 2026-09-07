"""Ways a show gets started without anyone touching the transport.

Four sources, one policy (see :mod:`.manager`):

* :class:`~.clock_source.ClockTriggerSource` - a wall-clock time from the config file
* :class:`~.websocket_source.WebSocketTriggerSource` - the show system's WebSocket server
* :class:`~.command_source.CommandTriggerSource` - another invocation's ``--trigger``
* ``Show.next_show`` - the show that just finished naming the next one
"""

from .base import CHAIN, CLOCK, COMMAND, MANUAL, WEBSOCKET, TriggerEvent, TriggerSource
from .clock_source import ClockTriggerSource
from .command_source import SOCKET_NAME, CommandTriggerSource, send_trigger
from .manager import TriggerManager
from .websocket_source import WebSocketTriggerSource

__all__ = [
    "CHAIN",
    "CLOCK",
    "COMMAND",
    "MANUAL",
    "SOCKET_NAME",
    "WEBSOCKET",
    "ClockTriggerSource",
    "CommandTriggerSource",
    "TriggerEvent",
    "TriggerManager",
    "TriggerSource",
    "WebSocketTriggerSource",
    "send_trigger",
]
