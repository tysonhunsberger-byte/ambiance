"""Utility helpers to expose bundled third-party audio tools."""

from __future__ import annotations

import platform
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple


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

    # --- Discovery helpers -------------------------------------------------
    def _app_target(self, name: str) -> Path:
        return self.cache_dir / name

    def _discover_executable(
        self, target_dir: Path, preferred: Optional[str] = None
    ) -> Tuple[Optional[Path], Optional[str]]:
        """Inspect ``target_dir`` and return a candidate executable.

        The returned tuple contains the discovered path (if any) and a string
        describing the kind of file that was found.  The ``kind`` value is one
        of ``"executable"`` or ``"installer"``.  ``None`` is returned if the
        directory does not contain an executable.
        """

        def classify(path: Path) -> str:
            name = path.name.lower()
            if "installer" in name or "setup" in name:
                return "installer"
            return "executable"

        if preferred:
            candidate = target_dir / preferred
            if candidate.exists():
                return candidate, classify(candidate)

        patterns = ("*.exe", "*.bat", "*.cmd")
        candidates: list[Path] = []
        for pattern in patterns:
            candidates.extend(target_dir.glob(pattern))
            candidates.extend(target_dir.rglob(pattern))

        unique: list[Path] = []
        seen: set[Path] = set()
        for candidate in sorted(candidates):
            if candidate in seen or not candidate.is_file():
                continue
            seen.add(candidate)
            unique.append(candidate)

        # Prefer non-installer executables when multiple files exist.
        for candidate in unique:
            kind = classify(candidate)
            if kind == "executable":
                return candidate, kind

        if unique:
            candidate = unique[0]
            return candidate, classify(candidate)

        return None, None

    def _find_zip(self, name: str) -> Optional[Path]:
        candidate = self.base_dir / name
        return candidate if candidate.exists() else None

    def ensure_modalys_installed(self) -> Optional[Path]:
        if not self.modalys_zip:
            return None
        target = self._app_target("modalys")
        executable, _ = self._prepare_app("modalys", target, self.modalys_zip, self.modalys_executable_name)
        return executable

    def ensure_praat_installed(self) -> Optional[Path]:
        if not self.praat_zip:
            return None
        target = self._app_target("praat")
        executable, _ = self._prepare_app("praat", target, self.praat_zip, self.praat_executable_name)
        return executable

    def modalys_installation(self) -> Optional[Path]:
        target_dir = self._app_target("modalys")
        if not target_dir.exists():
            return None
        executable, _ = self._discover_executable(target_dir, self.modalys_executable_name)
        return executable

    def praat_installation(self) -> Optional[Path]:
        target_dir = self._app_target("praat")
        if not target_dir.exists():
            return None
        executable, _ = self._discover_executable(target_dir, self.praat_executable_name)
        return executable

    def _extract(self, archive: Path, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(target_dir)

    def _prepare_app(
        self,
        name: str,
        target_dir: Path,
        archive: Optional[Path],
        preferred_name: Optional[str],
    ) -> Tuple[Optional[Path], Optional[str]]:
        if not archive:
            return None, None
        needs_extract = False
        if not target_dir.exists():
            needs_extract = True
        else:
            try:
                needs_extract = not any(target_dir.iterdir())
            except OSError:
                needs_extract = True
        if needs_extract:
            self._extract(archive, target_dir)
        return self._discover_executable(target_dir, preferred_name)

    def platform_supported(self) -> bool:
        return platform.system() in {"Windows", "Darwin", "Linux"}

    # --- Launching --------------------------------------------------
    def _normalize_args(self, args: Sequence[str] | str | None) -> list[str]:
        if args is None:
            return []
        if isinstance(args, str):
            import shlex

            text = args.strip()
            return shlex.split(text) if text else []
        return [str(item) for item in args]

    def launch_external(
        self,
        executable: str | Path,
        *,
        args: Sequence[str] | str | None = None,
        wait: bool = False,
        timeout: float | None = None,
        cwd: str | Path | None = None,
    ) -> dict[str, object]:
        """Run an arbitrary executable and return structured results."""

        exe_path = Path(executable).expanduser()
        if not exe_path.exists():
            raise FileNotFoundError(f"Executable not found: {exe_path}")
        if not exe_path.is_file():
            raise IsADirectoryError(f"Executable must be a file: {exe_path}")

        cmd: list[str] = [str(exe_path)]
        cmd.extend(self._normalize_args(args))

        working_dir = Path(cwd).expanduser() if cwd else exe_path.parent

        if wait:
            completed = subprocess.run(  # noqa: S603 - user provided
                cmd,
                cwd=str(working_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return {
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "args": cmd,
                "cwd": str(working_dir),
            }

        proc = subprocess.Popen(  # noqa: S603,S607 - user provided
            cmd,
            cwd=str(working_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {
            "ok": True,
            "pid": proc.pid,
            "args": cmd,
            "cwd": str(working_dir),
        }

    def status(self) -> dict[str, object]:
        """Return structured availability information for the bundled apps."""

        modalys_info = self._status_entry(
            "modalys",
            self.modalys_zip,
            self.modalys_executable_name,
        )
        praat_info = self._status_entry(
            "praat",
            self.praat_zip,
            self.praat_executable_name,
        )
        return {
            "modalys": modalys_info,
            "praat": praat_info,
            "platform_supported": self.platform_supported(),
        }

    def _status_entry(
        self,
        name: str,
        archive: Optional[Path],
        preferred_name: Optional[str],
    ) -> dict[str, object]:
        target_dir = self._app_target(name)
        if target_dir.exists():
            try:
                extracted = any(target_dir.iterdir())
            except OSError:
                extracted = False
        else:
            extracted = False
        executable: Optional[Path] = None
        kind: Optional[str] = None
        if extracted:
            executable, kind = self._discover_executable(target_dir, preferred_name)

        installed = bool(executable and kind != "installer")
        installer_only = bool(executable and kind == "installer")
        note: Optional[str] = None
        if installer_only:
            note = (
                "Only an installer was found. Provide extracted runtime files "
                "to launch the application directly."
            )
        elif not archive:
            note = "Bundle archive is missing."
        elif archive and not extracted:
            note = "Archive located. Extract to prepare the application."

        return {
            "zip_present": bool(archive),
            "installed": installed,
            "installer_only": installer_only,
            "kind": kind,
            "path": str(executable) if executable else None,
            "workspace": str(target_dir),
            "note": note,
        }
