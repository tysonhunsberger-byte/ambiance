"""Command-line interface for rendering procedural ambience tracks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import (
    AudioEngine,
    DelayEffect,
    LowPassFilterEffect,
    ModalysSource,
    NoiseSource,
    PraatSource,
    ReverbEffect,
    SineWaveSource,
)
from .utils.audio import write_wav


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Path to the output WAV file")
    parser.add_argument("--duration", type=float, default=5.0, help="Duration in seconds")
    parser.add_argument("--sample-rate", type=int, default=44100, help="Sample rate")
    parser.add_argument("--config", type=Path, help="JSON config describing sources/effects")
    return parser


def run_from_config(engine: AudioEngine, config_path: Path) -> None:
    data = json.loads(config_path.read_text())
    for source_conf in data.get("sources", []):
        source_type = source_conf.pop("type")
        engine.add_source(globals()[source_type](**source_conf))
    for effect_conf in data.get("effects", []):
        effect_type = effect_conf.pop("type")
        engine.add_effect(globals()[effect_type](**effect_conf))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    engine = AudioEngine(sample_rate=args.sample_rate)

    if args.config:
        run_from_config(engine, args.config)
    else:
        engine.add_source(SineWaveSource(frequency=432, amplitude=0.2))
        engine.add_source(NoiseSource(amplitude=0.05))
        engine.add_source(ModalysSource())
        engine.add_source(PraatSource(vowel="o", amplitude=0.15))
        engine.add_effect(ReverbEffect())
        engine.add_effect(DelayEffect(time=0.35, feedback=0.25))
        engine.add_effect(LowPassFilterEffect(cutoff=5500))

    buffer = engine.render(duration=args.duration)
    write_wav(args.output, buffer, engine.sample_rate)
    print(f"Rendered ambience to {args.output} ({len(buffer)} samples)")


if __name__ == "__main__":
    main()
