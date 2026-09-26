# Preset Studio

A standalone, local browser workspace for composing character/reference presets,
prompt concepts and LoRAs, then submitting image or video API workflows to ComfyUI.
It uses Python's standard library and browser modules, with no install/build step.

## Start

From this checkout, with Python 3.10 or newer:

```powershell
python tools/preset_studio/service.py --runtime C:/tools/image/ComfyUI --port 8791
```

Open http://127.0.0.1:8791/. For a hidden, persistent Windows process:

```powershell
./tools/preset_studio/launch.ps1 -Runtime C:/tools/image/ComfyUI
```

The app runs independently of ComfyUI and remains useful for composing while
ComfyUI is stopped. Set its local ComfyUI address in **Local connection**. It
does not start, stop, restart, or clear the queue of that server.

## Use

1. Create a **Character** preset with identity text and reference images, or use
   **Import existing library** to copy a Reference Library collection/profile.
2. Create **Concept / style** presets with text and optional LoRA filenames and
   model/CLIP strengths. The included “Amateur iPhone photo 1” is text-only until
   you choose an installed LoRA in its editor; the app never guesses a model.
3. Select presets in composition order. Click reference thumbnails to select
   their slot order; selected images stay fixed across seed variations.
4. Import a saved API workflow from the runtime library or a JSON file. Studio
   copies it into its own private store. **Map fields** assigns positive/negative
   prompt fields, reference slots and seed fields. Unmapped fields retain their
   workflow values. Review suggestions, particularly multiple text encoders.
5. For preset LoRAs, explicitly choose the MODEL source and optionally its CLIP
   source. The app inserts the ordered stack after these outputs, rewiring their
   consumers in a graph copy. Model-only workflows can leave CLIP unmapped.
6. Review the assembled prompt and stack, then **Queue quick test** or 2–8 seed
   variations. Change a concept and queue another batch to compare results.
7. Results refresh while the tab is visible. **Restore as copy** restores the
   original preset and workflow snapshots; **Save run JSON** includes the exact
   submitted graph and configuration. A preview download uses reference names
   that become concrete after upload, so a run export is the reproducible artifact.

## Local data and boundaries

All mutable state, uploaded/copied references, run snapshots and logs live in
`<runtime>/user/preset_studio/`, already ignored by this fork. Imported reference
images are stable local copies; source files and saved workflows are untouched.
Back up that directory with the service stopped. Also retain ComfyUI's inputs,
outputs, models and custom nodes to reproduce completed runs. A browser draft
remembers the current selection; authoritative presets/workflows/runs are on disk.
Never commit private state or images. The service refuses nonlocal ComfyUI URLs,
redirects, cross-origin writes, and cloud API nodes advertised by ComfyUI.

The first version supports a single MODEL/CLIP insertion point per workflow.
Multi-model pipelines needing different LoRA stacks on different branches need
those branches prepared in the API workflow. A workflow must already implement
the intended image/video conditioning; Studio does not infer identity conditioning
from arbitrary graphs. Prompt fields replace their mapped original text.
Reference slots must match the selected image count. Matching types and installed
dropdown values are checked before submission; ComfyUI still owns full execution
validation and model-family compatibility.

Submission stops on the first error. Uncertain network outcomes are saved without
automatic retry. Check ComfyUI history before retrying such a run. The service is
single-process/single-owner; don't run multiple Studio processes against one state
directory. Images are limited to PNG/JPEG/WebP/BMP, 20 MB each. Runs are retained on
disk, with the latest 100 displayed. Collection imports use the Default profile
and up to 200 references. Source library changes do not silently alter imported
presets. No browser click-through or GPU generation is part of automated tests.

An optional, feature-detected WebMCP action stages an existing combination without
queueing. Unsupported browsers simply omit it. This optional integration has not
been exercised in a supported WebMCP browser context.

## Focused checks

```powershell
python -m unittest discover -s tools/preset_studio/tests -v
node --check tools/preset_studio/web/app.js
```

Tests cover composition, conflicts, nonmutating graph adaptation, local state,
cross-origin protection, stable references, real loopback HTTP submission against
a test backend, seed variations, uncertain outcomes, output history and snapshots.
