"""A live 512-channel level monitor.

Custom-painted rather than built from widgets: 512 individual widgets repainting
40 times a second would be the single heaviest thing in the app on a Pi.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

COLUMNS = 32
ROWS = 16  # 32 x 16 = 512 channels


class DmxMonitor(QWidget):
    """Shows one universe as a grid of cells shaded by level."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame = bytes(512)
        self.setMinimumHeight(ROWS * 6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setToolTip("Live DMX levels, channel 1 top-left")

    def set_frame(self, frame: bytes) -> None:
        """Update the displayed levels. Cheap enough to call at UI rate."""
        if frame != self._frame:
            self._frame = bytes(frame).ljust(512, b"\x00")[:512]
            self.update()

    def clear(self) -> None:
        self.set_frame(bytes(512))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 24, 27))

        cell_width = self.width() / COLUMNS
        cell_height = self.height() / ROWS
        unlit = QColor(38, 38, 43)
        for index, level in enumerate(self._frame):
            column, row = index % COLUMNS, index // COLUMNS
            # Every cell is drawn, so the grid reads as 512 channels even when
            # the rig is dark. Amber ramp: legible at a glance across a booth.
            color = unlit if not level else QColor.fromHsv(38, 200, 40 + int(level * 215 / 255))
            painter.fillRect(
                QRectF(
                    column * cell_width + 0.5,
                    row * cell_height + 0.5,
                    cell_width - 1,
                    cell_height - 1,
                ),
                color,
            )

        painter.setPen(QColor(70, 70, 76))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

    def sizeHint(self):  # noqa: N802 - Qt naming
        from PySide6.QtCore import QSize

        return QSize(COLUMNS * 12, ROWS * 8)

    def minimumSizeHint(self):  # noqa: N802 - Qt naming
        from PySide6.QtCore import QSize

        return QSize(COLUMNS * 4, ROWS * 4)

    def channel_at(self, x: int, y: int) -> int | None:
        """1-based channel under a point, for future click-to-inspect."""
        if not self.rect().contains(x, y):
            return None
        column = int(x / (self.width() / COLUMNS))
        row = int(y / (self.height() / ROWS))
        channel = row * COLUMNS + column + 1
        return channel if 1 <= channel <= 512 else None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        position = event.position().toPoint()
        channel = self.channel_at(position.x(), position.y())
        if channel is not None:
            self.setToolTip(f"Channel {channel}: {self._frame[channel - 1]}")
        super().mouseMoveEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.setMouseTracking(True)
        super().enterEvent(event)
