import zipfile

import math
import struct
import wave

from ambiance.integrations.plugins import PluginRackManager


def write_preview_wav(path, seconds: float = 0.12, freq: float = 330.0, sample_rate: int = 44100) -> None:
    total = int(sample_rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for n in range(total):
            value = int(32767 * math.sin(2 * math.pi * freq * (n / sample_rate)))
            frames.extend(struct.pack("<h", value))
        wf.writeframes(bytes(frames))


def test_status_reports_workspace(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)

    status = manager.status()

    assert status["workspace"] == str(manager.workspace_path())
    assert status["workspace_exists"] is True
    assert status["plugins"] == []
    assert "Main" in status["streams"]


def test_discover_plugins(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()

    dream = workspace / "DreamSynth.vst3"
    dream.mkdir(parents=True)
    write_preview_wav(dream / "render.wav")
    (workspace / "textures.mc.svt").write_text("dummy")
    (workspace / "retro.dll").write_bytes(b"stub")
    (workspace / "EchoChamber.vst").write_bytes(b"plug")

    entries = manager.discover_plugins()
    names = {entry["name"] for entry in entries}

    assert "DreamSynth" in names
    assert "textures" in names
    assert any(name.lower() == "retro" for name in names)
    assert "EchoChamber" in names

    dream_entry = next(entry for entry in entries if entry["name"] == "DreamSynth")
    assert dream_entry.get("render_preview")
    assert any(entry["path"].endswith("retro.dll") for entry in entries)
    assert any(entry["path"].endswith("EchoChamber.vst") for entry in entries)


def test_assign_and_toggle(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()
    plugin = workspace / "bassline.vst3"
    plugin.mkdir()

    result = manager.assign_plugin(plugin, stream="Bass", lane="A")

    assert result["stream"] == "Bass"
    assert result["lane"] == "A"
    status = manager.status()
    lane_entries = status["streams"]["Bass"]["lanes"]["A"]
    assert lane_entries and lane_entries[0]["plugin"]["path"] == str(plugin)

    toggle = manager.toggle_lane("Bass")
    assert toggle["active_lane"] == "B"


def test_plugin_preview_payload(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()
    plugin = workspace / "atmos.vst3"
    plugin.mkdir()
    preview = plugin / "preview.wav"
    write_preview_wav(preview, seconds=0.2, freq=220.0)

    payload = manager.plugin_preview(plugin)

    assert payload["audio"].startswith("data:audio/wav;base64,")
    assert payload["duration"] > 0
    assert payload["channels"] == 1
    assert payload["relative_path"].endswith("atmos.vst3/preview.wav")


def test_remove_plugin(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()
    plugin = workspace / "pad.svt"
    plugin.write_text("data")

    manager.assign_plugin(plugin, stream="Main", lane="B", slot=3)
    removed = manager.remove_plugin(stream="Main", lane="B", slot=3)

    assert removed["removed"]
    status = manager.status()
    assert status["streams"]["Main"]["lanes"]["B"] == []


def test_assign_plugin_with_relative_path(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()
    plugin = workspace / "dream.vst3"
    plugin.mkdir()

    result = manager.assign_plugin("dream.vst3", stream="Dreams", lane="B")

    assert result["stream"] == "Dreams"
    status = manager.status()
    dream_lane = status["streams"]["Dreams"]["lanes"]["B"]
    assert dream_lane and dream_lane[0]["plugin"]["path"].endswith("dream.vst3")


def test_remove_plugin_with_relative_path(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()
    plugin = workspace / "texture.vst3"
    plugin.mkdir()

    manager.assign_plugin(plugin, stream="Textures", lane="A", slot=1)
    removed = manager.remove_plugin(stream="Textures", lane="A", path="texture.vst3")

    assert removed["removed"]
    status = manager.status()
    assert status["streams"]["Textures"]["lanes"]["A"] == []


def test_modalys_bundle_installation(tmp_path):
    archive = tmp_path / "Modalys Bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Modalys for Max/externals/mlys~.mxe64", b"stub")

    manager = PluginRackManager(base_dir=tmp_path)

    plugin_file = manager.workspace_path() / "Modalys" / "Modalys.mxe64"
    assert plugin_file.exists()

    entries = manager.discover_plugins()
    modalys = next((entry for entry in entries if "Modalys" in entry["name"]), None)

    assert modalys is not None
    assert modalys.get("origin") == "Bundled Modalys package"
    assert modalys.get("display_name") == "Modalys (Max)"

    notes = manager.status()["notes"]
    assert any("Modalys" in note for note in notes)


def test_assign_mixed_plugin_formats(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()

    windows = workspace / "Vibrant.dll"
    windows.write_bytes(b"stub")
    classic = workspace / "TapeEcho.vst"
    classic.write_bytes(b"plug")

    manager.assign_plugin(windows, stream="Instrument", lane="A")
    manager.assign_plugin("TapeEcho.vst", stream="Instrument", lane="B")

    status = manager.status()
    instrument = status["streams"]["Instrument"]
    lane_a = instrument["lanes"]["A"][0]
    lane_b = instrument["lanes"]["B"][0]

    assert lane_a["plugin"]["path"].endswith("Vibrant.dll")
    assert lane_b["plugin"]["path"].endswith("TapeEcho.vst")


def test_detect_flutter_vst3(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()

    bundle = workspace / "FlutterDream.vst3"
    assets = bundle / "Contents" / "Resources" / "flutter_assets"
    assets.mkdir(parents=True)
    (assets / "AssetManifest.json").write_text("{}")
    (assets / "pubspec.yaml").write_text(
        "\n".join(
            [
                "name: flutter_dream",
                "description: Dreamy Flutter-driven synthesizer",
                "homepage: https://example.com/flutter_dream",
                "flutter:",
                "  uses-material-design: true",
            ]
        )
    )

    entries = manager.discover_plugins()
    flutter_entry = next(entry for entry in entries if entry.get("name") == "flutter_dream")

    assert flutter_entry["format"] == "Flutter VST3"
    assert flutter_entry.get("flutter")
    assert flutter_entry["flutter"].get("assets_relative", "").endswith(
        "FlutterDream.vst3/Contents/Resources/flutter_assets"
    )
    assert any("Flutter" in note for note in flutter_entry.get("notes", []))

    status = manager.status()
    assert any("Flutter/Dart VST3" in note for note in status["notes"])


def test_flutter_toolkit_archive_unpack(tmp_path):
    manager = PluginRackManager(base_dir=tmp_path)
    workspace = manager.workspace_path()

    archive = workspace / "flutter_vst3_toolkit.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("flutter_vst3_toolkit/README.md", "Toolkit docs")
        zf.writestr("flutter_vst3_toolkit/flutter_assets/placeholder.txt", "asset")

    status = manager.status()
    toolkit = status.get("flutter_toolkit")

    assert toolkit
    assert toolkit.get("present") is True
    assert toolkit.get("ready") is True
    assert toolkit.get("archive", "").endswith("flutter_vst3_toolkit.zip")
    assert toolkit.get("directory")
    assert toolkit.get("assets")
    assert any("toolkit" in note.lower() for note in toolkit.get("notes", []))
