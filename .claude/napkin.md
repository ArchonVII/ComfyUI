# Napkin Runbook

## Curation Rules
- Re-prioritize on every read.
- Keep recurring, high-value notes only.
- Max 10 items per category.
- Each item includes date + "Do instead".

## Execution & Validation (Highest Priority)
1. **[2026-06-14] Local ComfyUI checkout lives below workspace root**
   Do instead: run repo commands from `C:\tools\image\ComfyUI`, not `C:\tools\image`.

## Shell & Command Reliability
1. **[2026-06-14] Custom node tests import from `custom_nodes`**
   Do instead: run focused pytest commands from `C:\tools\image\ComfyUI` with tests under the specific custom node folder.

## Domain Behavior Guardrails
1. **[2026-06-23] ComfyUI-side agent workflows live under the user workflow tree**
   Do instead: place local agent workflow assets in `C:\tools\image\ComfyUI\user\default\workflows\agent`, and use editor-format JSON when the file should open cleanly in the ComfyUI workflow browser.
2. **[2026-06-23] Civitai can mislabel VAE files as checkpoints**
   Do instead: route tokenized `vae` filenames to `models/vae`, keep `noVAE` checkpoint names in `models/checkpoints`, and do not feed VAE-targeted resources into `CheckpointLoaderSimple`.
3. **[2026-06-14] LoRA mismatch handling currently detects failures after selection**
   Do instead: keep proactive compatibility selection separate from session-watchdog error classification unless intentionally integrating them.
4. **[2026-06-14] Comfy canvas wheel/zoom can be reset with two settings**
   Do instead: if one mouse-wheel tick feels like a huge jump, check `Comfy.Graph.ZoomSpeed` and `Comfy.Canvas.MouseWheelScroll` via `http://127.0.0.1:8188/settings` or `C:\tools\image\ComfyUI\user\default\comfy.settings.json`; sane values are `1.1` and `panning`.
5. **[2026-06-14] Running ComfyUI does not pick up newly added custom-node routes**
   Do instead: restart the existing ComfyUI server after adding a new custom node with backend routes before testing its HTTP endpoint.

## User Directives
1. **[2026-06-14] Preserve prior local agent work**
   Do instead: avoid overwriting untracked custom nodes and local files unless the user explicitly asks for that scope.
