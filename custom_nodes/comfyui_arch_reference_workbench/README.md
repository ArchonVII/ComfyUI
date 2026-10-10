# Arch Reference Workbench

Five local nodes under **Arch / Reference Workbench** complement Random Reference
Source, Reference Library and Identity Score. No models are downloaded by this pack.

Start with `examples/Reference Workbench - Synthetic Demo.json`. It needs no image
files or generation model: two colored test images exercise Prepare, Contact Sheet,
Review and Run Record, with an empty Cast connected for metadata. The demo is also
installed as a new workflow on the 8192 instance. Replace Empty Image with your
source or generation output, then choose and enable Cast favorites as needed.

| Node | Purpose and wiring |
| --- | --- |
| arch-Reference Cast | Choose a saved source favorite for subject, clothing, environment and style. Enable each needed lane; lock preserves its selected path across runs and saved workflows. Unlocked lanes reroll. Connect `metadata_json` to Contact Sheet `manifest` and Run Record `reference_metadata_json`. |
| arch-Reference Contact Sheet | Connect role images (or an arbitrary image batch). Captions show roles, filenames and batch positions. Connect to Preview Image. |
| arch-Reference Prepare | Connect an image, choose full, subject or face, and target size. Full fits the whole image; subject needs a foreground mask; face uses the installed Identity Score YuNet helper/model. `crop_preview` shows the original crop boundary; `image` and `mask` are transformed together. |
| arch-Result Review | Connect reference and generated images. Optionally connect Identity Score `report_json` and run settings. After execution, compare all batch members, Keep/Reject the review, or save result copies to an existing subject/environment library collection. |
| arch-Run Record | Connect final images and actual reference metadata. Supply/convert prompt, seed, model and LoRA fields to inputs from the same sources driving generation. Saves new PNG copies and one JSON sidecar per run. |

Cast defaults all lanes off. An inactive/unassigned lane returns `None`; leave it
disconnected from consumers requiring IMAGE, or use a compatible lazy switch.
Contact Sheet accepts inactive lanes. First locked selections use the fixed Cast
seed, so queued runs agree before the first result reaches the browser. Changing
a favorite or unlocking clears that lane's retained path. Cast choices refresh when
groups are saved, renamed or deleted; a rename clears the affected lock. A missing locked file
raises an error rather than silently changing identity. Cast selects references;
connect its images to conditioning nodes appropriate for your generation model.

Prepare preserves aspect ratio with padding. Its output mask is foreground/coverage
(white means included), not an automatically inverted inpainting mask. Subject mode
does not segment automatically. Face mode reuses the local Arch Image Tools YuNet
detector, or the bounded Identity Score helper when installed. It reports missing local dependencies or no
face; full and subject modes remain usable without the detector.

Review copies and classifications live in the configured user directory under
`reference_reviews/<UUID>`. Keep/Reject applies to the complete review batch and
never deletes an original. Save to Library explicitly chooses all results or one.
Run Record writes to the configured output directory under
`reference_runs/<UUID>/<prefix>.json` with PNGs alongside. Its JSON distinguishes
supplied settings from the recorded API graph; settings are not inferred from image
pixels. Records can contain private local paths and prompts: keep them local.
Normal Comfy caching can reuse an unchanged output; change inputs to make a new run.

## Source integration

Random Reference Source adds `shuffle_cycle`: its 1-based index visits every member
of the current sorted pool once per cycle. Increment the index after generation
to traverse the shuffled pool. Preview uses the same choice. A changed pool changes
the sequence; adjacent cycles may share the same boundary image.

## Focused verification

Run the workbench tests with pytest and `--import-mode=importlib`. Tests use synthetic
images, exercise batch handling, transformed masks, lock persistence, review API
confinement and local records. Runtime verification also requires registering all
five nodes and exercising the UI in the installed Comfy frontend.
