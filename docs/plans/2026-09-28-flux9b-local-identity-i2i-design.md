# Flux 9B Local Identity-Preserving I2I Design

**Date:** 2026-09-28
**Status:** Implemented and live-validated on port 8192
**Runtime target:** Local ComfyUI install at `http://127.0.0.1:8192`

## Workspace revision (2026-09-29)

Owner approved reorganizing workflow 54 and its live copy in place. The main
canvas now keeps the five image inputs and adjacent enable switches together,
with prompt, seed, generation and identity controls below, and final/base saves
at the right. The mask and separate reference/base score previews stay visible.
Three native subgraphs contain model/prompt setup, reference preparation and
generation, and identity finishing/scoring. Double-click them for advanced
settings. Common settings are promoted with descriptive labels; seed and its
after-generation control stay together in the native seed node.

The executable API remains identical to the prior workflow. The builder checks
subgraph wiring by resolving it back to the original node IDs; focused tests
cover port reciprocity, exposed controls, input/switch adjacency, and overlap.
No model, sampling, identity-gate, or save-prefix defaults change. This is an
owner-authorized exception to the original new-workflows-only scope for #54.

### Reference browser integration (workspace version 5)

The owner subsequently approved replacing all five `LoadImage` inputs with
`RandomReferenceImageSource`. Each compact source opens the separate scrollable
Reference Browser and can use a folder, explicit image set, or saved favorite.
The image and mask output slots keep their positions. Main, identity, and
auxiliary sources remain independently selectable; optional sources still use
the same lazy enable switches. Favorite prompt outputs remain available on the
nodes but are not automatically inserted into the workflow's edit instruction.
All executable nodes after the five source nodes retain their prior settings
and connections. Source cards have extra height for their compact controls.

## Understanding summary

- Create a new standard Flux 9B image-to-image workflow based on the API graph
  in `D:\$workflows\Flux9 - fashion.json`.
- Preserve the regular Flux 9B editing path while adding reliable face-identity
  retention for a single primary person.
- Accept an optional dedicated identity image and fall back to the main image
  when the dedicated identity path is disabled.
- Accept three independently enabled auxiliary image references for clothing,
  environment, pose, style, props, or other visual guidance.
- Prevent narrow cutouts and other extreme reference shapes from dictating the
  output dimensions.
- Keep all images, prompts, embeddings, face analysis, inference, and output on
  the local machine.
- Add a new workflow and companion API graph; do not modify, move, or remove an
  existing saved workflow.

## Assumptions and scope

- The first version targets the largest detected source and target face.
- The normal image budget remains approximately one megapixel, using dimensions
  compatible with the installed Flux 9B stack.
- Reliability and identity accuracy take priority over the modest additional
  runtime of local face analysis and compositing.
- Automatic multi-person identity assignment is out of scope.
- Extreme profiles, very small faces, heavy occlusion, and covered faces require
  manual review and may require a different face index or source image.
- Port 8192 is authoritative for live schema checks and smoke runs. Verification
  must not fall back silently to another ComfyUI process.

## Architecture

### Inputs and reference roles

The workflow exposes five image roles:

1. Main i2i image: content and composition foundation.
2. Optional identity image: face identity source.
3. Auxiliary reference 1.
4. Auxiliary reference 2.
5. Auxiliary reference 3.

The identity selector defaults to the main image. A visible control enables the
dedicated identity image. Each auxiliary reference has an independent enable
control and preview. Disabled references are bypassed rather than represented
by blank images.

The main image is the first Flux reference. Enabled auxiliary references are
normalized independently and appended through the Flux reference-latent chain.
The dedicated identity image is reserved for the face-transfer stage so it does
not compete with the scene and auxiliary references during Flux sampling.
Prompt guidance identifies the role and order of each enabled image.

### Canvas policy

Output dimensions are independent of reference dimensions. Auto mode chooses a
conservative canvas family:

- portrait source: approximately 3:4;
- near-square source: 1:1;
- landscape source: approximately 4:3.

Extreme ratios are clamped to these ordinary canvas families. A narrow person
cutout therefore yields a normal portrait canvas instead of an extreme vertical
strip. Manual presets provide 1:1, 3:4, 2:3, 4:3, 3:2, and 16:9 choices.

Preset dimensions stay near the existing one-megapixel budget and use model-
compatible multiples. References are proportionally resized and padded or
fitted; they are never stretched. Reference normalization does not feed width
or height into the output latent.

### Flux generation

The existing Flux 9B model, text encoder, VAE, LoRA chain, reference encoding,
and sampler form the baseline. Implementation must audit model compatibility,
LoRA ordering and strengths, scheduler, steps, CFG, interpolation, pixel budget,
and conditioning flow against the installed runtime before retaining them.

Loaders are shared rather than duplicated. The graph is arranged left-to-right
in labeled groups: inputs, canvas, reference preparation, model and prompting,
sampling, identity transfer, SAM/blending, identity audit, and outputs.

### Identity preservation

After Flux generation, `ArchLocalFaceIdentityTransfer` uses the local
`inswapper_128.onnx` model, ArcFace embedding model, and YuNet five-point
landmarks to detect, affine-align, transform, and place the selected identity
onto the generated face. This is the landmark-aware stage; SAM is not described
as a landmark detector.

Local SAM refines the affected face region so blending remains bounded. The node
also offers a landmark-feather fallback. Generative face restoration is omitted
because it can replace identifying detail.

The workflow exposes previews for the normalized identity source, generated
face, SAM mask, and final result. It saves the base Flux result
and identity-finished result with distinct prefixes.

### Identity audit and failures

A local dual identity-score branch compares the final detected face with both
the selected identity source and the ungated Flux result. The strict gate is on
by default and blocks only the identity-finished save when the reference score
misses the configured threshold. When a dedicated identity image is selected,
the gate also requires the result to be closer to that identity than to the
ungated Flux face. The base Flux result remains available for diagnosis.

Missing or unreadable faces and invalid face selections must fail visibly; the
workflow must not silently represent an unchanged image as a successful identity
transfer. Face-index controls remain visible and default to zero.

## Local-only boundary

The workflow uses local model loaders, local reference files, local Flux
inference, local OpenCV/ArcFace/INSwapper analysis, local SAM inference, local image
processing, and local saves. It contains no remote API, upload, telemetry, or
hosted inference node. Owner images and generated outputs remain untracked and
must not be committed or pushed.

## Verification strategy

- Validate every node type against `/object_info` on the 8192 instance.
- Verify every selected model file exists locally.
- Generate editor-format and API-format workflows from one source and test their
  structural equivalence.
- Verify main-image identity fallback and dedicated identity selection.
- Queue configurations with zero, one, two, and three auxiliary references.
- Verify tall-cutout, portrait, square, landscape, and extreme-wide inputs map
  to the expected canvas without stretching.
- Exercise frontal, three-quarter, and tilted faces.
- Verify missing-face and invalid-index failures are visible.
- Confirm saved outputs match the selected dimensions.
- Confirm identity score and diagnostic previews are produced locally.
- Run a focused low-resolution end-to-end smoke test on port 8192. Required
  GitHub CI remains the only required full-suite delivery run.

## Decision log

| Decision | Alternatives | Reason |
| --- | --- | --- |
| Base the workflow on `Flux9 - fashion.json` | Numbered agent/custom workflows | Owner identified the external regular i2i graph as authoritative. |
| Use a focused local ArcFace + INSwapper + SAM finish | Legacy ReActor/Impact nodes; PuLID-only; Flux crop-and-compose | The 8192 install has the required local models and runtimes without importing the legacy node stacks. |
| Keep identity input separate with main-image fallback | Require a second image; always use main image | Supports both ordinary i2i and explicit identity transfer. |
| Provide three auxiliary references | One reference; unlimited dynamic references | Practical multi-reference capacity without an unwieldy graph or accidental over-conditioning. |
| Decouple output canvas from source dimensions | Preserve source dimensions | Prevents cutouts and extreme ratios from creating unsuitable outputs. |
| Use conservative Auto ratios plus manual presets | Fully arbitrary Auto output | Predictable composition while retaining deliberate creative control. |
| Disable generative face restoration by default | Always apply GFPGAN/CodeFormer | Restoration can reduce identity fidelity. |
| Gate only the identity-finished save | Diagnostic-only score; block every output | A full 9B smoke proved that a result can clear the absolute threshold while remaining closer to the base face. Keeping the base save preserves diagnosis and recovery. |
| Use two aligned identity passes by default | One pass; unrestricted passes | The full workflow improved from reference/base 0.479834/0.784951 with one pass to 0.871451/0.282268 with two; a three-pass ceiling bounds cost and visual drift. |
| Target only the 8192 runtime for live checks | Fall back to any active ComfyUI port | Prevents validating against the wrong installation. |
| Add new workflow files only | Modify an existing saved workflow | Existing workflow files are protected owner data. |

## Risks

- Landmark identity transfer may struggle with extreme profiles, tiny faces, or strong occlusion.
- Too many strong visual references can compete with the prompt or main image.
- SAM masks may require tuning around hair, hands, glasses, or partial occlusion.
- Identity similarity scores are useful evidence but not an absolute measure of
  perceptual likeness.
- Identity quality still depends on a clear source face; the local score remains
  visible so weak source images are not mistaken for successful preservation.

## Implementation plan

1. Add a focused `comfyui_arch_image_tools` custom node containing
   `ArchCanvasSize`. It maps Auto and the six approved manual modes to a
   model-compatible near-1MP canvas and clamps pathological source ratios.
2. Add test-first coverage for canvas selection, deterministic workflow
   generation, protected input/reference roles, lazy optional branches, Flux
   conditioning, local ArcFace/INSwapper landmark transfer, SAM-bounded blending, local
   identity scoring, and API/editor equivalence.
3. Add `scripts/build_flux9b_local_identity_i2i_workflow.py` to generate one new
   editor workflow and one API workflow from the same graph definition. Use a
   synthetic local placeholder; never embed or copy an owner image.
4. Generate the artifacts under `user/default/workflows/agent` and
   `user/default/api_workflows/agent`. Do not alter existing workflow files.
5. Run the focused node and workflow tests plus generator drift check. Once the
   selected ComfyUI instance is listening, validate node schemas through
   `http://127.0.0.1:8192/object_info` and run the focused smoke prompt there.

**Verification result:** 25 focused tests passed; all 53 executable nodes and
selected model values validated against live `/object_info`; direct 8192 smoke
tests completed for both landmark-feather and SAM modes. A representative local
SAM smoke scored 0.814869 against the selected source and 0.307450 against the
original target, confirming the identity direction changed as intended.

## Hardening pass

**Status:** Complete and live-validated on the 8192 install.

1. Make the node package, workflow #54, companion API workflow, and synthetic
   placeholder explicit tracked exceptions. Extend the generator with a checked
   install/sync path for the isolated 8192 root so canonical and live copies
   cannot drift silently.
2. Add an early identity preflight that validates every local model artifact,
   detects and selects the source face, computes its mapped identity vector on
   CPU, and returns a face preview. Route the main Flux reference through that
   node so a bad identity source fails before model loading or sampling.
3. Keep ArcFace and INSwapper ONNX sessions on CPU so their allocations do not
   compete with Flux 9B. Before CUDA SAM inference, explicitly ask ComfyUI to
   unload managed models and clear its cache. Clip the SAM box and report affine
   failures clearly.
4. Replace the hidden single comparison with `DualIdentityScore`. Add a shared
   identity-enable control plus a strict gate that blocks only the final identity
   save when the selected reference was not detected or did not meet the local
   identity threshold. The base Flux save remains unconditional.
5. Add focused red/green tests for preflight, face selection, disabled bypass,
   strict gating, portable embedding-map extraction, installation drift, graph
   ordering, and the visible dual score. Re-run live schema validation and
   focused 8192 identity/SAM smokes after installing the updated package.

**Hardening verification result:** 43 focused tests passed. The canonical files
and isolated 8192 runtime passed the install-drift check, and all new node types
were present in live `/object_info`. A complete Flux 9B run finished locally in
without OOM and the final verified run completed in 23.4 seconds, scoring
0.869893 to the dedicated reference versus 0.291177 to the base face. A forced
one-pass negative run scored 0.521441 to the
reference versus 0.750332 to the base; the dominance gate correctly blocked the
identity-finished save. Each aligned pass re-segments the updated face because
live testing showed that reusing the first SAM mask reduced identity fidelity.
The SAM model is loaded once per node execution and reused only as a model while
each updated image receives a fresh embedding and mask; ArcFace and INSwapper
remain CPU-only.

## Favorite prompt integration — 2026-09-29

Workflow v6 adds ReferencePromptCompose inside the prompt/model subgraph. Its exposed Edit instruction is combined with current prompt text from main and enabled identity/auxiliary sources, then connected to CLIPTextEncode.text. The same booleans govern optional images and optional text. Lazy prompt inputs avoid executing disabled sources. Combined prompt sent to Flux displays the executed text inside the subgraph.

Favorite prompt edits now apply immediately to the node, including clearing text. Save/Update persists the edited text for reuse. Existing saved #54 files matched the prior builder before backup and regeneration. No preset or personal image data was modified.

Verification: 75 focused tests passed; after the optional-unconnected-lane correction all 27 backend node tests passed again. An isolated CPU-only ComfyUI server executed real source → composer → PreviewAny prompts with optional lanes both disabled and enabled and returned the exact expected text. The temporary server was stopped. Live workflow/package files are synchronized, but an immediate pre-restart queue check found new work, so live port 8192 was not restarted. Activation requires a restart when the owner queue is clear, then browser refresh and reopening #54.

Activation completed on the following turn: live queue was empty, the manager restart was issued after a second queue check, and /object_info/ReferencePromptCompose confirmed the new node loaded on port 8192. Browser refresh and reopening the updated #54 are still required for an already-open canvas.

## Workflow usability follow-up — 2026-09-29

Owner authorized the four review fixes. Workflow v7 defers reference filesystem
validation until a source executes, allowing empty disabled slots. Preflight and
transfer publish their face selection order, index, and detection threshold to
the dual scorer; unavailable indices remain undetected instead of silently
scoring another face. Existing output slots keep their indices.

Identity finish OFF bypasses preflight detection, transfer, scoring, and manifest
writes. Scorer image inputs and preflight identity input are lazy. The separate
identity-reference switch still controls that image's Flux conditioning and
prompt contribution independently of the post-generation identity finish.

Three root status cards show preflight, transfer, and final-save status. The last
includes identity scores when the gate passes. Gate failures return an execution
blocker only on the image output, preserving the reason on the status output and
allowing the independent base branch to complete. No failing final image passes
to PreviewImage or SaveImage.

Verification: 77 focused tests passed, plus the 16 workflow tests after extending
runtime installation checks. A separate CPU-only process using the actual Comfy
executor validated and executed an empty optional source with identity finish
disabled, and verified that a weak identity blocks its image consumer while
status and base consumers complete. Runtime workflow and changed backend files
match the canonical build. Existing live #54 matched the previous commit before
backup and installation; no owner images were used for these checks.

Live activation also passed: the idle queue was rechecked immediately before restarting port 8192. Both smoke cases then passed through the live /prompt API. Refresh the frontend and reopen saved #54 to replace an already-open canvas.
