# Ambiance

Ambiance is a modular audio generation toolkit that blends procedural synthesis with
launch hooks for native audio tools. Drop any executable into the workspace directory
and the system exposes it through the UI and Python helpers while providing fallbacks
for cross-platform development and CI.

## Features

- **Composable audio engine** – Combine any number of sources and effects.
- **External tool integration** – Executables placed in the workspace directory are
  discovered automatically and can be launched from the UI or Python helpers.
- **In-app launcher** – Provide paths to third-party executables and run them from the
  External Apps Workbench, capturing stdout/stderr without leaving the UI.
- **Procedural audio sources** – Sine waves, noise beds, resonant instrument models,
  and formant-inspired vocal timbres.
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

   The command renders using the built-in procedural sources. To hook in an external
   tool, drop its executable inside `.cache/external_apps` (created on demand) and
   launch it with the workspace UI or the REST API.

3. Launch the interactive UI server to use the Noisetown interface together with the
   Python engine:

   ```bash
   python -m ambiance.server
   ```

   The command serves the bundled `noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html`
   interface at `http://127.0.0.1:8000/`. The UI exposes the external tools workspace,
   lets you launch any executable stored there, and renders ambience layers through the
   Python audio engine. If you place a different HTML interface on disk, pass its path
   via `--ui`.

4. Provide a JSON configuration to customize the engine:

   ```json
   {
     "sources": [
       {"type": "SineWaveSource", "frequency": 523.25, "amplitude": 0.15},
       {"type": "VocalFormantSource", "vowel": "i", "amplitude": 0.2}
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
