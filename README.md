# Ambiance

Ambiance is a modular audio generation toolkit that blends procedural synthesis with
a light-weight plugin rack. The engine can host VST/VST3, Audio Unit, and mc.svt
plug-ins (alongside a handful of built-in utility processors) so that ambience beds
and spot effects can be routed through familiar studio tools while remaining
scriptable from Python.

## Features

- **Composable audio engine** – Combine any number of sources and effects.
- **Plugin rack & desktop** – Register VST/VST3, Audio Unit, mc.svt, or built-in
  processors, assign them to specific streams or the master bus with A/B banks,
  and inspect per-stream pedalboards alongside the Noisetown blocks.
- **Interactive plugin control** – Open plug-in editors through Carla/Pluginval hosts
  directly from the UI so the processors remain usable in-app.
- **Procedural audio sources** – Sine waves, noise beds, resonator simulations, and
  formant-inspired vocal timbres.
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

   Provide a JSON configuration if you want to drive the plugin rack, sources, or effects
   from a saved template. The CLI understands the same schema that the UI renders.

3. Launch the interactive UI server to use the Noisetown interface together with the
   Python engine:

   ```bash
   python -m ambiance.server
   ```

   The command serves the bundled `noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html`
   interface at `http://127.0.0.1:8000/`. The UI exposes a **Plugin Desktop** that
   lists every registered processor, provides browse buttons for adding new plug-ins,
   and shows draggable "bubbles" for each plug-in editor that you launch through Carla
   or Pluginval. Use the rack controls to assign processors to named streams (the
   engine uses the `name` attribute from each source) or the master chain and flip
   between A/B banks while auditioning tweaks. If you place a different HTML interface
   on disk, pass its path via `--ui`.

### Working with the plugin rack

1. **Rescan or register plug-ins** – The rack automatically registers a pair of
   built-in processors (gain trim and high-pass). Use the *Rescan* button to search the
   default VST/AU locations or point the *Add Plug-in* field at any `.vst3`, `.vst`,
   `.dll`, `.component`, `.svt`, or `.mc.svt` file/directory. Entries are cached in
   `.cache/plugins/plugins.json`.
2. **Assign processors to streams** – Choose a stream key (the stream picker now lists
   every block/stream that exists in the UI), pick a plug-in, and add it to the active
   bank. Chains render in order and can target individual sources or the master bus.
3. **Use the pedalboard overlay** – Each Noisetown stream now exposes a *Plugin
   Pedalboard* card. Rename the stream key from the block, then glance at the pedalboard
   to see which processors are active on that stream without leaving the instrument view.
4. **A/B comparison** – Each bank maintains independent chains so you can toggle the
   active bank while exploring alternate routings or parameter sets. The rack API
   persists the configuration in `.cache/plugins/rack.json`.
5. **Open plug-in editors** – If Carla or Pluginval is available on your PATH, press
   *Open Editor* to spawn the plug-in UI inside a desktop bubble beneath the main
   Noisetown viewport.

4. Provide a JSON configuration to customize the engine:

   ```json
   {
     "sources": [
       {"type": "SineWaveSource", "frequency": 523.25, "amplitude": 0.15},
       {"type": "FormantVoiceSource", "vowel": "i", "amplitude": 0.2}
     ],
     "effects": [
       {"type": "ReverbEffect", "decay": 0.4, "mix": 0.25}
     ],
     "plugins": {
       "active_bank": "A",
       "banks": {
         "A": {
           "streams": {
             "sine": [
               {"slug": "builtin-gain", "params": {"gain_db": -3}}
             ],
             "master": [
               {"slug": "builtin-highpass", "params": {"cutoff_hz": 140}}
             ]
           }
         }
       }
     }
   }
   ```

   ```bash
   python -m ambiance.cli output.wav --config config.json
   ```

## Development

- Run tests with `pytest`.
- Package metadata lives in `pyproject.toml`.
- Plug-in caches live under `.cache/plugins`. Registering additional plug-ins simply
  records their paths in `plugins.json`, so version control stays clean.

## Upgrading

To add new audio engines or effects:

1. Create a subclass of `AudioSource` or `AudioEffect`.
2. Decorate the class with `@registry.register_source` or `@registry.register_effect`.
3. Drop the module anywhere under `src/ambiance/` and import it so registration happens.

The registry immediately makes the new feature available to the CLI and configuration
system without further wiring.
