# Progress: Civitai Collection Ingestor

## 2026-06-23
- Read ComfyUI DB, app settings, model folder code, and existing smart model loader.
- Probed Civitai collection/image/model-version APIs.
- Confirmed `collectionId=8081491&withMeta=true` returns collection images and generation metadata when available.
- Created feature branch `agent/codex/no-issue-civitai-collection-ingestor`.
- Added `custom_nodes/comfyui_civitai_ingestor` with SQLite persistence, Civitai API ingestion, model-version enrichment, local model matching, sequential download jobs, and a ComfyUI frontend panel.
- Added focused tests for URL parsing, image/resource extraction, SQLite storage, ingest orchestration, and local model matching.
- Verified `python -m pytest custom_nodes/comfyui_civitai_ingestor/tests -q` with 8 passing tests.
- Verified `python -m compileall -q custom_nodes/comfyui_civitai_ingestor`.
- Verified `node --check custom_nodes/comfyui_civitai_ingestor/web/civitai_ingestor.js`.
- Started ComfyUI locally at `http://127.0.0.1:8188` and verified the extension route and JavaScript asset.
- Live ingest smoke against `https://civitai.red/collections/8081491` with `max_items = 1` fetched 1 image and 5 referenced model versions.
- Continued the implementation with image caching, cached-image serving, workflow draft generation, read-only draft files, and panel actions for `Cache images`, `Save draft`, and `Queue draft`.
- Added tests for image caching, workflow draft generation, read-only draft persistence, VAE target-folder routing, and `noVAE` checkpoint guardrails.
- Verified `python -m pytest custom_nodes/comfyui_civitai_ingestor/tests -q` with 15 passing tests.
- Verified `python -m compileall -q custom_nodes/comfyui_civitai_ingestor`.
- Verified `node --check custom_nodes/comfyui_civitai_ingestor/web/civitai_ingestor.js`.
- Reingested `https://civitai.red/collections/8081491` with `max_items = 5`; refreshed 5 images and 9 model versions.
- Cached all 5 collection images locally, then verified the repeat cache run skipped 5 already-cached images.
- Verified cached image route `http://127.0.0.1:8188/civitai-ingestor/images/16382509/cached`.
- Saved a read-only draft at `C:\tools\image\ComfyUI\user\__civitai_ingestor\workflow_drafts\collection-8081491\image-16382509.workflow-draft.json`.

## Errors
- `https://civitai.red/collections/8081491` returns a Cloudflare browser challenge to plain `Invoke-WebRequest`; use `civitai.com` API normalization instead.
- `/api/v1/collections/8081491` and `/api/v1/collections/8081491/items` return HTML 404 pages; use `/api/v1/images?collectionId=...`.
- Civitai can classify VAE-looking files like `sdxl_vae.safetensors` as `Checkpoint`; target-folder mapping now uses filename heuristics while preserving `noVAE` checkpoint names.
- Exact workflow/run reconstruction is still gated by image metadata and local model availability. Queueing is wired, but drafts with missing models are intentionally not queued.
