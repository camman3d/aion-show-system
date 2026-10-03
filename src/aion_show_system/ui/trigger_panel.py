"""Trigger status: what can start a show, and what last did.

These machines run unattended, and every failure mode of a trigger is silent -
a WebSocket that never reconnected, a schedule that was never armed, a show
name nothing matches. So each source reports its own state here, and the last
trigger stays on screen whether it was accepted or refused.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from ..triggers import TriggerEvent, TriggerSource

_LABELS = {
    "clock": "Clock",
    "websocket": "WebSocket",
    "poll": "Poll",
    "command": "Command line",
}


class TriggerPanel(QGroupBox):
    """One status line per trigger source, plus the most recent trigger."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Triggers", parent)
        self._status_labels: dict[str, QLabel] = {}

        self._form = QFormLayout()
        self._form.setContentsMargins(8, 4, 8, 4)

        self.last_label = QLabel("none yet")
        self.last_label.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addLayout(self._form)
        self._form.addRow("Last trigger", self.last_label)
        self.setLayout(layout)

    def track(self, source: TriggerSource) -> None:
        """Add a row for ``source`` and keep it up to date."""
        name = _LABELS.get(source.source_name, source.source_name.capitalize())
        label = QLabel(source.status)
        label.setWordWrap(True)
        self._status_labels[source.source_name] = label
        # Insert above the "Last trigger" row so it stays at the bottom.
        self._form.insertRow(self._form.rowCount() - 1, name, label)
        source.status_changed.connect(
            lambda status, key=source.source_name: self.set_status(key, status)
        )

    def set_status(self, source_name: str, status: str) -> None:
        label = self._status_labels.get(source_name)
        if label is not None:
            label.setText(status)

    def show_triggered(self, event: TriggerEvent) -> None:
        self.last_label.setText(f"{event.show} — started ({event.detail or event.source})")

    def show_rejected(self, event: TriggerEvent, reason: str) -> None:
        self.last_label.setText(f"{event.show} — refused: {reason}")
