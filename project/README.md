
# AmbianceHost (JUCE desktop host) — Plus Features

Patched for JUCE 7 and extended:
- Async `FileChooser::launchAsync` (no modal loops)
- `AudioProcessorGraph::Node::Ptr`-safe iteration
- Detect plugin from file via `findAllTypesForFile`
- Editor window snapshots state
- **Global Wet/Dry mix** with custom `GainProcessor` (parallel dry tap)
- **Per-slot bypass**
- **Reorder** slots (Up/Down)
- **MIDI input** routed to plugins
- **Latency readout** (sum of plugin `getLatencySamples()`)

## Build
```
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
```
Run: `.uild\Release\AmbianceHost.exe`

VST3 enabled by default. Optional VST2 (legacy):
```
cmake -S . -B build -DJUCE_ENABLE_VST2=ON -DVST2_SDK_DIR=C:/path/to/VST2_SDK
cmake --build build --config Release
```
