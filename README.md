# Ambiance Workspace

## Project Overview
The Noisetown workspace is now delivered as a standard multi-file web project. The former 3,000+ line monolithic HTML file has been replaced with a clean entry point (`index.html`) that links to dedicated style and script bundles. This separation keeps presentation, behavior, and markup easy to reason about while preserving the existing synth workflow.

## Project Structure
```
./index.html            # markup only – references external CSS and JS
./styles/main.css       # consolidated theme, layout, and edit-mode rules
./scripts/app.js        # audio graph, UI wiring, session/preset logic
./scripts/mods-advanced.js
./scripts/mod-apply.js
./scripts/toolbar.js    # toolbar theming, XP chrome, clock/start button
./package.json          # tooling entry points (serve + prettier)
```
All former inline `<style>` and `<script>` blocks have been migrated into the files above. Shared helpers such as the XP taskbar chrome are now reusable functions instead of inlined snippets.

## Development
Install dependencies and start a static file server with:
```
npm install
npm run start
```
`npm run format` invokes Prettier across HTML, CSS, JS, and JSON should you want to clean up edits.

## Edit Mode Improvements
Edit mode now provides dedicated controls:

- Each stream header exposes **Remove Stream**, **Add Module**, and drag hints whenever edit mode is active.
- Module headers grow a **Remove** button (visible only in edit mode) so you can prune individual processors.
- The **Add Module** dropdown lets you re-insert any module type that was removed from the current stream.
- Drag-and-drop for streams and module cards has been stabilised so ordering works reliably after toggling edit mode.

These changes eliminate the previous issues where modules could not be added, removed, or reordered while editing.
