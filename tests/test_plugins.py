from pathlib import Path

from ambiance import AudioEngine, PluginManager, SineWaveSource
from ambiance.npcompat import np


def test_plugin_manager_reports_builtins(tmp_path):
    cache_dir = tmp_path / "plugins"
    manager = PluginManager(base_dir=tmp_path, cache_dir=cache_dir)

    status = manager.status()

    assert any(item["slug"] == "builtin-gain" for item in status["plugins"])
    assert status["rack"]["active_bank"] == "A"


def test_builtin_gain_chain_amplifies_signal(tmp_path):
    cache_dir = tmp_path / "plugins"
    manager = PluginManager(base_dir=tmp_path, cache_dir=cache_dir)
    config = {
        "active_bank": "A",
        "banks": {
            "A": {
                "streams": {
                    "sine": [
                        {"slug": "builtin-gain", "params": {"gain_db": 6.0}},
                    ]
                }
            }
        },
    }

    rack = manager.build_rack_from_config(config)

    baseline_engine = AudioEngine(sample_rate=48000)
    baseline_engine.add_source(SineWaveSource(frequency=440, amplitude=0.2))
    baseline = baseline_engine.render(0.05)

    engine = AudioEngine(sample_rate=48000)
    engine.add_source(SineWaveSource(frequency=440, amplitude=0.2))
    engine.set_plugin_rack(rack)
    processed = engine.render(0.05)

    baseline_vals = list(baseline)
    processed_vals = list(processed)

    assert len(processed_vals) == len(baseline_vals)
    assert max(abs(x) for x in processed_vals) > max(abs(x) for x in baseline_vals)
    ratios = [
        processed_vals[i] / baseline_vals[i]
        for i in range(len(baseline_vals))
        if abs(baseline_vals[i]) > 1e-6
    ]
    assert ratios
    first = ratios[0]
    for value in ratios:
        assert abs(value - first) < 1e-3
