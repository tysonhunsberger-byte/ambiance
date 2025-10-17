"""Integration layer that bridges the Flutter VST3 toolkit into Ambiance.

The real Flutter toolkit ships Dart/C++ binaries that host VST3 plugins with a
Flutter driven UI.  Shipping and executing those binaries isn't possible inside
this environment, but we can still provide a faithful bridge that understands
the toolkit metadata, surfaces plugin parameters to the UI, and offers a
Python-side DSP shim so the rest of Ambiance can interact with the hosted
plugins in real time.

The goal of this module is therefore twofold:

* Discover the Flutter toolkit that ships with this repository and expose its
  plugin metadata (names, parameters, defaults, etc.).
* Provide a light-weight host that mimics the behaviour of the toolkit's
  example plugins so we can stream previews, drive parameter automation, and
  render the hosted effect inside Ambiance's audio engine.

The bridge intentionally mirrors the data structures described in the toolkit's
`plugin_metadata.json` files so that, when the native toolchain is present, the
same API shape can be used to drive a real host binary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import threading
import zipfile
from typing import Any

from ..npcompat import np

from ..core.base import AudioEffect


# ---------------------------------------------------------------------------
# Metadata models


@dataclass(frozen=True)
class FlutterVSTParameter:
    """Description of a single plugin parameter."""

    id: int
    name: str
    display_name: str
    description: str
    default: float
    units: str = ""
    minimum: float = 0.0
    maximum: float = 1.0
    step: float = 0.01

    def to_dict(self, value: float | None = None) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "default": self.default,
            "units": self.units,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
        }
        if value is not None:
            payload["value"] = value
        return payload


@dataclass(frozen=True)
class FlutterVSTMetadata:
    """Container describing a Flutter generated plugin."""

    name: str
    vendor: str
    version: str
    category: str | None
    bundle_identifier: str | None
    parameters: tuple[FlutterVSTParameter, ...] = field(default_factory=tuple)

    def parameter_map(self) -> dict[int, FlutterVSTParameter]:
        return {param.id: param for param in self.parameters}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "vendor": self.vendor,
            "version": self.version,
            "category": self.category,
            "bundle_identifier": self.bundle_identifier,
            "parameters": [param.to_dict() for param in self.parameters],
        }


# ---------------------------------------------------------------------------
# Toolkit discovery


def _normalise_label(label: str) -> str:
    return label.replace(" ", "").replace("-", "").lower()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


_NOTE_RE = re.compile(r"^(?P<name>[A-Ga-g])(?P<accidental>[#b]?)(?P<octave>-?\d+)$")
_NOTE_ORDER = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
_A4_FREQUENCY = 440.0
_A4_MIDI = 69


def _note_to_frequency(note: int | float | str) -> float:
    """Convert a MIDI note or scientific pitch name to frequency (Hz)."""

    if isinstance(note, (int, float)):
        midi_value = float(note)
    else:
        match = _NOTE_RE.match(str(note).strip())
        if not match:
            raise ValueError(f"Invalid note '{note}'")
        name = match.group("name").lower()
        accidental = match.group("accidental")
        octave = int(match.group("octave"))
        semitone = _NOTE_ORDER[name]
        if accidental == "#":
            semitone += 1
        elif accidental == "b":
            semitone -= 1
        midi_value = (octave + 1) * 12 + semitone
    return _A4_FREQUENCY * (2 ** ((midi_value - _A4_MIDI) / 12.0))


def _synthesise_note(
    frequency: float,
    duration: float,
    sample_rate: int,
    waveform: str = "sine",
    velocity: float = 0.8,
    attack: float = 0.02,
    release: float = 0.4,
) -> np.ndarray:
    """Generate a monophonic waveform with a simple ADSR envelope."""

    samples = max(1, int(duration * sample_rate))
    t = np.linspace(0.0, duration, samples, endpoint=False)
    t_values = [float(x) for x in t]
    omega = 2 * math.pi * frequency
    waveform_key = waveform.lower()

    def frac(value: float) -> float:
        return value - math.floor(value)

    if waveform_key == "square":
        carrier = [1.0 if math.sin(omega * x) >= 0.0 else -1.0 for x in t_values]
    elif waveform_key == "saw":
        carrier = [2.0 * frac(x * frequency) - 1.0 for x in t_values]
    elif waveform_key == "triangle":
        carrier = [2.0 * abs(2.0 * frac(x * frequency) - 1.0) - 1.0 for x in t_values]
    else:
        carrier = [math.sin(omega * x) for x in t_values]

    attack = max(0.001, float(attack))
    release = max(0.001, float(release))
    sustain_start = min(attack, duration)
    release_start = max(duration - release, sustain_start)
    envelope = np.array([1.0] * samples)
    if sustain_start > 0:
        attack_samples = max(1, int(sustain_start * sample_rate))
        envelope[:attack_samples] = np.linspace(0.0, 1.0, attack_samples)
    if release_start < duration:
        release_samples = max(1, int((duration - release_start) * sample_rate))
        envelope[-release_samples:] = np.linspace(1.0, 0.0, release_samples)

    signal = np.array(
        velocity * float(carrier[i]) * float(envelope[i])
        for i in range(samples)
    )
    return np.clip(signal, -1.0, 1.0)


class FlutterVSTToolkit:
    """Load and index metadata from the bundled Flutter VST3 toolkit."""

    def __init__(self, root: Path | None) -> None:
        self.root = Path(root) if root else None
        self._zip_path: Path | None = None
        if self.root and self.root.is_file() and self.root.suffix.lower() == ".zip":
            self._zip_path = self.root
            self.available = True
        else:
            self.available = bool(self.root and (self.root / "vsts").exists())
        self._metadata_index: dict[str, FlutterVSTMetadata] = {}
        if self.available:
            if self._zip_path:
                self._load_metadata_from_zip()
            else:
                self._load_metadata_from_dir()

    # The toolkit is heavy to scan; cache the discovered instance at module
    # level so multiple hosts/effects share the same data.
    _DEFAULT_LOCK = threading.Lock()
    _DEFAULT_INSTANCE: "FlutterVSTToolkit | None" = None

    @classmethod
    def default(cls) -> "FlutterVSTToolkit":
        with cls._DEFAULT_LOCK:
            if cls._DEFAULT_INSTANCE is None:
                cls._DEFAULT_INSTANCE = cls.discover()
            return cls._DEFAULT_INSTANCE

    @classmethod
    def discover(cls, base_dir: Path | None = None) -> "FlutterVSTToolkit":
        candidates: list[Path] = []
        env = os.environ.get("FLUTTER_VST3_TOOLKIT")
        if env:
            candidates.append(Path(env))
        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[2]
        candidates.extend(
            [
                base_dir / "flutter_vst3-main",
                base_dir / "flutter_vst3",
                base_dir / "third_party" / "flutter_vst3",
                base_dir / "flutter_vst3-main.zip",
            ]
        )
        for candidate in candidates:
            if candidate.is_dir() and (candidate / "vsts").exists():
                return cls(candidate)
            if candidate.is_file() and candidate.suffix.lower() == ".zip":
                return cls(candidate)
        return cls(None)

    # ------------------------------------------------------------------
    # Metadata loading
    def _load_metadata_from_dir(self) -> None:
        assert self.root is not None
        vsts_dir = self.root / "vsts"
        for child in vsts_dir.iterdir():
            meta_file = child / "plugin_metadata.json"
            if not meta_file.exists():
                continue
            self._register_metadata(meta_file.read_text())

    def _load_metadata_from_zip(self) -> None:
        assert self._zip_path is not None
        try:
            with zipfile.ZipFile(self._zip_path) as archive:
                for entry in archive.namelist():
                    if entry.endswith("plugin_metadata.json") and entry.count("/") >= 2:
                        try:
                            data = archive.read(entry).decode("utf-8")
                        except Exception:
                            continue
                        self._register_metadata(data)
        except zipfile.BadZipFile:
            self.available = False

    def _register_metadata(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return
        metadata = self._build_metadata(data)
        self._metadata_index[_normalise_label(metadata.name)] = metadata
        if metadata.bundle_identifier:
            self._metadata_index[_normalise_label(metadata.bundle_identifier)] = metadata

    def _build_metadata(self, payload: dict[str, Any]) -> FlutterVSTMetadata:
        params: list[FlutterVSTParameter] = []
        for entry in payload.get("parameters", []):
            minimum = float(entry.get("minValue", 0.0))
            maximum = float(entry.get("maxValue", 1.0))
            default = float(entry.get("defaultValue", minimum))
            step = float(entry.get("step", 0.01))
            params.append(
                FlutterVSTParameter(
                    id=int(entry.get("id", len(params))),
                    name=str(entry.get("name", f"param{len(params)}")),
                    display_name=str(entry.get("displayName", entry.get("name", "Parameter"))),
                    description=str(entry.get("description", "")),
                    default=default,
                    units=str(entry.get("units", "")),
                    minimum=minimum,
                    maximum=maximum,
                    step=step,
                )
            )
        return FlutterVSTMetadata(
            name=str(payload.get("pluginName", "Flutter Plugin")),
            vendor=str(payload.get("vendor", "")),
            version=str(payload.get("version", "")),
            category=payload.get("category"),
            bundle_identifier=payload.get("bundleIdentifier"),
            parameters=tuple(params),
        )

    # ------------------------------------------------------------------
    # Metadata lookup helpers
    def metadata_for_plugin_path(self, plugin_path: Path) -> FlutterVSTMetadata:
        if not self.available:
            return self._fallback_metadata(plugin_path)
        keys = [
            _normalise_label(plugin_path.stem),
            _normalise_label(plugin_path.name),
        ]
        for key in keys:
            if key in self._metadata_index:
                return self._metadata_index[key]
        return self._fallback_metadata(plugin_path)

    def _fallback_metadata(self, plugin_path: Path) -> FlutterVSTMetadata:
        display = plugin_path.stem or "Plugin"
        param = FlutterVSTParameter(
            id=0,
            name="gain",
            display_name="Gain",
            description="Output gain multiplier",
            default=1.0,
            units="x",
            minimum=0.0,
            maximum=2.0,
            step=0.01,
        )
        return FlutterVSTMetadata(
            name=display,
            vendor="Unknown",
            version="",
            category=None,
            bundle_identifier=None,
            parameters=(param,),
        )

    def instantiate(
        self,
        plugin_path: str | Path,
        *,
        parameter_overrides: dict[str, float] | None = None,
    ) -> "FlutterVSTInstance":
        path = Path(plugin_path).expanduser()
        metadata = self.metadata_for_plugin_path(path)
        instance = FlutterVSTInstance(plugin_path=path, metadata=metadata)
        if parameter_overrides:
            for name, value in parameter_overrides.items():
                instance.set_parameter(name, float(value))
        return instance

    def warnings(self) -> list[str]:
        if self.available:
            return []
        return [
            "Flutter VST3 toolkit not found. Install it or set FLUTTER_VST3_TOOLKIT",
            "Realtime hosting will use a lightweight gain shim until the toolkit is installed.",
        ]


# ---------------------------------------------------------------------------
# DSP shim / host instance


class FlutterVSTInstance(AudioEffect):
    """Simulated DSP block for a Flutter generated plugin."""

    name: str = "flutter_vst"

    def __init__(self, plugin_path: Path, metadata: FlutterVSTMetadata) -> None:
        self.plugin_path = Path(plugin_path)
        self.metadata = metadata
        self._param_lookup = metadata.parameter_map()
        self._parameters: dict[int, float] = {
            param.id: float(param.default) for param in metadata.parameters
        }
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Parameter helpers
    def parameter_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._param_lookup[param_id].to_dict(value=value)
                for param_id, value in sorted(self._parameters.items())
            ]

    def set_parameter(self, identifier: int | str, value: float) -> float:
        with self._lock:
            param_id = self._resolve_identifier(identifier)
            param = self._param_lookup[param_id]
            clamped = float(value)
            if clamped < param.minimum:
                clamped = param.minimum
            elif clamped > param.maximum:
                clamped = param.maximum
            self._parameters[param_id] = clamped
            # Reset state if a parameter fundamentally changes topology
            if param.name in {"delayTime", "roomSize"}:
                self._state.pop(param.name, None)
            return clamped

    def get_parameter(self, identifier: int | str) -> float:
        param_id = self._resolve_identifier(identifier)
        return self._parameters[param_id]

    def _resolve_identifier(self, identifier: int | str) -> int:
        if isinstance(identifier, int):
            if identifier not in self._parameters:
                raise KeyError(f"Unknown parameter id {identifier}")
            return identifier
        key = _normalise_label(identifier)
        for param in self._param_lookup.values():
            if _normalise_label(param.name) == key:
                return param.id
        raise KeyError(f"Unknown parameter {identifier}")

    # ------------------------------------------------------------------
    # AudioEffect API
    def apply(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:  # pragma: no cover - alias
        return self.process(buffer, sample_rate)

    def process(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        name = _normalise_label(self.metadata.name)
        if "echo" in name:
            return self._process_echo(buffer, sample_rate)
        if "reverb" in name:
            return self._process_reverb(buffer, sample_rate)
        return self._process_gain(buffer)

    def _process_gain(self, buffer: np.ndarray) -> np.ndarray:
        gain = float(self._parameters.get(0, 1.0))
        out = (gain * buffer).astype(np.float32)
        return np.clip(out, -1.0, 1.0)

    def _process_echo(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        bypass = self._parameters.get(self._resolve_identifier("bypass"), 0.0)
        if bypass >= 0.5:
            return buffer.astype(np.float32)
        delay_value = self._parameters.get(self._resolve_identifier("delayTime"), 0.5)
        feedback = self._parameters.get(self._resolve_identifier("feedback"), 0.3)
        mix = self._parameters.get(self._resolve_identifier("mix"), 0.5)

        delay_seconds = float(_clamp(delay_value, 0.0, 1.0))
        feedback = float(_clamp(feedback, 0.0, 0.95))
        mix = float(_clamp(mix, 0.0, 1.0))

        delay_samples = max(1, int(delay_seconds * sample_rate))
        state_key = "echo_buffer"
        with self._lock:
            buf = self._state.get(state_key)
            idx = int(self._state.get("echo_index", 0))
            if buf is None or len(buf) != delay_samples:
                buf = np.zeros(delay_samples, dtype=np.float32)
                idx = 0
            output = np.zeros_like(buffer, dtype=np.float32)
            for i, sample in enumerate(buffer.astype(np.float32)):
                delayed = buf[idx]
                buf[idx] = sample + delayed * feedback
                output[i] = (1 - mix) * sample + mix * delayed
                idx = (idx + 1) % delay_samples
            self._state[state_key] = buf
            self._state["echo_index"] = idx
        return np.clip(output, -1.0, 1.0)

    def _process_reverb(self, buffer: np.ndarray, sample_rate: int) -> np.ndarray:
        room = self._parameters.get(self._resolve_identifier("roomSize"), 0.5)
        damping = self._parameters.get(self._resolve_identifier("damping"), 0.5)
        wet_level = self._parameters.get(self._resolve_identifier("wetLevel"), 0.3)
        dry_level = self._parameters.get(self._resolve_identifier("dryLevel"), 0.7)

        room = float(_clamp(room, 0.0, 1.0))
        damping = float(_clamp(damping, 0.0, 1.0))
        wet_level = float(_clamp(wet_level, 0.0, 1.0))
        dry_level = float(_clamp(dry_level, 0.0, 1.0))

        decay = 0.2 + room * 0.75
        mix = max(0.05, wet_level * (1.0 - 0.4 * damping))

        from ..effects.spatial import ReverbEffect  # Local import to avoid cycle

        effect = ReverbEffect(decay=decay, mix=1.0)
        wet = effect.apply(buffer.astype(np.float32), sample_rate)
        combined = dry_level * buffer.astype(np.float32) + wet_level * wet
        return np.clip(combined, -1.0, 1.0)

    # ------------------------------------------------------------------
    # Serialisation helpers
    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.plugin_path),
            "metadata": self.metadata.to_dict(),
            "parameters": self.parameter_snapshot(),
        }


# ---------------------------------------------------------------------------
# Public host facade used by the HTTP server


class FlutterVSTHost:
    """Thread-safe manager that exposes a single hosted Flutter plugin."""

    def __init__(self, toolkit: FlutterVSTToolkit | None = None, base_dir: Path | None = None) -> None:
        if toolkit is None:
            if base_dir is None:
                base_dir = Path(__file__).resolve().parents[2]
            toolkit = FlutterVSTToolkit.discover(base_dir)
        self.toolkit = toolkit
        self._lock = threading.RLock()
        self._instance: FlutterVSTInstance | None = None

    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
                "available": self.toolkit.available,
                "toolkit_path": str(self.toolkit.root) if self.toolkit.root else None,
                "warnings": self.toolkit.warnings(),
            }
            if self._instance is None:
                payload["plugin"] = None
                payload["parameters"] = []
            else:
                payload["plugin"] = self._instance.to_dict()
                payload["parameters"] = self._instance.parameter_snapshot()
            return payload

    def load_plugin(self, plugin_path: str | Path, parameters: dict[str, float] | None = None) -> dict[str, Any]:
        with self._lock:
            instance = self.toolkit.instantiate(plugin_path, parameter_overrides=parameters)
            self._instance = instance
            return instance.to_dict()

    def unload(self) -> None:
        with self._lock:
            self._instance = None

    def set_parameter(self, identifier: int | str, value: float) -> dict[str, Any]:
        with self._lock:
            if self._instance is None:
                raise RuntimeError("No plugin hosted")
            self._instance.set_parameter(identifier, value)
            return {
                "plugin": self._instance.to_dict(),
                "parameters": self._instance.parameter_snapshot(),
            }

    def render_preview(self, duration: float = 1.5, sample_rate: int = 44100) -> np.ndarray:
        with self._lock:
            if self._instance is None:
                raise RuntimeError("No plugin hosted")
            samples = max(1, int(duration * sample_rate))
            impulse = np.zeros(samples, dtype=np.float32)
            impulse[0] = 1.0
            return self._instance.process(impulse, sample_rate)

    def render_note(
        self,
        note: int | float | str,
        *,
        duration: float = 1.5,
        velocity: float = 0.85,
        sample_rate: int = 44100,
        waveform: str = "sine",
        attack: float = 0.02,
        release: float = 0.35,
    ) -> np.ndarray:
        """Render a monophonic note through the hosted plugin."""

        frequency = _note_to_frequency(note)
        source = _synthesise_note(
            frequency,
            duration,
            sample_rate,
            waveform=waveform,
            velocity=float(_clamp(velocity, 0.0, 1.0)),
            attack=attack,
            release=release,
        )
        with self._lock:
            if self._instance is None:
                # Provide a dry preview if no plugin is present so the UI remains usable.
                return source
            return self._instance.process(source, sample_rate)

    # Convenience used by the offline renderer / registry effect
    def create_effect(self, plugin_path: str | Path, parameters: dict[str, float] | None = None) -> FlutterVSTInstance:
        return self.toolkit.instantiate(plugin_path, parameter_overrides=parameters)


__all__ = [
    "FlutterVSTHost",
    "FlutterVSTToolkit",
    "FlutterVSTInstance",
    "FlutterVSTMetadata",
    "FlutterVSTParameter",
]
