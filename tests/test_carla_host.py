from pathlib import Path
from typing import Any

import pytest

from ambiance.integrations import carla_host


class _DummyBackend:
    def __init__(self, base_dir=None):
        self.available = True
        self.warnings: list[str] = []
        self._plugin = None
        self.closed = False
        self.load_calls: list[str] = []
        self.show_requests: list[bool] = []
        self.ui_visible = False
        self.supports_ui = True

    def can_handle_path(self, path: Path) -> bool:
        return True

    def status(self) -> dict:
        return {
            "available": True,
            "plugin": self._plugin,
            "parameters": [],
            "capabilities": {"editor": self.supports_ui, "instrument": False},
            "ui_visible": self.ui_visible,
        }

    def load_plugin(self, plugin_path: Path, parameters=None, *, show_ui: bool = False) -> dict:
        self.load_calls.append(str(plugin_path))
        self.show_requests.append(show_ui)
        self._plugin = {"path": str(plugin_path)}
        self.ui_visible = bool(show_ui and self.supports_ui)
        return self._plugin

    def unload(self) -> None:
        self._plugin = None
        self.ui_visible = False

    def set_parameter(self, identifier, value):
        return {"id": identifier, "value": value}

    def describe_ui(self, plugin_path=None):
        return {"plugin": self._plugin, "path": str(plugin_path) if plugin_path else None}

    def show_ui(self) -> dict:
        if not self._plugin:
            raise carla_host.CarlaHostError("No plugin hosted")
        if not self.supports_ui:
            raise carla_host.CarlaHostError("Plugin does not expose a custom UI")
        self.ui_visible = True
        return self.status()

    def hide_ui(self) -> dict:
        if not self._plugin:
            raise carla_host.CarlaHostError("No plugin hosted")
        self.ui_visible = False
        return self.status()

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


class _FailingBackend(_DummyBackend):
    def load_plugin(self, plugin_path: Path, parameters=None, *, show_ui: bool = False) -> dict:
        raise carla_host.CarlaHostError("backend rejected plugin")


def test_dependency_directories_for_vst3_bundle(tmp_path):
    bundle = tmp_path / "Plugin.vst3"
    arch_dir = bundle / "Contents" / "x86_64-win"
    resources_dir = bundle / "Contents" / "Resources"
    arch_dir.mkdir(parents=True)
    resources_dir.mkdir()

    directories = carla_host.CarlaBackend._dependency_directories_for(bundle)

    resolved = {path for path in directories}
    assert bundle.parent.resolve() in resolved
    assert bundle.resolve() in resolved
    assert (bundle / "Contents").resolve() in resolved
    assert arch_dir.resolve() in resolved
    assert resources_dir.resolve() in resolved


def test_dependency_directories_for_dll(tmp_path):
    plugin = tmp_path / "Effect.dll"
    plugin.write_text("stub")

    directories = carla_host.CarlaBackend._dependency_directories_for(plugin)

    assert directories == [tmp_path.resolve()]


def test_register_dependency_directories_tracks_handles(monkeypatch, tmp_path):
    backend = carla_host.CarlaBackend.__new__(carla_host.CarlaBackend)
    backend._dll_directories = {}
    backend.warnings = []

    handles: list[Any] = []

    class _Handle:
        def __init__(self, path: str) -> None:
            self.path = path
            self.closed = False

        def close(self) -> None:
            self.closed = True

    def fake_add_dll_directory(path: str):
        handle = _Handle(path)
        handles.append(handle)
        return handle

    monkeypatch.setattr(carla_host.os, "add_dll_directory", fake_add_dll_directory, raising=False)

    plugin = tmp_path / "Instrument.dll"
    plugin.write_text("stub")

    backend._register_dependency_directories = carla_host.CarlaBackend._register_dependency_directories.__get__(backend, carla_host.CarlaBackend)
    backend._clear_dependency_directories = carla_host.CarlaBackend._clear_dependency_directories.__get__(backend, carla_host.CarlaBackend)
    backend._enable_dll_registration = True

    backend._register_dependency_directories(plugin)

    assert handles and handles[0].path == str(tmp_path.resolve())
    assert Path(handles[0].path) in backend._dll_directories

    backend._clear_dependency_directories()

    assert backend._dll_directories == {}
    assert handles[0].closed is True


def test_carla_vst_host_prefers_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _DummyBackend)
    monkeypatch.setattr(carla_host, "FlutterVSTHost", _DummyFlutterHost)

    plugin_path = tmp_path / "Test.vst3"
    plugin_path.write_text("stub")

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)
    plugin = host.load_plugin(plugin_path)

    assert plugin["path"] == str(plugin_path)
    assert host._backend.load_calls == [str(plugin_path)]
    assert host._backend.show_requests == [True]
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


def test_carla_vst_host_ui_toggle(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _DummyBackend)
    monkeypatch.setattr(carla_host, "FlutterVSTHost", _DummyFlutterHost)

    plugin_path = tmp_path / "UiPlugin.vst3"
    plugin_path.write_text("stub")

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)
    host.load_plugin(plugin_path)

    status = host.show_ui()
    assert status["ui_visible"] is True

    status = host.hide_ui()
    assert status["ui_visible"] is False


def test_carla_vst_host_propagates_backend_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(carla_host, "CarlaBackend", _FailingBackend)
    monkeypatch.setattr(carla_host, "FlutterVSTHost", _DummyFlutterHost)

    plugin_path = tmp_path / "Broken.vst3"
    plugin_path.write_text("stub")

    host = carla_host.CarlaVSTHost(base_dir=tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        host.load_plugin(plugin_path)

    assert "backend rejected plugin" in str(excinfo.value)
    assert host._active is None
    assert host._fallback.loaded == []
