# Findings: Civitai Collection Ingestor

## ComfyUI Persistence
- ComfyUI already has `app.database` with SQLite via SQLAlchemy/Alembic. Default URL resolves to `user/comfyui.db`.
- Existing core schema is for assets, asset references, tags, and typed metadata. `app/database/models.py` still has a TODO for general models.
- User settings are still stored in `user/default/comfy.settings.json`.
- Best fit for this custom feature is a custom-node-owned SQLite database in a system user folder so we avoid core migration coupling.
- Implemented database path: `C:\tools\image\ComfyUI\user\__civitai_ingestor\civitai_ingestor.sqlite3`.

## Local Model Catalog
- Existing `custom_nodes/comfyui_smart_model_loader` scans `diffusion_models`, `checkpoints`, `text_encoders`, `vae`, and `loras`.
- `folder_paths.py` maps `loras` to `models/loras`, `checkpoints` to `models/checkpoints`, `vae` to `models/vae`, and `diffusion_models` to `models/unet` plus `models/diffusion_models`.
- Current local matching uses exact filename/basename across relevant ComfyUI model folders and records Civitai SHA256/AutoV2 hashes for future hard matching.
- A future hash index would improve confidence but should be opt-in or cached because hashing multi-GB models is expensive.
- Civitai may label `sdxl_vae.safetensors` as a checkpoint resource. The ingestor now routes tokenized `vae` filenames to `models/vae` but keeps checkpoint names like `noVAE` in `models/checkpoints`.

## Civitai API
- Official docs moved to `developer.civitai.com`; the docs source is `civitai/civitai-developer-docs`.
- `/api/v1/images` supports `withMeta=true`, `imageId`, `postId`, `modelVersionId`, cursor pagination, and returns free-form `meta` when available.
- `collectionId` is accepted by the live `/api/v1/images` endpoint even though it is not listed in the current images docs.
- `/api/v1/model-versions/{id}` returns version metadata, files, hashes, trained words, AIR, and download URLs.
- `civitai.red` page fetches hit Cloudflare challenge from non-browser clients, but the collection ID can be normalized and queried through `civitai.com/api/v1/images`.
- `civitai.red/api/v1/images` also worked in live smoke testing when using the API endpoint directly.

## Data Limitations
- Some image records have `meta: null`; these cannot become exact workflows without user-provided workflow details or external image metadata.
- Civitai metadata is free-form across generators. Store raw meta and make workflow reconstruction best-effort.
- Workflow drafts are saved as read-only JSON under `user/__civitai_ingestor/workflow_drafts`.
- The panel can queue a generated ComfyUI API prompt through `/prompt`, but only when the draft is marked runnable.
