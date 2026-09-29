# Random Reference Presets and Prompt Prefixes

**Status:** Complete

## Reference browser revision — 2026-09-29

**Status:** Implemented and installed on 8192; browser visual verification blocked
by Chrome's local-page restriction.

Replace the oversized node controls with a compact source summary, preview,
selection policy, and an Open Reference Browser button. The browser has a
searchable Favorites sidebar, explicit Folder/Selected images controls, a
scrollable paginated thumbnail grid, selection actions, and click-to-enlarge.
It always identifies the target node. Advanced source fields remain serialized
under the existing names so saved workflows retain their input/output contract.

Switching sources clears conflicting fields and detaches the previous favorite.
Auto remains accepted for legacy workflows but is not a new UI choice. Absolute
image selections must work without validating an unrelated previous folder.
Preview requests discard stale responses, and large pools load in bounded pages.
Favorites retain their current package-local storage and prompt text; no image
or preset is migrated, uploaded, or deleted by this revision.

Implementation order: regression tests for pool resolution and frontend source
transitions; backend preview pagination; browser/compact-node UI; five source
nodes in workflow #54; focused tests and live installation checks. Update only
the authorized #54 workflow and generated companion API. Preserve the existing
generation settings and lazy optional reference branches. Verify with the
random-reference package tests, workflow #54 tests, JavaScript syntax checks,
and local preview requests using disposable synthetic images. Restart 8192 only
after checking its queue is idle. Browser visual checks depend on local-page
access being available to the browser tool.

**Verification:** Source-transition and dense/legacy widget persistence tests,
browser scrolling/selection/target-switch/stale-response tests, backend pool and
pagination checks pass. Live synthetic checks covered a 29-image folder in
24+5 pages, filename search, an enlarged preview, absolute selection with a
missing old folder, and a queued source-node execution. Existing favorite files
were hash-checked during deployment and left unchanged. Only #54's five source
nodes change its executable API; the remaining generation graph is identical.

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

## Usability review follow-up — 2026-09-29

Fixed destructive image-mode switching, favorite deletion clearing current sources, stale favorite names across target nodes, gallery resets on seed/prompt changes, stale searches across sources, and comma-containing selected filenames. Favorite prompt editor now reports disconnected output and explains Save/Update. Reopened seeded/sequential nodes enforce fixed/increment controls; owner explicitly rejected retaining broken historical behavior.

Frontend files are installed on port 8192. Backend files are copied but restart is deferred because the owner has running and queued generation jobs. Empty-folder validation and comma-containing favorite restoration need that restart. No workflow files or preset data were changed during this review. Focused combined suite passed 70 tests; the final backend comma fix then passed all 24 node tests, including its new regression. JavaScript syntax and scoped whitespace checks pass. No visual UI verification was performed.

## Prompt panel goal — 2026-09-29 (complete)

Owner approved the dedicated panel and all identified QoL fixes. Keep favorites, image gallery, and prompt editing together in a responsive three-column browser. Larger reference-text editor updates the node on input, with explicit saved/modified state; Save changes updates only its identified favorite, Save as new requires a unique name, Revert restores saved text. Separate raw image paths from prompt authoring. Preserve per-node/per-source text and proposed names when switching targets/sources and reopening the panel; store drafts in node properties so workflow saves retain them. Never overwrite a draft on unrelated refresh. Save failures leave drafts intact.

Live preview resolves the actual executable prompt graph locally, lists enabled/disabled lane contributions, and combines the exact text before generation. Display unsupported/disconnected paths honestly rather than guessing. Refresh while typing and when switches or the base instruction change. No images or text leave this machine. Do not change owner favorites during verification.

Sequence: implement draft lifecycle and save contracts; build editor/status/actions panel; implement graph-based combined preview; test source/target switching, reload, naming, failures, revert, enabled lanes and preview equivalence; install frontend files and verify served assets. No saved workflow edits are required for this frontend feature. Focused tests plus local API/CLI checks; no mandatory full suite. Preserve active generation jobs. Owner / maintainer: local ComfyUI install. Goal completed after installation and verification.


Prompt panel closeout: implemented the responsive editor, explicit save actions, stable proposed names, saved/modified/draft status, Revert, workflow-persisted per-source drafts, and live graph-based combined preview with enabled/empty/off lane indicators. Source selection and saves use sequencing guards so late responses cannot erase newer edits or choices. Re-selecting a favorite and deleting it preserve current draft text. Duplicate names and empty source saves fail without modifying presets.

Verification: 90 focused package/workflow tests passed; all three JS modules parse; scoped diff whitespace checks pass. Tests cover UI input/save/revert behavior, panel close and target changes, workflow draft round trips, failed and delayed saves, preset collisions, missing sources, and preview equivalence with the Python composer using #54's real API graph. A separate review found six draft/race/validation issues, all fixed with regression tests. Runtime frontend files match served assets byte-for-byte. Server restarted only after idle queue check; live save-validation smoke returned the expected error and owner preset bytes were unchanged. Existing workflows and images were not modified during the panel build. Browser visual appearance was not verified; DOM interaction and CSS contracts were checked programmatically. Ctrl+F5 is required for an already-open browser tab.
