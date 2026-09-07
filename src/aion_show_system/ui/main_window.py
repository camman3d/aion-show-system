"""Main application window: media transport, timeline position and DMX output."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME
from ..config import AppConfig
from ..media import PlaybackState, list_output_devices
from ..paths import config_dir
from ..show import MediaCue, Show, ShowEngine, ShowLibrary
from ..show.demo import build_demo_show
from ..triggers import TriggerManager
from .dmx_monitor import DmxMonitor
from .dmx_panel import DmxPanel
from .trigger_panel import TriggerPanel
from .video_widget import ShowVideoWidget

log = logging.getLogger(__name__)

MEDIA_FILTER = (
    "Media (*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.mp4 *.mov *.mkv *.avi);;"
    "Audio (*.wav *.mp3 *.flac *.ogg *.m4a *.aac);;"
    "Video (*.mp4 *.mov *.mkv *.avi);;"
    "All files (*)"
)
SHOW_FILTER = "Show files (*.show.json *.json);;All files (*)"
UI_REFRESH_MS = 50  # 20 Hz is plenty for a monitor; DMX itself runs at 40 Hz


def format_ms(milliseconds: float) -> str:
    """Render a millisecond position as ``m:ss`` (or ``h:mm:ss`` when long)."""
    seconds, _ = divmod(max(0, int(milliseconds)), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class MainWindow(QMainWindow):
    def __init__(
        self,
        engine: ShowEngine | None = None,
        config: AppConfig | None = None,
        *,
        start_triggers: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(880, 760)

        self.config = config or AppConfig()
        self.engine = engine or ShowEngine(parent=self)
        self.player = self.engine.player
        self.library = ShowLibrary([self.config.shows_path])
        self.triggers = TriggerManager(self.engine, self.library, self.config, parent=self)
        self._scrubbing = False
        self._last_frame_count = 0
        self._last_rate_check = time.perf_counter()

        self._build_menu()
        self.setCentralWidget(self._build_central())
        self._connect_signals()

        self.player.set_video_output(self.video)
        self.player.volume = 0.8
        self.volume_slider.setValue(80)
        self._refresh_devices()

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(UI_REFRESH_MS)
        self._ui_timer.timeout.connect(self._refresh_live_state)
        self._ui_timer.start()

        self._refresh_transport_buttons()
        self._apply_dmx_config()
        # Tests build windows without wanting a live IPC endpoint or a socket
        # dialling out, so arming the triggers is opt-out.
        if start_triggers:
            self.start_triggers()

        self.statusBar().showMessage("Ready")

    def start_triggers(self) -> None:
        """Build the configured trigger sources and start listening."""
        self.triggers.build_default_sources()
        for source in self.triggers.sources:
            self.trigger_panel.track(source)
        self.triggers.start()

    # -- construction ------------------------------------------------------
    def _build_menu(self) -> None:
        open_media = QAction("&Open Media...", self)
        open_media.setShortcut(QKeySequence.StandardKey.Open)
        open_media.triggered.connect(self.open_media)

        open_show = QAction("Open S&how...", self)
        open_show.triggered.connect(self.open_show)

        save_show = QAction("&Save Show As...", self)
        save_show.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_show.triggered.connect(self.save_show)

        demo = QAction("Build &Demo Sequence", self)
        demo.setStatusTip("Generate a DMX chase across the loaded media's duration")
        demo.triggered.connect(self.build_demo)

        quit_action = QAction("E&xit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(open_media)
        file_menu.addAction(open_show)
        file_menu.addAction(save_show)
        file_menu.addSeparator()
        file_menu.addAction(demo)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        full_screen = QAction("Video &Full Screen", self)
        full_screen.setShortcut(QKeySequence(Qt.Key.Key_F11))
        full_screen.triggered.connect(lambda: self.video.toggle_full_screen())
        self.menuBar().addMenu("&View").addAction(full_screen)

        about = QAction("&About", self)
        about.triggered.connect(self.show_about)
        self.menuBar().addMenu("&Help").addAction(about)

    def _build_central(self) -> QWidget:
        self.video = ShowVideoWidget()
        self.video.setVisible(False)

        # The loaded show is the first thing an operator looks for, so it gets
        # its own line in a larger face rather than sharing the status bar.
        self.show_label = QLabel("No show loaded")
        show_font = self.show_label.font()
        show_font.setBold(True)
        show_font.setPointSize(show_font.pointSize() + 2)
        self.show_label.setFont(show_font)

        self.file_label = QLabel("No media")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderPressed.connect(self._on_scrub_start)
        self.position_slider.sliderReleased.connect(self._on_scrub_end)

        self.time_label = QLabel("0:00 / 0:00")
        self.sync_label = QLabel("sync --")
        self.sync_label.setToolTip(
            "Media position minus timeline clock. Small numbers are normal; a "
            "persistently large value means the machine cannot keep up."
        )

        time_row = QHBoxLayout()
        time_row.addWidget(self.time_label)
        time_row.addStretch(1)
        time_row.addWidget(self.sync_label)

        self.play_button = QPushButton("Play")
        self.play_button.setShortcut(Qt.Key.Key_Space)
        self.play_button.clicked.connect(self.toggle_playback)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_playback)

        self.loop_check = QCheckBox("Loop")
        self.loop_check.setToolTip("Restart the show from the top when it reaches the end")
        self.loop_check.toggled.connect(self._on_loop_toggled)

        open_button = QPushButton("Open...")
        open_button.clicked.connect(self.open_media)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(140)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)

        transport = QHBoxLayout()
        transport.addWidget(open_button)
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addWidget(self.loop_check)
        transport.addStretch(1)
        transport.addWidget(QLabel("Volume"))
        transport.addWidget(self.volume_slider)

        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        audio_row = QHBoxLayout()
        audio_row.addWidget(QLabel("Audio output"))
        audio_row.addWidget(self.device_combo, 1)

        self.dmx_panel = DmxPanel()
        self.trigger_panel = TriggerPanel()

        self.universe_combo = QComboBox()
        self.universe_combo.setMaximumWidth(90)
        self.monitor = DmxMonitor()
        self.monitor.setMaximumHeight(200)  # a level grid should not dwarf the transport
        monitor_box = QGroupBox("Levels")
        monitor_layout = QVBoxLayout()
        universe_row = QHBoxLayout()
        universe_row.addWidget(QLabel("Universe"))
        universe_row.addWidget(self.universe_combo)
        universe_row.addStretch(1)
        monitor_layout.addLayout(universe_row)
        monitor_layout.addWidget(self.monitor)
        monitor_layout.addStretch(1)  # keep the grid against the top of its box
        monitor_box.setLayout(monitor_layout)

        layout = QVBoxLayout()
        layout.addWidget(self.video, 3)
        layout.addWidget(self.show_label)
        layout.addWidget(self.file_label)
        layout.addWidget(self.position_slider)
        layout.addLayout(time_row)
        layout.addLayout(transport)
        layout.addLayout(audio_row)
        layout.addWidget(self.trigger_panel)
        layout.addWidget(self.dmx_panel)
        layout.addWidget(monitor_box, 1)

        central = QWidget()
        central.setLayout(layout)
        return central

    def _connect_signals(self) -> None:
        self.player.duration_changed.connect(self._on_duration_changed)
        self.player.state_changed.connect(self._on_state_changed)
        self.player.source_changed.connect(self._on_source_changed)
        self.player.has_video_changed.connect(self.video.setVisible)
        self.player.error_occurred.connect(self._on_error)
        self.engine.show_changed.connect(self._on_show_changed)
        self.engine.show_finished.connect(self._on_show_finished)
        self.dmx_panel.output_requested.connect(self._on_output_requested)
        self.dmx_panel.output_released.connect(self._on_output_released)
        self.triggers.triggered.connect(self.trigger_panel.show_triggered)
        self.triggers.rejected.connect(self.trigger_panel.show_rejected)
        self.triggers.triggered.connect(
            lambda event: self.statusBar().showMessage(f"Triggered {event.show}")
        )
        self.triggers.rejected.connect(
            lambda event, reason: self.statusBar().showMessage(f"Trigger refused: {reason}")
        )

    # -- actions -----------------------------------------------------------
    @Slot()
    def open_media(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Media", "", MEDIA_FILTER)
        if path:
            self.load_media(path)

    def load_media(self, path: str | Path) -> None:
        """Point the current show at a media file, keeping any lighting tracks."""
        show = self.engine.show or Show()
        show.media = MediaCue(path=str(path))
        show.name = Path(path).stem
        self.engine.load_show(show)

    def load_file(self, path: str | Path) -> None:
        """Open whatever the command line pointed at: a show file or media.

        A ``.json`` file is a show; anything else is media to hang a show on.
        """
        target = Path(path).expanduser()
        if target.suffix.lower() == ".json":
            try:
                self.engine.load_show(Show.load(target))
            except (OSError, ValueError, KeyError) as error:
                self._on_error(f"Could not open show {target}: {error}")
            return
        try:
            self.load_media(target)
        except FileNotFoundError:
            self._on_error(f"No such media file: {target}")

    @Slot()
    def open_show(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Show", str(config_dir()), SHOW_FILTER)
        if not path:
            return
        try:
            self.engine.load_show(Show.load(path))
        except (OSError, ValueError, KeyError) as error:
            self._on_error(f"Could not open show: {error}")

    @Slot()
    def save_show(self) -> None:
        show = self.engine.show
        if show is None:
            self._on_error("There is no show to save yet.")
            return
        suggested = str(config_dir() / f"{show.name}.show.json")
        path, _ = QFileDialog.getSaveFileName(self, "Save Show", suggested, SHOW_FILTER)
        if path:
            show.save(path)
            self.statusBar().showMessage(f"Saved {path}")

    @Slot()
    def build_demo(self) -> None:
        """Generate a chase over the loaded media so the rig can be verified."""
        show = self.engine.show
        duration = self.player.duration or 30_000
        media_path = show.media.path if show and show.media else None
        demo = build_demo_show(duration_ms=duration, media_path=media_path)
        self.engine.load_show(demo)
        self.statusBar().showMessage(
            f"Built demo: {len(demo.tracks)} track(s) over {format_ms(duration)}"
        )

    @Slot()
    def toggle_playback(self) -> None:
        if self.engine.is_playing:
            self.engine.pause()
        else:
            self.engine.play()
        self._refresh_transport_buttons()

    @Slot()
    def stop_playback(self) -> None:
        self.engine.stop()
        self._refresh_transport_buttons()

    def _on_loop_toggled(self, looping: bool) -> None:
        self.engine.set_loop(looping)

    @Slot()
    def show_about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br>DMX show playback synchronised to audio and video."
            "<br>Built with PySide6, Art-Net and sACN.",
        )

    # -- engine callbacks --------------------------------------------------
    @Slot(int)
    def _on_duration_changed(self, duration: int) -> None:
        self._refresh_duration()

    @Slot(PlaybackState)
    def _on_state_changed(self, state: PlaybackState) -> None:
        self._refresh_transport_buttons()
        self.statusBar().showMessage(state.value.capitalize())

    @Slot(object)
    def _on_source_changed(self, source: Path | None) -> None:
        self.file_label.setText(str(source) if source else "No media")

    @Slot(object)
    def _on_show_changed(self, show: Show | None) -> None:
        universes = show.universes if show else []
        self.universe_combo.clear()
        for universe in universes or [0]:
            self.universe_combo.addItem(str(universe), universe)
        self.monitor.clear()

        if show is None:
            self.show_label.setText("No show loaded")
            self.file_label.setText("No media")
            return

        tracks = f"{len(show.tracks)} track(s)" if show.tracks else "no lighting"
        flags = []
        if show.loop:
            flags.append("looping")
        if not show.allow_override:
            flags.append("not overridable")
        if show.next_show:
            flags.append(f"then {show.next_show}")
        suffix = f" — {', '.join(flags)}" if flags else ""
        self.show_label.setText(f"{show.name} — {tracks}{suffix}")
        self.file_label.setText(show.media.path if show.media else "No media")

        # Reflect the file's own loop flag without echoing back into the engine.
        with QSignalBlocker(self.loop_check):
            self.loop_check.setChecked(show.loop)
        self._refresh_duration()
        self._refresh_transport_buttons()

    @Slot(object)
    def _on_show_finished(self, show: Show) -> None:
        self.statusBar().showMessage(f"{show.name} finished")
        self._refresh_transport_buttons()

    def _refresh_duration(self) -> None:
        """Size the progress bar to the show, which may outlast its media."""
        self.position_slider.setRange(0, max(0, self.engine.duration_ms))

    def _refresh_transport_buttons(self) -> None:
        playing = self.engine.is_playing
        self.play_button.setText("Pause" if playing else "Play")
        has_show = self.engine.show is not None
        self.play_button.setEnabled(has_show)
        self.stop_button.setEnabled(has_show)
        self.loop_check.setEnabled(has_show)

    def _apply_dmx_config(self) -> None:
        """Point the output panel at the config file, and go live if it says to.

        The panel stays usable either way; the config just decides what it
        starts as, so a machine that boots into a show needs no clicks.
        """
        from .dmx_panel import ART_NET, DRY_RUN, SACN

        dmx = self.config.dmx
        labels = {"artnet": ART_NET, "sacn": SACN, "none": DRY_RUN}
        self.dmx_panel.protocol_combo.setCurrentText(labels.get(dmx.protocol, DRY_RUN))
        if dmx.host:
            self.dmx_panel.host_edit.setText(dmx.host)
        self.dmx_panel.universe_spin.setValue(dmx.universe)
        if dmx.enabled:
            log.info("Going live on DMX from config: %s", dmx.protocol)
            self.dmx_panel.go_live_button.setChecked(True)

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, APP_NAME, message)

    @Slot(object)
    def _on_output_requested(self, output) -> None:
        self.engine.clear_outputs()
        self.engine.add_output(output)
        self.engine.sender.start()  # keep the rig refreshed even before Play

    @Slot()
    def _on_output_released(self) -> None:
        show = self.engine.show
        if show:
            self.engine.sender.blackout(show.universes)
        self.engine.clear_outputs()
        self.monitor.clear()

    # -- widget callbacks --------------------------------------------------
    def _on_scrub_start(self) -> None:
        self._scrubbing = True

    def _on_scrub_end(self) -> None:
        self._scrubbing = False
        self.engine.seek(self.position_slider.value())

    def _on_volume_changed(self, value: int) -> None:
        self.player.volume = value / 100

    def _on_device_changed(self, index: int) -> None:
        device = self.device_combo.itemData(index)
        if device is not None:
            self.player.set_output_device(device)

    def _refresh_devices(self) -> None:
        self.device_combo.clear()
        devices = list_output_devices()
        if not devices:
            self.device_combo.addItem("No audio output found", None)
            self.device_combo.setEnabled(False)
            return
        for device in devices:
            self.device_combo.addItem(str(device), device)

    def _refresh_live_state(self) -> None:
        """Drive the timeline readouts off the show clock, not the media player."""
        position = self.engine.position_ms
        if not self._scrubbing:
            self.position_slider.setValue(int(position))
        self.time_label.setText(f"{format_ms(position)} / {format_ms(self.engine.duration_ms)}")

        sender = self.engine.sender
        now = time.perf_counter()
        elapsed = now - self._last_rate_check
        if elapsed >= 0.5:
            frames = sender.frames_sent
            rate = (frames - self._last_frame_count) / elapsed
            self._last_frame_count = frames
            self._last_rate_check = now
            self.dmx_panel.set_frame_rate(rate, sender.late_frames)
            drift = (self.engine.clock.rate - 1.0) * 100
            self.sync_label.setText(f"clock {drift:+.2f}%")

        universe = self.universe_combo.currentData()
        if universe is not None:
            frame = sender.last_frame.get(universe)
            if frame:
                self.monitor.set_frame(frame)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.triggers.stop()  # release the IPC endpoint before the process goes
        self.engine.stop()
        self.engine.clear_outputs()
        super().closeEvent(event)
