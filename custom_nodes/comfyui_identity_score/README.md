# ComfyUI Identity Score and Identity Lab

This local ComfyUI extension provides two related tools:

- `OpenCV Identity Score`, the compatibility node for one reference-to-output comparison.
- `Dual Identity Score`, which compares a generated image with both the identity reference and the base image and shows both scores directly on the executed node.
- `Identity Lab`, a sidebar panel for bounded, resumable Flux/Klein 9B checkpoint, LoRA, seed, and sampling experiments.

Face detection uses OpenCV YuNet. Face embeddings and cosine similarity use OpenCV SFace. No cloud service is involved.

## Safety and interpretation

Use only images of people who authorized this local processing. The extension compares supplied faces; it is not intended to identify unknown people.

All source images, generated images, experiment rows, ratings, and notes remain in the configured ComfyUI directories. The HTTP routes are meant for the same local ComfyUI session and do not add authentication or make a server safe to expose publicly.

Identity similarity is a comparative debugging and ranking signal, not proof of identity and not a measure of image quality. Lighting, crop, pose, occlusion, multiple faces, and detector choice can move a score. Treat the gallery and your visual review as authoritative.

## Install and restart

The scorer models normally live in this extension's `models/` directory:

- `face_detection_yunet_2023mar.onnx`
- `face_recognition_sface_2021dec.onnx`

If either file is missing, run:

```powershell
powershell -ExecutionPolicy Bypass -File C:\tools\image\ComfyUI\custom_nodes\comfyui_identity_score\scripts\download_opencv_models.ps1
```

Restart the ComfyUI server after installing or updating this extension. A browser refresh alone cannot load the Python node, SQLite service, or `/identity-lab` routes. After the server is back, reload the ComfyUI page so the Identity Lab sidebar extension is current too.

## Score one output manually

Add `Dual Identity Score` from `arch-image/identity`, then connect:

1. `base_image`: the original image that supplies composition, pose, and scene.
2. `reference_image`: the image that supplies the intended face identity.
3. `generated_image`: the final decoded or composited result.

Set `experiment_mode` to:

- `face_swap` to rank by reference-to-output similarity.
- `identity_i2i` to rank by base-to-output similarity.

The executed node displays reference, base, and active cosine similarities; whether every face was detected; whether the active score met the configured same-identity threshold; and whether the result is rankable. It also returns the individual scores and booleans, a JSON report, and `EXTRA_METADATA`.

A result is rankable only when the base, reference, and generated faces were all detected. A missing face is reported as unavailable rather than as a meaningful zero. Adjust `face_selection` between `largest` and `highest_confidence` when an image contains more than one face.

Leave `experiment_id` and `run_id` unconnected for ordinary manual use. When both IDs are supplied by Identity Lab, the node saves the exact result and completes that run in SQLite.

`OpenCV Identity Score` remains available for older workflows. Its optional catalog resolves below the ComfyUI input directory: `subject` scores one subject folder, while `all_subjects` treats each immediate subfolder as a subject.

## Load an experiment template

Use one of the two editor workflows under `user/default/workflows/agent`:

- `39 - Flux 9B Identity Lab - Face Swap.json`
- `40 - Flux 9B Identity Lab - Identity I2I.json`

The templates default both image loaders to `wan_q4_placeholder.ppm`. Replace both placeholders before queueing:

- Face swap: the base image supplies body, pose, composition, environment, and the target head location; the reference image supplies the replacement identity. The graph detects and refines both heads, generates the target crop, and composites it back into the base.
- Identity i2i: the base image supplies composition and the starting latent; the reference image drives the Flux.2 PuLID identity conditioning.

Do not rename or duplicate nodes whose titles begin with `IDENTITY_LAB_`. Those stable roles are the panel's validated patch contract for image loaders, checkpoint, three LoRA slots, sampler, pixel budget, and scorer. The panel rejects an incompatible or ambiguous loaded workflow before queueing.

The templates intentionally expose no more than three LoRA slots. They include ordinary Save and Preview nodes as well as the scorer, so they remain useful outside the panel.

## Run a staged experiment

1. Load the template for the intended mode and choose the two images in the graph.
2. Open the flask-shaped `Identity Lab` tab in the ComfyUI sidebar.
3. Choose the matching mode, experiment name, checkpoints, seeds, sampler, scheduler, steps, guidance/CFG, denoise, and pixel budget. Select up to three candidate LoRAs and their strengths.
4. Wait for the backend estimate to refresh. It shows run count, approximate duration, and estimated storage. Launch is blocked above 100 runs or when estimated output exceeds free space.
5. Select `Create & run one at a time`.

The first stage is the checkpoint baseline, aligned across the same seed set. Runs are submitted serially through ComfyUI's normal queue. `Pause after current` stops new submissions but does not interrupt the prompt already using the GPU.

Use the result-card checkboxes to select finalists. Then choose and explicitly preview and confirm one of:

- LoRA singles
- LoRA pairs
- LoRA triples
- Focused refine

Triples are never planned implicitly. Focused refine applies the selected steps, CFG, denoise, pixel budget, sampler, and scheduler to promoted finalists. Promotion is always a human decision; the active identity score never silently advances a run.

## Resume after a restart or interruption

Experiments persist independently of the browser page:

1. Restart ComfyUI and reopen Identity Lab.
2. Select the experiment from `Load active experiment`.
3. Select `Resume planned or confirmed-stale work`.

The panel reloads the saved API-format workflow and setup. Completed combinations remain immutable and are not queued twice. Planned work continues. A stale queued/running row is reset only after the service confirms that its run ID is absent from ComfyUI's active queue and reconciles terminal history. Failed and non-rankable results remain visible for diagnosis.

## Review the gallery

Each result card shows the local output, both identity similarities, the active score, rankability and detection status, checkpoint, LoRA stack, seed, sampling settings, and runtime.

The default sort is active score. Filters cover stage, checkpoint, LoRA, state, favorite, and 1–5 rating; alternative sorts use rating or newest completion. You can:

- set a 1–5 rating;
- favorite or unfavorite a run;
- use `Reject (1)` for a one-star non-favorite;
- add local review notes;
- select specific result cards for the next stage.

Manual review should consider likeness, artifacts, blending, composition, and overall quality together.

## Files and privacy

With the standard ComfyUI directories:

- SQLite: `<user-directory>/default/identity_lab/identity_lab.sqlite3`
- Recorded experiment result: `<output-directory>/identity_lab/results/<run-id>.png`
- Optional manual-score manifest: `<user-directory>/default/identity_score_runs/`

SQLite uses relative output paths and stores plans, state, scalar score reports, ratings, favorites, and notes. It does not store image bytes or face embeddings. The result PNG carries normal ComfyUI prompt metadata when that metadata is available.

Changing `--user-directory` or `--output-directory` moves these locations. Back up the database and `identity_lab/results` together if you want a portable experiment history.

## Archive and delete

`Archive` hides an inactive experiment from the default selector and retains its rows and every output. It is allowed only after queued/running work has quiesced; planned rows become archived.

Deletion is separate and irreversible:

1. Load the archived experiment by enabling `Include archived experiments`.
2. Select `Preview deletion`.
3. Review the exact run IDs and result files.
4. Type the displayed `DELETE <experiment-id>` confirmation exactly.
5. Select `Delete archived experiment`.

The preview is snapshot-token protected. If the rows or files change, request a new preview. The service quarantines only the previewed result files while removing the corresponding SQLite rows and restores them if the database operation fails. A reported `recoverable trash` path means final file cleanup failed and needs manual local inspection.

There is no automatic retention cleanup.

## Current scope

The runner currently targets the local Flux/Klein 9B model family. Qwen and Z-Image-family execution adapters, automatic aesthetic scoring, arbitrary workflow input sweeping, multi-user or multi-GPU scheduling, and exhaustive Cartesian searches are deferred.
