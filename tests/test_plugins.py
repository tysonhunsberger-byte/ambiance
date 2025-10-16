from ambiance.integrations.plugins import PluginRackManager


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

    (workspace / "DreamSynth.vst3").mkdir(parents=True)
    (workspace / "textures.mc.svt").write_text("dummy")

    entries = manager.discover_plugins()
    names = {entry["name"] for entry in entries}

    assert "DreamSynth" in names
    assert "textures" in names


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
