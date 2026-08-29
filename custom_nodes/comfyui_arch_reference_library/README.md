# Arch Reference Library

A fully local ComfyUI library for reusable subject/character and
environment/location references. It keeps managed image copies, editable tags,
prompt additions, LoRA profiles, and four locked reference slots available to
any workflow that has been wired to the selector nodes once.

## Privacy and storage

All personal data stays under ComfyUI's ignored user-data directory:

```text
user/reference_library/
├── catalog.sqlite3
├── images/
└── thumbnails/
```

- Imports copy the selected image. The original is never moved or modified.
- Identical content is stored once and may belong to multiple collections.
- Thumbnails are generated locally and can be rebuilt from managed originals.
- No cloud API, telemetry, upload service, or SmartGallery process is used.
- The repository ignores this entire data tree. Never force-add its database,
  images, thumbnails, WAL files, or SHM files to git.

## Sidebar workflow

Open **Reference Library** in the ComfyUI sidebar.

1. Choose **Subjects / Characters** or **Environments / Locations**.
2. Create a collection and make it active.
3. Select local image files and click **Import images**.
4. Create grouped tags such as `framing: portrait`, `framing: full body`, or
   `gaze: not looking at camera`.
5. Select thumbnails and use **Apply tag** or **Remove tag** for batch edits.
6. For each tag, choose `must have`, `may have`, `exclude`, or `not filtered`.
7. Pin exact images to any of the four slots, or choose a random, seeded, or
   sequential policy and click **Reroll references**.
8. Edit the Default profile or add model-family profiles such as Flux, Qwen, or
   Wan. Each profile can add positive/negative prompt text and an ordered stack
   of locally installed LoRAs.

Selections stay locked in the local catalog until they are explicitly changed
or rerolled. Switching the active Subject or Environment updates every selector
node that is in `follow_sidebar` mode.

## Workflow nodes

### arch-Subject Reference Selector

Resolves the active subject or a pinned subject/profile. It returns:

- `reference_1` through `reference_4` as independent `IMAGE` outputs;
- `reference_images` as a list-valued `IMAGE` output that preserves each
  source's dimensions;
- positive and negative prompt additions;
- an ordered LoRA manifest;
- collection, profile, selection, reference, and tag metadata;
- the stable collection ID.

### arch-Environment Reference Selector

Has the same interface, but accepts only environment collections.

### arch-Apply Reference Profile LoRAs

Connect the selector's `lora_manifest_json` plus the workflow's `MODEL` and
`CLIP`. Enabled LoRAs are resolved only through ComfyUI's local LoRA catalog and
applied in profile order with their separate model and CLIP strengths.

`strict_missing=true` stops execution if an enabled LoRA is not installed.
Turn it off only when the workflow should skip missing entries and report them
in `applied_metadata_json`.

## One-time workflow integration

Existing workflows are not rewritten automatically because reference and
conditioning interfaces differ across node packs. Add the appropriate selector
once, then connect whichever of its image, prompt, and LoRA outputs that workflow
uses. New selectors follow the sidebar by default; use **Pin current sidebar
selection** on the node when a saved workflow must remain tied to stable local
collection and profile IDs.

Prompt additions are plain strings. They can be concatenated with an existing
prompt, passed into a prompt builder, or ignored. Likewise, the LoRA manifest is
available even when a workflow applies LoRAs through another advanced loader.

## Safe removal and deletion

- **Remove from collection** only unlinks the managed image from that
  collection. It does not delete the file.
- A shared managed image cannot be permanently deleted while any collection
  still uses it.
- Unlinked managed images appear under **Unassigned managed images**. Permanent
  deletion there requires a separate confirmation and removes only the managed
  copy and cached thumbnail—not the original import source.
- Deleting a collection unlinks its images but keeps their managed copies in the
  unassigned area.

## Backup and restore

Stop ComfyUI before copying or restoring `user/reference_library/`, then back up
the entire directory together. Keeping the SQLite database and content-addressed
image tree together preserves collection memberships and profiles. Thumbnails
may be omitted from a backup because they regenerate when requested.

Do not edit the SQLite database directly while ComfyUI is running.

## Supported media and limits

The first release supports still PNG, JPEG, WebP, BMP, TIFF, and non-animated
GIF files. Animated images and video are rejected. Each import is capped at 256
MiB by the package; the surrounding ComfyUI server may have a lower request
limit.

Tags are manual and batch-driven. Automatic vision tagging and an optional
SmartGallery **Add to Reference Library** action are intentionally deferred.
