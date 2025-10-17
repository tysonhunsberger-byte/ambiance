"""Helpers for discovering and routing native audio plugins."""

from __future__ import annotations

import base64
import json
import os
import shutil
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


PLUGIN_EXTENSIONS = {
    ".vst": "VST2",
    ".vst3": "VST3",
    ".dll": "VST (Windows)",
    ".component": "Audio Unit",
    ".mxo": "Max External",
    ".mxe": "Max External",
    ".mxe64": "Max External",
    ".svt": "SVT",
}

MODALYS_FILENAMES = {
    "mlys~.mxe64": "Modalys.mxe64",
    "mlys~.mxe": "Modalys.mxe",
    "mlys~.mxo": "Modalys.mxo",
}

LANES = ("A", "B")


@dataclass
class PluginRackManager:
    """Manage discovery and lightweight routing metadata for audio plugins."""

    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    workspace_dir: Path | None = None
    config_filename: str = "rack.json"
    max_preview_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        if self.workspace_dir is None:
            self.workspace_dir = self.base_dir / ".cache" / "plugins"
        else:
            self.workspace_dir = Path(self.workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self.workspace_dir / self.config_filename
        self._hydrate_modalys_bundle()
        if not self._config_path.exists():
            self._save_config({"streams": {}})

    # ------------------------------------------------------------------
    # Workspace discovery
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir)

    def _candidate_paths(self) -> Iterable[Path]:
        root = self.workspace_path()
        if not root.exists():
            return []

        def walker() -> Iterator[Path]:
            for dirpath, dirnames, filenames in os.walk(root):
                current = Path(dirpath)
                for dirname in list(dirnames):
                    candidate = current / dirname
                    if self._looks_like_plugin(candidate):
                        yield candidate
                        dirnames.remove(dirname)
                for filename in filenames:
                    candidate = current / filename
                    if self._looks_like_plugin(candidate):
                        yield candidate

        return walker()

    @staticmethod
    def _normalize_suffix(path: Path) -> str:
        name = path.name.lower()
        if name.endswith(".mc.svt"):
            return ".mc.svt"
        if name.endswith(".mcsvt"):
            return ".mcsvt"
        return path.suffix.lower()

    def _looks_like_plugin(self, path: Path) -> bool:
        if path.is_dir():
            suffix = self._normalize_suffix(path)
            return suffix in {".vst3", ".component"}
        suffix = self._normalize_suffix(path)
        if suffix in PLUGIN_EXTENSIONS or suffix in {".mc.svt", ".mcsvt"}:
            return True
        try:
            mode = path.stat().st_mode
        except OSError:
            return False
        return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

    def _describe_plugin(self, path: Path) -> dict[str, object] | None:
        if not self._looks_like_plugin(path):
            return None
        try:
            relative = path.relative_to(self.workspace_path())
            relative_text = str(relative)
        except ValueError:
            relative_text = ""
        suffix = self._normalize_suffix(path)
        name = path.name
        if suffix and name.lower().endswith(suffix):
            name = name[: -len(suffix)] or path.stem
        else:
            name = path.stem

        info: dict[str, object] = {
            "name": name,
            "path": str(path),
            "relative_path": relative_text,
            "type": "bundle" if path.is_dir() else "file",
            "format": self._format_for(path),
        }
        if path.is_file():
            try:
                info["size"] = path.stat().st_size
            except OSError:
                info["size"] = None
        metadata = self._load_plugin_metadata(path)
        if metadata:
            if metadata.get("name"):
                info["name"] = metadata["name"]
            if metadata.get("format"):
                info["format"] = metadata["format"]
            for key in ("display_name", "origin"):
                if metadata.get(key):
                    info[key] = metadata[key]
            notes = metadata.get("notes")
            if notes:
                if isinstance(notes, (list, tuple, set)):
                    for note in notes:
                        self._append_note(info, str(note))
                else:
                    self._append_note(info, str(notes))
        flutter_meta = self._flutter_vst3_descriptor(path)
        if flutter_meta:
            for key in ("name", "display_name", "format", "origin"):
                if flutter_meta.get(key):
                    info[key] = flutter_meta[key]
            if flutter_meta.get("flutter"):
                info["flutter"] = flutter_meta["flutter"]
            for note in flutter_meta.get("notes", []) or []:
                self._append_note(info, note)
        preview = self._find_preview_audio(path)
        if preview:
            info["render_preview"] = str(preview)
            try:
                info["render_preview_relative"] = str(preview.relative_to(self.workspace_path()))
            except ValueError:
                info["render_preview_relative"] = ""
        return info

    def _normalize_plugin_path(self, path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_path() / candidate
        try:
            return candidate.resolve()
        except OSError:
            return candidate

    def _format_for(self, path: Path) -> str:
        suffix = self._normalize_suffix(path)
        if suffix == ".mc.svt" or suffix == ".mcsvt":
            return "Max mc.svt"
        if suffix in {".mxe", ".mxe64"}:
            return "Max External"
        return PLUGIN_EXTENSIONS.get(suffix, suffix.lstrip("."))

    def discover_plugins(self, limit: int = 256) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for candidate in self._candidate_paths():
            info = self._describe_plugin(candidate)
            if info is None:
                continue
            entries.append(info)
            if len(entries) >= limit:
                break
        modalys = self._modalys_descriptor()
        if modalys and all(entry.get("path") != modalys.get("path") for entry in entries):
            entries.append(modalys)
        entries.sort(key=lambda item: (item.get("relative_path") or item.get("path") or "").lower())
        return entries

    # ------------------------------------------------------------------
    # Configuration persistence
    def _load_config(self) -> dict[str, object]:
        if not self._config_path.exists():
            return {"streams": {}}
        try:
            return json.loads(self._config_path.read_text())
        except json.JSONDecodeError:
            return {"streams": {}}

    def _save_config(self, data: dict[str, object]) -> None:
        tmp_path = self._config_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp_path.replace(self._config_path)

    def _ensure_stream(self, config: dict[str, object], stream: str) -> dict[str, object]:
        streams = config.setdefault("streams", {})
        stream_cfg = streams.get(stream)
        if not stream_cfg:
            stream_cfg = {
                "active_lane": "A",
                "lanes": {lane: [] for lane in LANES},
            }
            streams[stream] = stream_cfg
        else:
            lanes = stream_cfg.setdefault("lanes", {})
            for lane in LANES:
                lanes.setdefault(lane, [])
            if stream_cfg.get("active_lane") not in LANES:
                stream_cfg["active_lane"] = "A"
        return stream_cfg

    def _assignment_payload(self, entry: dict[str, object], plugins: dict[str, dict[str, object]]) -> dict[str, object]:
        payload = dict(entry)
        plugin = plugins.get(entry.get("path", ""))
        if plugin:
            payload["plugin"] = plugin
        return payload

    # ------------------------------------------------------------------
    # Rack operations
    def assign_plugin(
        self,
        path: str | Path,
        *,
        stream: str = "Main",
        lane: str = "A",
        slot: int | None = None,
    ) -> dict[str, object]:
        plugin_path = self._normalize_plugin_path(path)
        if not plugin_path.exists():
            raise FileNotFoundError(f"Plugin not found: {plugin_path}")
        plugin_path = plugin_path.resolve()
        lane_key = lane.upper()
        if lane_key not in LANES:
            raise ValueError(f"Unsupported lane '{lane}'")

        config = self._load_config()
        stream_cfg = self._ensure_stream(config, stream)
        lane_entries: list[dict[str, object]] = stream_cfg["lanes"][lane_key]

        if slot is None:
            slot_numbers = {int(entry.get("slot", 0)) for entry in lane_entries}
            next_slot = 0
            while next_slot in slot_numbers:
                next_slot += 1
            slot_idx = next_slot
        else:
            slot_idx = int(slot)

        replaced = False
        for entry in lane_entries:
            if int(entry.get("slot", -1)) == slot_idx:
                entry["path"] = str(plugin_path)
                replaced = True
                break
        if not replaced:
            lane_entries.append({"slot": slot_idx, "path": str(plugin_path)})
        lane_entries.sort(key=lambda item: int(item.get("slot", 0)))

        self._save_config(config)
        descriptor = self._describe_plugin(plugin_path) or {
            "name": plugin_path.stem,
            "path": str(plugin_path),
            "relative_path": "",
            "type": "file" if plugin_path.is_file() else "bundle",
            "format": self._format_for(plugin_path),
        }
        return {
            "stream": stream,
            "lane": lane_key,
            "slot": slot_idx,
            "plugin": descriptor,
        }

    def remove_plugin(
        self,
        *,
        stream: str,
        lane: str = "A",
        slot: int | None = None,
        path: str | None = None,
    ) -> dict[str, object]:
        lane_key = lane.upper()
        if lane_key not in LANES:
            raise ValueError(f"Unsupported lane '{lane}'")

        config = self._load_config()
        stream_cfg = self._ensure_stream(config, stream)
        lane_entries: list[dict[str, object]] = stream_cfg["lanes"][lane_key]

        if slot is None and path is None:
            raise ValueError("Provide a slot or path to remove a plugin")

        removed: list[dict[str, object]] = []
        keep: list[dict[str, object]] = []
        target_path: Path | None = None
        if path is not None:
            target_path = self._normalize_plugin_path(path)

        for entry in lane_entries:
            entry_slot = int(entry.get("slot", -1))
            entry_path = entry.get("path")
            if slot is not None and entry_slot == int(slot):
                removed.append(entry)
                continue
            if target_path is not None:
                entry_path_text = str(entry_path or "")
                if entry_path_text:
                    entry_target = self._normalize_plugin_path(entry_path_text)
                    if entry_target == target_path:
                        removed.append(entry)
                        continue
            keep.append(entry)
        lane_entries[:] = keep
        self._save_config(config)
        return {
            "stream": stream,
            "lane": lane_key,
            "removed": removed,
        }

    def toggle_lane(self, stream: str) -> dict[str, object]:
        config = self._load_config()
        stream_cfg = self._ensure_stream(config, stream)
        current = stream_cfg.get("active_lane", "A").upper()
        next_lane = "B" if current == "A" else "A"
        stream_cfg["active_lane"] = next_lane
        self._save_config(config)
        return {"stream": stream, "active_lane": next_lane}

    # ------------------------------------------------------------------
    # Status reporting
    def status(self) -> dict[str, object]:
        toolkit = self._flutter_toolkit_status()
        plugins = self.discover_plugins()
        plugin_lookup = {item["path"]: item for item in plugins}
        config = self._load_config()
        streams: dict[str, object] = {}
        for stream, stream_cfg in config.get("streams", {}).items():
            active_lane = stream_cfg.get("active_lane", "A")
            lane_payload: dict[str, list[dict[str, object]]] = {}
            for lane in LANES:
                entries = [
                    self._assignment_payload(entry, plugin_lookup)
                    for entry in stream_cfg.get("lanes", {}).get(lane, [])
                ]
                entries.sort(key=lambda item: int(item.get("slot", 0)))
                lane_payload[lane] = entries
            streams[stream] = {
                "active_lane": active_lane,
                "lanes": lane_payload,
            }
        if not streams:
            streams["Main"] = {
                "active_lane": "A",
                "lanes": {lane: [] for lane in LANES},
            }
        notes = [
            "Drop VST, VST3, Audio Unit, or mc.svt plugins into this folder to load them into the rack.",
            "Assign plugins to lane A or B to build parallel chains and toggle them for instant A/B comparisons.",
        ]
        if any(plugin.get("format") == "Flutter VST3" for plugin in plugins):
            notes.append(
                "Flutter/Dart VST3 bundles are supported. Generate them with MelbourneDeveloper/flutter_vst3 and drop the build output into the workspace."
            )
        if any(plugin.get("origin") == "Bundled Modalys package" for plugin in plugins):
            notes.append(
                "Modalys (Max) is bundled for quick experiments. Route it through a lane to explore physical modelling textures."
            )
        if toolkit and toolkit.get("notes"):
            for note in toolkit["notes"]:
                if note not in notes:
                    notes.append(note)
        return {
            "workspace": str(self.workspace_path()),
            "workspace_exists": self.workspace_path().exists(),
            "plugins": plugins,
            "streams": streams,
            "notes": notes,
            "flutter_toolkit": toolkit,
        }

    # ------------------------------------------------------------------
    # Flutter toolkit helpers
    def _flutter_toolkit_status(self) -> dict[str, object]:
        workspace = self.workspace_path()
        status: dict[str, object] = {
            "present": False,
            "ready": False,
            "has_archive": False,
            "notes": [],
        }
        archive = self._find_flutter_toolkit_archive()
        directory = self._existing_flutter_toolkit_dir()
        target_dir = workspace / "flutter_vst3_toolkit"
        if archive:
            status["has_archive"] = True
            status["archive"] = str(archive)
            try:
                status["archive_relative"] = str(archive.relative_to(workspace))
            except ValueError:
                status["archive_relative"] = ""
            extracted = self._ensure_flutter_toolkit_unpacked(archive, target_dir)
            if extracted:
                directory = extracted
            elif not directory:
                status["notes"].append(
                    "A flutter_vst3_toolkit archive was found but could not be unpacked. Verify the download and retry."
                )
        if directory and directory.exists():
            status["present"] = True
            status["ready"] = True
            status["directory"] = str(directory)
            try:
                status["directory_relative"] = str(directory.relative_to(workspace))
            except ValueError:
                status["directory_relative"] = ""
            assets_dir = self._locate_flutter_assets(directory)
            if assets_dir:
                status["assets"] = str(assets_dir)
                try:
                    status["assets_relative"] = str(assets_dir.relative_to(workspace))
                except ValueError:
                    status["assets_relative"] = ""
            status.setdefault(
                "notes",
                [],
            ).append(
                "Flutter VST3 toolkit unpacked — use it to scaffold Dart-driven plugins alongside your rack."
            )
            status["summary"] = "Toolkit unpacked and ready to scaffold Flutter VST3 plugins."
        elif archive:
            status["present"] = True
            status.setdefault("notes", []).append(
                "Flutter VST3 toolkit archive detected. It will be unpacked into the workspace on refresh."
            )
            status["summary"] = "Toolkit archive detected — unpacking in progress."
        else:
            status["summary"] = (
                "Drop flutter_vst3_toolkit.zip into the workspace to enable Flutter/Dart plugin scaffolding."
            )
        return status

    def _find_flutter_toolkit_archive(self) -> Path | None:
        candidates: list[Path] = []
        for root in {self.workspace_path(), self.base_dir}:
            try:
                if not root.exists():
                    continue
            except OSError:
                continue
            try:
                for candidate in root.glob("flutter_vst3_toolkit*.zip"):
                    if candidate.is_file():
                        try:
                            if zipfile.is_zipfile(candidate):
                                candidates.append(candidate)
                        except OSError:
                            continue
            except OSError:
                continue
        if not candidates:
            return None
        try:
            candidates.sort(key=lambda item: (item.stat().st_mtime, item.name))
        except OSError:
            candidates.sort(key=lambda item: item.name)
        return candidates[-1]

    def _existing_flutter_toolkit_dir(self) -> Path | None:
        workspace_candidate = self.workspace_path() / "flutter_vst3_toolkit"
        if workspace_candidate.exists() and workspace_candidate.is_dir():
            return workspace_candidate
        base_candidate = self.base_dir / "flutter_vst3_toolkit"
        if base_candidate.exists() and base_candidate.is_dir():
            return base_candidate
        return None

    def _ensure_flutter_toolkit_unpacked(self, archive: Path, target: Path) -> Path | None:
        try:
            stamp = f"{archive.resolve()}|{archive.stat().st_mtime_ns}"
        except OSError:
            stamp = str(archive)
        marker = target / ".toolkit-source"
        if target.exists() and marker.exists():
            try:
                if marker.read_text().strip() == stamp:
                    return target
            except OSError:
                pass
        try:
            with zipfile.ZipFile(archive) as zf:
                temp_dir = target.with_name(target.name + "__tmp__")
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                temp_dir.mkdir(parents=True, exist_ok=True)
                zf.extractall(temp_dir)
        except (OSError, zipfile.BadZipFile):
            return None
        extracted_root = self._collapse_single_directory(temp_dir)
        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            if extracted_root != temp_dir:
                shutil.move(str(extracted_root), str(target))
                shutil.rmtree(temp_dir, ignore_errors=True)
            else:
                temp_dir.rename(target)
            marker.write_text(stamp)
        except OSError:
            return None
        return target

    @staticmethod
    def _collapse_single_directory(directory: Path) -> Path:
        try:
            entries = [entry for entry in directory.iterdir() if entry.name != ".toolkit-source"]
        except OSError:
            return directory
        if len(entries) == 1 and entries[0].is_dir():
            return entries[0]
        return directory

    # ------------------------------------------------------------------
    # Modalys helpers
    def _modalys_bundle_candidates(self) -> list[Path]:
        roots = [self.base_dir]
        seen: set[Path] = set()
        candidates: list[Path] = []
        for root in roots:
            root_path = Path(root)
            if not root_path.exists():
                continue
            try:
                entries = list(root_path.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry in seen:
                    continue
                if "modalys" not in entry.name.lower():
                    continue
                if entry == self.workspace_path():
                    continue
                if entry.is_dir() or entry.suffix.lower() == ".zip":
                    candidates.append(entry)
                    seen.add(entry)
        return sorted(candidates)

    def _modalys_target_dir(self) -> Path:
        return self.workspace_path() / "Modalys"

    def _modalys_already_installed(self, target_dir: Path) -> bool:
        try:
            return any(target_dir.glob("Modalys.*"))
        except OSError:
            return False

    def _hydrate_modalys_bundle(self) -> None:
        target_dir = self._modalys_target_dir()
        if self._modalys_already_installed(target_dir):
            return
        for candidate in self._modalys_bundle_candidates():
            try:
                if self._install_modalys_candidate(candidate, target_dir):
                    break
            except Exception:  # pragma: no cover - defensive guard
                continue

    def _install_modalys_candidate(self, candidate: Path, target_dir: Path) -> bool:
        target_dir.mkdir(parents=True, exist_ok=True)
        installed: list[Path] = []
        if candidate.is_dir():
            installed = self._copy_modalys_from_dir(candidate, target_dir)
        elif candidate.suffix.lower() == ".zip":
            installed = self._copy_modalys_from_zip(candidate, target_dir)
        if not installed:
            return False
        self._write_modalys_metadata(target_dir, candidate)
        return True

    def _copy_modalys_from_dir(self, source: Path, target_dir: Path) -> list[Path]:
        installed: list[Path] = []
        for root, _, files in os.walk(source):
            for filename in files:
                lower = filename.lower()
                alias = MODALYS_FILENAMES.get(lower)
                if not alias:
                    continue
                dest = target_dir / alias
                if dest.exists():
                    continue
                src_path = Path(root) / filename
                try:
                    shutil.copy2(src_path, dest)
                except OSError:
                    continue
                installed.append(dest)
        return installed

    def _copy_modalys_from_zip(self, archive: Path, target_dir: Path) -> list[Path]:
        installed: list[Path] = []
        try:
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = Path(info.filename).name
                    alias = MODALYS_FILENAMES.get(name.lower())
                    if not alias:
                        continue
                    dest = target_dir / alias
                    if dest.exists():
                        continue
                    try:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, dest.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                    except OSError:
                        continue
                    installed.append(dest)
        except zipfile.BadZipFile:
            return []
        return installed

    def _write_modalys_metadata(self, target_dir: Path, source: Path) -> None:
        metadata = {
            "name": "Modalys (Max)",
            "display_name": "Modalys (Max)",
            "origin": "Bundled Modalys package",
            "format": "Max External",
            "notes": [
                "Modalys ships as a Max external. Load it into Max or mc.svt hosts to experiment with physical modelling.",
                f"Installed from {source.name}",
            ],
        }
        meta_path = target_dir / ".ambiance_plugin.json"
        try:
            meta_path.write_text(json.dumps(metadata, indent=2))
        except OSError:
            pass

    def _load_plugin_metadata(self, path: Path) -> dict[str, object] | None:
        workspace = self.workspace_path()
        current = path if path.is_dir() else path.parent
        while True:
            try:
                current.relative_to(workspace)
            except ValueError:
                break
            meta_path = current / ".ambiance_plugin.json"
            if meta_path.exists():
                try:
                    return json.loads(meta_path.read_text())
                except (OSError, json.JSONDecodeError):
                    return None
            if current == workspace:
                break
            current = current.parent
        return None

    @staticmethod
    def _ensure_note_list(info: dict[str, object]) -> list[str]:
        existing = info.get("notes")
        if isinstance(existing, list):
            return existing
        notes: list[str] = []
        if existing:
            notes.append(str(existing))
        info["notes"] = notes
        return notes

    def _append_note(self, info: dict[str, object], note: str) -> None:
        if not note:
            return
        notes = self._ensure_note_list(info)
        if note not in notes:
            notes.append(note)

    def _flutter_vst3_descriptor(self, path: Path) -> dict[str, object] | None:
        suffix = self._normalize_suffix(path)
        if suffix != ".vst3":
            return None
        bundle_root = path if path.is_dir() else path.parent
        assets_dir = self._locate_flutter_assets(bundle_root)
        if not assets_dir:
            return None
        descriptor: dict[str, object] = {
            "format": "Flutter VST3",
            "origin": "Flutter VST3 project",
            "notes": [
                "Flutter assets detected inside the bundle; the plugin can render Dart-driven UIs.",
                "Build and maintain the bundle with MelbourneDeveloper/flutter_vst3.",
            ],
        }
        flutter_meta = {
            "assets_path": str(assets_dir),
        }
        try:
            flutter_meta["assets_relative"] = str(assets_dir.relative_to(self.workspace_path()))
        except ValueError:
            flutter_meta["assets_relative"] = ""
        descriptor["flutter"] = flutter_meta
        pubspec = self._find_flutter_pubspec(bundle_root)
        if pubspec:
            pubspec_path, meta = pubspec
            if meta.get("name"):
                descriptor.setdefault("name", meta["name"])
                descriptor.setdefault("display_name", meta["name"].replace("_", " ").title())
            if meta.get("description"):
                descriptor.setdefault("notes", descriptor.get("notes", []))
                descriptor["notes"].append(meta["description"])
            if meta.get("homepage"):
                descriptor["flutter"]["homepage"] = meta["homepage"]
            descriptor["flutter"]["pubspec_path"] = str(pubspec_path)
            try:
                descriptor["flutter"]["pubspec_relative"] = str(pubspec_path.relative_to(self.workspace_path()))
            except ValueError:
                descriptor["flutter"]["pubspec_relative"] = ""
        return descriptor

    def _locate_flutter_assets(self, bundle_root: Path) -> Path | None:
        search_roots = [bundle_root]
        for child in ("Contents", "Resources"):
            candidate = bundle_root / child
            if candidate.exists():
                search_roots.append(candidate)
        for root in search_roots:
            direct = root / "flutter_assets"
            try:
                if direct.exists() and direct.is_dir():
                    return direct
            except OSError:
                continue
        try:
            for candidate in bundle_root.rglob("flutter_assets"):
                try:
                    if candidate.is_dir():
                        return candidate
                except OSError:
                    continue
        except OSError:
            return None
        return None

    def _find_flutter_pubspec(self, bundle_root: Path) -> tuple[Path, dict[str, str]] | None:
        candidates: list[Path] = []
        preferred = bundle_root / "pubspec.yaml"
        if preferred.exists():
            candidates.append(preferred)
        try:
            for candidate in bundle_root.rglob("pubspec.yaml"):
                if candidate == preferred:
                    continue
                candidates.append(candidate)
        except OSError:
            pass
        for candidate in candidates:
            try:
                text = candidate.read_text()
            except OSError:
                continue
            parsed = self._parse_flutter_pubspec_text(text)
            if parsed:
                return candidate, parsed
        return None

    @staticmethod
    def _parse_flutter_pubspec_text(text: str) -> dict[str, str] | None:
        lowered = text.lower()
        if "flutter" not in lowered and "flutter_vst3" not in lowered:
            return None
        name = None
        description = None
        homepage = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                continue
            value = value.split("#", 1)[0].strip().strip("'\"")
            if key == "name" and not name:
                name = value
            elif key == "description" and not description:
                description = value
            elif key == "homepage" and not homepage:
                homepage = value
        if not name and not description:
            return None
        return {k: v for k, v in {"name": name, "description": description, "homepage": homepage}.items() if v}

    def _modalys_descriptor(self) -> dict[str, object] | None:
        workspace = self.workspace_path()
        candidates: list[Path] = []
        for pattern in ("Modalys.mxe64", "Modalys.mxe", "Modalys.mxo"):
            candidates.extend(workspace.rglob(pattern))
        if not candidates:
            return None
        plugin_path = min(candidates, key=lambda p: len(p.parts))
        descriptor = self._describe_plugin(plugin_path)
        if descriptor:
            descriptor.setdefault("name", "Modalys (Max)")
            descriptor.setdefault("display_name", descriptor["name"])
            descriptor.setdefault("origin", "Bundled Modalys package")
            descriptor.setdefault("format", "Max External")
        return descriptor

    # ------------------------------------------------------------------
    # Preview discovery
    def _find_preview_audio(self, path: Path) -> Path | None:
        """Locate a rendered preview file that belongs to *path* if available."""

        candidates: list[Path] = []
        stem = path.stem
        parent = path.parent

        if path.is_dir():
            candidates.extend(
                [
                    path / "render.wav",
                    path / "rendered.wav",
                    path / "preview.wav",
                    path / f"{stem}.wav",
                    path / f"{stem}_render.wav",
                    path / f"{stem}_preview.wav",
                ]
            )
        else:
            candidates.extend(
                [
                    path.with_suffix(".wav"),
                    parent / f"{stem}.wav",
                    parent / f"{stem}_render.wav",
                    parent / f"{stem}_preview.wav",
                    parent / "render.wav",
                    parent / "preview.wav",
                ]
            )

        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    def _parse_wav_metadata(self, data: bytes) -> tuple[int, int, float]:
        """Extract channels, sample rate, and duration from PCM WAV bytes."""

        if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise ValueError("Preview is not a valid WAV file")
        offset = 12
        channels = 0
        sample_rate = 0
        bits_per_sample = 0
        data_size = 0
        while offset + 8 <= len(data):
            chunk_id = data[offset : offset + 4]
            chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
            chunk_start = offset + 8
            if chunk_id == b"fmt ":
                if chunk_size < 16:
                    raise ValueError("Invalid WAV fmt chunk")
                fmt = data[chunk_start : chunk_start + 16]
                audio_format = int.from_bytes(fmt[:2], "little")
                channels = int.from_bytes(fmt[2:4], "little")
                sample_rate = int.from_bytes(fmt[4:8], "little")
                bits_per_sample = int.from_bytes(fmt[14:16], "little")
                if audio_format not in {1, 3}:  # PCM / IEEE float
                    raise ValueError("Preview WAV must be PCM/float")
            elif chunk_id == b"data":
                data_size = chunk_size
                break
            offset = chunk_start + chunk_size
        if not channels or not sample_rate or not data_size:
            raise ValueError("Incomplete WAV preview metadata")
        bytes_per_sample = max(bits_per_sample // 8, 1)
        frame_size = bytes_per_sample * channels
        if not frame_size:
            raise ValueError("Invalid WAV preview frame size")
        duration = data_size / float(frame_size * sample_rate)
        return channels, sample_rate, duration

    def plugin_preview(self, path: str | Path) -> dict[str, object]:
        """Return a data URL for a rendered preview that belongs to *path*."""

        plugin_path = self._normalize_plugin_path(path)
        preview_path = self._find_preview_audio(plugin_path)
        if not preview_path:
            raise FileNotFoundError(f"Preview not found for plugin: {plugin_path}")
        try:
            raw = preview_path.read_bytes()
        except OSError as exc:  # pragma: no cover - filesystem edge
            raise FileNotFoundError(f"Unable to read preview: {preview_path}") from exc
        if len(raw) > self.max_preview_bytes:
            raise ValueError("Preview file is too large")
        channels, sample_rate, duration = self._parse_wav_metadata(raw)
        encoded = base64.b64encode(raw).decode("ascii")
        try:
            relative = str(preview_path.relative_to(self.workspace_path()))
        except ValueError:
            relative = ""
        return {
            "path": str(preview_path),
            "relative_path": relative,
            "audio": f"data:audio/wav;base64,{encoded}",
            "channels": channels,
            "sample_rate": sample_rate,
            "duration": duration,
            "size": len(raw),
        }
