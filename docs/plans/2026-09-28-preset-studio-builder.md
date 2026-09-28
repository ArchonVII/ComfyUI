# Preset Studio Builder — Design and Implementation Plan

Status: implemented and focused checks passing
Owner: Codex
Source: owner-approved design discussion, 2026-09-28

## Goal and scope

Add a local-first Builder destination that makes prompt composition and ComfyUI
workflow construction substantially faster than editing raw graphs. It must
support new custom workflows and imported workflows, while preserving uncommon
nodes and never modifying existing saved workflow files. Editing never queues a
generation; Generate is always explicit.

The builder combines four versioned documents: a `PromptBoard` of ordered
positive/negative blocks; a typed `WorkflowGraph` of curated blocks plus
preserved advanced nodes; an `Experiment` containing named option branches; and
immutable `OptionRevision` snapshots tied to generated outputs. Wildcard files
remain linked and refreshable. All state and images remain local.

## Decisions and invariants

- Use a layered builder, not a clone of the full ComfyUI editor and not a
  template-only wizard.
- Curated blocks cover common prompt, model, LoRA, reference, conditioning,
  sampler, image/video, upscale, and output patterns. Unknown imported nodes
  remain connected as collapsible advanced blocks with generic input editing.
- Compile the builder document into an independent API graph; source workflows
  are read-only.
- Provide instant local composition and graph validation, but require explicit
  Generate or its keyboard shortcut for queue submission.
- Branching creates named options; generation creates immutable revisions.
  Outputs retain the exact option revision, graph, prompts, resources, and
  settings that produced them.
- Keep the UI MVVM, compact, multi-column, keyboard accessible, and accent-coded.
- Optimize for thousands of prompt items, hundreds of experiments/workflows,
  and imported graphs containing hundreds of nodes.

## Implementation stages

1. **Builder document core.** Add pure Python normalization, validation,
   prompt rendering, immutable revision creation, and atomic experiment storage
   under `tools/preset_studio/builder.py`. Cover migrations and malformed input.
2. **Prompt catalog and board.** Index built-in prompt options, preset text,
   linked wildcard files, and user favorites. Add ordered positive/negative
   blocks, weights, enabled state, groups, duplication, and reusable bundles.
3. **Builder MVVM shell.** Add a full Builder destination with catalog rail,
   central prompt/graph canvas, properties/validation rail, and option
   filmstrip. Drag/drop and keyboard actions update only the active draft.
4. **Curated graph and import.** Define the block registry, import API graphs,
   recognize common node patterns, preserve unknown nodes, expose editable
   controls, and validate typed connections.
5. **Compiler and generation.** Compile prompt board and resource selections
   into the graph, reuse existing safe graph validation/submission, require an
   explicit action, and attach outputs to the submitted immutable revision.
6. **Experiments and comparison.** Branch, rename, duplicate, compare, promote,
   save as a workflow or variation set, and discard drafts without affecting
   saved revisions or source workflows.
7. **Pattern extraction.** Extract reusable curated patterns from installed
   workflows and allow locally maintained block adapters without expanding into
   universal node support.

## Verification

Use test-first development for each behavioral slice. Focused checks cover pure
builder documents, storage recovery, prompt rendering, import preservation,
compiler output, branching/revisions, and submission lineage. Browser-module
tests cover MVVM state transitions and drag/drop semantics. Existing character,
workflow, submission, and reference-batch tests must remain green. Before
completion run Python discovery for `tools/preset_studio/tests` and
`tools/character_catalog/tests`, Node module tests, JavaScript syntax checks,
Python compilation, and `git diff --check`. Required GitHub CI remains the only
required full repository suite.

## Current state

Stages 1–6 are implemented in the isolated worktree. The Builder has an atomic
local document store, linked prompt catalog, compact three-column UI, prompt
drag/drop, favorites and bundles, imported/basic workflow graphs, curated and
advanced node inspection, checkpoint/LoRA/reference controls, branching,
renaming, immutable generated revisions, output attachment, workflow promotion,
and safe option discard. Import recognition is also the initial stage-7 pattern
extraction path: common installed workflow nodes become curated blocks while
unrecognized nodes remain intact.

Focused verification on 2026-09-28: 24 character-catalog Python tests, 55
Preset Studio Python tests, and 11 browser-module tests pass. JavaScript syntax
and Python compilation checks pass. A local HTTP server smoke check succeeded;
visual browser automation was unavailable because this environment exposed no
controllable Chrome, Edge, or in-app browser surface. No commit, push, merge,
live-worktree change, or owner-image tracking was performed.
