# Standalone Preset Studio

Status: implementing. Owner: Codex. User authorized implementation on 2026-09-25.

## Scope and decisions

Build a local browser workspace outside the ComfyUI UI, served by a small standalone Python service in `tools/preset_studio`. ComfyUI remains the HTTP execution backend. Use standard-library Python and browser modules: no cloud, external assets, build chain, or dependency installation. Code belongs to this fork; private state belongs to ignored `user/preset_studio` in the live runtime. The feature worktree may run against that runtime without changing its saved workflows.

Characters and concepts carry positive/negative text, local references, and ordered LoRA settings. Composition follows explicit selection order. A workflow adapter binds prompt fields, reference slots, seed fields, and an optional MODEL/CLIP insertion point. Imported API graphs are copied into private app state. Every run snapshots its composition and compiled graph; errors remain visible and uncertain submissions are never automatically retried.

The initial variation control changes seeds while keeping the composition fixed. Users can change any selected preset and submit another batch, or restore a previous combination. Images and video outputs appear in the local run history. No automatic GPU generation during implementation validation.

## Steps

1. Test composition, graph copying, field binding, LoRA chaining, missing-reference and conflict errors.
2. Implement atomic local persistence, preset/workflow CRUD, reference uploads, runtime-library discovery, ComfyUI validation/submission and history retrieval.
3. Build the responsive browser workspace: preset cards/editor, composition preview, workflow mapping, run controls and output comparison.
4. Verify focused unit/integration tests, browser-module syntax, and live read-only HTTP connectivity. Start a retained local app and give the owner a clickable entrypoint.

## Delivery

Issue-less lane: fork has issues disabled. Branch `agent/codex/no-issue-preset-studio`, isolated worktree. Target is fork/master only. The sole PR template is for upstream API nodes and does not apply. No changelog or teardown command is declared. Plan plus focused tests form the first draft checkpoint. Merge requires owner authorization. Preserve all pre-existing live-checkout changes.

## Acceptance

Select character plus concept, add custom text, inspect prompt/references/LoRAs, map an API workflow, preview patched graph, and explicitly queue reproducible seed variations. Persistence survives restart. Reject nonlocal backend URLs and cross-origin writes. Never rewrite existing workflow files or send images off machine.
