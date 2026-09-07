"""Output configuration: pick a protocol, point it at a node, go live."""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

from ..dmx import ArtNetOutput, DmxOutput, NullOutput, SacnOutput

log = logging.getLogger(__name__)

ART_NET = "Art-Net"
SACN = "sACN (E1.31)"
DRY_RUN = "Dry run (no network)"


class DmxPanel(QGroupBox):
    """Builds a :class:`DmxOutput` from the user's choices."""

    output_requested = Signal(object)  # DmxOutput
    output_released = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("DMX output", parent)
        self._live = False
        self._description = ""

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems([ART_NET, SACN, DRY_RUN])
        self.protocol_combo.currentTextChanged.connect(self._on_protocol_changed)

        self.host_edit = QLineEdit("255.255.255.255")
        self.host_edit.setPlaceholderText("Node address")
        self.host_edit.setMaximumWidth(160)

        self.universe_spin = QSpinBox()
        self.universe_spin.setRange(0, 63999)  # 0 is legal Art-Net, rejected by sACN
        self.universe_spin.setValue(1)
        self.universe_spin.setMaximumWidth(80)

        self.go_live_button = QPushButton("Go live")
        self.go_live_button.setCheckable(True)
        self.go_live_button.toggled.connect(self._on_go_live)

        self.status_label = QLabel("Offline")

        layout = QHBoxLayout()
        layout.addWidget(QLabel("Protocol"))
        layout.addWidget(self.protocol_combo)
        self.host_label = QLabel("Host")
        layout.addWidget(self.host_label)
        layout.addWidget(self.host_edit)
        layout.addWidget(QLabel("Universe"))
        layout.addWidget(self.universe_spin)
        layout.addWidget(self.go_live_button)
        layout.addWidget(self.status_label, 1)
        self.setLayout(layout)

    @property
    def live(self) -> bool:
        return self._live

    def build_output(self) -> DmxOutput:
        """Construct the configured transport."""
        protocol = self.protocol_combo.currentText()
        host = self.host_edit.text().strip()
        if protocol == ART_NET:
            return ArtNetOutput(host or "255.255.255.255", universe=self.universe_spin.value())
        if protocol == SACN:
            # Blank host means multicast, which is the sACN default and usually right.
            return SacnOutput(host or None)
        return NullOutput()

    def set_frame_rate(self, fps: float, late_frames: int = 0) -> None:
        """Show the measured output rate; late frames are the health signal."""
        if not self._live:
            return
        warning = f"  ({late_frames} late)" if late_frames else ""
        self.status_label.setText(f"{self._description}  ·  {fps:.1f} Hz{warning}")

    def _on_protocol_changed(self, protocol: str) -> None:
        network = protocol != DRY_RUN
        self.host_edit.setEnabled(network)
        self.host_label.setEnabled(network)
        if protocol == SACN:
            self.host_edit.setPlaceholderText("blank = multicast")
            if self.host_edit.text().strip() == "255.255.255.255":
                self.host_edit.clear()
        elif protocol == ART_NET and not self.host_edit.text().strip():
            self.host_edit.setText("255.255.255.255")

    def _on_go_live(self, checked: bool) -> None:
        if checked:
            try:
                output = self.build_output()
            except (OSError, ValueError) as error:
                log.error("Could not open DMX output: %s", error)
                self.status_label.setText(f"Failed: {error}")
                self.go_live_button.setChecked(False)
                return
            self._live = True
            self._description = str(output)
            self.go_live_button.setText("Go offline")
            self.status_label.setText(self._description)
            self.output_requested.emit(output)
        else:
            self._live = False
            self.go_live_button.setText("Go live")
            self.status_label.setText("Offline")
            self.output_released.emit()
