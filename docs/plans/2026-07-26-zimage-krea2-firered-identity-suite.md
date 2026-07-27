# Z-Image, Krea 2, and FireRed Identity/I2I Suite

**Goal:** Add focused, editable ComfyUI workflows that compare current Z-Image, Krea 2, and FireRed approaches for identity transfer and image-to-image editing on a 16 GB RTX 5070 Ti.

**Scope:** Preserve existing workflows and models. Add new assets only under the local model directories, `custom_nodes`, `scripts`, `tests/workflows`, `user/default/workflows/agent`, and a dedicated evidence directory under `output/agent`.

## Approved design

- Keep each model family in a focused workflow instead of one large graph.
- Use current community techniques rather than copying ComfyUI default templates.
- Keep native generative identity output distinct from any ReActor baseline.
- Use synthetic or public reference images for automated proof runs.
- Validate both editable workflow JSON and executable API graphs.
- Require one saved, visibly successful face-transfer result plus identity-similarity evidence before completion.

## Model and node matrix

| Lane | Model | Quantization | Supporting assets | Intended use |
| --- | --- | --- | --- | --- |
| Z-Image Turbo | Tongyi-MAI Z-Image Turbo | `z_image_turbo-Q8_0.gguf` | full Qwen3 4B encoder, existing AE | fast low-denoise I2I and anchor-based identity experiment |
| Z-Image Base | Tongyi-MAI Z-Image Base | `z_image-Q8_0.gguf` | shared full Qwen3 4B encoder, existing AE | higher-quality two-stage I2I/refinement |
| Krea 2 | Krea 2 Turbo | `krea2_turbo_fp8_scaled.safetensors` | Qwen3-VL 4B FP8, existing Qwen VAE, Identity Edit v1.2 LoRA | current community identity-edit method |
| FireRed | FireRed Image Edit 1.1 | `FireRed-Image-Edit-1.1-Q4_K_M.gguf` | existing Qwen2.5-VL encoder/VAE, Lightning 8-step v1.2 LoRA | native single/multi-reference identity editing |

The eight downloaded model files total 52.77 GiB. Final verification left
22.6 GB free on the current drive.

## Workflow artifacts

1. `40 - Z-Image Turbo Identity Anchor I2I.json`
   - Reference portrait and target scene inputs.
   - Honest native-output lane.
   - Low-denoise and anchor guidance notes.
   - Identity score and saved output.
2. `41 - Z-Image Base Two Stage Precision I2I.json`
   - Community-derived first pass plus low-denoise refinement.
   - Source identity audit.
3. `42 - Krea 2 Identity Edit v1.2.json`
   - One target scene plus one identity reference.
   - Krea2Edit model patch and grounded conditioning.
   - Eight-step Turbo defaults.
4. `43 - FireRed 1.1 Identity MultiRef.json`
   - Target image and identity reference.
   - Current Lightning LoRA.
   - Native identity score and saved output.
5. `44 - Face Swap Proof and ReActor Baseline.json`
   - Controlled public/synthetic source and target.
   - Native best-result comparison and explicitly labeled ReActor baseline.
   - Contact-sheet evidence and identity-score outputs.

## Implementation tasks

### 1. Test-first workflow contract

- Add focused tests that define required files, metadata, node types, model paths, connected inputs, output prefixes, and provenance notes.
- Run the tests and confirm they fail because the builder/artifacts do not exist.
- Implement the smallest deterministic builder that satisfies the contract.
- Re-run focused tests to green.

### 2. Install current components

- Install the maintained Krea2Edit custom node at its current tagged/recommended revision.
- Install RES4LYF only if the Z-Image Base graph uses its community `res_2s` sampler nodes.
- Download model files from their official Hugging Face repositories where available.
- Record source URL, revision, size, SHA-256, license, and destination in a local manifest.

### 3. Runtime validation

- Verify custom-node imports against the local ComfyUI build.
- Start an isolated ComfyUI instance on an unused local port.
- Query `/object_info` and validate every workflow node type and widget/model filename.
- Convert or emit API-format graphs and run a small smoke image through each lane.

### 4. Face-swap evidence

- Generate or use public/synthetic source and target portraits with clearly different identities.
- Run at least the strongest native identity-edit lane end to end.
- Run the labeled ReActor baseline separately when available.
- Save reference, target, native result, baseline result, contact sheet, workflow/API payload, and identity-score report under `output/agent/identity-model-benchmark`.
- Treat queued execution alone as insufficient: inspect the saved result and require a visible identity transfer.

### 5. Delivery notes

- Write a concise usage and comparison guide with recommended starting values, VRAM expectations, licensing, limitations, and exact model placement.
- Run fresh focused verification immediately before reporting completion.

## Closeout

- **Status:** Completed on 2026-07-26 for the workflow/build scope, native Krea
  identity proof, and controlled ReActor face-swap proof.
- **Issue:** Not created. Issues are disabled on the owner fork, so this uses
  the established `no-issue` branch convention.
- **Branch:** `agent/codex/no-issue-modern-identity-suite`.
- **PR target:** `ArchonVII/ComfyUI:master`.
- **Delivered:** Five editable workflows, two executable API graphs, a
  deterministic workflow builder, model/download manifest, usage guide,
  focused tests, synthetic source/target fixtures, a saved native Krea result,
  and saved ReActor/GFPGAN control results.
- **Proof:** The first submitted native Krea API run completed in 50.57 seconds,
  visibly transferred the source identity while preserving the target scene,
  and scored `0.771222` cosine identity similarity against the configured
  `0.363` same-identity threshold. The preferred restored ReActor control
  scored `0.780879`; the highest raw control result scored `0.812342`.
- **Verification:** All eight model files matched their expected sizes and
  SHA-256 hashes; 25 workflow tests, 2 Krea node tests, Ruff, JSON parsing,
  live/direct node schema checks, and proof-integrity checks passed.
- **Review closeout:** A P1 portability review found OS-native separators in
  nested model selector values. The final workflows use separator-free model
  filenames at each category root; Windows exposes the existing downloads
  through zero-storage NTFS hardlinks. A regression test and live combo-option
  validation cover this contract.
- **FireRed review closeout:** A second P1 review found that the generated
  `TextEncodeQwenImageEditPlus` inputs did not follow the registered positional
  schema. Both positive and unconditional nodes now declare
  `clip, prompt, vae, image1, image2, image3`, with a regression test covering
  the exact order and normal link-integrity checks covering the resulting
  target slots.
- **Reproduction review closeout:** Final P2 review found stale nested FireRed
  encoder placement text and an undocumented GFPGAN v1.4 dependency. The guide
  now matches the flat selector path and explains the zero-storage alias; the
  manifest records the required restorer's ReActor dataset URL, path, byte
  size, SHA-256 hash, and license. Two focused tests enforce both contracts.
- **Final labeling/provenance closeout:** A later P2 review found the Krea API
  save prefix under the control-evidence directory and an unpinned
  `inswapper_128.onnx`. Krea API results now save under
  `agent/modern-identity/krea2-identity-v1-2`; the manifest pins the swap
  model's ReActor URL, destination, size, SHA-256 hash, and InsightFace
  non-commercial terms. Tests enforce both behaviors.
- **Z-Image schema closeout:** A later P1 review found both `ImageStitch`
  declarations placing `image2` before the registered widget inputs. Both
  declarations and generated links now follow the live schema order, with
  `image2` in target slot 5; a focused regression covers both nodes.
- **Native runtime closeout:** An isolated ComfyUI 0.26.0 server on the final PR
  head registered the Krea v1.2 nodes and ran the committed Krea API graph
  against the synthetic source/target pair. Prompt
  `0df57a3f-f7c7-4455-ae22-1df9dc495803` completed successfully on its first
  submission and saved
  `output/agent/modern-identity/krea2-identity-v1-2_00001_.png` plus
  `user/default/identity_score_runs/20260726-205004-krea2-native-proof.json`.
  Visual inspection confirmed identity transfer and target-scene preservation;
  the report classified the result as the same identity at `0.771222`.
  Z-Image and FireRed remain schema/selector-validated experimental lanes with
  no committed runtime result. The separately labeled ReActor evidence remains
  the controlled baseline.
