# I2I Consistency Suite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add reliable local Klein 9B masked editing, Klein 9B PuLID identity conditioning, Qwen-Image-Edit-2511 Q4_K_M precision editing, and an isolated Musubi character-LoRA training lane for the RTX 5070 Ti 16 GB workstation.

**Architecture:** Generate three deterministic editor-format ComfyUI workflows without modifying existing graphs. Install runtime-only PuLID and Qwen assets into the main ComfyUI base, keep Musubi in a separate pinned virtual environment, and provide tested dataset/config helpers that emit ComfyUI-compatible character LoRAs without contaminating ComfyUI's Python environment.

**Tech Stack:** ComfyUI editor JSON, Python workflow builders and contract tests, ComfyUI-GGUF, ComfyUI-PuLID-Flux2, InsightFace, Qwen-Image-Edit-2511 GGUF, Musubi Tuner, PowerShell launch wrappers, pytest.

**Plan Status:** Active until implementation closeout; update the Plan Closeout section before PR ready/merge.

---

## Understanding Summary

- The work targets literal image-to-image editing and character consistency on one local Windows workstation.
- Klein 9B remains the fast daily editor; masked compositing must preserve original pixels outside the edit region.
- PuLID is an experimental face-identity conditioner for FLUX.2 Klein, not a promise of full-body or mature edit-mode consistency.
- Qwen-Image-Edit-2511 Q4_K_M supplies the precision/multi-reference path using the encoder, VAE, and edit LoRAs already installed in the runtime.
- Character LoRA training must run beside ComfyUI in an isolated environment and keep datasets local.
- The 16 GB GPU can run the generation paths with offloading; 31 GB system RAM makes Klein 9B and Qwen Edit training experimental and potentially swap-heavy.
- Existing numbered workflows and dirty runtime-checkout changes must remain untouched.

## Non-Functional Requirements

- **Performance:** default to 1024-class I2I generation, reduced-resolution smoke tests, batch-one training, cached embeddings/latents, FP8, gradient checkpointing, and block swapping.
- **Scale:** one local user, one character dataset per directory, approximately 10-30 curated images per initial training run.
- **Privacy:** no dataset uploads, cloud inference, or remote training APIs.
- **Reliability:** resumable/size-checked downloads, pinned trainer revision, deterministic workflow generation, output non-overwrite, disk guards, and explicit low-memory warnings.
- **Maintenance:** runtime extensions and the trainer remain separately updateable; tracked docs record exact source revisions, paths, assets, and verification commands.

## Decision Log

1. Create three focused workflows rather than one oversized switchboard.
2. Use masked generation plus final compositing for pixel-exact preservation outside the edit mask.
3. Measure PuLID face retention with the existing local OpenCV identity scorer and label the graph experimental.
4. Use Qwen-Image-Edit-2511 Q4_K_M for inference; never present GGUF or distilled inference weights as trainable base checkpoints.
5. Use Musubi Tuner because it directly supports Qwen Edit 2511 and FLUX.2/Klein, works on Windows, and exposes the necessary low-memory controls.
6. Install trainer code under `C:\tools\image\trainers\musubi-tuner`, datasets/runs under `C:\tools\image\training\characters`, and copy only approved LoRAs to `models\loras\trained\characters`.
7. Install generation assets now, but defer large train-only BF16/base checkpoints until a real dataset exists.
8. Use focused local checks and runtime smokes; required GitHub CI remains the sole required full-suite run for the final PR head.

## Delivery Contract

- **Issue:** not available; issues are disabled on `ArchonVII/ComfyUI`, so this uses the established `no-issue` convention.
- **Branch:** `agent/codex/no-issue-i2i-consistency-suite`.
- **Worktree:** `C:\tools\image\ComfyUI-worktrees\no-issue-i2i-consistency-suite`.
- **PR template:** none applicable; the only committed template is API-node-specific.
- **Changelog:** not required; this fork does not define a changelog lane.
- **Companion docs:** this plan plus `docs/i2i-consistency-suite.md`.
- **Required local gates:** focused pytest contracts, deterministic regeneration, Python compilation, live node-schema validation, runtime smokes, and trainer environment/config validation.
- **Required remote gates:** GitHub-required checks on the final PR head.

### Task 1: Workflow Contract Tests

**Files:**
- Create: `tests/workflows/test_i2i_consistency_workflows.py`

**Step 1: Write failing workflow contracts**

Assert three new workflow filenames, exact model defaults, stable placeholder images, deterministic metadata, and valid link topology.

**Step 2: Specify masked Klein behavior**

Assert mask growth/feather controls, an edit-only generation branch, exact original-image compositing outside the mask, optional consistency LoRA, and identity scoring.

**Step 3: Specify PuLID behavior**

Assert separate scene and face references, FLUX.2 PuLID loader/apply nodes, adjustable identity strength, a clear experimental note, and reference-versus-output identity scoring.

**Step 4: Specify Qwen behavior**

Assert `Qwen-Image-Edit-2511-Q4_K_M.gguf`, the installed Qwen 2.5-VL encoder and VAE, one required plus two optional references, an optional Lightning path, and accuracy-oriented sampling defaults.

**Step 5: Verify RED**

Run:

`C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest tests\workflows\test_i2i_consistency_workflows.py -q`

Expected: failures because the three workflows and builder do not exist.

### Task 2: Deterministic I2I Workflow Builder

**Files:**
- Create: `scripts/build_i2i_consistency_workflows.py`
- Create: `user/default/workflows/agent/35 - Klein 9B Masked Precision I2I.json`
- Create: `user/default/workflows/agent/36 - Klein 9B PuLID Identity Lab.json`
- Create: `user/default/workflows/agent/37 - Qwen 2511 Q4KM Precision MultiRef.json`

**Step 1: Build reusable graph helpers**

Clone only committed/live node exemplars, allocate deterministic IDs, rebuild links, and emit stable workflow metadata.

**Step 2: Generate masked Klein**

Wire source image, source mask, mask refinement, Klein edit conditioning, sampling, decode, final pixel-preserving composite, optional consistency LoRA, previews, save output, and identity score.

**Step 3: Generate PuLID identity lab**

Wire Klein 9B, a separate clean face reference, PuLID loaders/apply node, conservative/strong documented strengths, sampling, output, and identity score.

**Step 4: Generate Qwen precision edit**

Wire GGUF diffusion model, Qwen text encoder/VAE, primary and optional reference inputs, Lightning bypass branch, sampling, decode, preview, and save output.

**Step 5: Verify GREEN**

Run the focused workflow contracts and deterministic regeneration twice; require byte-identical output.

### Task 3: Character Dataset and Training Helpers

**Files:**
- Create: `tests/tools/test_character_lora_training.py`
- Create: `tools/lora_training/character_dataset.py`
- Create: `tools/lora_training/render_musubi_config.py`
- Create: `tools/lora_training/install-musubi.ps1`
- Create: `tools/lora_training/start-character-training.ps1`
- Create: `tools/lora_training/templates/character-flux2-klein9b.toml`
- Create: `tools/lora_training/templates/character-qwen-edit-2511.toml`

**Step 1: Write failing dataset/config tests**

Cover missing captions, unsupported files, duplicate stems, image-count warnings, trigger-token validation, non-overwrite behavior, disk thresholds, model-specific memory warnings, and deterministic config rendering.

**Step 2: Verify RED**

Run:

`C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest tests\tools\test_character_lora_training.py -q`

Expected: import failures because the helpers do not exist.

**Step 3: Implement the dataset validator**

Return actionable errors/warnings without reading private image contents beyond dimensions and hashes required for validation.

**Step 4: Implement config rendering**

Render model-specific Musubi TOML from validated paths and character settings, keep batch one, enable caching/FP8/checkpointing/block swap, and refuse to overwrite completed run configs.

**Step 5: Implement PowerShell wrappers**

Install/update only the pinned trainer in its own venv, create conventional local directories, validate free disk, and launch cache/train phases without importing ComfyUI's environment.

**Step 6: Verify GREEN**

Run focused tests, PowerShell parser checks, config rendering against a temporary valid dataset, and dry-run command validation.

### Task 4: Runtime Assets and Dependencies

**Runtime-only targets:**
- `C:\tools\image\ComfyUI\custom_nodes\ComfyUI-PuLID-Flux2`
- `C:\tools\image\ComfyUI\models\pulid`
- `C:\tools\image\ComfyUI\models\insightface\models\antelopev2`
- `C:\tools\image\ComfyUI\models\diffusion_models\Qwen\Qwen-Image-Edit-2511-Q4_K_M.gguf`
- `C:\tools\image\trainers\musubi-tuner`
- `C:\tools\image\training\characters`

**Step 1: Record authoritative revisions and asset manifests**

Resolve the latest stable PuLID and Musubi revisions, enumerate required files/sizes, and check available disk before downloading.

**Step 2: Install PuLID selectively**

Clone the pinned node, install only missing packages into ComfyUI's venv, download native FLUX.2 weights and AntelopeV2, and preflight imports.

**Step 3: Download Qwen Q4_K_M**

Use a resumable transfer, verify the Hugging Face-reported size and repository metadata, and keep the model in the loader-visible Qwen directory.

**Step 4: Install Musubi**

Run the isolated installer, verify CUDA visibility and imports, create dataset/output directories, and record the pinned revision.

### Task 5: Live Validation and Documentation

**Files:**
- Create: `docs/i2i-consistency-suite.md`
- Modify: `docs/plans/2026-07-24-i2i-consistency-suite.md`

**Step 1: Start an isolated validation server**

Launch the worktree code with `C:\tools\image\ComfyUI` as its base directory on a free port, hidden and with a captured log.

**Step 2: Validate live schemas**

Compare every executable workflow node and input name with `/object_info`; fail on missing nodes or unknown inputs.

**Step 3: Run reduced Klein masked smoke**

Verify completion, saved output, and pixel equality outside the final composite mask.

**Step 4: Run reduced PuLID smoke**

Verify completion, face detection, and a recorded identity score; report the measured value without inventing an acceptance threshold.

**Step 5: Run reduced Qwen smoke**

Verify a single-reference edit completes with the Q4_K_M model and record elapsed time and peak-memory observations available from logs.

**Step 6: Document operation and limitations**

Record workflow purpose, model locations, direct authoritative links, installed revisions, trainer commands, dataset layout, expected memory behavior, licenses, recovery steps, and measured smoke evidence.

### Task 6: Delivery and Merge

**Files:**
- Modify: `docs/plans/2026-07-24-i2i-consistency-suite.md`

**Step 1: Close the plan**

Mark every completed item and explicitly document any external limitation or deferred train-only checkpoint.

**Step 2: Run final focused verification**

Run focused tests, deterministic regeneration, compile/parser checks, live schema validation, runtime smokes, and trainer dry-run from the final diff.

**Step 3: Commit and update the PR**

Stage only scoped files, record exact evidence in the PR body, push, and mark the draft ready.

**Step 4: Wait for GitHub gates and reviews**

Require mergeability, successful required checks, no change requests, no unresolved review threads, and no pending configured review agent.

**Step 5: Merge and activate**

Merge through GitHub without bypass, preserve the dirty runtime checkout, fast-forward or selectively activate the merged workflow/docs/scripts without overwriting user edits, run post-merge smoke, and clean the retired worktree/branch.

## Plan Closeout

- Status: Active.
- Final verification: pending.
- Runtime assets: pending.
- PR and merge: pending.
