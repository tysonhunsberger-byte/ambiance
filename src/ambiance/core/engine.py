"""Audio engine that combines sources and effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from ..npcompat import np

from .base import AudioEffect, AudioSource

try:  # pragma: no cover - optional import to avoid cycle at runtime
    from ..integrations.plugins import PluginRack
except Exception:  # pragma: no cover - plugins optional for import time
    PluginRack = None  # type: ignore[assignment]


def mix(buffers: Iterable[np.ndarray]) -> np.ndarray:
    """Mix any number of buffers, padding with zeros as needed."""
    buffers = list(buffers)
    if not buffers:
        return np.zeros(1, dtype=np.float32)
    max_len = max(len(buffer) for buffer in buffers)
    mix_buffer = np.zeros(max_len, dtype=np.float32)
    for buffer in buffers:
        cast = buffer.astype(np.float32) if hasattr(buffer, "astype") else buffer
        for idx in range(len(cast)):
            mix_buffer[idx] += float(cast[idx])
    # prevent clipping
    max_abs = np.max(np.abs(mix_buffer)) or 1.0
    if max_abs > 1.0:
        mix_buffer /= max_abs
    return mix_buffer


@dataclass
class AudioEngine:
    """Coordinate synthesis by invoking registered sources and effects."""

    sample_rate: int = 44100
    sources: List[AudioSource] = field(default_factory=list)
    effects: List[AudioEffect] = field(default_factory=list)
    plugin_rack: Optional["PluginRack"] = None

    def add_source(self, source: AudioSource) -> None:
        self.sources.append(source)

    def add_effect(self, effect: AudioEffect) -> None:
        self.effects.append(effect)

    def set_plugin_rack(self, rack: "PluginRack" | None) -> None:
        self.plugin_rack = rack

    def render(self, duration: float) -> np.ndarray:
        """Render a buffer from all sources and effects."""
        buffers = []
        for source in self.sources:
            buffer = source.generate(duration, self.sample_rate)
            if self.plugin_rack:
                stream_id = getattr(source, "name", source.__class__.__name__)
                buffer = self.plugin_rack.process_stream(stream_id, buffer, self.sample_rate)
            buffers.append(buffer)
        combined = mix(buffers)
        if self.plugin_rack:
            combined = self.plugin_rack.process_master(combined, self.sample_rate)
        for effect in self.effects:
            combined = effect.apply(combined, self.sample_rate)
        return combined

    def configuration(self) -> dict:
        return {
            "sample_rate": self.sample_rate,
            "sources": [source.to_dict() for source in self.sources],
            "effects": [effect.to_dict() for effect in self.effects],
            "plugins": self.plugin_rack.to_config() if self.plugin_rack else None,
        }
