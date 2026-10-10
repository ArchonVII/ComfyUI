# Reference workbench and targeted startup repair

Owner authorized the five companion nodes and targeted startup changes in chat.
Continue the open reference-source PR/worktree; update its title/body to cover
the final feature set. The existing deployment at 8192 is the runtime target.

## Contracts

- **Contact Sheet**: produce a labeled image from selected references, with role
  and filename captions. Unequal dimensions must not distort the source images.
- **Reference Prepare**: face, mask/subject, or full-image crop/pad with target
  dimensions and a preview marking the region used. Reuse existing face detection;
  no downloads or independent identity scorer. Return owned transformed outputs.
- **Reference Cast**: select from named favorite groups for subject, clothing,
  environment, and style. Enable/lock each lane independently. Locks retain paths,
  never resident image tensors, and changing a group invalidates its old lock.
  Expose lane images and actual-choice metadata for downstream model-specific nodes.
- **Result Review**: local reference/result comparison, optional existing score
  report and run settings, explicit Keep/Reject classification without deleting
  originals, and Save to Library integration.
- **Run Record**: save outputs plus local JSON sidecars containing actual reference
  metadata, supplied prompt, seed/model/LoRA settings and workflow/API graph metadata.
  Unique run paths, atomic sidecar writes, no external calls, no original overwrites.
- Add shuffle-without-repeats to the existing source rather than another selector.

Startup scope: restore missing RMBG SAM3 imports with a compatible pinned Windows
Triton build and test its GPU kernel path. Correct deprecated timm imports only
where traced. No broad upgrades, Matrix-sharing installation, multi-GPU override,
renderer changes without a reproduced problem, or renaming of the live directory.

## Execution and verification

Use a new `custom_nodes/comfyui_arch_reference_workbench` package. Imaging and
review/record modules are independent implementation tasks; integration, Cast,
source shuffle, documentation, startup repairs and deployment remain with primary.
Focused regressions first, synthetic images only, isolated UI/API smoke tests,
then idle-queue deployment/restart and node-registration/live preview verification.
Preserve existing workflows, favorites, library data, and unrelated edits. Images
and video never enter Git. No new model download is needed for these features.

## State

Implementation in progress. Existing PR: https://github.com/ArchonVII/ComfyUI/pull/25
Merge remains unauthorized; deliver a tested local activation and review-ready PR.
