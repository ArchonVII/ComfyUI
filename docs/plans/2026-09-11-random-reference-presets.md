# Random Reference Presets and Prompt Prefixes

**Status:** Complete

## Goal and source

Update the local `arch-Random Reference Image Source` requested on 2026-09-11 so reusable favorites can represent either a folder or an explicit set of image paths. Each favorite may also carry prompt text. When the node receives an incoming prompt, it emits the favorite text first, followed by a comma and the incoming prompt. Make the updated package available to the restricted ComfyUI server on port 8192 without enabling unrelated custom or API nodes.

Saved workflow JSON and personal images are owner data and remain untouched. Presets store paths only; they never copy, move, modify, or upload images.

## Decisions

- Keep the existing node class name and existing input/output positions. Add optional fields and append the combined prompt output so old workflow links remain valid.
- Store versioned JSON below ComfyUI's active user directory rather than inside the plugin. The 8192 instance therefore owns its presets under its private runtime user tree.
- Seed an empty user store from the bundled folder-only favorites on first mutation. This preserves the existing named folders without treating repository files as mutable owner data.
- A preset contains a stable name, source kind (`folder` or `selection`), base folder, selected paths when applicable, recursive-folder flag, and optional prompt prefix.
- Manage presets from transient node buttons and refresh the existing favorite combo in place. Loading a preset fills the visible source fields and prompt-prefix editor.
- BCARD-3D will retain `--disable-all-custom-nodes` and add a fixed whitelist for only `comfyui_random_reference_source`.

## Implementation

1. Add focused preset-store and prompt-composition tests, then implement validated, atomic JSON reads/writes and legacy normalization.
2. Teach pool resolution and preview/execution to use folder and selection presets. Add the optional incoming prompt and append the combined prompt output.
3. Add local preset list/save/delete routes and node controls without serializing transient UI widgets.
4. Update package documentation and focused frontend persistence contracts.
5. In the linked BCARD-3D issue lane, add the fixed custom-node whitelist and align launcher documentation.
6. Synchronize the verified package into the ignored 8192 install, restart only its managed server, and verify the node and routes through loopback.

## Verification

- Focused package pytest suite passes, including legacy workflow persistence, folder presets, selection presets, invalid data, and prefix ordering.
- JavaScript parses and transient controls do not create sparse saved widget arrays.
- BCARD-3D focused launcher tests prove the exact whitelist and continued API-node restriction.
- Port 8192 reports `RandomReferenceImageSource` and `ReferenceLanePack`; a disposable fixture confirms `favorite text, incoming prompt` without reading or changing owner images.
- Git scope checks show no saved workflow, personal image, or runtime preset data tracked.

## Closeout

- RED was observed for the absent preset API and absent BCARD launcher whitelist before implementation.
- The package suite passes 42 tests; Ruff lint/format and JavaScript syntax checks pass.
- The BCARD launcher suite passes 37 tests with the fixed one-package whitelist.
- The verified package was synchronized into the ignored ComfyUI 0.34.2 installation and loaded on port 8192 with all other custom nodes and API/cloud nodes still disabled.
- A generated two-image selection favorite saved its ordered paths and prompt prefix, returned both images through the live preview route, and was deleted. The generated fixture files were also removed.
- The active user store is schema version 1 with the five migrated folder favorites and no smoke-test favorite. No saved workflow or personal image was changed.
