"""Carla-backed VST host integration.

This module embeds the Carla backend into the Ambiance runtime so real VST2 and
VST3 plug-ins can be discovered and manipulated from the Python process.  The
implementation favours a pure Python bridge using Carla's ``libcarla`` shared
library which ships with the Carla source tree bundled in this repository.

The goal is to expose an API compatible with :class:`FlutterVSTHost` so the
existing HTTP server and UI can control either implementation transparently.
If Carla is not available (because the shared library has not been built yet)
we fall back to the Flutter shim, ensuring the rest of Ambiance keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from .flutter_vst_host import FlutterVSTHost


class CarlaHostError(RuntimeError):
    """Raised when the Carla backend cannot perform the requested action."""


@dataclass(frozen=True, slots=True)
class CarlaParameterSnapshot:
    """Lightweight representation of a Carla parameter."""

    identifier: int
    name: str
    display_name: str
    units: str
    default: float
    minimum: float
    maximum: float
    step: float
    value: float
    description: str = ""

    def to_status_entry(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "name": self.name,
            "display_name": self.display_name or self.name,
            "description": self.description,
            "units": self.units,
            "default": self.default,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "value": self.value,
        }

    def to_metadata_entry(self) -> dict[str, Any]:
        payload = self.to_status_entry()
        payload.pop("value", None)
        return payload


class CarlaBackend:
    """Thin wrapper around Carla's ``libcarla_standalone2`` shared library."""

    _PLUGIN_TYPE_LABELS = {
        5: "VST2",
        6: "VST3",
    }

    _PLUGIN_CATEGORY_LABELS = {
        0: "Unknown",
        1: "Synth",
        2: "Delay",
        3: "EQ",
        4: "Filter",
        5: "Distortion",
        6: "Dynamics",
        7: "Modulator",
        8: "Utility",
        9: "Other",
    }

    _PREFERRED_DRIVERS = (
        "Dummy",
        "JACK",
        "ALSA",
        "PulseAudio",
        "CoreAudio",
        "DirectSound",
        "WASAPI",
        "PortAudio",
    )

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
        self.root = self._discover_root()
        self.library_path: Path | None = None
        self.module: ModuleType | None = None
        self.host: Any | None = None
        self.available = False
        self.warnings: list[str] = []
        self._engine_running = False
        self._driver_name: str | None = None
        self._lock = threading.RLock()
        self._plugin_id: int | None = None
        self._plugin_path: Path | None = None
        self._parameters: list[CarlaParameterSnapshot] = []

        if not self.root:
            self.warnings.append("Carla source tree not found – set CARLA_ROOT")
            return

        try:
            self.library_path = self._locate_library(self.root)
        except FileNotFoundError as exc:  # pragma: no cover - depends on build artefacts
            self.warnings.append(str(exc))
            return

        try:
            self.module = self._load_backend_module(self.root)
        except Exception as exc:  # pragma: no cover - import errors surfaced to user
            self.warnings.append(f"Failed to import Carla backend: {exc}")
            return

        try:
            assert self.module is not None
            self.host = self.module.CarlaHostDLL(str(self.library_path), True)
        except Exception as exc:  # pragma: no cover - depends on shared library availability
            self.warnings.append(f"Failed to load libcarla: {exc}")
            self.host = None
            return

        self.available = True

    # ------------------------------------------------------------------
    # Discovery helpers
    def _discover_root(self) -> Path | None:
        env = (Path(p).expanduser() for p in (
            os.environ.get("CARLA_ROOT"),
            os.environ.get("CARLA_HOME"),
        ) if p)
        for candidate in env:
            if candidate.exists():
                return candidate
        default = self.base_dir / "Carla-main"
        return default if default.exists() else None

    def _locate_library(self, root: Path) -> Path:
        names = (
            "libcarla_standalone2.so",
            "libcarla_standalone2.dylib",
            "libcarla_standalone2.dll",
        )
        search_roots = [root / "bin", root / "build", root]
        for directory in search_roots:
            for name in names:
                candidate = directory / name
                if candidate.exists():
                    return candidate
        for name in names:  # fallback to a bounded glob search
            matches = list(root.glob(f"**/{name}"))
            if matches:
                return matches[0]
        raise FileNotFoundError("libcarla_standalone2 library not found; build Carla first")

    def _load_backend_module(self, root: Path) -> ModuleType:
        frontend = root / "source" / "frontend"
        module_path = frontend / "carla_backend.py"
        if not module_path.exists():
            raise FileNotFoundError(f"carla_backend.py missing at {module_path}")
        sys.path.insert(0, str(frontend))
        try:
            spec = importlib.util.spec_from_file_location("ambiance_carla_backend", module_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Unable to load spec for {module_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        finally:
            try:
                sys.path.remove(str(frontend))
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Engine lifecycle
    def _ensure_engine(self) -> None:
        if not self.available or self.host is None:
            raise CarlaHostError("Carla backend is not available")
        if self._engine_running:
            return
        driver = self._select_driver()
        if not driver:
            raise CarlaHostError("No usable Carla audio driver found")
        if not self.host.engine_init(driver, "AmbianceCarlaHost"):
            message = self.host.get_last_error() if hasattr(self.host, "get_last_error") else "unknown error"
            raise CarlaHostError(f"Failed to initialise Carla engine: {message}")
        self._driver_name = driver
        self._engine_running = True

    def _select_driver(self) -> str | None:
        assert self.host is not None
        try:
            count = int(self.host.get_engine_driver_count())
        except Exception as exc:  # pragma: no cover - depends on libcarla
            self.warnings.append(f"Unable to enumerate Carla drivers: {exc}")
            return None
        names: list[str] = []
        for index in range(count):
            try:
                name = self.host.get_engine_driver_name(index)
            except Exception:  # pragma: no cover - defensive
                continue
            if not isinstance(name, str):
                continue
            names.append(name)
        for preferred in self._PREFERRED_DRIVERS:
            for candidate in names:
                if candidate.lower() == preferred.lower():
                    return candidate
        return names[0] if names else None

    # ------------------------------------------------------------------
    # Public API
    def can_handle_path(self, plugin_path: Path) -> bool:
        suffix = plugin_path.suffix.lower()
        if suffix == ".vst3":
            return True
        if suffix in {".vst", ".dll", ".so", ".dylib"}:
            return True
        return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
                "available": self.available,
                "toolkit_path": str(self.root) if self.root else None,
                "engine_path": str(self.library_path) if self.library_path else None,
                "warnings": list(self.warnings),
            }
            if self._driver_name:
                payload["driver"] = self._driver_name
            if self._plugin_id is None:
                payload["plugin"] = None
                payload["parameters"] = []
            else:
                payload["plugin"] = self._plugin_payload()
                payload["parameters"] = [param.to_status_entry() for param in self._parameters]
            return payload

    def load_plugin(self, plugin_path: str | Path, parameters: dict[str, float] | None = None) -> dict[str, Any]:
        path = Path(plugin_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Plugin not found: {path}")
        with self._lock:
            if not self.can_handle_path(path):
                raise CarlaHostError(f"Unsupported plugin format: {path.suffix}")
            self._ensure_engine()
            assert self.host is not None
            self.host.remove_all_plugins()
            plugin_type = self._plugin_type_for(path)
            if plugin_type is None:
                raise CarlaHostError(f"Unsupported plugin type for {path}")
            added = self.host.add_plugin(
                self.module.BINARY_NATIVE if self.module else 0,
                plugin_type,
                str(path),
                path.stem,
                path.stem,
                0,
                None,
                0,
            )
            if not added:
                message = self.host.get_last_error() if hasattr(self.host, "get_last_error") else "unknown"
                raise CarlaHostError(f"Failed to load plugin: {message}")
            self._plugin_id = 0
            self._plugin_path = path
            self._parameters = self._collect_parameters()
            if parameters:
                for key, value in parameters.items():
                    try:
                        self.set_parameter(key, float(value))
                    except CarlaHostError:
                        continue
            return self._plugin_payload()

    def unload(self) -> None:
        with self._lock:
            if not self.available or self.host is None:
                return
            if self._plugin_id is not None:
                self.host.remove_all_plugins()
            self._plugin_id = None
            self._plugin_path = None
            self._parameters = []

    def set_parameter(self, identifier: int | str, value: float) -> dict[str, Any]:
        with self._lock:
            if self._plugin_id is None or self.host is None:
                raise CarlaHostError("No plugin hosted")
            param_id = self._resolve_parameter_identifier(identifier)
            self.host.set_parameter_value(self._plugin_id, param_id, float(value))
            for index, param in enumerate(self._parameters):
                if param.identifier == param_id:
                    self._parameters[index] = CarlaParameterSnapshot(
                        identifier=param.identifier,
                        name=param.name,
                        display_name=param.display_name,
                        units=param.units,
                        default=param.default,
                        minimum=param.minimum,
                        maximum=param.maximum,
                        step=param.step,
                        value=float(value),
                        description=param.description,
                    )
                    break
            return {
                "plugin": self._plugin_payload(),
                "parameters": [param.to_status_entry() for param in self._parameters],
            }

    def describe_ui(self, plugin_path: str | Path | None = None) -> dict[str, Any]:
        with self._lock:
            if plugin_path is None:
                if self._plugin_id is None:
                    raise CarlaHostError("No plugin hosted")
                return self._build_descriptor()

            path = Path(plugin_path).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"Plugin not found: {path}")
            if not self.can_handle_path(path):
                raise CarlaHostError(f"Unsupported plugin format: {path.suffix}")

            state = self._snapshot_state()
            try:
                self.load_plugin(path)
                return self._build_descriptor()
            finally:
                self._restore_state(state)

    # ------------------------------------------------------------------
    # Internal helpers
    def _plugin_type_for(self, path: Path) -> int | None:
        suffix = path.suffix.lower()
        if suffix == ".vst3":
            return getattr(self.module, "PLUGIN_VST3", 6)
        if suffix in {".vst", ".dll", ".so", ".dylib"}:
            return getattr(self.module, "PLUGIN_VST2", 5)
        return None

    def _collect_parameters(self) -> list[CarlaParameterSnapshot]:
        assert self.host is not None
        if self._plugin_id is None:
            return []
        count = int(self.host.get_parameter_count(self._plugin_id))
        results: list[CarlaParameterSnapshot] = []
        for index in range(count):
            info = self.host.get_parameter_info(self._plugin_id, index)
            ranges = self.host.get_parameter_ranges(self._plugin_id, index)
            value = float(self.host.get_current_parameter_value(self._plugin_id, index))
            name = info.get("name") or f"Parameter {index}"
            display_name = info.get("symbol") or name
            units = info.get("unit") or ""
            results.append(
                CarlaParameterSnapshot(
                    identifier=index,
                    name=name,
                    display_name=display_name,
                    units=units,
                    default=float(ranges.get("def", 0.0)),
                    minimum=float(ranges.get("min", 0.0)),
                    maximum=float(ranges.get("max", 1.0)),
                    step=float(ranges.get("step", 0.01)),
                    value=value,
                    description=info.get("comment") or "",
                )
            )
        return results

    def _resolve_parameter_identifier(self, identifier: int | str) -> int:
        if isinstance(identifier, int):
            return identifier
        try:
            index = int(identifier)
        except (TypeError, ValueError):
            index = None
        for param in self._parameters:
            if identifier == param.name or identifier == param.display_name:
                return param.identifier
            if index is not None and param.identifier == index:
                return param.identifier
        raise CarlaHostError(f"Unknown parameter '{identifier}'")

    def _plugin_payload(self) -> dict[str, Any]:
        assert self.host is not None
        if self._plugin_id is None or self._plugin_path is None:
            raise CarlaHostError("No plugin hosted")
        info = self.host.get_plugin_info(self._plugin_id)
        metadata = {
            "name": info.get("name") or self._plugin_path.stem,
            "vendor": info.get("maker") or "",
            "version": "",
            "category": self._PLUGIN_CATEGORY_LABELS.get(info.get("category", 0), "Unknown"),
            "bundle_identifier": None,
            "parameters": [param.to_metadata_entry() for param in self._parameters],
            "format": self._PLUGIN_TYPE_LABELS.get(info.get("type", 0), "Unknown"),
        }
        payload = {
            "path": str(self._plugin_path),
            "metadata": metadata,
            "parameters": [param.to_status_entry() for param in self._parameters],
        }
        return payload

    def _build_descriptor(self) -> dict[str, Any]:
        plugin = self._plugin_payload()
        controls = []
        for param in self._parameters:
            control = {
                "id": param.identifier,
                "name": param.display_name or param.name,
                "label": param.display_name or param.name,
                "type": "slider",
                "min": param.minimum,
                "max": param.maximum,
                "step": param.step,
                "units": param.units,
                "value": param.value,
            }
            controls.append(control)
        descriptor = {
            "title": plugin["metadata"].get("name", plugin.get("path")),
            "subtitle": plugin["metadata"].get("vendor", ""),
            "keyboard": {"min_note": 36, "max_note": 84},
            "panels": [{"name": "Parameters", "controls": controls}],
            "parameters": [param.to_status_entry() for param in self._parameters],
            "plugin": plugin,
            "capabilities": {
                "instrument": self._plugin_is_instrument(),
            },
        }
        return descriptor

    def _plugin_is_instrument(self) -> bool:
        if self.host is None or self._plugin_id is None:
            return False
        info = self.host.get_plugin_info(self._plugin_id)
        hints = int(info.get("hints", 0))
        flag = getattr(self.module, "PLUGIN_IS_SYNTH", 0x004) if self.module else 0x004
        return bool(hints & flag)

    def _snapshot_state(self) -> dict[str, Any] | None:
        if self._plugin_id is None or self._plugin_path is None:
            return None
        return {
            "path": str(self._plugin_path),
            "parameters": {param.identifier: param.value for param in self._parameters},
        }

    def _restore_state(self, state: dict[str, Any] | None) -> None:
        if state is None:
            self.unload()
            return
        try:
            self.load_plugin(state["path"], state.get("parameters"))
        except Exception as exc:  # pragma: no cover - best effort restore
            self.warnings.append(f"Failed to restore Carla plugin state: {exc}")


class CarlaVSTHost:
    """Facade that prefers Carla but falls back to the Flutter shim."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2]
        self._backend = CarlaBackend(base_dir=self.base_dir)
        self._fallback = FlutterVSTHost(base_dir=self.base_dir)
        self._lock = threading.RLock()
        self._active: str | None = None

    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._active == "carla" or (self._backend.available and self._active is None):
                status = self._backend.status()
                if self._active != "carla" and status.get("plugin") is None:
                    status.setdefault("warnings", []).append("Carla backend idle")
                return status
            status = self._fallback.status()
            if not self._backend.available:
                status.setdefault("warnings", []).extend(self._backend.warnings)
            else:
                status.setdefault("warnings", []).append("Using Flutter fallback host")
            return status

    def load_plugin(self, plugin_path: str | Path, parameters: dict[str, float] | None = None) -> dict[str, Any]:
        with self._lock:
            path = Path(plugin_path).expanduser()
            if self._backend.available and self._backend.can_handle_path(path):
                try:
                    plugin = self._backend.load_plugin(path, parameters)
                    self._fallback.unload()
                    self._active = "carla"
                    return plugin
                except (CarlaHostError, OSError) as exc:
                    self._backend.warnings.append(str(exc))
            plugin = self._fallback.load_plugin(path, parameters)
            self._active = "flutter"
            return plugin

    def unload(self) -> None:
        with self._lock:
            if self._active == "carla":
                self._backend.unload()
            elif self._active == "flutter":
                self._fallback.unload()
            else:
                self._backend.unload()
                self._fallback.unload()
            self._active = None

    def set_parameter(self, identifier: int | str, value: float) -> dict[str, Any]:
        with self._lock:
            if self._active == "carla":
                return self._backend.set_parameter(identifier, value)
            if self._active == "flutter":
                return self._fallback.set_parameter(identifier, value)
            raise RuntimeError("No plugin hosted")

    def render_preview(self, duration: float = 1.5, sample_rate: int = 44100):
        with self._lock:
            if self._active == "carla":
                raise RuntimeError(
                    "Carla backend does not support offline rendering in this environment"
                )
            return self._fallback.render_preview(duration=duration, sample_rate=sample_rate)

    def play_note(
        self,
        note: int,
        *,
        velocity: float = 0.8,
        duration: float = 1.0,
        sample_rate: int = 44100,
    ):
        with self._lock:
            if self._active == "carla":
                raise RuntimeError(
                    "Carla backend does not expose MIDI playback in this environment"
                )
            return self._fallback.play_note(
                note,
                velocity=velocity,
                duration=duration,
                sample_rate=sample_rate,
            )

    def describe_ui(self, plugin_path: str | Path | None = None) -> dict[str, Any]:
        with self._lock:
            if plugin_path is not None:
                path = Path(plugin_path).expanduser()
                if self._backend.available and self._backend.can_handle_path(path):
                    try:
                        return self._backend.describe_ui(path)
                    except CarlaHostError as exc:
                        self._backend.warnings.append(str(exc))
                return self._fallback.describe_ui(plugin_path)
            if self._active == "carla":
                return self._backend.describe_ui()
            if self._active == "flutter":
                return self._fallback.describe_ui()
            raise RuntimeError("No plugin hosted")


__all__ = ["CarlaVSTHost", "CarlaHostError"]

