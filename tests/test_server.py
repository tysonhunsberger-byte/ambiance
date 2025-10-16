from pathlib import Path

from ambiance.server import build_homepage, render_payload


def test_render_payload_produces_audio_data_url():
    payload = {
        "duration": 0.1,
        "sample_rate": 8000,
        "sources": [
            {"name": "sine", "frequency": 220, "amplitude": 0.1},
        ],
        "effects": [
            {"name": "lowpass", "cutoff": 1000},
        ],
    }

    response = render_payload(payload)

    assert response["ok"] is True
    assert response["audio"].startswith("data:audio/wav;base64,")
    assert response["samples"] == int(payload["duration"] * payload["sample_rate"])


def test_build_homepage_includes_status_details():
    status = {
        "workspace": "/tmp/plugins",
        "workspace_exists": True,
        "plugins": [{"path": "/tmp/plugins/example.vst3"}],
    }

    html = build_homepage(status, Path("noisetown.html"))

    assert "1 plugin available." in html
    assert "/tmp/plugins" in html
    assert "noisetown.html" in html
    assert "href=\"/ui/\"" in html
