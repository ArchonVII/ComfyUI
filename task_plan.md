# Adaptive LTX and Wan I2V Workflow Implementation Plan

**Goal:** Replace three brittle LTX image-to-video workflows and add three Wan 2.2 GGUF image-to-video workflows that adapt resolution to the source image and run on the installed RTX 5070 Ti/16 GB environment.

**Architecture:** Each workflow scales its source image to a model-specific total-pixel budget while preserving aspect ratio and rounding to a safe spatial multiple, then passes the derived width and height into the video conditioning node. Wan workflows use the installed high/low GGUF experts with explicit expert handoff; advanced guidance is optional and baseline behavior remains inspectable.

**Tech stack:** ComfyUI editor-format JSON, native video/image nodes, ComfyUI-GGUF, installed KJNodes/RIFE nodes, Python semantic validation tests.

**Plan status:** Complete; awaiting draft PR review.

## Understanding and Constraints

- Build six workflows under `user/default/workflows/agent`.
- Preserve source aspect ratio without fixed landscape, portrait, or square assumptions.
- Tune defaults for batch 1 on an RTX 5070 Ti with 16 GB VRAM.
- Use installed models and node packs; do not download large checkpoints.
- Do not touch the unrelated modified workflow in the protected master checkout.
- Keep generation local; no partner/cloud API nodes.

## Decision Log

1. Use `ImageScaleToTotalPixels` followed by `GetImageSize` as the canonical adaptive-sizing chain. This directly implements Wan's input-aspect/pixel-area policy and avoids fragile arithmetic graphs.
2. Keep LTX 0.9.8 runnable rather than referencing uninstalled LTX 2.3 assets. LTX 2.3 remains the recommended future model migration when storage is available.
3. Use the installed Wan 2.2 high/low GGUF pair. The existing FP8 workflow references missing files.
4. Use separate draft, quality, and first/last-frame workflows. One graph with many switches would be harder to audit and easier to misconfigure.
5. Exclude deprecated TeaCache. Add live-installed EasyCache, NAG, Enhance-A-Video, and RIFLEx controls to both Wan expert lanes, bypassed by default and documented as opt-ins.
6. Use root planning files as the canonical task record; do not create a duplicate `docs/plans` document.
7. Proceed with a `no-issue` branch because issues are disabled at `https://github.com/ArchonVII/ComfyUI`.

## Tasks

### 1. Workflow Contract Tests — Complete

- Create `tests/workflows/test_adaptive_video_workflows.py`.
- Assert all six editor JSON files exist and parse.
- Assert each graph contains source-aware total-pixel scaling and dimension propagation.
- Assert frame counts satisfy the model rules and output nodes save MP4.
- Assert every loader default resolves in the live main-runtime model catalog.
- Assert Wan graphs use the installed GGUF high/low experts and correct handoff.
- Run the focused test and capture the expected RED failures against the current workflows.

### 2. Deterministic Workflow Builder — Complete

- Create `scripts/build_adaptive_video_workflows.py`.
- Reuse the current editor graph schema while generating stable node IDs, links, groups, notes, and widget values.
- Generate the three replacement LTX workflows and three Wan workflows.
- Keep source images selectable and avoid missing placeholder defaults.
- Run the focused tests until GREEN.

### 3. Runtime Validation — Complete

- Validate all node types and input schemas against `http://127.0.0.1:8190/object_info`.
- Convert or submit one low-cost Wan draft prompt against an isolated worktree server using the main runtime base.
- Confirm adaptive dimensions follow a real portrait input and remain model-safe.
- Record any runtime limitation without weakening semantic tests.

### 4. Delivery — In progress

- Review `git diff`, confirm only scoped files changed, and rerun full focused verification.
- Update this plan, `findings.md`, and `progress.md` with final evidence and closeout state.
- Commit selectively, push the branch, and open a draft PR using the repository template.

## Errors Encountered

| Error | Attempt | Resolution |
| --- | --- | --- |
| `package.json` absent during session-start script check | 1 | No npm agent helpers exist in this checkout; used repository-native git checks. |
| PowerShell interpolated `$name:` as an invalid variable | 1 | Switched to format-string output. |
| `gh issue list` reported issues disabled | 1 | Use the fork's established `no-issue` branch convention and record the limitation. |
| Live `object_info` request was refused after research | 1 | The original ComfyUI process stopped; defer live checks to an isolated worktree server. |
| Existing weak workflow files were absent from the new worktree | 1 | They are intentionally ignored local assets; generate and force-add only the six scoped files. |
| Model-resolution tests failed when the runtime-base environment variable was omitted | 1 | Reran with `COMFY_RUNTIME_BASE=C:\tools\image\ComfyUI`; the worktree intentionally does not duplicate large models. |
| LightX2V Seko LoRAs reported unsupported residual keys through the GGUF loader | 1 | Kept the installed four-step pair because GGUF LoRA support is explicitly experimental, the supported patches loaded, and the full dual-expert smoke rendered coherently; recorded the limitation in findings. |

## Plan Closeout

- Status: Implementation and runtime validation complete.
- Six deterministic workflows generated, 28 contract tests pass, all executable nodes match the live registry, and the Wan fast path produced a verified 9-frame MP4.
- Remaining delivery action: selective commit, push, and draft PR.
