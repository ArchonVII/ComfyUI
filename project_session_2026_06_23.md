---
type: project
date: 2026-06-23
branch: agent/codex/no-issue-civitai-collection-ingestor
---

# Project Session: Civitai Collection Ingestor

## Completed
- Added `custom_nodes/comfyui_civitai_ingestor` as a ComfyUI custom extension.
- Implemented Civitai collection ingestion from URLs like `https://civitai.red/collections/8081491`.
- Added custom SQLite persistence at `C:\tools\image\ComfyUI\user\__civitai_ingestor\civitai_ingestor.sqlite3`.
- Stores image metadata, prompts/settings where exposed, raw Civitai JSON, model-version data, files, hashes, download URLs, trained words, local status, and image-resource links.
- Added local model matching across ComfyUI model folders and sequential download jobs with progress and disk-space checks.
- Added local image caching and cached-image serving.
- Added workflow draft generation, read-only draft JSON saving, and panel actions for `Cache images`, `Save draft`, and `Queue draft`.
- Hardened VAE/checkpoint routing so tokenized `vae` filenames go to `models/vae`, while `noVAE` checkpoint names stay in `models/checkpoints`.
- Updated `task_plan.md`, `findings.md`, `progress.md`, and `.claude/napkin.md` with current state and findings.

## In Progress
- Work is uncommitted on branch `agent/codex/no-issue-civitai-collection-ingestor`.
- ComfyUI was left running at `http://127.0.0.1:8188`.
- Example cached images live under `C:\tools\image\ComfyUI\user\__civitai_ingestor\images\collection-8081491`.
- Example workflow draft saved at `C:\tools\image\ComfyUI\user\__civitai_ingestor\workflow_drafts\collection-8081491\image-16382509.workflow-draft.json`.
- Current collection summary: 5 images, 3 with metadata, 11 required files, 11 missing locally.

## Next
- Add a user confirmation screen for model downloads before starting large files.
- Add optional hash indexing for local models so matches can be verified by SHA256/AutoV2 instead of filename only.
- Improve workflow draft reconstruction for VAEs, ControlNet, alternate schedulers, hires/upscale, and generator-specific metadata.
- Add workflow copy/edit/save UX after a draft is generated.
- Commit selectively if the user wants this saved in Git; do not stage unrelated pre-existing local changes.

## Context
- Civitai collection page HTML may hit Cloudflare from plain HTTP clients, but the API endpoint works: `/api/v1/images?collectionId=8081491&withMeta=true`.
- Some Civitai image rows have `meta: null`; exact workflow reconstruction is impossible for those without user-provided workflow data.
- Some Civitai resource labels are unreliable; target folder should consider file names as well as model type.
- Existing dirty/untracked workspace entries outside this lane were preserved.

