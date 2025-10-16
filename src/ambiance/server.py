"""Serve the Noisetown UI alongside JSON endpoints for the audio engine."""

from __future__ import annotations

import argparse
import base64
import json
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from string import Template
from typing import Any
from urllib.parse import urlparse

from .core.engine import AudioEngine
from .core.registry import registry
from .integrations.plugins import PluginRackManager
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


HOMEPAGE_TEMPLATE = Template("""<!DOCTYPE html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <title>Ambiance server</title>
    <style>
      body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;background:#0f1117;color:#f8f9fb}
      header{background:#1b1e27;padding:2.5rem 1.5rem 2rem 1.5rem;text-align:center;border-bottom:1px solid #2a2f3a}
      header h1{margin:0;font-size:2rem;font-weight:600}
      main{padding:2rem 1.5rem;max-width:720px;margin:0 auto;line-height:1.6}
      a{color:#7cc7ff;text-decoration:none}
      a:hover{text-decoration:underline}
      .card{background:#181b23;border:1px solid #2a2f3a;border-radius:12px;padding:1.25rem;margin-bottom:1.25rem;box-shadow:0 18px 45px rgba(0,0,0,0.25)}
      code{background:#11141b;padding:0.1rem 0.35rem;border-radius:6px;font-size:0.95em}
      ul{margin:0;padding-left:1.25rem}
      li{margin-bottom:0.35rem}
      .meta{display:flex;flex-wrap:wrap;gap:1rem;margin-top:1rem;font-size:0.95em;color:#c5c9d3}
    </style>
  </head>
  <body>
    <header>
      <h1>Ambiance control surface</h1>
      <p>Launch the interactive experience or explore the HTTP API below.</p>
    </header>
    <main>
      <section class=\"card\">
        <h2>Open the interface</h2>
        <p><a href=\"$ui_href\">Start the Noisetown UI</a> to browse the plugin rack and render ambience layers.</p>
        <p class=\"meta\">Currently serving <code>$ui_label</code>.</p>
      </section>
      <section class=\"card\">
        <h2>Plugin workspace</h2>
        <p>The rack watches <code>$workspace</code> for compatible plugins.</p>
        <div class=\"meta\">$plugin_summary</div>
      </section>
      <section class=\"card\">
        <h2>HTTP endpoints</h2>
        <ul>
          <li><code>GET /api/status</code> – Current rack status.</li>
          <li><code>GET /api/plugins</code> – Detailed plugin inventory and streams.</li>
          <li><code>POST /api/render</code> – Render ambience from JSON payloads.</li>
        </ul>
      </section>
    </main>
  </body>
</html>
""")


def build_homepage(status: dict[str, Any], ui_path: Path) -> str:
    """Render a compact landing page that links to the UI."""

    plugins = status.get("plugins") or []
    plugin_count = len(plugins)
    if plugin_count == 0:
        plugin_summary = "No plugins discovered yet. Drop VST, VST3, Audio Unit, or mc.svt files into the workspace."
    elif plugin_count == 1:
        plugin_summary = "1 plugin available."
    else:
        plugin_summary = f"{plugin_count} plugins available."

    workspace = status.get("workspace") or "Unavailable"
    if status.get("workspace_exists") is False:
        workspace_text = f"{workspace} (not found)"
    else:
        workspace_text = workspace

    ui_href = "/ui/" if status else "/ui/"

    ui_label = ui_path.name or "interface"

    return HOMEPAGE_TEMPLATE.substitute(
        ui_href=ui_href,
        workspace=workspace_text,
        plugin_summary=plugin_summary,
        ui_label=ui_label,
    )


class AmbianceRequestHandler(SimpleHTTPRequestHandler):
    """Serve static assets and lightweight JSON APIs."""

    def __init__(
        self,
        *args: Any,
        directory: str,
        manager: PluginRackManager,
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
        if path in {"/api/status", "/api/plugins"}:
            payload = self.manager.status()
            self._send_json(payload)
            return
        if path == "/api/registry":
            payload = {"sources": list(registry.sources()), "effects": list(registry.effects())}
            self._send_json(payload)
            return
        if path in {"/", ""}:
            self._serve_homepage()
            return
        if path in {"/ui", "/ui/"}:
            self._serve_ui()
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        path = urlparse(self.path).path
        try:
            if path == "/api/render":
                payload = self._read_json()
                response = render_payload(payload)
                self._send_json(response)
                return
            if path == "/api/plugins/assign":
                payload = self._read_json()
                plugin_path = payload.get("path")
                if not plugin_path:
                    self._send_json({"ok": False, "error": "Missing 'path'"}, HTTPStatus.BAD_REQUEST)
                    return
                stream = payload.get("stream", "Main")
                lane = payload.get("lane", "A")
                slot = payload.get("slot")
                result = self.manager.assign_plugin(
                    plugin_path,
                    stream=stream,
                    lane=lane,
                    slot=slot,
                )
                self._send_json({"ok": True, "assignment": result, "status": self.manager.status()})
                return
            if path == "/api/plugins/remove":
                payload = self._read_json()
                stream = payload.get("stream")
                if not stream:
                    self._send_json({"ok": False, "error": "Missing 'stream'"}, HTTPStatus.BAD_REQUEST)
                    return
                lane = payload.get("lane", "A")
                slot = payload.get("slot")
                remove_path = payload.get("path")
                result = self.manager.remove_plugin(
                    stream=stream,
                    lane=lane,
                    slot=slot,
                    path=remove_path,
                )
                self._send_json({"ok": True, "removed": result, "status": self.manager.status()})
                return
            if path == "/api/plugins/toggle":
                payload = self._read_json()
                stream = payload.get("stream") or "Main"
                result = self.manager.toggle_lane(stream)
                self._send_json({"ok": True, "toggle": result, "status": self.manager.status()})
                return
        except Exception as exc:  # pylint: disable=broad-except
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    # --- Static helpers ----------------------------------------------
    def _serve_homepage(self) -> None:
        status = self.manager.status()
        data = build_homepage(status, self.ui_path).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def serve(host: str = "127.0.0.1", port: int = 8000, ui: Path | None = None) -> None:
    base_dir = Path(__file__).resolve().parents[2]
    directory = str(base_dir)
    ui_path = Path(ui) if ui else base_dir / "noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html"
    manager = PluginRackManager(base_dir=base_dir)

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

