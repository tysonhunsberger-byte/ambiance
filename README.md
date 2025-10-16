# Ambiance

Ambiance is a modular audio generation toolkit that blends procedural synthesis with
external acoustic modeling tools. The repository ships with the Windows installers for
**Modalys 3.9.0** and **Praat 6.4.45** so that sound designers who run on Windows can
hook directly into those environments. The Python code offers drop-in simulations when
those executables are not available, which keeps the package cross-platform friendly
and ready for CI environments.

## Features

- **Composable audio engine** – Combine any number of sources and effects.
- **External tool integration** – Modalys and Praat installers are detected, extracted
  into a cache directory on demand, and exposed through Python wrappers.
- **Procedural audio sources** – Sine waves, noise beds, Modalys resonators, and
  Praat-inspired vocal timbres.
- **Signal processing effects** – Reverb, ping-pong delay, and low-pass filtering.
- **Command line renderer** – Render ambience tracks directly to WAV files.
- **Upgradeable architecture** – New sources/effects can be registered by importing a
  class and annotating it with the registry decorators.

## Getting started

1. Create a virtual environment and install the project:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```

2. Render an ambience track using the default configuration:

   ```bash
   python -m ambiance.cli output.wav --duration 10
   ```

   If you run the command on Windows and keep the bundled installers in the repository
   root, the wrappers will extract them into `.cache/external_apps` and allow you to use
   the native binaries. On other platforms, the Python fallbacks generate similar sounds
   so your workflows stay portable.

3. Provide a JSON configuration to customize the engine:

   ```json
   {
     "sources": [
       {"type": "SineWaveSource", "frequency": 523.25, "amplitude": 0.15},
       {"type": "PraatSource", "vowel": "i", "amplitude": 0.2}
     ],
     "effects": [
       {"type": "ReverbEffect", "decay": 0.4, "mix": 0.25}
     ]
   }
   ```

   ```bash
   python -m ambiance.cli output.wav --config config.json
   ```

## Development

- Run tests with `pytest`.
- Package metadata lives in `pyproject.toml`.
- External resources are kept at the repository root and extracted to `.cache/` when
  requested. The `.gitignore` prevents accidental commits of unpacked binaries.

## Upgrading

To add new audio engines or effects:

1. Create a subclass of `AudioSource` or `AudioEffect`.
2. Decorate the class with `@registry.register_source` or `@registry.register_effect`.
3. Drop the module anywhere under `src/ambiance/` and import it so registration happens.

The registry immediately makes the new feature available to the CLI and configuration
system without further wiring.
