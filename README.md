# Ambiance Workspace

## Project Overview
This repository currently ships the Noisetown workspace as a single, monolithic HTML document named `noisetown_ADV_CHORD_PATCHED_v4g1_applyfix.html`. The file embeds all structure, styling, and interactive logic inside `<style>` and `<script>` blocks, resulting in more than three thousand lines of tightly coupled markup, CSS, and JavaScript.

## Should the project be split into multiple files?
Splitting the project into a multi-file structure would offer clear benefits:

- **Maintainability** – Isolating the HTML template, CSS themes, and JavaScript controllers reduces cognitive load when editing. Developers can reason about one layer at a time instead of scrolling through thousands of lines to locate the correct section.
- **Reusability** – Shared assets, such as the Windows XP and Windows 98 theme rules, could live in standalone stylesheets that other documents (or future components) can import without duplication.
- **Tooling** – With a `package.json`, you could codify formatting, linting, and bundling scripts (for example using Vite, Parcel, or a lightweight static server). That makes it easier to run automated checks—one of the user’s original goals.

There are a few trade-offs to consider:

- **Migration effort** – Extracting each `<style>` and `<script>` block will take time and care. You will need to convert inline `document.getElementById` lookups or template injections so they still run after moving to external modules.
- **Deployment** – If the current hosting pipeline expects a single HTML file, you will need to update it to serve additional assets.

## Suggested next steps
If you decide to modularize, a minimal plan could look like this:

1. Rename the entry point to `index.html` and replace inline `<style>` blocks with `<link rel="stylesheet" href="styles/base.css">`, `styles/theme-xp.css`, etc.
2. Move general interaction logic (drag/drop handling, style editing tools, preset management) into `scripts/app.js` while preserving any `defer` loading behavior.
3. Introduce a `package.json` with scripts such as `"start": "npx serve ."` or `"lint": "eslint scripts"`. From there you can add Prettier or TypeScript incrementally.
4. Consider breaking very large logical areas—like the modular synth configuration or preset registry—into separate JS modules so that each file stays approachable.

Keeping everything in one file remains viable for distribution, but a multi-file setup will make ongoing maintenance significantly easier, especially now that many historical features (like random dark palettes) have already been removed.
