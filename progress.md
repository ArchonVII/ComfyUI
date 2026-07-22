# Progress: Adaptive LTX and Wan I2V Workflows

## 2026-07-14

- Inspected all six existing LTX/Wan agent workflows and summarized their node graphs.
- Verified the protected master checkout has one unrelated modified workflow and left it untouched.
- Resolved live host, GPU, disk, node, model, branch, and server facts.
- Researched official Wan 2.2, LightX2V/Wan2.2-Lightning, NAG, Enhance-A-Video, RIFLEx, EasyCache, and LTX 2.3 sources.
- Confirmed the six-workflow implementation scope with the user.
- Attempted required issue gating; `https://github.com/ArchonVII/ComfyUI` has issues disabled.
- Created worktree `C:\tools\image\ComfyUI-worktrees\no-issue-wan-i2v-workflows` on branch `agent/codex/no-issue-wan-i2v-workflows` from fresh `fork/master`.
- Refreshed the canonical root planning files for this lane.
- Confirmed the target workflow directory is ignored by default and the existing weak workflows are local-only assets; the branch will force-add only the six scoped replacements.
- Confirmed `C:\tools\image\ComfyUI\input\example.png` exists as a stable loader default.
- Added deterministic workflow generation for three adaptive LTX 0.9.8 paths and three adaptive Wan 2.2 GGUF paths.
- Added paired high/low LightX2V four-step LoRAs to the Wan draft graph and 40-step no-LoRA schedules to the Wan quality graphs.
- Added bypassed EasyCache, Enhance-A-Video, RIFLEx, and NAG chains to both Wan experts, with safe usage notes in each workflow.
- Started isolated ComfyUI validation at `http://127.0.0.1:8190/` and checked every executable node/input against its live registry.
- Ran a real portrait through adaptive sizing: `2133x4096` became model-safe `480x896` at the 0.40 MP policy.
- Executed the complete reduced Wan fast path and visually inspected its middle frame.

## Verification Log

- RED confirmed: `C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest tests\workflows\test_adaptive_video_workflows.py -q` produced 24 expected missing-workflow failures and 1 passing retirement guard.
- GREEN: `$env:COMFY_RUNTIME_BASE='C:\tools\image\ComfyUI'; C:\tools\image\ComfyUI\venv\Scripts\python.exe -m pytest tests\workflows\test_adaptive_video_workflows.py -q` -> `28 passed in 0.09s`.
- Live schema: six graphs, 150 total nodes, no missing executable types, and no unknown executable inputs.
- Runtime prompt `b1dc40af-b950-453f-ad3f-b145d70c0e51` -> completed in 40.68 seconds with no node errors.
- Smoke artifact: `C:\tools\image\ComfyUI\output\agent\smoke\wan22-fast-9f_00001_.mp4` -> `224x224`, 9 frames, 24 fps, H.264, 13,996 bytes.
- Visual check: middle frame is coherent and preserves the source character/content.

## Current Step

- Review the scoped diff, rerun verification, then commit selectively and open the draft PR.
