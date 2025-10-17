from pathlib import Path

import pytest

from ambiance.integrations.flutter_vst_host import FlutterVSTHost, FlutterVSTToolkit
from ambiance.npcompat import np


def test_toolkit_discovery():
    toolkit = FlutterVSTToolkit.discover(Path(__file__).resolve().parents[1])
    assert toolkit.root is not None
    assert toolkit.available is True
    assert toolkit.metadata_for_plugin_path(Path('Echo.vst3')).name.lower().startswith('echo')


def test_host_load_and_preview(tmp_path):
    plugin_path = tmp_path / "Echo.vst3"
    plugin_path.mkdir()

    host = FlutterVSTHost(base_dir=Path(__file__).resolve().parents[1])
    plugin = host.load_plugin(plugin_path)

    assert plugin["metadata"]["name"].lower().startswith("echo")

    status = host.status()
    assert status["plugin"] is not None
    params = {param["name"]: param["value"] for param in status["parameters"]}
    assert "mix" in params

    host.set_parameter("mix", 0.8)
    updated = host.status()
    mix_value = next(param for param in updated["parameters"] if param["name"] == "mix")
    assert mix_value["value"] == 0.8

    preview = host.render_preview(duration=0.05, sample_rate=44100)
    assert isinstance(preview, np.ndarray)
    assert np.max(np.abs(preview)) > 0

    host.unload()
    assert host.status()["plugin"] is None


def test_host_fallback_metadata(tmp_path):
    plugin_path = tmp_path / "Mystery.vst3"
    plugin_path.mkdir()

    toolkit = FlutterVSTToolkit(None)
    host = FlutterVSTHost(toolkit=toolkit)

    plugin = host.load_plugin(plugin_path)
    assert plugin["metadata"]["name"] == "Mystery"

    buffer = host.render_preview(duration=0.01, sample_rate=44100)
    assert buffer.shape[0] > 0


def test_render_note_with_plugin(tmp_path):
    plugin_path = tmp_path / "Echo.vst3"
    plugin_path.mkdir()

    host = FlutterVSTHost(base_dir=Path(__file__).resolve().parents[1])
    host.load_plugin(plugin_path)

    note = host.render_note("C4", duration=0.1, sample_rate=16000, waveform="square")
    assert isinstance(note, np.ndarray)
    assert note.shape[0] == int(0.1 * 16000)
    assert np.max(np.abs(note)) > 0


def test_render_note_without_plugin():
    host = FlutterVSTHost(toolkit=FlutterVSTToolkit(None))
    note = host.render_note("A4", duration=0.05, sample_rate=8000)
    assert note.shape[0] == int(0.05 * 8000)
    assert np.max(np.abs(note)) > 0


def test_render_note_invalid_note():
    host = FlutterVSTHost(toolkit=FlutterVSTToolkit(None))
    with pytest.raises(ValueError):
        host.render_note("H2")
