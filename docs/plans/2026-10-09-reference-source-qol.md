# Reference source usability and library integration

Owner authorized the recommended four-stage order in chat on October 9, 2026.
Work is isolated on `agent/codex/reference-source-qol`; deployment targets the
existing installation on port 8192. No existing saved workflows, favorites,
library records, images, or unrelated edits are to be replaced.

## Behavior and sequence

1. Fix group photo replacement to retain the destination prompt. Refresh all
   consumers of edited groups while retaining genuinely modified prompt drafts.
   Encode comma-containing paths correctly when opening enlarged previews.
2. Distinguish checked photos from the active run source with a persistent count,
   pending/applied status, and explicit apply action. Closing must not silently
   imply that checked photos were applied.
3. Publish the actual loaded image through ComfyUI execution UI data. Display
   Last used separately from the next-image/pool preview, with a reuse button.
   Reuse fixes the node to that image; it does not queue or reroll generation.
4. Load subject or environment collections from the Reference Library into the
   current node. Support its existing tag-filtered pool and optional profile
   positive prompt; explain that negative prompts and LoRAs require the existing
   library selector/profile nodes. Loading is an explicit snapshot, not a hidden
   link to global sidebar state. Save checked photos to either collection kind
   and offer a direct way to open the destination in the library.

Assumptions: this is the owner's local single-user install; images stay local.
Use existing APIs and node outputs where possible, no new dependencies, automatic
model downloads, or generation jobs. Preserve workflow node names and output
positions. Favor asynchronous local requests and protect against stale responses.

## Verification and delivery

Write focused regressions for saved-prompt preservation, shared-group refresh,
comma paths, pending selection state, execution/reuse, and library loading.
Run package tests with the installed main venv, plus browser validation with
synthetic local images if feasible. Hash-check deployment and preserved config.
Restart only an idle 8192 queue; report any approval-system restriction honestly.
Required CI is the full-suite authority; do not duplicate it locally.

Issues are disabled on the fork. The only checked-in PR template is for paid API
nodes and does not apply to these local nodes. No claim tool, changelog fragment
rule, check map, or worktree teardown command is declared in this repository.
README updates will describe final user behavior. A draft fork PR tracks delivery;
merge to master requires the owner's landing instruction.

## State

All four stages implemented and deployed to port 8192 on October 9, 2026.
ComfyUI Manager's native restart activated the Python changes after an idle-queue
check. Every deployed package file matches the reviewed source; both favorite
configuration files retained their original hashes. No saved workflow was edited.

Verification: 96 reference-source tests and 60 library tests passed. Independent
spec/correctness review found no remaining blockers. An isolated CPU-only browser
smoke checked comma-path enlargement, pending/applied state, environment saves,
opening the correct library collection, loading a collection snapshot, execution
metadata, and exact-image reuse. A final preview-only prompt on 8192 completed
successfully and reported `Doe, Jane.png` as the actual last-used synthetic image.
No diffusion model or personal image was used in verification.

Fork PR: https://github.com/ArchonVII/ComfyUI/pull/25
Implementation complete; owner authorized review and merge to master on October 9, 2026.
