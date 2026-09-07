"""Application bootstrap shared by the entry point and the tests."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORG_DOMAIN, ORG_NAME, __version__
from .logging_setup import configure_logging
from .ui import MainWindow

log = logging.getLogger(__name__)


def create_app(argv: list[str] | None = None) -> QApplication:
    """Return the (possibly already running) QApplication, branded."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)
    return app


def run(argv: list[str] | None = None) -> int:
    configure_logging()
    argv = list(sys.argv if argv is None else argv)
    app = create_app(argv)

    window = MainWindow()
    if len(argv) > 1:
        window.load(argv[1])
    window.show()

    log.info("%s %s started", APP_NAME, __version__)
    return app.exec()
