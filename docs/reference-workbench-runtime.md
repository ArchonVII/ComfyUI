# Reference Workbench runtime maintenance

Deployment target: the separate ComfyUI instance on port 8192, installed at
`C:\tools\image\ComfyUI-v0.34.2-h3-test` (actual ComfyUI version 0.35.1).

The companion package is `custom_nodes/comfyui_arch_reference_workbench`.
Copy package Python/web files along with the updated Random Reference Source
package. Preserve each installation's favorites/config and library user data.
Restart through ComfyUI Manager only with an idle queue, then reload the frontend.

## Targeted startup repair, 2026-10-09

Installed **triton-windows==3.6.0.post26** in this runtime's `.venv`, matching
PyTorch **2.11.0+cu130** according to the Windows project's compatibility table:
https://github.com/triton-lang/triton-windows

Validated a JIT-compiled vector-add kernel on the RTX 5070 Ti and `pip check`.
This restores the dependency used by RMBG's bundled SAM3 segmentation module.
Core Comfy Kitchen may still report its Triton backend disabled; the enabled CUDA
backend is separate and no backend forcing is required.

In the installed RMBG pack, `models/modeling_florence2.py` used the deprecated
`timm.models.layers` first and the modern import as fallback. Changed that block to
`from timm.layers import DropPath, trunc_normal_`, supported by installed timm 1.0.30.
Original file retained under
`runtime/deployment-backups/reference-workbench-20261009/modeling_florence2.py`.
An RMBG update may supersede this small local patch; inspect before reapplying.

A warning-stack trace also identified installed GroundingDINO's
`models/GroundingDINO/backbone/swin_transformer.py`; this and its
`models/GroundingDINO/fuse_modules.py` now import their unchanged symbols from
`timm.layers`. Backups are `groundingdino_swin_transformer.py` and
`groundingdino_fuse_modules.py` in the same deployment-backup directory.
Dependency reinstallations can replace these two environment-local edits.

No Matrix sharing dependency, OpenGL accelerator, multi-GPU override or renderer
switch is needed for this work. SAM3 model inference is separate from dependency
and import validation; no model download was performed.
