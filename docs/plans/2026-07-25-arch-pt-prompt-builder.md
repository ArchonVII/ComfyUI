# Arch PT Prompt Builder Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add a new, self-contained `arch-pt-` prompt-building system with focused Identity, Pose, Clothing, Environment, Camera, and Lighting nodes; copied model-specific choices; protected built-ins; explicit user option management; structured combining; and future LoRA association metadata, without changing existing nodes or workflows.

**Architecture:** A new `comfyui_arch_prompt_tools` custom-node package owns versioned schemas, protected Flux/Qwen option catalogs, user-option persistence, deterministic prompt assembly, API routes, and a schema-driven frontend. Each focused node serializes complete copied state inside the workflow and emits both a normal prompt string and an `ARCH_PT_BUNDLE`; `arch-pt-Combine` merges bundles, metadata, and future LoRA requests.

**Tech Stack:** Python 3.10+, ComfyUI custom-node APIs, JSON catalogs, aiohttp routes, browser JavaScript/DOM widgets, pytest.

**Plan Status:** Active until implementation closeout; update the Plan Closeout section before PR ready/merge.

---

## Understanding Summary

- Add new focused nodes for Identity, Pose, Clothing, Environment, Camera, and Lighting; preserve every existing node and saved workflow unchanged.
- All fields start blank or disabled and emit nothing until the user deliberately selects or types something.
- Small mutually exclusive button groups serve bounded choices; compatible attribute groups remain additive; searchable choices serve field libraries of a few dozen entries.
- Selecting an option copies its Flux/Qwen phrase and optional LoRA association into workflow-owned editable state. Catalog changes and model-family changes never silently rewrite copied text.
- Every node owns its own `model_family` selector, defaulting to Flux; Flux and Qwen are the initial phrase profiles.
- Built-ins are protected. Users may duplicate built-ins or explicitly save, edit, and delete user-owned choices scoped by node, field, and model family.
- Focused nodes emit positive prompt text only. Existing prompt-library and LoRA-stack paths continue to own negative prompts.

## Non-Functional Requirements

- **Performance:** Cache validated schemas/catalogs by file fingerprint; keep field searches responsive for a few dozen options and avoid network calls.
- **Scale:** One local user, six focused nodes per workflow, dozens rather than thousands of options per field.
- **Privacy/security:** Store data locally, render user labels/text safely, accept no executable expressions, and handle no credentials.
- **Reliability:** Use validated, locked, atomic user-catalog writes; preserve invalid files for recovery; serialize complete copied fragments into workflows.
- **Maintenance:** Keep protected built-ins separate from user data, version schemas/state, retain stable IDs, and leave all legacy node mappings untouched.
- **Compatibility:** Python execution must work from serialized widget values without the frontend extension; ordinary STRING outputs remain usable by standard ComfyUI nodes.

## Approved Node Design

### `arch-pt-Identity`

Collapsible sections:

1. Core identity: subject, age group, exact-age specifics, general identity text.
2. Body structure: body type, height, weight/build, chest/breasts, hips/butt, waist, body snippets, custom specifics.
3. Appearance: skin, hair length/texture/color/style, eyes, facial features.
4. Expression: overall expression, mouth, gaze/eyes, custom expression.

Stable order: subject, age, proportions, skin, hair, eyes/face, expression, specifics.

### `arch-pt-Pose`

Collapsible sections:

1. Overall: standing, seated, kneeling, crouching, lying, on all fours, airborne, pose snippets, action text.
2. Frame orientation: eight image-relative body-axis arrows, separate subject-facing direction, separate depth orientation.
3. Head/torso: head, neck, shoulders, torso/spine, hips/pelvis.
4. Arms/hands: subject-anatomical left/right arm and hand fields sharing side-aware action catalogs.
5. Legs/feet: subject-anatomical left/right leg and foot fields plus balance/contact specifics.

No contradiction checking is performed.

### `arch-pt-Clothing`

Collapsible sections:

1. State/transfer: fully clothed, keep source clothing, use reference clothing, nude; independent topless, bottomless, partially undressed, underwear-visible, and open/unfastened modifiers.
2. Upper body: headwear, facewear, neckwear, bra, top, outerwear, sleeves, gloves.
3. Waist/lower body: waist, belt, underwear, bottom, hosiery, footwear.
4. Whole outfit: dress, suit, uniform, costume, swimwear, sleepwear, other outfit snippets.
5. Materials/details: colors, material, pattern, fit, condition, jewelry, bags, accessories, specifics.

State selections never silently clear detailed garment selections.

### `arch-pt-Environment`

Collapsible sections:

1. Scene type: indoor, outdoor, mixed, studio/set, abstract.
2. Location: type, named setting, architecture, terrain, natural features, specifics.
3. Contents: foreground, midground, background, furniture, props, plants, people/crowds, optional scene-density spectrum.
4. Time/conditions: time of day, season, weather, atmospheric and surface conditions.
5. Mood/character: mood, palette, condition/age, period, cultural/regional character, snippets, specifics.

Camera and lighting language is intentionally excluded.

### `arch-pt-Camera`

Collapsible sections:

1. Framing/distance: extreme close-up through extreme wide, plus subject framing.
2. Viewpoint/angle: eye/high/low/overhead/ground/Dutch/POV/over-shoulder and custom angle.
3. Lens/optics: 14/24/35/50/85/135/200mm, lens type, aperture character, distortion, compression.
4. Focus/depth: target and disabled-by-default semantic depth-of-field controls.
5. Composition/effects: compositional snippets, bokeh, lens flare, motion blur, aberration, vignette.

Still-image composition and optics only; no camera movement.

### `arch-pt-Lighting`

Collapsible sections:

1. Environment illumination: disabled-by-default semantic brightness, exposure, and contrast spectra.
2. Sources: count, primary, secondary/fill, practical/background, natural/artificial, specifics.
3. Primary direction: frame-relative direction plus optional elevation.
4. Color/temperature: primary/fill color and disabled-by-default semantic temperature.
5. Quality/shadows: hardness, shadow hardness/depth, falloff, contrast ratio.
6. Techniques/effects: rim, backlight, three-point, Rembrandt, chiaroscuro, volumetric, rays, caustics, bounce, gels, silhouette.

### `arch-pt-Combine`

Inputs:

- Optional `base_prompt` STRING.
- Optional Identity, Pose, Clothing, Environment, Camera, and Lighting `ARCH_PT_BUNDLE` inputs.
- Optional `extra_prompt` STRING.
- Separator and exact-fragment deduplication controls.

Outputs:

- `positive_prompt` STRING.
- `metadata_json`.
- `lora_requests_json`.

Stable order: base, identity, pose, clothing, environment, camera, lighting, extra.

## Interaction and State Contract

- Each field may render quick buttons, searchable choices, semantic sliders, copied-fragment chips, Additional Specifics text, and an assembled preview.
- A mutually exclusive selection replaces only the copied fragment from its own group. Additive selections append. Manual specifics remain untouched.
- Copied fragments may be edited or removed without affecting their source option.
- Model-family changes affect future selections only.
- Built-ins expose Duplicate as custom; user options expose explicit Edit/Delete.
- Semantic sliders are disabled by default, emit no raw numbers, and copy authored text for their selected range.
- Optional LoRA metadata is copied with the prompt phrase and has an independent enabled flag. This phase records requests but does not load LoRAs.

## Data Contract

Built-in files:

- `custom_nodes/comfyui_arch_prompt_tools/data/schemas.json`
- `custom_nodes/comfyui_arch_prompt_tools/data/builtin_options.json`

User file:

- `<ComfyUI user directory>/arch_prompt_tools/options.json`

Workflow state stores versioned field fragments. Each fragment includes stable instance ID, source option ID/label, node, field, group, copied phrase, copied model family, optional LoRA snapshot/enabled flag, and user edits. Workflows remain reproducible after source options change or disappear.

## Decision Log

1. Use six focused smart-form nodes, not one node per field and not one monolithic Prompt Studio.
2. Prefix every new display name/category with `arch-pt-`.
3. Preserve all legacy classes and workflows; add only new node types and a new example workflow.
4. Copy selections into workflow state; never use live catalog references for prompt output.
5. Permit additive compatible groups and one active value inside mutually exclusive groups.
6. Use collapsible sections for all focused nodes.
7. Keep model-family selection on every node, default Flux, with Flux/Qwen initial support.
8. Keep focused nodes positive-only.
9. Separate selected fragments from manual specifics so replacements cannot erase user text.
10. Use subject-anatomical left/right for limbs and explicit frame-relative language for image placement.
11. Keep body-axis, facing direction, and depth orientation separate.
12. Do not implement contradiction checks.
13. Protect built-ins and store user-owned duplicates separately.
14. Reserve explicit LoRA associations now; apply LoRAs later in one centralized node.
15. Emit normal prompt strings plus structured bundles for compatibility and future integration.

## Delivery Contract

- **Issue:** not created; this is a fork-local custom-node feature and the user authorized implementation, not external issue creation.
- **Branch:** `agent/codex/no-issue-arch-pt-prompt-builder`.
- **Worktree:** `C:\tools\image\ComfyUI-worktrees\no-issue-arch-pt-prompt-builder`.
- **Draft PR:** not created; pushing/opening external GitHub state was not authorized.
- **PR template:** the repository only contains an API-node-specific template, which does not apply.
- **Changelog:** not required; this fork defines no changelog lane.
- **Companion docs:** this plan and the package README.
- **Required local gates:** focused package pytest, Python compilation, frontend contract checks, deterministic example-workflow validation, and `git diff --check`.
- **Required remote gates:** GitHub-required checks if the user later authorizes a PR; per repository baseline, do not duplicate the full CI suite locally.

### Task 1: Catalog and User-Store Contracts

**Files:**

- Create: `custom_nodes/comfyui_arch_prompt_tools/tests/test_catalog.py`
- Create: `custom_nodes/comfyui_arch_prompt_tools/catalog.py`
- Create: `custom_nodes/comfyui_arch_prompt_tools/data/schemas.json`
- Create: `custom_nodes/comfyui_arch_prompt_tools/data/builtin_options.json`

**Step 1: Write failing catalog tests**

Specify versioned schema loading, stable unique option IDs, Flux/Qwen phrase validation, field/group validation, protected built-ins, current-family filtering, and semantic spectrum validation.

**Step 2: Verify RED**

Run:

`C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest custom_nodes/comfyui_arch_prompt_tools/tests/test_catalog.py -q`

Expected: import/collection failure because the package does not exist.

**Step 3: Implement minimal catalog loading and validation**

Create immutable record helpers that validate JSON without mutating source data, index options by node/field/family, and expose schemas plus option lists.

**Step 4: Add the approved initial schemas and representative options**

Provide enough protected Flux/Qwen records to exercise every control type and every approved section; the full hand-authored catalog is completed in Task 4.

**Step 5: Verify GREEN**

Run the focused catalog tests and require all passing.

### Task 2: Copied State and Prompt Assembly

**Files:**

- Create: `custom_nodes/comfyui_arch_prompt_tools/tests/test_engine.py`
- Create: `custom_nodes/comfyui_arch_prompt_tools/engine.py`

**Step 1: Write failing state/assembly tests**

Cover blank output, fixed section/field order, additive fragments, mutually exclusive replacement, preserved specifics, edited copies, model-family snapshot behavior, semantic-slider copies, exact dedupe, and future LoRA request collection.

**Step 2: Verify RED**

Run the focused engine test module and require expected missing-symbol failures.

**Step 3: Implement state normalization and assembly**

Validate versioned state, preserve complete copied records, assemble field and node prompts deterministically, and return prompt, metadata, and enabled LoRA requests without reading live catalog text.

**Step 4: Verify GREEN**

Run catalog plus engine tests and require all passing.

### Task 3: Focused Nodes and Structured Combiner

**Files:**

- Create: `custom_nodes/comfyui_arch_prompt_tools/tests/test_nodes.py`
- Create: `custom_nodes/comfyui_arch_prompt_tools/nodes.py`
- Create: `custom_nodes/comfyui_arch_prompt_tools/__init__.py`

**Step 1: Write failing node contracts**

Assert seven new class/display mappings, `arch-pt` categories, Flux default, hidden serialized state input, STRING plus `ARCH_PT_BUNDLE` focused outputs, combiner inputs/outputs, positive-only behavior, and no imports/modifications of legacy packages.

**Step 2: Verify RED**

Run the focused node tests and require expected missing-node failures.

**Step 3: Implement focused node classes**

Use one shared base with fixed schema keys and stable display mappings. Return ordinary prompt text and structured bundle dictionaries.

**Step 4: Implement `arch-pt-Combine`**

Merge optional base/extra strings and bundles in approved order, exact-dedupe fragments, preserve metadata, and collect enabled LoRA requests as JSON.

**Step 5: Verify GREEN**

Run catalog, engine, and node tests.

### Task 4: Full Flux/Qwen Built-In Catalog

**Files:**

- Modify: `custom_nodes/comfyui_arch_prompt_tools/data/schemas.json`
- Modify: `custom_nodes/comfyui_arch_prompt_tools/data/builtin_options.json`
- Modify: `custom_nodes/comfyui_arch_prompt_tools/tests/test_catalog.py`

**Step 1: Add failing coverage checks**

Require every approved field, 5–7 high-level options where suitable, both model families for model-specific records, all eight body-axis directions, anatomical side-aware pose actions, clothing transfer states, camera focal lengths, and every semantic-lighting spectrum.

**Step 2: Verify RED**

Run the catalog coverage tests and confirm they fail on missing records.

**Step 3: Hand-author the complete initial catalog**

Use concise natural-language labels and uncluttered model-family phrases. Keep visible choices understandable and leave uncommon specifics to user options/free text.

**Step 4: Verify GREEN**

Run catalog coverage and assembly tests.

### Task 5: User Option Persistence and HTTP Routes

**Files:**

- Create: `custom_nodes/comfyui_arch_prompt_tools/tests/test_store.py`
- Create: `custom_nodes/comfyui_arch_prompt_tools/tests/test_routes.py`
- Create: `custom_nodes/comfyui_arch_prompt_tools/store.py`
- Create: `custom_nodes/comfyui_arch_prompt_tools/routes.py`
- Modify: `custom_nodes/comfyui_arch_prompt_tools/__init__.py`

**Step 1: Write failing store/route tests**

Cover default user path, empty store, explicit create/update/delete, protected built-in rejection, node/field/family scoping, duplicate labels with stable IDs, atomic replacement, invalid-file preservation, payload validation, and safe read-only schema/catalog payloads.

**Step 2: Verify RED**

Run store/route tests and require expected missing-symbol failures.

**Step 3: Implement the user store**

Use a process lock, validated reads, temporary-file replacement, and explicit mutations only.

**Step 4: Implement routes**

Provide read endpoints for schemas/options and explicit create/update/delete endpoints for user options. Keep route registration safe in isolated tests.

**Step 5: Verify GREEN**

Run all focused Python tests.

### Task 6: Schema-Driven Frontend

**Files:**

- Create: `custom_nodes/comfyui_arch_prompt_tools/tests/test_frontend_contract.py`
- Create: `custom_nodes/comfyui_arch_prompt_tools/web/arch_prompt_tools.js`
- Modify: `custom_nodes/comfyui_arch_prompt_tools/__init__.py`

**Step 1: Write failing frontend contract tests**

Require extension registration for all focused nodes, hidden raw-state widget, collapsible sections, quick buttons, searchable selection UI, semantic slider enable switches, copied-fragment edit/remove, Additional Specifics, built-in duplication, user save/edit/delete, model-family filtering, safe text rendering, state restoration, and LoRA enabled indicators.

**Step 2: Verify RED**

Run the frontend contract test and confirm the missing frontend fails.

**Step 3: Implement shared DOM rendering**

Fetch schemas/options, render every node from the schema, synchronize complete state JSON on every explicit edit, preserve serialized widget ordering, and rerender after workflow configuration.

**Step 4: Implement explicit option actions**

Wire duplicate/save/edit/delete to the routes, refresh affected field choices, and never mutate a saved option merely because copied text changes.

**Step 5: Verify GREEN**

Run frontend contracts and all focused package tests.

### Task 7: Documentation and Example Workflow

**Files:**

- Create: `custom_nodes/comfyui_arch_prompt_tools/README.md`
- Create: `custom_nodes/comfyui_arch_prompt_tools/tests/test_example_workflow.py`
- Create: `user/default/workflows/agent/38 - Arch PT Prompt Builder.json`
- Modify: `docs/plans/2026-07-25-arch-pt-prompt-builder.md`

**Step 1: Write a failing workflow contract**

Require one new editor-format example containing all six focused nodes, `arch-pt-Combine`, visible explanatory notes, valid link topology, blank defaults, and no references to existing workflow files.

**Step 2: Verify RED**

Run the example-workflow test and confirm the missing file fails.

**Step 3: Create the example workflow**

Build a prompt-only graph that demonstrates base prompt, six bundles, combined prompt preview, metadata preview, and LoRA request preview without requiring model files.

**Step 4: Document operation**

Explain blank defaults, copied selections, model-family behavior, user option ownership, data locations, future LoRA metadata, wiring, backup/recovery, and legacy-node coexistence.

**Step 5: Verify GREEN**

Run the workflow contract and all focused tests.

### Task 8: Focused Verification and Plan Closeout

**Files:**

- Modify: `docs/plans/2026-07-25-arch-pt-prompt-builder.md`

**Step 1: Review requirements line by line**

Map every approved requirement and decision to implementation evidence; record any deliberately deferred behavior.

**Step 2: Run fresh focused verification**

Run:

- `C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest custom_nodes/comfyui_arch_prompt_tools/tests -q`
- `C:\tools\image\ComfyUI\venv\Scripts\python.exe -m compileall -q custom_nodes/comfyui_arch_prompt_tools`
- `git diff --check`

Do not run the repository full suite locally; required GitHub CI is the authoritative full-suite run if a PR is later authorized.

**Step 3: Inspect scoped diff and legacy preservation**

Confirm no pre-existing custom-node package or workflow file changed and the worktree contains only this plan, the new package, and the new example workflow.

**Step 4: Close the plan**

Replace Active status with exact completion/deferred evidence and leave no stale unchecked execution guidance.

## Plan Closeout

- Status: active implementation.
- Evidence: pending.
- Deferred by design: actual LoRA loading/application; only explicit association metadata and enabled requests are implemented in this phase.
