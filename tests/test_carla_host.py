from pathlib import Path


from ambiance.integrations import carla_host


class _DummyBackend:
    def __init__(self, base_dir=None):
        self.available = True
        self.warnings: list[str] = []
        self._plugin = None
        self.closed = False
        self.load_calls: list[str] = []

    def can_handle_path(self, path: Path) -> bool:
        return True

    def status(self) -> dict:
        return {"available": True, "plugin": self._plugin, "parameters": []}

    def load_plugin(self, plugin_path: Path, parameters=None) -> dict:
        self.load_calls.append(str(plugin_path))
        self._plugin = {"path": str(plugin_path)}
        return self._plugin

    def unload(self) -> None:
        self._plugin = None

    def set_parameter(self, identifier, value):
        return {"id": identifier, "value": value}

    def describe_ui(self, plugin_path=None):
        return {"plugin": self._plugin, "path": str(plugin_path) if plugin_path else None}

    def close(self) -> None:
        self.closed = True
        self.unload()


class _DummyFlutterHost:
    def __init__(self, base_dir=None):
        self.loaded: list[Path] = []

    def status(self) -> dict:
        return {"available": False, "plugin": None, "parameters": []}

    def load_plugin(self, plugin_path, parameters=None):
        self.loaded.append(Path(plugin_path))
        return {"path": str(plugin_path)}

    def unload(self) -> None:
        self.loaded.clear()

    def set_parameter(self, identifier, value):
        return {"id": identifier, "value": value}

    def describe_ui(self, plugin_path=None):
        return {"path": str(plugin_path) if plugin_path else None}


def test_carla_vst_host_prefers_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _DummyBackend)
    monkeypatch.setattr(carla_host, "FlutterVSTHost", _DummyFlutterHost)

    plugin_path = tmp_path / "Test.vst3"
    plugin_path.write_text("stub")

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)
    plugin = host.load_plugin(plugin_path)

    assert plugin["path"] == str(plugin_path)
    assert host._backend.load_calls == [str(plugin_path)]
    assert host._active == "carla"
    assert not host._fallback.loaded


def test_carla_vst_host_shutdown(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _DummyBackend)
    monkeypatch.setattr(carla_host, "FlutterVSTHost", _DummyFlutterHost)

    plugin_path = tmp_path / "Another.vst3"
    plugin_path.write_text("stub")

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)
    host.load_plugin(plugin_path)
    host.shutdown()

    assert host._backend.closed is True
    assert host._backend.status()["plugin"] is None
    assert host._fallback.loaded == []
