# Task Plan: Civitai Collection Ingestor

## Goal
Build a ComfyUI custom node extension that ingests a Civitai collection URL, stores valuable image/model/prompt/settings metadata, checks required resources against local model folders, and exposes a first UI slice for review and downloads.

## Current Phase
1. [completed] Document current DB/API findings and implementation plan
2. [completed] Add Civitai importer backend with SQLite persistence and API client
3. [completed] Add local model matching and download status primitives
4. [completed] Add ComfyUI frontend panel for collection ingest and status
5. [completed] Write focused tests for ingestion, matching, and storage behavior
6. [completed] Run verification and report limitations
7. [completed] Add local image caching and cached-image serving
8. [completed] Add read-only workflow draft generation and panel actions
9. [completed] Add queue-draft UI path gated by runnable/missing-model status
10. [completed] Harden target-folder mapping for VAE-looking files

## Decisions
- Use a custom-node-owned SQLite database under ComfyUI `user/__civitai_ingestor/civitai_ingestor.sqlite3`, not ComfyUI core Alembic migrations.
- Use Civitai `/api/v1/images?collectionId=...&withMeta=true` plus cursor pagination for collection ingestion.
- Enrich required resources through `/api/v1/model-versions/{id}` and store raw JSON snapshots as well as normalized fields.
- Reuse local model folder conventions from `folder_paths.py` and the existing `comfyui_smart_model_loader` scan shape where practical.

## Acceptance Slice
- User can enter `https://civitai.red/collections/8081491` or `https://civitai.com/collections/8081491`.
- Backend ingests the collection and returns counts, image rows, resource rows, and local missing/present status.
- UI shows progress/status text and a table/list of images/resources.
- Model download endpoints exist with progress status, storage check, and sequential queue behavior.
- Cached collection images can be stored under the ingestor user directory and served back to the panel.
- Workflow drafts can be saved as read-only JSON and queued only when enough metadata and local models are available.
- Exact generation remains gated by available metadata and model availability.

## Verification
- `python -m pytest custom_nodes/comfyui_civitai_ingestor/tests -q` passed.
- `python -m compileall -q custom_nodes/comfyui_civitai_ingestor` passed.
- `node --check custom_nodes/comfyui_civitai_ingestor/web/civitai_ingestor.js` passed.
- Live ComfyUI route smoke passed against `http://127.0.0.1:8188/civitai-ingestor/collections/8081491`.
- Live ingest smoke passed against `https://civitai.red/collections/8081491` with `max_items = 1`.
- Second-slice verification: 15 focused pytest tests passed, compile passed, and JS syntax passed.
- Live cache smoke cached 5 images, then skipped 5 already-cached images on repeat.
- Live draft smoke saved `C:\tools\image\ComfyUI\user\__civitai_ingestor\workflow_drafts\collection-8081491\image-16382509.workflow-draft.json`.
