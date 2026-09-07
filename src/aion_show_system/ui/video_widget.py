"""The video output surface.

A show video surface wants to be black, borderless, and able to go full screen
on a chosen display - a projector or an LED wall is rarely the GUI's screen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette, QScreen, QShortcut
from PySide6.QtMultimediaWidgets import QVideoWidget


class ShowVideoWidget(QVideoWidget):
    """Black video surface with full-screen support on any connected display."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.activated.connect(self.leave_full_screen)

    def show_on_screen(self, screen: QScreen) -> None:
        """Go full screen on a specific display, e.g. the projector."""
        self.setParent(None)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()

    def leave_full_screen(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    def toggle_full_screen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
