# Track B buildout — execution record (2026-08-25)

Owner authorized the buildout ("Build it out, i want this landed", 2026-08-25).
Hard rules from `docs/local-agent-handoff.md` §2 held throughout: no workflow
file modified, moved or deleted; no PR; pushes only to
`claude/workflow-addons-research-h8v30e`.

## Installed (B4)

`tools/workflow_library/install_addons.ps1 -ComfyRoot C:\tools\image\ComfyUI`
cloned the three researched addons into `custom_nodes` (none has a
requirements.txt, so no pip installs):

| addon | version installed | registers |
| --- | --- | --- |
| comfyui-adaptiveprompts | latest (shallow clone 2026-08-25) | 24 Python nodes incl. `PromptGenerator` |
| ComfyUI-Autocomplete-Plus | 1.11.0 (`9cfd2ac`) | JS only; self-downloaded danbooru CSVs on first boot |
| comfyui-g-workflows | latest (shallow clone 2026-08-25) | JS panel + server routes |

arch-pt wildcards (216 files / 1,192 phrases) were exported to
`C:\tools\image\ComfyUI\wildcards\archpt` and copied into
`custom_nodes\comfyui-adaptiveprompts\wildcards\archpt` by the installer.

The installer's pip step was fixed first to target the ComfyUI venv
interpreter instead of PATH `python` (commit on this branch).

## Verified (B5)

- Server restart: all packs imported, zero IMPORT FAILED.
- `/object_info`: 24 adaptiveprompts node types present (2,735 total).
- `/extensions`: 12 JS files served from the three packs.
- End-to-end scratch API workflow (`PromptGenerator` → `PreviewAny`, POSTed to
  `/prompt`): `__archpt/flux/camera/focal_length__` resolves to in-catalog
  phrases deterministically per seed; `__archpt/flux/identity/hair_color^hair__`
  + `__^hair__` return the identical value in both positions (seeds 0/7/42).
- g-workflows UI: panel opens (separate window), lists 655 workflows, loads the
  `.tags.txt` sidecars (134 tags), and filtering by a `dup:` tag isolates a
  duplicate family (25 members verified).

## Open finding: Autocomplete-Plus vs Vue nodes

ComfyUI frontend 1.45.19 with `Comfy.VueNodes.Enabled: true` (the current
user setting) renders node text widgets WITHOUT the legacy
`.comfy-multiline-input` class, and Autocomplete-Plus 1.11.0 attaches only via
the legacy `ComfyWidgets.STRING` override plus a `.comfy-multiline-input`
MutationObserver (`web/js/main.js`), so **autocomplete does not attach at all
while Vue nodes are on**. Empirically verified both ways on 2026-08-25:
with the setting flipped to `false` (temporarily, then restored), the danbooru
dropdown appears when typing in a CLIPTextEncode widget.

**Owner decision needed** — either:
1. Settings → search "Vue nodes" → disable (`Comfy.VueNodes.Enabled: false` in
   `user\default\comfy.settings.json`) — restores autocomplete, reverts to the
   legacy node look; or
2. keep Vue nodes and wait for upstream Autocomplete-Plus support
   (https://github.com/newtextdoc1111/ComfyUI-Autocomplete-Plus).

B6 (ComfyUI-Custom-Scripts conflict) is moot: that pack is not installed.

## SmartGallery (B1)

Portable v2.22.1 downloaded from
https://github.com/biagiomaf/smart-comfyui-gallery and unpacked to
`C:\tools\image\SmartGallery\`. `run_smartgallery.bat` is configured:
output `C:/tools/image/ComfyUI/output`, input `C:/tools/image/ComfyUI/input`,
cache `C:/tools/image/SmartGallery/cache` (outside the library),
ffprobe `C:/ffmpeg/bin/ffprobe.exe`, port 8189.
First index: 643 files scanned, 631 hash-indexed, 3.4 s. Workflow badges show
on PNG cards. Human checks remaining: judge results; workflow-recovery test
(select an image, `W`/`C`, paste onto ComfyUI canvas).

## Still owner-gated

- **B2 duplicate deletion** — decision list in
  `docs/workflow-duplicate-triage.md`; hard rule 2 forbids agent deletion.
- **B3 tag vocabulary** — current rules live in
  `tools/workflow_library/tagging.py`; veto/adjust freely.
- Browser hard-refresh (`Ctrl+F5`) of any open ComfyUI tab to pick up the new
  frontend extensions.
