from aion_show_system.ui.main_window import MainWindow, format_ms

# Windows here must not claim the IPC endpoint a real running instance listens on.


def test_format_ms():
    assert format_ms(0) == "0:00"
    assert format_ms(1500) == "0:01"
    assert format_ms(61_000) == "1:01"
    assert format_ms(3_723_000) == "1:02:03"
    assert format_ms(-5) == "0:00"


def test_main_window_builds(app):
    window = MainWindow(start_triggers=False)
    assert window.play_button.text() == "Play"
    assert window.time_label.text() == "0:00 / 0:00"
    assert not window.video.isVisible()  # hidden until a video source loads


def test_volume_slider_drives_player(app):
    window = MainWindow(start_triggers=False)
    window.volume_slider.setValue(50)
    assert 0.4 < window.player.volume < 0.6


def test_demo_sequence_loads_into_the_engine(app):
    window = MainWindow(start_triggers=False)
    window.build_demo()
    show = window.engine.show
    assert show is not None and show.tracks
    assert window.universe_combo.count() == 1


def test_dmx_panel_builds_each_output_type(app):
    from aion_show_system.dmx import ArtNetOutput, NullOutput, SacnOutput
    from aion_show_system.ui.dmx_panel import ART_NET, DRY_RUN, SACN, DmxPanel

    panel = DmxPanel()
    for label, expected in ((ART_NET, ArtNetOutput), (SACN, SacnOutput), (DRY_RUN, NullOutput)):
        panel.protocol_combo.setCurrentText(label)
        output = panel.build_output()
        assert isinstance(output, expected)
        output.close()


def test_dmx_monitor_maps_points_to_channels(app):
    from aion_show_system.ui.dmx_monitor import DmxMonitor

    monitor = DmxMonitor()
    monitor.resize(320, 160)  # 32 x 16 cells of 10 px
    assert monitor.channel_at(0, 0) == 1
    assert monitor.channel_at(15, 0) == 2
    assert monitor.channel_at(0, 15) == 33
