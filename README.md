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
- **In-app launcher** – Provide paths to third-party executables and run them from the
  External Apps Workbench, capturing stdout/stderr without leaving the UI.
- **External workspace bubbles** – Register zipped web UIs or extracted tool folders
  and interact with them inside the External App Desktop that lives beneath the main
  Noisetown canvas.
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

3. Launch the interactive UI server to use the Noisetown interface together with the
   Python engine:

   ```bash
   python -m ambiance.server
   ```

   The command serves the bundled `noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html`
   interface at `http://127.0.0.1:8000/`. The UI exposes controls for checking the
   bundled Modalys and Praat installers, triggering extractions, launching any
   executable that you point to (including custom tools or the extracted installers),
   registering standalone executables or entire workspaces for external tools, and
   rendering ambience layers through the Python audio engine. If you place a
   different HTML interface on disk, pass its path via `--ui`.

### External workspaces & desktop bubbles

The External Apps Workbench includes a *Workspace Source* form that turns local
archives or folders into interactive "bubbles" on the External App Desktop (the band
of windows shown underneath the main Noisetown viewport):

1. **Source** – Enter a path to a `.zip` archive, an extracted directory, or a single
   executable file. The helper safely copies/expands the contents into
   `.cache/external_apps/workspaces/<slug>`. The bundled Modalys download is an
   installer; if you prefer to work with the raw Modalys files or Max 9 patches,
   extract them first (or request the raw files) and point the source field at that
   folder, a fresh zip of the unpacked files, or the executable you want to run.
2. **Entry HTML (optional)** – Provide a relative path to an HTML file when you want
   the workspace to surface inside the app as an iframe.
3. **Executable (optional)** – Supply a relative path to a native binary or script to
   expose a *Launch* button. The launcher reuses the same process-management logic that
   powers the generic executable runner, so captured stdout/stderr and background PIDs
   are streamed into the bubble's log.
4. **Default args (optional)** – Pre-populate launch arguments that appear in the
   bubble's input field.

Each workspace entry shows up in the workspace list for quick management and receives a
dedicated bubble. Web workspaces automatically load inside an iframe (with a reload
button for rapid iteration). Native workspaces show the log area and launch controls so
you can spawn the underlying executable while keeping an eye on the output. Removing a
workspace purges the cached copy from `.cache/external_apps/workspaces`.

4. Provide a JSON configuration to customize the engine:

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
