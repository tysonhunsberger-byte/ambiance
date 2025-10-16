"""Serve the Noisetown UI alongside JSON endpoints for the audio engine."""

from __future__ import annotations

import argparse
import base64
import json
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import urlparse

from .core.engine import AudioEngine
from .core.registry import registry
from .integrations.external_apps import ExternalAppManager
from .utils.audio import encode_wav_bytes


def _build_engine(payload: dict[str, Any]) -> tuple[AudioEngine, float]:
    duration = float(payload.get("duration", 5.0))
    sample_rate = int(payload.get("sample_rate", 44100))
    engine = AudioEngine(sample_rate=sample_rate)

    for source_conf in payload.get("sources", []):
        config = dict(source_conf)
        name = config.pop("name", config.pop("type", None))
        if not name:
            raise ValueError("Source configuration missing 'name'")
        engine.add_source(registry.create_source(name, **config))

    for effect_conf in payload.get("effects", []):
        config = dict(effect_conf)
        name = config.pop("name", config.pop("type", None))
        if not name:
            raise ValueError("Effect configuration missing 'name'")
        engine.add_effect(registry.create_effect(name, **config))

    return engine, duration


def render_payload(payload: dict[str, Any]) -> dict[str, Any]:
    engine, duration = _build_engine(payload)
    buffer = engine.render(duration)
    audio = encode_wav_bytes(buffer, engine.sample_rate)
    encoded = base64.b64encode(audio).decode("ascii")
    return {
        "ok": True,
        "audio": f"data:audio/wav;base64,{encoded}",
        "duration": duration,
        "samples": len(buffer),
        "sample_rate": engine.sample_rate,
        "config": engine.configuration(),
    }


class AmbianceRequestHandler(SimpleHTTPRequestHandler):
    """Serve static assets and lightweight JSON APIs."""

    def __init__(
        self,
        *args: Any,
        directory: str,
        manager: ExternalAppManager,
        ui_path: Path,
        **kwargs: Any,
    ) -> None:
        self.manager = manager
        self.ui_path = ui_path
        super().__init__(*args, directory=directory, **kwargs)

    # --- Response helpers -------------------------------------------
    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON payload") from exc

    # --- Routing -----------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        path = urlparse(self.path).path
        if path == "/api/status":
            payload = self.manager.status()
            self._send_json(payload)
            return
        if path == "/api/registry":
            payload = {"sources": list(registry.sources()), "effects": list(registry.effects())}
            self._send_json(payload)
            return
        if path == "/api/workspaces":
            payload = {"ok": True, "workspaces": self.manager.workspaces_payload()}
            self._send_json(payload)
            return
        if path.startswith("/api/workspaces/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "workspaces":
                slug = parts[2]
                workspace = self.manager.workspace_payload(slug)
                if not workspace:
                    self.send_error(HTTPStatus.NOT_FOUND, "Workspace not found")
                    return
                self._send_json({"ok": True, "workspace": workspace})
                return
        if path.startswith("/apps/"):
            self._serve_workspace_asset(path)
            return
        if path in {"/", "", "/ui"}:
            self._serve_ui()
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        path = urlparse(self.path).path
        try:
            if path == "/api/install":
                payload = self._read_json()
                slug = payload.get("slug") or payload.get("bundle")
                if not slug:
                    self._send_json({"ok": False, "error": "Missing 'slug'"}, HTTPStatus.BAD_REQUEST)
                    return
                try:
                    status = self.manager.install_bundled(str(slug))
                except FileNotFoundError:
                    self._send_json({"ok": False, "error": "Unknown bundled resource"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": bool(status.get("installed")), "status": status})
                return
            if path == "/api/render":
                payload = self._read_json()
                response = render_payload(payload)
                self._send_json(response)
                return
            if path == "/api/run-app":
                payload = self._read_json()
                executable = payload.get("path") or payload.get("executable")
                if not executable:
                    self._send_json({"ok": False, "error": "Missing 'path'"}, HTTPStatus.BAD_REQUEST)
                    return
                args = payload.get("args")
                wait = bool(payload.get("wait", False))
                timeout_raw = payload.get("timeout")
                cwd = payload.get("cwd")
                timeout_value = None
                if timeout_raw not in (None, ""):
                    try:
                        timeout_value = float(timeout_raw)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Invalid timeout value") from exc
                result = self.manager.launch_external(
                    executable,
                    args=args,
                    wait=wait,
                    timeout=timeout_value,
                    cwd=cwd,
                )
                payload = {"ok": bool(result.get("ok", False)), **result}
                self._send_json(payload)
                return
            if path == "/api/workspaces":
                payload = self._read_json()
                source = payload.get("source")
                if not source:
                    self._send_json({"ok": False, "error": "Missing 'source'"}, HTTPStatus.BAD_REQUEST)
                    return
                info = self.manager.ensure_workspace(
                    source,
                    name=payload.get("name"),
                    entry=payload.get("entry"),
                    executable=payload.get("executable"),
                    args=payload.get("args"),
                )
                self._send_json({"ok": True, "workspace": info.to_payload(self.manager.workspaces_dir / info.slug)})
                return
            if path.startswith("/api/workspaces/") and path.endswith("/launch"):
                parts = path.strip("/").split("/")
                if len(parts) != 4 or parts[0] != "api" or parts[1] != "workspaces" or parts[3] != "launch":
                    self.send_error(HTTPStatus.NOT_FOUND, "Unknown workspace endpoint")
                    return
                slug = parts[2]
                payload = self._read_json()
                timeout_value = None
                timeout_raw = payload.get("timeout")
                if timeout_raw not in (None, ""):
                    try:
                        timeout_value = float(timeout_raw)
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Invalid timeout value") from exc
                result = self.manager.launch_workspace(
                    slug,
                    args=payload.get("args"),
                    wait=bool(payload.get("wait", False)),
                    timeout=timeout_value,
                )
                self._send_json({"ok": bool(result.get("ok", False)), **result})
                return
        except Exception as exc:  # pylint: disable=broad-except
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib signature
        path = urlparse(self.path).path
        if path.startswith("/api/workspaces/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "workspaces":
                slug = parts[2]
                removed = self.manager.remove_workspace(slug)
                if not removed:
                    self.send_error(HTTPStatus.NOT_FOUND, "Workspace not found")
                    return
                self._send_json({"ok": True})
                return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    # --- Static helpers ----------------------------------------------
    def _serve_ui(self) -> None:
        if not self.ui_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "UI file missing")
            return
        data = self.ui_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_workspace_asset(self, path: str) -> None:
        parts = path.strip("/").split("/", 2)
        if len(parts) < 2:
            self.send_error(HTTPStatus.NOT_FOUND, "Workspace not found")
            return
        slug = parts[1]
        relative = parts[2] if len(parts) > 2 else None
        asset = self.manager.workspace_asset(slug, relative)
        if not asset:
            self.send_error(HTTPStatus.NOT_FOUND, "Workspace asset not found")
            return
        data = asset.read_bytes()
        self.send_response(HTTPStatus.OK)
        mime = self.guess_type(asset.name)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def serve(host: str = "127.0.0.1", port: int = 8000, ui: Path | None = None) -> None:
    base_dir = Path(__file__).resolve().parents[2]
    directory = str(base_dir)
    ui_path = Path(ui) if ui else base_dir / "noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html"
    manager = ExternalAppManager(base_dir=base_dir)

    def handler(*args: Any, **kwargs: Any) -> AmbianceRequestHandler:
        kwargs.setdefault("directory", directory)
        kwargs.setdefault("manager", manager)
        kwargs.setdefault("ui_path", ui_path)
        return AmbianceRequestHandler(*args, **kwargs)

    with ThreadingHTTPServer((host, port), handler) as httpd:
        print(f"Ambiance UI available at http://{host}:{port}/")
        httpd.serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Ambiance UI server")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--ui", type=Path, help="Path to a custom UI HTML file")
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, ui=args.ui)


if __name__ == "__main__":  # pragma: no cover - manual usage
    main()

