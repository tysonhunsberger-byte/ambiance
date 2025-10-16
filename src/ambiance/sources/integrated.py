"""Sources that integrate external audio tools bundled with the repo."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Optional

from ..npcompat import np

from ..core.base import AudioSource
from ..core.registry import registry
from ..integrations.external_apps import ExternalAppManager

_MANAGER = ExternalAppManager()


@dataclass
@registry.register_source
class ModalysSource(AudioSource):
    """Wrapper around the Modalys installer shipped in the repository."""

    name: str = "modalys"
    preset: str = "string-resonator"
    amplitude: float = 0.25
    seed: Optional[int] = None

    def generate(self, duration: float, sample_rate: int) -> np.ndarray:
        app_path = _MANAGER.ensure_modalys_installed()
        if not app_path:
            return self._simulate(duration, sample_rate)
        if platform.system() != "Windows":
            return self._simulate(duration, sample_rate)
        # For Windows users, this would invoke the installer/exe to render audio.
        # We do not execute it in this environment but leave the hook for runtime use.
        return self._simulate(duration, sample_rate)

    def _simulate(self, duration: float, sample_rate: int) -> np.ndarray:
        rng = np.random.default_rng(self.seed)
        t = np.linspace(0, duration, int(duration * sample_rate), endpoint=False)
        envelope = np.exp(-3 * t)
        waveform = envelope * np.sin(2 * np.pi * 196 * t)  # G3 string-like tone
        noise = 0.02 * rng.standard_normal(len(t))
        return self.amplitude * (waveform + noise).astype(np.float32)

    def to_dict(self) -> dict[str, object]:
        data = super().to_dict()
        data.update({
            "preset": self.preset,
            "amplitude": self.amplitude,
            "seed": self.seed,
            "resource": str(_MANAGER.modalys_zip) if _MANAGER.modalys_zip else None,
        })
        return data


@dataclass
@registry.register_source
class PraatSource(AudioSource):
    """Formant-style voice synthesis based on the Praat binary."""

    name: str = "praat"
    vowel: str = "a"
    amplitude: float = 0.2
    vibrato_rate: float = 5.0
    vibrato_depth: float = 0.005

    def generate(self, duration: float, sample_rate: int) -> np.ndarray:
        app_path = _MANAGER.ensure_praat_installed()
        # As with Modalys, we fallback to simulation when execution is not possible.
        return self._simulate(duration, sample_rate)

    def _simulate(self, duration: float, sample_rate: int) -> np.ndarray:
        vowel_formants = {
            "a": (730, 1090, 2440),
            "e": (530, 1840, 2480),
            "i": (270, 2290, 3010),
            "o": (570, 840, 2410),
            "u": (300, 870, 2240),
        }
        f1, f2, f3 = vowel_formants.get(self.vowel, vowel_formants["a"])
        t = np.linspace(0, duration, int(duration * sample_rate), endpoint=False)
        base = np.sin(2 * np.pi * 110 * t)
        vibrato = np.sin(2 * np.pi * self.vibrato_rate * t) * self.vibrato_depth
        waveform = (
            0.6 * np.sin(2 * np.pi * f1 * t + vibrato)
            + 0.3 * np.sin(2 * np.pi * f2 * t + vibrato)
            + 0.1 * np.sin(2 * np.pi * f3 * t + vibrato)
        )
        return (self.amplitude * base * waveform).astype(np.float32)

    def to_dict(self) -> dict[str, object]:
        data = super().to_dict()
        data.update({
            "vowel": self.vowel,
            "amplitude": self.amplitude,
            "vibrato_rate": self.vibrato_rate,
            "vibrato_depth": self.vibrato_depth,
            "resource": str(_MANAGER.praat_zip) if _MANAGER.praat_zip else None,
        })
        return data
