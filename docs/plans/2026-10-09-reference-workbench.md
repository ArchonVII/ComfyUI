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

Implementation complete. Existing PR: https://github.com/ArchonVII/ComfyUI/pull/25
Owner authorized review and merge on October 9, 2026. Review found and fixed a
dependency on an untracked live-install face helper: clean checkouts now reuse
the tracked Arch Image Tools detector, with the bounded helper retained when
installed. A real-detector synthetic regression covers this checkout difference.
Review also fixed Cast choices remaining stale after favorite creation, rename or
deletion; renamed lanes follow the new group name and invalidate their old locks.

- Initial validation: 24 workbench and 102 source tests passed.
- Final review validation: 188 workbench/source/library tests passed, including
  clean-checkout real face detection and Cast favorite-refresh regressions.
- Isolated installed frontend 1.51.10 registered and executed all five nodes;
  successful synthetic prompt `a893f479-0a03-46fb-95ec-a20460110338`.
- Browser verified full two-image review, persistent Keep status, library import
  of both result copies, hidden Cast state and disabled independent seed mutation.
- Run Record persisted images/sidecar with Comfy's nonfinite cache marker explicitly
  represented; source graph remains unmodified. Regression added.
- Real local YuNet detector executed on synthetic blank input (no face expected).
- Triton GPU compile/run and dependency check passed; RMBG now registers 43 nodes,
  including SAM3Segment. Isolated startup has no missing-Triton or timm warnings.
- Runtime files and review fixes deployed, with the new synthetic demo workflow.
  Manager restarted port 8192 after confirming no running/pending jobs. All five
  workbench nodes and SAM3Segment registered. Synthetic live prompt
  `915c5c39-f8fb-47a4-976e-30348cffe1c3` succeeded, producing a two-image review
  and Run Record sidecar. Hard-refresh already-open browser tabs for updated JS.
