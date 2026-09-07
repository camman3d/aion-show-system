"""Enumeration of the machine's audio output devices."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtMultimedia import QAudioDevice, QMediaDevices


@dataclass(frozen=True)
class AudioOutputDevice:
    """A selectable audio output, e.g. an interface channel pair on a show rig."""

    name: str
    is_default: bool
    qt_device: QAudioDevice

    def __str__(self) -> str:
        return f"{self.name} (default)" if self.is_default else self.name


def list_output_devices() -> list[AudioOutputDevice]:
    """Return every output the platform reports, default first."""
    default = QMediaDevices.defaultAudioOutput()
    devices = [
        AudioOutputDevice(
            name=device.description(),
            is_default=device.id() == default.id(),
            qt_device=device,
        )
        for device in QMediaDevices.audioOutputs()
    ]
    devices.sort(key=lambda d: (not d.is_default, d.name.lower()))
    return devices


def default_output_device() -> AudioOutputDevice | None:
    """The system default output, or ``None`` when the host has no audio."""
    for device in list_output_devices():
        if device.is_default:
            return device
    return None
