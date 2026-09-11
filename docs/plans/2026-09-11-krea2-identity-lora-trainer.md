# Krea 2 Identity LoRA Trainer

**Status:** Tooling implemented and locally verified; proof run pending model assets
**Owner:** Codex  
**Source:** Owner request on 2026-09-11 for a local-only identity trainer

## Goal and scope

Add a launcher-based Krea 2 identity-LoRA lane to the existing isolated
`tools/lora_training` framework. Train ordinary text-to-image LoRAs on Krea 2
RAW, evaluate them on Krea 2 Turbo, and require explicit approval before a
staged LoRA is copied into ComfyUI. Personal source images, captions, manifests,
caches, checkpoints, and samples remain local and outside Git.

This lane targets one consenting adult identity per run. It does not add
in-process ComfyUI training controls, cloud services, multi-person training, or
Krea 2 Edit/control-image training.

## Decisions and invariants

1. Use the existing pinned Musubi revision, which already contains the dedicated
   Krea 2 cache, training, inference, and `networks.lora_krea2` modules.
2. Give Krea 2 a configurable dedicated runtime root, defaulting to
   `E:\image-training\krea2`; do not disrupt the established Klein/Qwen runtime.
3. Treat the source image directory as read-only. Dataset preparation copies an
   explicit curated selection into a local working dataset and never deletes or
   rewrites source images.
4. Keep captions local and associate a caller-provided trigger token with the
   subject while describing changeable scene attributes separately.
5. Provide separate immutable `proof` and `quality` run directories. Approval
   is a distinct operation and never overwrites an installed LoRA.
6. Default to batch one, BF16 mixed precision, scaled FP8 base weights,
   gradient checkpointing, resolution-aware Krea timestep sampling, and maximum
   practical block swap for the 16 GiB GPU. Training is explicitly experimental
   on this 31 GiB RAM host.

## Implementation

1. Extend `tests/tools/test_character_lora_training.py` with Krea-specific RED
   tests for the model profile, RAW/BF16 checkpoint validation, no-control
   dataset configuration, dedicated Musubi commands, immutable stage naming,
   configurable roots, and safe approval.
2. Add a Krea TOML template and extend
   `tools/lora_training/render_musubi_config.py` with the dedicated cache and
   training scripts, `networks.lora_krea2`, proof/quality profiles, and
   low-memory defaults.
3. Extend `tools/lora_training/start-character-training.ps1` and the installer
   so Krea can use its dedicated root without changing the existing model
   defaults. Validate all resolved paths and refuse quantized or Turbo weights
   as training bases.
4. Add a generic, local-only dataset-preparation helper that consumes an
   explicit selection manifest and caption mapping. It must copy without
   overwrite, record hashes without caption text, and reject paths outside the
   selected source and destination roots.
5. Update `docs/i2i-consistency-suite.md` with generic setup, dry-run, proof,
   quality, recovery, and approval instructions. Do not include personal data.

## Verification

- Focused RED/GREEN cycle:
  `venv\Scripts\python.exe -m pytest tests\tools\test_character_lora_training.py -q`
- PowerShell parser validation for changed launch/install scripts.
- Dry-run against the pinned installed Musubi checkout, confirming the exact
  Krea scripts and arguments without downloading weights or starting GPU work.
- Inspect `git diff` and `git status` to prove no images or local run artifacts
  are tracked.
- After tooling delivery, prepare the private dataset and run a short proof.
  A quality run and ComfyUI approval remain manual post-review actions.

## Delivery contract

- Issue: unavailable; the ArchonVII fork has issues disabled.
- Branch: `agent/codex/no-issue-krea2-identity-trainer`
- Worktree: `C:\tools\image\ComfyUI-worktrees\no-issue-krea2-identity-trainer`
- PR target: `ArchonVII/ComfyUI:master`; never upstream.
- Changelog: not required by repository policy.
- Companion documentation: `docs/i2i-consistency-suite.md`.
- Teardown: no repository command is declared; use Git worktree removal only
  after the owner authorizes landing and the worktree is clean.
