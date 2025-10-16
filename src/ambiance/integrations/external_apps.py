"""Utility helpers to work with user-supplied external executables."""

from __future__ import annotations

import os
import platform
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass
class ExternalAppManager:
    """Manage discovery and execution for external tools dropped into a workspace."""

    base_dir: Path = Path(__file__).resolve().parents[2]
    workspace_dir: Path | None = None

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        if self.workspace_dir is None:
            self.workspace_dir = self.base_dir / ".cache" / "external_apps"
        else:
            self.workspace_dir = Path(self.workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    # --- Workspace helpers -----------------------------------------
    def workspace_path(self) -> Path:
        """Return the directory where executables should be stored."""

        return Path(self.workspace_dir)

    def _candidate_paths(self) -> Iterable[Path]:
        """Yield likely executable candidates from the workspace."""

        root = self.workspace_path()
        if not root.exists():
            return []

        def walker() -> Iterable[Path]:
            for dirpath, dirnames, filenames in os.walk(root):
                current = Path(dirpath)
                for dirname in list(dirnames):
                    candidate = current / dirname
                    if candidate.suffix.lower() == ".app":
                        yield candidate
                        dirnames.remove(dirname)
                for filename in filenames:
                    yield current / filename

        return walker()

    @staticmethod
    def _looks_executable(path: Path) -> bool:
        if path.is_dir():
            return path.suffix.lower() == ".app"

        suffix = path.suffix.lower()
        if suffix in {".exe", ".bat", ".cmd", ".com", ".ps1", ".sh", ".bin", ".command"}:
            return True

        try:
            mode = path.stat().st_mode
        except OSError:
            return False

        return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

    def discover_workspace(self, limit: int = 128) -> list[dict[str, object]]:
        """Return metadata for executables living inside the workspace."""

        entries: list[dict[str, object]] = []
        for candidate in self._candidate_paths():
            if not self._looks_executable(candidate):
                continue
            try:
                relative = candidate.relative_to(self.workspace_path())
            except ValueError:
                relative = candidate.name
            entry = {
                "name": candidate.name,
                "path": str(candidate),
                "relative_path": str(relative),
                "type": "bundle" if candidate.is_dir() else "file",
            }
            if candidate.is_file():
                try:
                    entry["size"] = candidate.stat().st_size
                except OSError:
                    entry["size"] = None
            entries.append(entry)
            if len(entries) >= limit:
                break
        entries.sort(key=lambda item: item["relative_path"].lower())
        return entries

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
        """Return structured availability information for the workspace."""

        workspace = self.workspace_path()
        executables = self.discover_workspace()
        notes: list[str] = []
        if not executables:
            notes.append(
                "Place executables in the workspace folder to have them appear in the UI."
            )
        return {
            "workspace": str(workspace),
            "workspace_exists": workspace.exists(),
            "executables": executables,
            "count": len(executables),
            "platform_supported": self.platform_supported(),
            "notes": notes,
        }
