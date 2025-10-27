"""Lifecycle helpers for launching Carla bridges from Python."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

_SUPPORTED_SUFFIXES = {
    ".vst": "vst2",
    ".dll": "vst2",
    ".vst3": "vst3",
}


@dataclass(slots=True)
class CarlaHostStatus:
    """Snapshot describing the Carla bridge availability and runtime state."""

    available: bool
    bridge_path: str | None
    python_executable: str
    running: bool
    plugin_path: str | None
    plugin_format: str | None
    last_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "bridge_path": self.bridge_path,
            "python_executable": self.python_executable,
            "running": self.running,
            "plugin_path": self.plugin_path,
            "plugin_format": self.plugin_format,
            "last_error": self.last_error,
        }


class CarlaHost:
    """Manage a Carla bridge process for hosting native VST plugins."""

    def __init__(
        self,
        base_dir: Path | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.python_executable = python_executable or sys.executable
        self._bridge_script = self._discover_bridge_script()
        self._process: subprocess.Popen[bytes] | None = None
        self._plugin_path: Path | None = None
        self._plugin_format: str | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # Discovery helpers
    def _candidate_bridge_paths(self) -> list[Path]:
        env = os.environ.get("CARLA_SINGLE")
        candidates: list[Path] = []
        if env:
            candidates.append(Path(env))
        roots = [
            self.base_dir / "Carla-main" / "data" / "carla-single",
            self.base_dir / "Carla-main" / "bin" / "carla-single",
            self.base_dir / "Carla" / "bin" / "carla-single",
            Path("/usr/bin/carla-single"),
            Path("/usr/local/bin/carla-single"),
        ]
        candidates.extend(roots)
        return candidates

    def _discover_bridge_script(self) -> Path | None:
        for candidate in self._candidate_bridge_paths():
            try:
                if candidate.exists():
                    if candidate.is_file():
                        return candidate
            except OSError:
                continue
        return None

    # ------------------------------------------------------------------
    # Process helpers
    @staticmethod
    def _detect_format(plugin_path: Path) -> str | None:
        suffix = plugin_path.suffix.lower()
        if suffix in _SUPPORTED_SUFFIXES:
            return _SUPPORTED_SUFFIXES[suffix]
        name = plugin_path.name.lower()
        for suffix, plugin_format in _SUPPORTED_SUFFIXES.items():
            if name.endswith(suffix):
                return plugin_format
        return None

    def available(self) -> bool:
        return bool(self._bridge_script and os.access(self._bridge_script, os.X_OK))

    def status(self) -> CarlaHostStatus:
        running = bool(self._process and self._process.poll() is None)
        return CarlaHostStatus(
            available=self.available(),
            bridge_path=str(self._bridge_script) if self._bridge_script else None,
            python_executable=self.python_executable,
            running=running,
            plugin_path=str(self._plugin_path) if self._plugin_path else None,
            plugin_format=self._plugin_format,
            last_error=self._last_error,
        )

    def ensure_executable(self) -> None:
        if not self._bridge_script:
            return
        try:
            mode = self._bridge_script.stat().st_mode
        except OSError:
            return
        if mode & 0o111:
            return
        try:
            self._bridge_script.chmod(mode | 0o755)
        except OSError:
            pass

    def launch(
        self,
        plugin_path: str | os.PathLike[str],
        *,
        plugin_format: str | None = None,
        arch: str | None = None,
        label: str | None = None,
    ) -> CarlaHostStatus:
        self._last_error = None
        path = Path(plugin_path)
        if not path.exists():
            self._last_error = f"Plugin path not found: {path}"
            return self.status()
        if self._process and self._process.poll() is None:
            self.terminate()
        if not self._bridge_script:
            self._last_error = "Carla bridge script not found"
            return self.status()
        self.ensure_executable()
        detected_format = plugin_format or self._detect_format(path)
        if not detected_format:
            self._last_error = "Unsupported plugin format for Carla bridge"
            return self.status()
        command = [self.python_executable, str(self._bridge_script)]
        if arch and arch != "native":
            command.append(arch)
        command.append(detected_format)
        command.append(str(path))
        if label:
            command.append(label)
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._plugin_path = path
            self._plugin_format = detected_format
        except OSError as exc:
            self._last_error = str(exc)
            self._process = None
            self._plugin_path = None
            self._plugin_format = None
        return self.status()

    def terminate(self) -> CarlaHostStatus:
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    self._process.kill()
                    self._process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        self._process = None
        self._plugin_path = None
        self._plugin_format = None
        return self.status()


__all__ = ["CarlaHost", "CarlaHostStatus"]
