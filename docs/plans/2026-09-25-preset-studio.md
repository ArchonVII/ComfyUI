# Standalone Preset Studio

Status: first version implemented; local user review pending. Owner: Codex. User authorized implementation on 2026-09-25. Draft fork PR: https://github.com/ArchonVII/ComfyUI/pull/22. No merge authorized.

## Scope and decisions

Build a local browser workspace outside the ComfyUI UI, served by a small standalone Python service in `tools/preset_studio`. ComfyUI remains the HTTP execution backend. Use standard-library Python and browser modules: no cloud, external assets, build chain, or dependency installation. Code belongs to this fork; private state belongs to ignored `user/preset_studio` in the live runtime. The feature worktree may run against that runtime without changing its saved workflows.

Characters and concepts carry positive/negative text, local references, and ordered LoRA settings. Composition follows explicit selection order. A workflow adapter binds prompt fields, reference slots, seed fields, and an optional MODEL/CLIP insertion point. Imported API graphs are copied into private app state. Every run snapshots its composition and compiled graph; errors remain visible and uncertain submissions are never automatically retried.

Variation controls support seed sweeps with fixed references, or one run per selected character image with the seed and all other inputs fixed. A character image group occupies one workflow slot. Users can change any selected preset and submit another batch, or restore a previous combination. Images and video outputs appear in the local run history. No automatic GPU generation during implementation validation.

## Steps

1. Test composition, graph copying, field binding, LoRA chaining, missing-reference and conflict errors.
2. Implement atomic local persistence, preset/workflow CRUD, reference uploads, runtime-library discovery, ComfyUI validation/submission and history retrieval.
3. Build the responsive browser workspace: preset cards/editor, composition preview, workflow mapping, run controls and output comparison.
4. Verify focused unit/integration tests, browser-module syntax, and live read-only HTTP connectivity. Start a retained local app and give the owner a clickable entrypoint.

## Delivery

Issue-less lane: fork has issues disabled. Branch `agent/codex/no-issue-preset-studio`, isolated worktree. Target is fork/master only. The sole PR template is for upstream API nodes and does not apply. No changelog or teardown command is declared. Plan plus focused tests form the first draft checkpoint. Merge requires owner authorization. Preserve all pre-existing live-checkout changes.

## Acceptance

Select character plus concept, add custom text, inspect prompt/references/LoRAs, map an API workflow, preview patched graph, and explicitly queue reproducible seed variations. Persistence survives restart. Reject nonlocal backend URLs and cross-origin writes. Never rewrite existing workflow files or send images off machine.

## Verification and handoff

- All four implementation steps are complete. Focused suite: 23 passing Python tests plus four browser-selection module tests, including a real loopback HTTP pipeline against a test ComfyUI backend. Browser JavaScript syntax and HTML asset/element references checked.
- Owner refinements: flattened compact workspace; per-character exact-image selection or one-run-each groups, with fixed environment/seed, explicit queue count, input-image attribution and single-result restore.
- Local app runs independently at http://127.0.0.1:8791, with a clickable share-folder entrypoint at http://127.0.0.1:8790/preset-studio.html. Windows launcher was exercised, including restart with persisted data.
- Connected to the existing ComfyUI process on 8192. Read-only validation confirms the saved Klein 9B subject/environment graph matches its 987-node catalog. A private, independently mapped workflow copy and the existing empty subject collection were imported into Studio.
- The existing Flux 4B and GGUF Wan examples do not match this server's installed models/nodes. They remain untouched; the app reports such mismatches before queue submission.
- No GPU generation or browser click-through was performed. Optional WebMCP staging is feature-detected; no supported WebMCP validation context was available. Remaining work is owner review of the first interface and a chosen real generation, then any requested refinements and separately authorized landing.
