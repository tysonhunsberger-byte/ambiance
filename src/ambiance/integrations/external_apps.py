"""Utility helpers to expose bundled third-party audio tools."""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence


@dataclass
class WorkspaceInfo:
    """Metadata describing an extracted workspace for an external app."""

    slug: str
    title: str
    root: str = "."
    kind: str = "native"
    entry: str | None = None
    executable: str | None = None
    args: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "title": self.title,
            "root": self.root,
            "kind": self.kind,
            "entry": self.entry,
            "executable": self.executable,
            "args": list(self.args),
        }

    def to_payload(self, base: Path) -> dict[str, object]:
        root_path = self.root_path(base)
        payload = self.to_json()
        payload["path"] = str(root_path)
        if self.entry:
            payload["entry_url"] = f"/apps/{self.slug}/{self.entry}"
            payload["entry_path"] = str(root_path / self.entry)
        if self.executable:
            payload["executable_path"] = str(self.executable_path(base))
        return payload

    def root_path(self, base: Path) -> Path:
        return (base / Path(self.root)).resolve()

    def entry_path(self, base: Path) -> Path | None:
        if not self.entry:
            return None
        return (self.root_path(base) / self.entry).resolve()

    def executable_path(self, base: Path) -> Path | None:
        if not self.executable:
            return None
        return (self.root_path(base) / self.executable).resolve()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "workspace"


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
        self.workspaces_dir = self.cache_dir / "workspaces"
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)

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
            root = target_dir.resolve()
            for member in zf.namelist():
                destination = root / member
                if not str(destination.resolve()).startswith(str(root)):
                    raise ValueError("Archive contains unsafe paths")
            zf.extractall(target_dir)

    def platform_supported(self) -> bool:
        return platform.system() in {"Windows", "Darwin", "Linux"}

    # --- Workspaces -------------------------------------------------
    def ensure_workspace(
        self,
        source: str | Path,
        *,
        name: str | None = None,
        entry: str | None = None,
        executable: str | None = None,
        args: Sequence[str] | str | None = None,
    ) -> WorkspaceInfo:
        """Extract or copy a workspace and return its metadata."""

        source_path = Path(source).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(f"Workspace source not found: {source_path}")

        slug = _slugify(name or source_path.stem or "workspace")
        base = self.workspaces_dir / slug
        if base.exists():
            shutil.rmtree(base)
        base.mkdir(parents=True, exist_ok=True)

        if source_path.is_dir():
            shutil.copytree(source_path, base, dirs_exist_ok=True)
        elif zipfile.is_zipfile(source_path):
            self._extract(source_path, base)
        else:
            raise ValueError("Workspace source must be a directory or zip archive")

        root_dir = self._discover_root(base)
        root_rel = root_dir.relative_to(base)

        entry_rel = self._resolve_entry(root_dir, entry)
        executable_rel = self._resolve_executable(root_dir, executable)

        normalized_args = self._normalize_args(args) if args is not None else []

        kind = "native"
        if entry_rel and executable_rel:
            kind = "hybrid"
        elif entry_rel:
            kind = "web"

        info = WorkspaceInfo(
            slug=slug,
            title=name or source_path.stem,
            root=root_rel.as_posix(),
            kind=kind,
            entry=entry_rel,
            executable=executable_rel,
            args=normalized_args,
        )
        self._write_workspace_metadata(base, info)
        return info

    def list_workspaces(self) -> list[WorkspaceInfo]:
        workspaces: list[WorkspaceInfo] = []
        for child in sorted(self.workspaces_dir.iterdir()):
            if not child.is_dir():
                continue
            info = self._read_workspace_metadata(child)
            if info:
                workspaces.append(info)
        workspaces.sort(key=lambda item: item.title.lower())
        return workspaces

    def workspaces_payload(self) -> list[dict[str, object]]:
        return [info.to_payload(self.workspaces_dir / info.slug) for info in self.list_workspaces()]

    def workspace_info(self, slug: str) -> WorkspaceInfo | None:
        target = self.workspaces_dir / slug
        if not target.is_dir():
            return None
        return self._read_workspace_metadata(target)

    def workspace_payload(self, slug: str) -> dict[str, object] | None:
        info = self.workspace_info(slug)
        if not info:
            return None
        return info.to_payload(self.workspaces_dir / info.slug)

    def remove_workspace(self, slug: str) -> bool:
        target = self.workspaces_dir / slug
        if not target.exists():
            return False
        shutil.rmtree(target)
        return True

    def workspace_asset(self, slug: str, relative: str | None) -> Path | None:
        info = self.workspace_info(slug)
        if not info:
            return None
        base = self.workspaces_dir / info.slug
        root = info.root_path(base)
        asset = relative or info.entry
        if not asset:
            return None
        rel_path = Path(asset)
        if rel_path.is_absolute():
            return None
        candidate = (root / rel_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        if candidate.is_dir():
            candidate = candidate / "index.html"
        return candidate if candidate.exists() else None

    def launch_workspace(
        self,
        slug: str,
        *,
        args: Sequence[str] | str | None = None,
        wait: bool = False,
        timeout: float | None = None,
    ) -> dict[str, object]:
        info = self.workspace_info(slug)
        if not info:
            raise FileNotFoundError(f"Unknown workspace: {slug}")
        if not info.executable:
            raise FileNotFoundError("Workspace has no executable")
        base = self.workspaces_dir / info.slug
        exe_path = info.executable_path(base)
        if not exe_path or not exe_path.exists():
            raise FileNotFoundError(f"Executable not found: {info.executable}")
        launch_args = self._normalize_args(args) if args is not None else list(info.args)
        return self.launch_external(
            exe_path,
            args=launch_args,
            wait=wait,
            timeout=timeout,
            cwd=exe_path.parent,
        )

    def _discover_root(self, base: Path) -> Path:
        root = base
        while True:
            entries = [p for p in root.iterdir() if p.name not in {"__MACOSX"}]
            if len(entries) == 1 and entries[0].is_dir():
                root = entries[0]
                continue
            return root

    def _resolve_entry(self, root: Path, entry: str | None) -> str | None:
        if entry:
            entry_path = (root / entry).expanduser() if not Path(entry).is_absolute() else Path(entry)
            entry_path = entry_path.resolve()
            try:
                entry_path.relative_to(root)
            except ValueError as exc:  # pragma: no cover - safety guard
                raise ValueError("Entry must reside inside the workspace") from exc
            if not entry_path.is_file():
                raise FileNotFoundError(f"Workspace entry not found: {entry}")
            return entry_path.relative_to(root).as_posix()

        for candidate in ["index.html", "index.htm", "main.html", "app.html"]:
            candidate_path = root / candidate
            if candidate_path.is_file():
                return candidate
        html_files = sorted(root.glob("*.html"))
        if html_files:
            return html_files[0].name
        deep_html = sorted(root.rglob("*.html"))
        if deep_html:
            return deep_html[0].relative_to(root).as_posix()
        return None

    def _resolve_executable(self, root: Path, executable: str | None) -> str | None:
        if executable:
            exe_path = (root / executable).expanduser() if not Path(executable).is_absolute() else Path(executable)
            exe_path = exe_path.resolve()
            try:
                exe_path.relative_to(root)
            except ValueError as exc:  # pragma: no cover - safety guard
                raise ValueError("Executable must reside inside the workspace") from exc
            if not exe_path.is_file():
                raise FileNotFoundError(f"Executable not found: {executable}")
            return exe_path.relative_to(root).as_posix()

        candidates: list[tuple[int, Path]] = []
        for path in root.rglob("*"):
            if path.is_dir() and path.suffix.lower() != ".app":
                continue
            if path.is_file():
                suffix = path.suffix.lower()
                if suffix not in {".exe", ".bat", ".cmd", ".com", ".sh"}:
                    continue
            elif path.suffix.lower() == ".app":
                suffix = ".app"
            else:
                continue
            depth = len(path.relative_to(root).parts)
            score = depth * 10
            name_lower = path.name.lower()
            if "setup" in name_lower or "install" in name_lower:
                score += 5
            if any(keyword in name_lower for keyword in ("modalys", "praat", "max")):
                score -= 3
            candidates.append((score, path))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1].name.lower()))
        return candidates[0][1].relative_to(root).as_posix()

    def _write_workspace_metadata(self, base: Path, info: WorkspaceInfo) -> None:
        meta_path = base / ".workspace.json"
        meta_path.write_text(json.dumps(info.to_json(), indent=2), encoding="utf-8")

    def _read_workspace_metadata(self, base: Path) -> WorkspaceInfo | None:
        meta_path = base / ".workspace.json"
        if not meta_path.exists():
            return None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        args = data.get("args") or []
        if not isinstance(args, list):
            args = self._normalize_args(args)
        return WorkspaceInfo(
            slug=base.name,
            title=data.get("title", base.name),
            root=data.get("root", "."),
            kind=data.get("kind", "native"),
            entry=data.get("entry"),
            executable=data.get("executable"),
            args=args,
        )

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
            "workspaces": self.workspaces_payload(),
        }
