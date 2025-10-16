"""Ambiance - Modular audio generation and integration toolkit."""

from .core.engine import AudioEngine
from .core.registry import registry
from .server import serve
from .sources.basic import NoiseSource, SineWaveSource
from .sources.integrated import ResonantInstrumentSource, VocalFormantSource
from .effects.spatial import ReverbEffect, DelayEffect, LowPassFilterEffect

__all__ = [
    "AudioEngine",
    "registry",
    "NoiseSource",
    "SineWaveSource",
    "ResonantInstrumentSource",
    "VocalFormantSource",
    "ReverbEffect",
    "DelayEffect",
    "LowPassFilterEffect",
    "serve",
]
