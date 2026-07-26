# Flux Identity Experiment Lab Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Build and deliver a local, resumable ComfyUI experiment harness for Flux/Klein 9B face-swap and identity-i2i parameter searches.

**Architecture:** Extend `comfyui_identity_score` with a dual-score output node, deterministic staged planner, SQLite store, local HTTP routes, and a ComfyUI experiment/gallery panel. Generate two stable editor-format Flux workflow templates that expose a validated patch contract and feed their final image into the scorer.

**Tech Stack:** Python 3.12, pytest, SQLite, OpenCV YuNet/SFace, Pillow, aiohttp/ComfyUI routes, vanilla JavaScript, Node test harness, ComfyUI editor-format JSON.

**Plan Status:** Active until implementation closeout; update the Plan Closeout section before PR ready/merge.

---

### Task 1: Dual identity scoring core and visible node

**Files:**
- Modify: `custom_nodes/comfyui_identity_score/identity_core.py`
- Modify: `custom_nodes/comfyui_identity_score/nodes.py`
- Modify: `custom_nodes/comfyui_identity_score/__init__.py`
- Test: `custom_nodes/comfyui_identity_score/tests/test_identity_core.py`
- Test: `custom_nodes/comfyui_identity_score/tests/test_nodes.py`

**Step 1: Write failing core tests**

Add tests for one generated-face detection feeding both comparisons, `face_swap` and `identity_i2i` active-score selection, and explicit non-rankable missing-face results.

**Step 2: Verify RED**

Run:

```powershell
C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest custom_nodes\comfyui_identity_score\tests\test_identity_core.py -q
```

Expected: new tests fail because the dual-report API is absent.

**Step 3: Implement the minimal dual-report API**

Add a small result structure and a function that detects each input once, computes both comparisons, selects the active score by mode, and returns detection/rankability status without changing the legacy report API.

**Step 4: Write and verify failing node-contract tests**

Assert `DualIdentityScore` inputs, returned values, `OUTPUT_NODE`, display name/category, and ComfyUI `ui` payload fields.

**Step 5: Implement the node**

Add `DualIdentityScore` while retaining `OpenCVIdentityScore` compatibility. Return both raw scores/booleans, active score, rankable flag, report JSON, metadata, and visible UI text.

**Step 6: Verify GREEN**

Run:

```powershell
C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest custom_nodes\comfyui_identity_score\tests -q
```

Expected: all identity-score tests pass.

**Step 7: Commit**

```powershell
git add custom_nodes/comfyui_identity_score
git commit -m "feat(identity-lab): add visible dual identity scoring"
```

### Task 2: Deterministic planner and SQLite experiment store

**Files:**
- Create: `custom_nodes/comfyui_identity_score/experiment_planner.py`
- Create: `custom_nodes/comfyui_identity_score/experiment_store.py`
- Create: `custom_nodes/comfyui_identity_score/tests/test_experiment_planner.py`
- Create: `custom_nodes/comfyui_identity_score/tests/test_experiment_store.py`

**Step 1: Write planner RED tests**

Specify canonical combination hashes, aligned checkpoint/seed expansion, single/pair/optional-triple LoRA stages, focused refine settings, deterministic ordering, duplicate removal, and the 100-run limit.

**Step 2: Verify planner RED**

Run the new planner test file and confirm imports or assertions fail for the missing implementation.

**Step 3: Implement the planner**

Use immutable normalized records and stable JSON hashing. Reject invalid strengths, empty seeds, more than three active LoRAs, unsupported modes/stages, and plans above 100 runs.

**Step 4: Write store RED tests**

Use a temporary SQLite database to specify schema initialization, experiment creation, unique run insertion, valid state transitions, stale-run resume, immutable completion data, ratings/favorites/notes, archive, and relative output paths.

**Step 5: Verify store RED**

Run the new store test file and confirm failure because the store is absent.

**Step 6: Implement the store**

Use transactions, foreign keys, WAL mode, row dictionaries, UTC timestamps, and narrow repository methods. Do not store face embeddings or image bytes.

**Step 7: Verify GREEN**

Run:

```powershell
C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest custom_nodes\comfyui_identity_score\tests\test_experiment_planner.py custom_nodes\comfyui_identity_score\tests\test_experiment_store.py -q
```

Expected: planner and store tests pass.

**Step 8: Commit**

```powershell
git add custom_nodes/comfyui_identity_score
git commit -m "feat(identity-lab): persist staged experiments"
```

### Task 3: Local routes, catalogs, estimates, and score recording

**Files:**
- Create: `custom_nodes/comfyui_identity_score/experiment_service.py`
- Create: `custom_nodes/comfyui_identity_score/routes.py`
- Modify: `custom_nodes/comfyui_identity_score/nodes.py`
- Modify: `custom_nodes/comfyui_identity_score/__init__.py`
- Create: `custom_nodes/comfyui_identity_score/tests/test_experiment_service.py`
- Create: `custom_nodes/comfyui_identity_score/tests/test_routes.py`
- Modify: `custom_nodes/comfyui_identity_score/tests/test_nodes.py`

**Step 1: Write service and route RED tests**

Specify local Flux 9B model/LoRA catalogs, template-role validation, run/disk/time estimates, experiment CRUD payloads, stage planning/promotion, result listing, rating updates, resume, archive, and safe output-file serving.

**Step 2: Verify RED**

Run the new test files and confirm the missing service/routes are the failure cause.

**Step 3: Implement service and routes**

Resolve database/output paths through `folder_paths`, validate all filenames against live local catalogs, reject traversal, and keep route registration safe when imported outside ComfyUI tests.

**Step 4: Write node-recording RED tests**

Specify that a node call with experiment/run IDs saves the result image, completes the exact run, records both scores and runtime metadata, and reports a non-rankable no-face result without failing the queue.

**Step 5: Implement recording**

Delegate persistence and image saving to the service. Keep manual node execution independent of the experiment database when IDs are blank.

**Step 6: Verify GREEN**

Run all custom-node tests and confirm they pass.

**Step 7: Commit**

```powershell
git add custom_nodes/comfyui_identity_score
git commit -m "feat(identity-lab): expose local experiment service"
```

### Task 4: ComfyUI experiment panel and ranked gallery

**Files:**
- Create: `custom_nodes/comfyui_identity_score/web/identity_lab.js`
- Create: `custom_nodes/comfyui_identity_score/web/identity_lab.css`
- Modify: `custom_nodes/comfyui_identity_score/__init__.py`
- Create: `custom_nodes/comfyui_identity_score/tests/test_web_panel.py`

**Step 1: Write browser-panel RED tests**

Create a Node-based minimal DOM/API harness specifying extension registration, setup fields, count/estimate rendering, current-workflow capture, serial prompt submission, pause-after-current, resume, score sorting, filters, rating/favorite updates, explicit promotion, and archive/delete confirmation behavior.

**Step 2: Verify RED**

Run:

```powershell
C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest custom_nodes\comfyui_identity_score\tests\test_web_panel.py -q
```

Expected: failure because the web extension does not exist.

**Step 3: Implement the panel**

Use existing local `app.registerExtension`, `api.fetchApi`, and `/prompt` conventions. Keep data rendering escaped, queue runs serially, poll bounded result endpoints, and display actionable failures.

**Step 4: Verify GREEN**

Run the web-panel test and all custom-node tests.

**Step 5: Commit**

```powershell
git add custom_nodes/comfyui_identity_score
git commit -m "feat(identity-lab): add experiment review panel"
```

### Task 5: Flux face-swap and identity-i2i workflow templates

**Files:**
- Create: `scripts/build_flux_identity_lab_workflows.py`
- Create: `tests/workflows/test_flux_identity_lab_workflows.py`
- Create: `user/default/workflows/agent/39 - Flux 9B Identity Lab - Face Swap.json`
- Create: `user/default/workflows/agent/40 - Flux 9B Identity Lab - Identity I2I.json`

**Step 1: Write workflow-contract RED tests**

Require two parseable editor graphs, unique node/link IDs, live node-type roles, `input/example.png` defaults, stable patch-role titles for model/LoRA/sampler inputs, separate mode semantics, and final outputs wired to `DualIdentityScore`.

**Step 2: Verify RED**

Run:

```powershell
C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest tests\workflows\test_flux_identity_lab_workflows.py -q
```

Expected: failures because the builder/templates are absent.

**Step 3: Implement the deterministic builder**

Build the face-swap graph from the proven face detection/SAM/crop/reference-latent/uncrop chain and the i2i graph from the installed PuLID chain. Expose no more than three LoRA slots and the focused settings. Add clear notes and stable role titles.

**Step 4: Generate and force-add templates**

Run the builder, then add the otherwise ignored workflow files explicitly.

**Step 5: Verify GREEN**

Run the workflow-contract tests with `COMFY_RUNTIME_BASE=C:\tools\image\ComfyUI`, then run all identity-lab focused tests.

**Step 6: Commit**

```powershell
git add scripts/build_flux_identity_lab_workflows.py tests/workflows/test_flux_identity_lab_workflows.py
git add -f "user/default/workflows/agent/39 - Flux 9B Identity Lab - Face Swap.json" "user/default/workflows/agent/40 - Flux 9B Identity Lab - Identity I2I.json"
git commit -m "feat(identity-lab): add Flux experiment templates"
```

### Task 6: Documentation, live smoke, and delivery closeout

**Files:**
- Modify: `custom_nodes/comfyui_identity_score/README.md`
- Modify: `docs/specs/2026-07-26-flux-identity-experiment-lab.md`
- Modify: `docs/plans/2026-07-26-flux-identity-experiment-lab.md`

**Step 1: Document usage and safety**

Explain server restart, opening the panel, loading the correct template, creating/staging/resuming an experiment, reading both scores, manual ratings, data/output locations, archive/delete semantics, and local-only identity constraints.

**Step 2: Run focused verification**

Run:

```powershell
$env:COMFY_RUNTIME_BASE='C:\tools\image\ComfyUI'
C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest custom_nodes\comfyui_identity_score\tests tests\workflows\test_flux_identity_lab_workflows.py -q
```

Expected: all focused tests pass.

**Step 3: Run isolated live validation**

Start the worktree server with the main runtime base on a free port. Validate `/object_info`, both editor graphs, experiment routes, one deliberately low-cost Flux prompt, visible dual-score execution data, SQLite completion, saved output, and gallery retrieval. Stop the isolated server afterward.

**Step 4: Review the scoped diff**

Confirm no unrelated files are modified, no private source images or database files are tracked, and the implementation matches the approved design.

**Step 5: Close the plan**

Set `Plan Status` to complete, record focused and live evidence, note any explicitly deferred non-goals, and make the document historical rather than active guidance.

**Step 6: Commit**

```powershell
git add custom_nodes/comfyui_identity_score/README.md docs/specs/2026-07-26-flux-identity-experiment-lab.md docs/plans/2026-07-26-flux-identity-experiment-lab.md
git commit -m "docs(identity-lab): document local experiment workflow"
```

**Step 7: Update the draft PR and wait for required GitHub CI**

Push the final head, update the PR body with exact evidence, promote it when checks are green, verify merge readiness, and merge into `master` as authorized.

## Plan Closeout

- Status: Active.
- Completion evidence: Pending.
- Deferred scope: Qwen and Z-Image-family execution adapters, automatic aesthetic scoring, multi-user/multi-GPU scheduling, and exhaustive sweeps.
