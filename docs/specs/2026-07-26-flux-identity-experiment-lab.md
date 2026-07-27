# Flux Identity Experiment Lab Design

**Status:** Approved on 2026-07-26
**Scope:** Local Flux/Klein 9B face-swap and identity-preserving image-to-image experiments
**Owner:** Local ComfyUI user

## Understanding Summary

- Build a local experiment system for two-image `face_swap` and `identity_i2i` work.
- Start with the installed Flux/Klein 9B diffusion models and add other model-family adapters later.
- Keep separate task-specific workflow templates behind one experiment panel.
- Lock both source images, the prompt, and the seed set within an experiment.
- Sweep checkpoint, up to three LoRAs and strengths, seed, steps, guidance/CFG, sampler, scheduler, denoise, and pixel budget.
- Use staged testing instead of an exhaustive Cartesian grid.
- Rank with the mode-appropriate identity score, then make the final choice in a local visual gallery.

## Assumptions and Non-Functional Requirements

- One local user, one ComfyUI server, and one GPU execute generations serially.
- An experiment supports up to 100 planned runs.
- Interrupted experiments are resumable and completed parameter combinations are not queued twice.
- Images, face embeddings, thumbnails, ratings, and experiment data remain on the local machine.
- SQLite is the durable experiment store; output images remain ordinary ComfyUI files.
- Launch estimates show run count, approximate duration, and disk usage. No automatic output deletion occurs.
- OpenCV SFace similarity is a comparative signal, not an absolute identity verdict. Manual review is authoritative.
- Only authorized local reference subjects are used.

Version one does not execute Qwen or Z-Image-family graphs, use cloud services, add automatic aesthetic scoring, schedule multiple users or GPUs, expose every arbitrary node input, or perform exhaustive searches.

## Approaches Considered

### Recommended: Custom-node experiment service plus reusable templates

Extend `comfyui_identity_score` into a cohesive identity experiment extension. The Python side owns scoring, deterministic run planning, SQLite persistence, local routes, and result recording. A ComfyUI web extension owns experiment setup and the ranked review gallery. Two editor-format workflows provide explicit Flux contracts for swap and i2i.

This approach keeps generation in ComfyUI, makes the scorer useful during ordinary manual queues, survives browser or server restarts, and gives later model families a narrow adapter boundary.

### Workflow-only matrix

A single graph could duplicate model and LoRA branches. It would be easy to inspect but difficult to scale, resume, deduplicate, or review after dozens of runs. Every new model family would make the graph larger and more fragile.

### External command-line runner

A PowerShell or Python runner could patch API prompts and create reports. It would be straightforward to test but would split the user experience between the terminal and ComfyUI and would not provide the requested in-graph score or integrated gallery.

The custom-node service approach was selected. The panel-driven approach, reusable templates, and staged search were explicitly approved.

## Architecture

The existing `comfyui_identity_score` custom node remains the extension boundary. It gains four focused layers:

1. `identity_core.py` detects faces and computes embeddings and similarities without persistence.
2. `experiment_planner.py` validates experiment configuration and expands deterministic, deduplicated stages.
3. `experiment_store.py` owns the SQLite schema and transactional experiment/run/rating operations.
4. `routes.py` exposes local catalog, experiment, queue-plan, result, rating, resume, archive, and output-serving endpoints.

`nodes.py` exposes a new `DualIdentityScore` output node. The web extension in `web/identity_lab.js` uses the routes and ComfyUI's existing `/prompt` endpoint. It never receives or transmits raw embeddings.

Two workflow templates define the patch contract for the Flux adapter. The runner patches only named, validated inputs. The adapter rejects a template when required node roles are missing or when a selected model/LoRA is not in the live local catalog.

SQLite lives below the ComfyUI user directory, not in the repository. Generated images live below the normal output directory. Database rows store relative paths so the runtime base can move without invalidating records.

## Dual Identity Scoring

`Dual Identity Score` accepts the base/input image, identity/reference image, generated image, experiment mode, thresholds, and optional experiment/run metadata. It detects the generated face once, then compares that embedding with the selected face from each source.

The result contains:

- reference-to-output cosine similarity and same-identity decision;
- base-to-output cosine similarity and same-identity decision;
- active ranking score (`reference` for `face_swap`, `base` for `identity_i2i`);
- face-detection status for all three images;
- experiment ID, run ID, and saved result path when recording is enabled;
- a JSON report and metadata output for existing workflow integrations.

The node returns ComfyUI `ui` data so both scores, the active score, status, and result ID appear directly on the executed node. Missing faces produce an explicit non-rankable result rather than a misleading zero score or an entire queue failure.

When experiment metadata is present, the node saves the generated image with prompt metadata and completes the matching SQLite run transactionally. With no experiment metadata, it behaves as a manual scoring output node and may write the existing JSON manifest format.

## Experiment and Staging Model

An experiment locks mode, base image, identity image, prompt, negative prompt where used, seed set, workflow template, and model family. A canonical JSON representation is hashed with every parameter combination. The unique `(experiment_id, combination_hash)` constraint prevents accidental duplicates.

Stages are explicit:

1. `checkpoint`: selected checkpoints with no experimental LoRA, aligned across the same seeds.
2. `lora_single`: every selected LoRA individually on promoted checkpoint finalists.
3. `lora_pair`: pair combinations among promoted LoRA finalists.
4. `lora_triple`: optional and never generated unless enabled.
5. `refine`: selected strengths and sampling settings on the promoted finalists.

Promotion is human-controlled from the gallery. The panel can preselect the highest active scores, but it does not silently advance or treat identity score as image quality.

The planner estimates duration from the experiment's completed-run median, falling back to a clearly labeled user-editable estimate. Disk usage uses recent output sizes when available and otherwise a conservative per-image estimate. Launch is blocked above 100 runs or when the estimate exceeds currently available output-disk space.

## Queueing, Resume, and Failure Handling

The panel captures the loaded workflow in API format, validates the Flux template contract, asks the backend to create the planned run rows, then queues only pending runs through ComfyUI's normal prompt endpoint. Each queued prompt carries stable experiment and run IDs into `DualIdentityScore`.

The database uses `planned`, `queued`, `running`, `completed`, `failed`, and `archived` states. A completed run is immutable except for rating, favorite, notes, and archive state. Resume changes stale `queued` or `running` rows back to `planned` only after confirming they are absent from ComfyUI queue/history, then queues pending work.

Invalid model paths, LoRA paths, parameters, node contracts, or run counts fail validation before queue submission. Per-run generation or scoring failures are recorded with a concise local error and do not erase completed results. A no-face result is completed but marked non-rankable so it remains visible for diagnosis.

## Review Gallery

The web panel has three views: setup, progress, and results. Setup selects mode, the loaded compatible template, checkpoints, candidate LoRAs, strengths, seed set, and focused sampler settings. It shows the expanded run count and storage/time estimate before launch.

Progress shows stage counts, current/pending/failed runs, pause-after-current behavior, and resume. Pausing does not interrupt an executing ComfyUI prompt.

Results show local thumbnails with both similarities, active score, checkpoint, LoRA stack, sampling settings, runtime, and detection status. The default sort is active score, with filters for stage, checkpoint, LoRA, state, favorite, and manual rating. Users can set favorite/reject, a 1–5 rating, and notes. Promotion to the next stage is explicit and uses selected results or selected parameter candidates.

Archive hides an experiment and its rows without deleting images. Delete requires a separate explicit confirmation and lists the exact database records and output files that would be removed.

## Workflow Templates

The face-swap template uses the proven crop, mask-refinement, Flux reference-latent, and uncrop-composite path. The base image supplies body, pose, composition, and environment; the identity image supplies the replacement face. The final composited image feeds `DualIdentityScore`.

The identity-i2i template uses the installed Flux.2 PuLID path. The base image supplies scene/composition and the identity image supplies facial identity. The decoded result feeds the same scorer.

Both templates use `input/wan_q4_placeholder.ppm` as a safe loader default, share stable role titles, expose the focused sweep inputs, and contain notes explaining mode semantics. A deterministic builder and semantic workflow tests prevent node IDs, titles, links, or patch roles from drifting.

## Testing and Validation

Python unit tests cover dual scoring, missing-face behavior, mode ranking, canonical hashes, stage expansion, limits, state transitions, resume semantics, ratings, estimates, and route payload validation. JavaScript tests exercise setup validation, run-count rendering, queue sequencing, resume, gallery sorting/filtering, and rating updates with a minimal DOM harness.

Workflow contract tests parse both editor JSON files, validate link integrity and required node roles, assert loader defaults resolve against the main runtime base, and ensure both final outputs feed `DualIdentityScore`.

Runtime validation starts an isolated server from the worktree so the branch custom node remains authoritative. A temporary extra-model-path configuration points at the main checkout's installed models, the main input directory supplies authorized ephemeral smoke inputs, and isolated temporary user/output directories keep validation data separate. The smoke checks live `/object_info`, both workflow contracts, `/identity-lab` routes, one deliberately low-cost Flux run, score data in prompt history, SQLite completion, the recorded PNG, and gallery retrieval. Repository GitHub CI remains the only required full-suite run for the final PR head.

## Risks

- ComfyUI frontend APIs can change. The panel will use the same `app.registerExtension`, `api.fetchApi`, and `/prompt` patterns already used by local extensions and will keep queue logic isolated.
- Face selection can choose the wrong person in multi-face images. Version one keeps explicit `largest` and `highest_confidence` choices and surfaces detection status; per-face manual selection is deferred.
- Model and LoRA compatibility is not inferable perfectly from filenames. The Flux adapter limits candidates to the configured local family and validates existence, while runtime incompatibility becomes a recorded failed run.
- One hundred Flux runs can consume considerable time and disk. Staging, estimates, hard run caps, pause/resume, and explicit promotion constrain the cost.

## Decision Log

1. Use two explicit modes with mode-specific ranking.
2. Use a panel-driven runner and reusable workflow templates.
3. Use staged rather than Cartesian search.
4. Keep a ranked visual gallery with manual ratings.
5. Keep all processing and persistence local.
6. Persist resumable, deduplicated runs in SQLite.
7. Sweep only the focused parameter surface.
8. Keep swap and i2i as separate templates.
9. Test LoRAs as singles, finalist pairs, and explicitly enabled triples.
10. Lock source images, prompt, and aligned seed sets per experiment.
11. Consolidate both comparisons into one visible dual-score node.
12. Retain outputs by default and require explicit archive/delete actions.
13. Extend the existing identity-score extension instead of creating a second overlapping custom node.
14. Use human-controlled stage promotion; automatic identity ranking never decides image quality.
