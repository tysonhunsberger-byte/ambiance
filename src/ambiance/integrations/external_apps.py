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
    cache_dir: Path | None = None

    modalys_executable_name: str = "Modalys for Max 3.9.0 Installer.exe"
    praat_executable_name: str = "Praat.exe"

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        if self.cache_dir is None:
            self.cache_dir = self.base_dir / ".cache" / "external_apps"
        else:
            self.cache_dir = Path(self.cache_dir)
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
        executable = target / self.modalys_executable_name
        if not executable.exists():
            self._extract(self.modalys_zip, target)
        return executable if executable.exists() else None

    def ensure_praat_installed(self) -> Optional[Path]:
        if not self.praat_zip:
            return None
        target = self.cache_dir / "praat"
        executable = target / self.praat_executable_name
        if not executable.exists():
            self._extract(self.praat_zip, target)
        return executable if executable.exists() else None

    def modalys_installation(self) -> Optional[Path]:
        target = self.cache_dir / "modalys" / self.modalys_executable_name
        return target if target.exists() else None

    def praat_installation(self) -> Optional[Path]:
        target = self.cache_dir / "praat" / self.praat_executable_name
        return target if target.exists() else None

    def _extract(self, archive: Path, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(target_dir)

    def platform_supported(self) -> bool:
        return platform.system() in {"Windows", "Darwin", "Linux"}

    def status(self) -> dict[str, object]:
        """Return structured availability information for the bundled apps."""

        modalys_path = self.modalys_installation()
        praat_path = self.praat_installation()
        return {
            "modalys": {
                "zip_present": bool(self.modalys_zip),
                "installed": bool(modalys_path),
                "path": str(modalys_path) if modalys_path else None,
            },
            "praat": {
                "zip_present": bool(self.praat_zip),
                "installed": bool(praat_path),
                "path": str(praat_path) if praat_path else None,
            },
            "platform_supported": self.platform_supported(),
        }
