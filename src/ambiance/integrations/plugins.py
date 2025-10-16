"""Plugin discovery and lightweight hosting utilities."""

from __future__ import annotations

import json
import math
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, MutableMapping, Sequence

from ..npcompat import np

try:  # pragma: no cover - optional dependency
    from pedalboard import Pedalboard, load_plugin  # type: ignore
except Exception:  # pragma: no cover - graceful optional import
    Pedalboard = None  # type: ignore[assignment]
    load_plugin = None  # type: ignore[assignment]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "plugin"


class BuiltinProcessor:
    """Simple base class for built-in processors that mimic plugins."""

    def process(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def to_params(self) -> dict[str, Any]:  # pragma: no cover - interface
        return {}


class GainProcessor(BuiltinProcessor):
    """Apply a constant gain in dB."""

    def __init__(self, gain_db: float = 0.0) -> None:
        self.gain_db = float(gain_db)

    def process(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:  # noqa: ARG002 - sample_rate unused
        factor = math.pow(10.0, self.gain_db / 20.0)
        return (buffer * factor).astype(np.float32)

    def to_params(self) -> dict[str, float]:
        return {"gain_db": self.gain_db}


class HighPassProcessor(BuiltinProcessor):
    """Simple one-pole high-pass filter for utility sculpting."""

    def __init__(self, cutoff_hz: float = 120.0) -> None:
        self.cutoff_hz = max(5.0, float(cutoff_hz))
        self._prev_x = 0.0
        self._prev_y = 0.0

    def process(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        rc = 1.0 / (2.0 * math.pi * self.cutoff_hz)
        dt = 1.0 / float(sample_rate)
        alpha = rc / (rc + dt)
        out = np.zeros_like(buffer, dtype=np.float32)
        prev_y = float(self._prev_y)
        prev_x = float(self._prev_x)
        for idx, value in enumerate(buffer.tolist()):
            y = alpha * (prev_y + value - prev_x)
            out[idx] = y
            prev_y = y
            prev_x = value
        self._prev_y = prev_y
        self._prev_x = prev_x
        return out

    def to_params(self) -> dict[str, float]:
        return {"cutoff_hz": self.cutoff_hz}


BUILTIN_DEFINITIONS: dict[str, dict[str, Any]] = {
    "builtin-gain": {
        "name": "Gain Trim",
        "format": "builtin",
        "factory": GainProcessor,
        "metadata": {"category": "Utility", "parameters": ["gain_db"]},
    },
    "builtin-highpass": {
        "name": "High-Pass",
        "format": "builtin",
        "factory": HighPassProcessor,
        "metadata": {"category": "Filter", "parameters": ["cutoff_hz"]},
    },
}


@dataclass
class PluginDescriptor:
    """Metadata describing a discovered plugin."""

    slug: str
    name: str
    format: str
    kind: str = "external"
    path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def exists(self) -> bool:
        if self.kind == "builtin":
            return True
        return bool(self.path and self.path.exists())

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "slug": self.slug,
            "name": self.name,
            "format": self.format,
            "kind": self.kind,
            "metadata": dict(self.metadata),
        }
        if self.path is not None:
            payload["path"] = str(self.path)
        payload["available"] = self.exists()
        return payload


@dataclass
class PluginSlot:
    """A plugin assignment inside a chain."""

    descriptor: PluginDescriptor
    params: dict[str, Any] = field(default_factory=dict)

    def to_config(self) -> dict[str, Any]:
        data = {"slug": self.descriptor.slug}
        if self.params:
            data["params"] = dict(self.params)
        return data


@dataclass
class PluginChain:
    """Ordered collection of plugins for a single stream."""

    slots: list[PluginSlot] = field(default_factory=list)

    def to_config(self) -> list[dict[str, Any]]:
        return [slot.to_config() for slot in self.slots]


@dataclass
class PluginBank:
    name: str
    streams: dict[str, PluginChain] = field(default_factory=dict)

    def to_config(self) -> dict[str, list[dict[str, Any]]]:
        return {stream: chain.to_config() for stream, chain in self.streams.items()}


@dataclass
class PluginRack:
    """Holds plugin chains for multiple banks and streams."""

    banks: dict[str, PluginBank] = field(default_factory=dict)
    active_bank: str = "A"
    host: "PluginHost" | None = None

    def to_config(self) -> dict[str, Any]:
        return {
            "active_bank": self.active_bank,
            "banks": {name: bank.to_config() for name, bank in self.banks.items()},
        }

    def with_host(self, host: "PluginHost" | None) -> "PluginRack":
        self.host = host
        return self

    def set_active_bank(self, bank: str) -> None:
        if bank in self.banks:
            self.active_bank = bank

    # --- Processing -------------------------------------------------
    def _active_bank(self) -> PluginBank | None:
        return self.banks.get(self.active_bank)

    def _chain_for(self, stream: str) -> PluginChain | None:
        bank = self._active_bank()
        if not bank:
            return None
        if stream in bank.streams:
            return bank.streams[stream]
        return bank.streams.get("*")

    def process_stream(self, stream: str, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        if not self.host:
            return buffer
        chain = self._chain_for(stream)
        if not chain or not chain.slots:
            return buffer
        return self.host.process_chain(chain, buffer, sample_rate)

    def process_master(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        return self.process_stream("master", buffer, sample_rate)

    # --- Construction -----------------------------------------------
    @classmethod
    def from_config(
        cls,
        config: MutableMapping[str, Any] | None,
        *,
        library: "PluginLibrary",
        host: "PluginHost" | None = None,
    ) -> "PluginRack":
        if config is None:
            config = {}
        active = str(config.get("active_bank", "A"))
        banks_payload = config.get("banks", {}) or {}
        banks: dict[str, PluginBank] = {}
        for name, bank_data in banks_payload.items():
            streams: dict[str, PluginChain] = {}
            stream_map = bank_data.get("streams") if isinstance(bank_data, dict) else bank_data
            if not isinstance(stream_map, dict):
                stream_map = {}
            for stream_name, slot_defs in stream_map.items():
                chain_slots: list[PluginSlot] = []
                for slot_def in slot_defs or []:
                    slug = slot_def.get("slug") if isinstance(slot_def, dict) else None
                    if not slug:
                        continue
                    descriptor = library.get(slug)
                    if not descriptor:
                        continue
                    params = slot_def.get("params") if isinstance(slot_def, dict) else None
                    chain_slots.append(PluginSlot(descriptor=descriptor, params=dict(params or {})))
                if chain_slots:
                    streams[stream_name] = PluginChain(slots=chain_slots)
            banks[name] = PluginBank(name=name, streams=streams)
        rack = cls(banks=banks, active_bank=active)
        return rack.with_host(host)


class PluginLibrary:
    """Persistent catalog of available plugins."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._library_path = self.cache_dir / "plugins.json"
        self._descriptors: dict[str, PluginDescriptor] = {}
        self._load()
        self._ensure_builtins()
        self._save()

    # --- Persistence ------------------------------------------------
    def _load(self) -> None:
        if not self._library_path.exists():
            return
        data = json.loads(self._library_path.read_text(encoding="utf-8"))
        for item in data.get("plugins", []):
            slug = item.get("slug")
            name = item.get("name")
            fmt = item.get("format", "unknown")
            kind = item.get("kind", "external")
            path = item.get("path")
            descriptor = PluginDescriptor(
                slug=slug or _slugify(name or "plugin"),
                name=name or slug or "Unnamed Plugin",
                format=fmt,
                kind=kind,
                path=Path(path) if path else None,
                metadata=item.get("metadata") or {},
            )
            self._descriptors[descriptor.slug] = descriptor

    def _save(self) -> None:
        payload = {
            "plugins": [descriptor.to_payload() for descriptor in self._descriptors.values()],
        }
        self._library_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _ensure_builtins(self) -> None:
        for slug, info in BUILTIN_DEFINITIONS.items():
            if slug in self._descriptors:
                continue
            self._descriptors[slug] = PluginDescriptor(
                slug=slug,
                name=info["name"],
                format=info["format"],
                kind="builtin",
                metadata=info.get("metadata", {}),
            )

    # --- Query ------------------------------------------------------
    def list(self) -> list[PluginDescriptor]:
        return sorted(self._descriptors.values(), key=lambda item: item.name.lower())

    def get(self, slug: str) -> PluginDescriptor | None:
        return self._descriptors.get(slug)

    # --- Registration -----------------------------------------------
    def register_path(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        format_hint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PluginDescriptor:
        plugin_path = Path(path).expanduser().resolve()
        if not plugin_path.exists():
            raise FileNotFoundError(f"Plugin path not found: {plugin_path}")
        for descriptor in self._descriptors.values():
            if descriptor.path and descriptor.path.resolve() == plugin_path:
                return descriptor
        fmt = format_hint or self._detect_format(plugin_path)
        final_name = name or plugin_path.stem
        slug = self._unique_slug(final_name)
        descriptor = PluginDescriptor(
            slug=slug,
            name=final_name,
            format=fmt,
            kind="external",
            path=plugin_path,
            metadata=metadata or {},
        )
        self._descriptors[slug] = descriptor
        self._save()
        return descriptor

    def remove(self, slug: str) -> bool:
        descriptor = self._descriptors.get(slug)
        if not descriptor or descriptor.kind == "builtin":
            return False
        del self._descriptors[slug]
        self._save()
        return True

    def rescan(self, extra_paths: Sequence[str | Path] | None = None) -> list[PluginDescriptor]:
        discovered: list[PluginDescriptor] = []
        for directory in self._default_search_paths():
            discovered.extend(self._register_directory(directory))
        for source in extra_paths or []:
            discovered.extend(self._register_directory(Path(source)))
        if discovered:
            self._save()
        return discovered

    def _register_directory(self, directory: Path) -> list[PluginDescriptor]:
        directory = directory.expanduser()
        if not directory.exists():
            return []
        results: list[PluginDescriptor] = []
        for child in directory.iterdir():
            if child.name.startswith("."):
                continue
            if child.is_dir() and child.suffix.lower() not in {".vst3", ".component"}:
                continue
            before = set(self._descriptors.keys())
            try:
                descriptor = self.register_path(child)
            except FileExistsError:
                continue
            except FileNotFoundError:
                continue
            except ValueError:
                continue
            else:
                if descriptor.slug not in before:
                    results.append(descriptor)
        return results

    def _unique_slug(self, name: str) -> str:
        base = _slugify(name)
        slug = base
        counter = 2
        while slug in self._descriptors:
            slug = f"{base}-{counter}"
            counter += 1
        return slug

    @staticmethod
    def _detect_format(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".vst3":
            return "vst3"
        if suffix in {".vst", ".dll", ".so", ".dylib"}:
            return "vst"
        if suffix == ".component":
            return "au"
        if suffix in {".svt", ".mc.svt"}:
            return "mcsvt"
        if path.is_dir() and path.name.endswith(".vst3"):
            return "vst3"
        return "unknown"

    @staticmethod
    def _default_search_paths() -> list[Path]:
        system = platform.system()
        paths: list[Path] = []
        home = Path(os.environ.get("HOME", "~")).expanduser()
        if system == "Windows":
            program_files = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
            program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
            paths.extend(
                [
                    program_files / "Common Files" / "VST3",
                    program_files / "Steinberg" / "VSTPlugins",
                    program_files_x86 / "Steinberg" / "VSTPlugins",
                ]
            )
        elif system == "Darwin":
            paths.extend(
                [
                    Path("/Library/Audio/Plug-Ins/VST3"),
                    Path("/Library/Audio/Plug-Ins/Components"),
                    home / "Library/Audio/Plug-Ins/VST3",
                    home / "Library/Audio/Plug-Ins/Components",
                ]
            )
        else:
            paths.extend(
                [
                    Path("/usr/lib/vst3"),
                    Path("/usr/local/lib/vst3"),
                    home / ".vst",
                    home / ".vst3",
                ]
            )
        return paths


class PluginHost:
    """Instantiate plugins and process buffers."""

    def __init__(self, library: PluginLibrary) -> None:
        self.library = library
        self._pedalboard_available = Pedalboard is not None and load_plugin is not None

    @property
    def pedalboard_available(self) -> bool:
        return self._pedalboard_available

    def process_chain(self, chain: PluginChain, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        def _to_array(values: np.ndarray) -> np.ndarray:
            try:
                return np.asarray(values, dtype=np.float32)
            except TypeError:
                arr = np.asarray(values)
                if hasattr(arr, "astype"):
                    try:
                        return arr.astype(np.float32)
                    except Exception:  # pragma: no cover - fallback
                        return arr
                return arr

        audio = _to_array(buffer)
        for slot in chain.slots:
            descriptor = slot.descriptor
            params = slot.params or {}
            if descriptor.kind == "builtin":
                processor = self._instantiate_builtin(descriptor, params)
                audio = _to_array(processor.process(_to_array(audio), sample_rate))
                continue
            if not self._pedalboard_available or not descriptor.path:
                continue
            try:
                plugin = load_plugin(str(descriptor.path))  # type: ignore[arg-type]
            except Exception:
                continue
            for key, value in params.items():
                if hasattr(plugin, key):
                    try:
                        setattr(plugin, key, value)
                    except Exception:
                        continue
            try:
                board = Pedalboard([plugin])  # type: ignore[operator]
                audio = _to_array(board(_to_array(audio), sample_rate))
            except Exception:
                continue
        return _to_array(audio)

    def _instantiate_builtin(self, descriptor: PluginDescriptor, params: dict[str, Any]) -> BuiltinProcessor:
        definition = BUILTIN_DEFINITIONS.get(descriptor.slug)
        if not definition:
            return GainProcessor()  # pragma: no cover - defensive fallback
        factory = definition.get("factory", GainProcessor)
        if not callable(factory):  # pragma: no cover - defensive fallback
            return GainProcessor()
        return factory(**params)

    # --- UI helpers -------------------------------------------------
    def available_editor_commands(self) -> list[str]:
        commands: list[str] = []
        for name in (
            "carla-single",
            "carla-bridge-win64",
            "carla-bridge-wine64",
            "carla-bridge-native",
            "pluginval",
        ):
            path = shutil.which(name)
            if path:
                commands.append(path)
        return commands

    def launch_editor(self, descriptor: PluginDescriptor, extra_args: Sequence[str] | None = None) -> dict[str, Any]:
        if descriptor.kind == "builtin":
            raise ValueError("Built-in processors do not expose an editor")
        if not descriptor.path:
            raise FileNotFoundError("Plugin path unavailable")
        commands = self.available_editor_commands()
        if not commands:
            raise RuntimeError("No plugin host executables found on PATH")
        command = commands[0]
        args: list[str] = [command]
        command_name = Path(command).name.lower()
        if "carla" in command_name:
            args.extend(["--plugin", descriptor.format, str(descriptor.path)])
        else:
            args.append(str(descriptor.path))
        if extra_args:
            args.extend(list(extra_args))
        proc = subprocess.Popen(args, start_new_session=True)  # noqa: S603,S607 - user provided
        return {"pid": proc.pid, "args": args, "ok": True}


class PluginManager:
    """High-level facade combining the plugin library, host, and rack config."""

    def __init__(self, base_dir: Path | None = None, cache_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[2])
        if cache_dir is None:
            cache_dir = self.base_dir / ".cache" / "plugins"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.library = PluginLibrary(self.cache_dir)
        self.host = PluginHost(self.library)
        self._rack_path = self.cache_dir / "rack.json"
        self._rack_config = self._load_rack_config()

    # --- Rack config ------------------------------------------------
    def _load_rack_config(self) -> dict[str, Any]:
        if not self._rack_path.exists():
            return {"active_bank": "A", "banks": {}}
        data = json.loads(self._rack_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"active_bank": "A", "banks": {}}
        return data

    def _save_rack_config(self) -> None:
        self._rack_path.write_text(json.dumps(self._rack_config, indent=2), encoding="utf-8")

    def rack(self) -> PluginRack:
        return PluginRack.from_config(self._rack_config, library=self.library, host=self.host)

    def set_rack(self, config: dict[str, Any]) -> PluginRack:
        self._rack_config = config or {"active_bank": "A", "banks": {}}
        self._save_rack_config()
        return self.rack()

    def build_rack_from_config(self, config: dict[str, Any] | None) -> PluginRack:
        if config is None:
            return self.rack()
        return PluginRack.from_config(config, library=self.library, host=self.host)

    def update_active_bank(self, bank: str) -> PluginRack:
        self._rack_config.setdefault("banks", {})
        self._rack_config["active_bank"] = bank
        self._save_rack_config()
        return self.rack()

    def add_plugin_to_chain(self, bank: str, stream: str, slot: dict[str, Any]) -> PluginRack:
        descriptor = self.library.get(slot.get("slug", ""))
        if not descriptor:
            raise FileNotFoundError("Unknown plugin slug")
        self._rack_config.setdefault("banks", {})
        bank_config = self._rack_config.setdefault("banks", {}).setdefault(bank, {"streams": {}})
        streams = bank_config.setdefault("streams", {})
        chain = streams.setdefault(stream, [])
        chain.append({"slug": descriptor.slug, "params": slot.get("params", {})})
        self._save_rack_config()
        return self.rack()

    def remove_plugin_from_chain(self, bank: str, stream: str, index: int) -> PluginRack:
        banks = self._rack_config.get("banks")
        if not isinstance(banks, dict):
            return self.rack()
        bank_cfg = banks.get(bank)
        if not isinstance(bank_cfg, dict):
            return self.rack()
        streams = bank_cfg.get("streams")
        if not isinstance(streams, dict) or stream not in streams:
            return self.rack()
        slots = streams[stream]
        if not isinstance(slots, list) or not (0 <= index < len(slots)):
            return self.rack()
        slots.pop(index)
        if not slots:
            del streams[stream]
        self._save_rack_config()
        return self.rack()

    # --- Library helpers --------------------------------------------
    def register_plugin(self, path: str | Path, *, name: str | None = None) -> PluginDescriptor:
        return self.library.register_path(path, name=name)

    def remove_plugin(self, slug: str) -> bool:
        return self.library.remove(slug)

    def rescan(self, extra_paths: Sequence[str | Path] | None = None) -> list[PluginDescriptor]:
        return self.library.rescan(extra_paths)

    # --- Status -----------------------------------------------------
    def status(self) -> dict[str, Any]:
        rack = self.rack()
        return {
            "platform": platform.system(),
            "plugins": [descriptor.to_payload() for descriptor in self.library.list()],
            "rack": rack.to_config(),
            "active_bank": rack.active_bank,
            "pedalboard_available": self.host.pedalboard_available,
            "editor_commands": self.host.available_editor_commands(),
        }

    # --- Editor -----------------------------------------------------
    def launch_editor(self, slug: str, extra_args: Sequence[str] | None = None) -> dict[str, Any]:
        descriptor = self.library.get(slug)
        if not descriptor:
            raise FileNotFoundError(f"Unknown plugin: {slug}")
        return self.host.launch_editor(descriptor, extra_args)

