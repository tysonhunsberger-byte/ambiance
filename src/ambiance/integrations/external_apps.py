"""Utility helpers to expose bundled third-party audio tools."""

from __future__ import annotations

import platform
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ExternalAppManager:
    """Manage extraction and discovery of bundled installers/binaries."""

    base_dir: Path = Path(__file__).resolve().parents[2]
    cache_dir: Path = base_dir / ".cache" / "external_apps"

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.modalys_zip = self._find_zip("Modalys 3.9.0 for Windows.zip")
        self.praat_zip = self._find_zip("praat6445_win-intel64.zip")

    def _find_zip(self, name: str) -> Optional[Path]:
        candidate = self.base_dir / name
        return candidate if candidate.exists() else None

    def ensure_modalys_installed(self) -> Optional[Path]:
        if not self.modalys_zip:
            return None
        target = self.cache_dir / "modalys"
        executable = target / "Modalys for Max 3.9.0 Installer.exe"
        if not executable.exists():
            self._extract(self.modalys_zip, target)
        return executable if executable.exists() else None

    def ensure_praat_installed(self) -> Optional[Path]:
        if not self.praat_zip:
            return None
        target = self.cache_dir / "praat"
        executable = target / "Praat.exe"
        if not executable.exists():
            self._extract(self.praat_zip, target)
        return executable if executable.exists() else None

    def _extract(self, archive: Path, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(target_dir)

    def platform_supported(self) -> bool:
        return platform.system() in {"Windows", "Darwin", "Linux"}
