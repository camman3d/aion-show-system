"""Application bootstrap shared by the entry point and the tests."""

from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORG_DOMAIN, ORG_NAME, __version__
from .config import AppConfig
from .logging_setup import configure_logging
from .triggers import SOCKET_NAME, send_trigger
from .ui import MainWindow

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aion-show-system",
        description="Automated DMX show playback synchronised to audio and video.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Show file (.show.json or .json) to load on launch",
    )
    parser.add_argument(
        "--trigger",
        metavar="SHOW",
        help=(
            "Trigger a show in the already-running system and exit. "
            "SHOW is a show name or a path to a show file."
        ),
    )
    parser.add_argument(
        "--config", metavar="PATH", help="Config file to read instead of the default"
    )
    parser.add_argument(
        "--socket",
        default=SOCKET_NAME,
        help=f"IPC endpoint used by --trigger (default: {SOCKET_NAME})",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser


def create_app(argv: list[str] | None = None) -> QApplication:
    """Return the (possibly already running) QApplication, branded."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)
    return app


def run_trigger(show: str, socket_name: str = SOCKET_NAME) -> int:
    """Hand a trigger to the running instance and report what it said.

    No GUI: this is the command line talking to a show system that is already
    up. It needs a ``QCoreApplication`` for the socket, not a ``QApplication``,
    so it works over SSH on a machine with no display.
    """
    QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    accepted, reply = send_trigger(show, socket_name=socket_name)
    stream = sys.stdout if accepted else sys.stderr
    print(reply, file=stream)
    return 0 if accepted else 1


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    args = build_parser().parse_args(argv[1:])

    configure_logging()
    if args.trigger:
        return run_trigger(args.trigger, args.socket)

    app = create_app(argv)
    config = AppConfig.load(args.config)

    window = MainWindow(config=config)
    if args.file:
        window.load_file(args.file)
    window.show()

    log.info("%s %s started", APP_NAME, __version__)
    return app.exec()
