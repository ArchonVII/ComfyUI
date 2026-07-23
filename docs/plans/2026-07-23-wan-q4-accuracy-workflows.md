# WAN Q4 Accuracy Workflows Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add a model-author-aligned WAN 2.2 Q4_K_M workflow set for fast iteration, prompt/camera adherence, measurable face-identity retention, and first/last-frame endpoint control on a 16 GB RTX 5070 Ti.

**Architecture:** Generate four deterministic editor-format workflows from the existing native WAN graph while removing incompatible Lightning LoRAs and irrelevant low-step patches. Use the installed native nodes and ComfyUI-GGUF, preserve input aspect ratio, and reserve the local OpenCV identity scorer for the identity-audit workflow.

**Tech Stack:** ComfyUI workflow JSON, Python deterministic builder, pytest contract tests, ComfyUI native WAN nodes, ComfyUI-GGUF.

**Plan Status:** Complete; the external checkpoint transfer state is documented below.

---

## Understanding Summary

- The current Q8 experts nearly fill the 16.3 GB GPU individually and are a poor default for interactive iteration.
- The selected FAST MOVE V2 checkpoints already contain Lightning acceleration.
- The publisher recommends Euler/simple, CFG 1, shift 5, and a 2+2 or 2+3 expert schedule.
- Additional Lightning LoRAs must not be applied to these merged checkpoints.
- Fast previews must reduce frames and pixels, not merely rename a full 81-frame render.
- Existing numbered workflows and user edits remain untouched.
- Generation and identity scoring remain local.

## Decision Log

1. Use the publisher's Q4_K_M high/low pair because it is the practical quantization for 16 GB VRAM.
2. Create four distinct workflows: 17-frame preview, 49-frame timeline prompt, 81-frame identity audit, and 81-frame first/last-frame control.
3. Use 2+2 steps for preview and 2+3 steps for all accuracy workflows.
4. Emit 16 fps video, matching the native 81-frame, approximately five-second Wan cadence.
5. Omit external Lightning LoRAs, EasyCache, Enhance-A-Video, RIFLEx, NAG, and SageAttention from the baseline graphs.
6. Score middle and final decoded frames in the identity workflow with the installed local OpenCV scorer.
7. Preserve partial checkpoint downloads and provide direct publisher download links if the host remains unreliable.

### Task 1: Workflow Contracts

**Files:**
- Create: `tests/workflows/test_wan_q4_accuracy_workflows.py`

1. Define the four workflow specifications.
2. Assert exact Q4_K_M checkpoint names and author-aligned sampling.
3. Assert adaptive aspect-preserving sizing, frame counts, and 16 fps output.
4. Assert unwanted acceleration/guidance nodes are absent.
5. Assert identity and first/last-frame variants have the intended wiring.
6. Run the focused test and confirm it fails because the workflows are missing.

### Task 2: Deterministic Builder

**Files:**
- Create: `scripts/build_wan_q4_accuracy_workflows.py`
- Create: `user/default/workflows/agent/31 - WAN Q4 FAST Preview 17f.json`
- Create: `user/default/workflows/agent/32 - WAN Q4 Prompt Camera 49f.json`
- Create: `user/default/workflows/agent/33 - WAN Q4 Identity Audit 81f.json`
- Create: `user/default/workflows/agent/34 - WAN Q4 First Last Control 81f.json`

1. Clone only stable native node exemplars.
2. Remove the old LoRA and optional patch chains.
3. Apply per-workflow frame, pixel, prompt, sampling, and output settings.
4. Add identity-frame selectors and scorers to the audit workflow.
5. Add correctly scaled end-frame conditioning to the first/last workflow.
6. Generate all four JSON files.

### Task 3: Verification and Handoff

**Files:**
- Modify: `docs/plans/2026-07-23-wan-q4-accuracy-workflows.md`

1. Run the focused workflow contracts.
2. Validate JSON parseability and link integrity.
3. Validate executable node types and input names against a live ComfyUI registry when available.
4. Run a reduced smoke render only if a complete compatible model pair is available.
5. Record checkpoint download URLs, hashes, partial-download state, and measured evidence.
6. Mark this plan complete or explicitly document remaining external blockers.

## Plan Closeout

- Status: Complete.
- Four deterministic workflow JSON files were generated without modifying the
  existing WAN workflows.
- Focused verification: `15 passed in 0.05s`; builder compilation and
  deterministic regeneration also passed.
- Live schema verification: 4 workflows, 78 nodes, no missing executable node
  types, and no unknown inputs.
- Runtime topology smoke: the complete local Q8 pair rendered 224x224, 5 frames,
  2+2 steps in 44.38 seconds; final-frame face similarity was `0.789915`.
- The Q4_K_M low expert completed and matches its published SHA-256. Q4 runtime
  benchmarking was not claimed because the publisher reset the high-expert
  transfer after 1.81 GB. Direct high/low links and SHA-256 values are recorded
  in `docs/wan-q4-accuracy-workflows.md`.
