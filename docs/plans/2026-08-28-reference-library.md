# Local Subject and Environment Reference Library Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Build a fully local ComfyUI reference library that manages reusable subject and environment images, tags, prompt/LoRA profiles, locked selections, and workflow-facing selector nodes.

**Architecture:** Add a dedicated `comfyui_arch_reference_library` custom-node package. A transactional SQLite catalog under ignored ComfyUI user data owns metadata and content-addressed managed image copies; authenticated-to-the-local-Comfy-session HTTP routes power a custom sidebar, while model-agnostic selector nodes and a companion LoRA applicator expose the library to workflows.

**Tech Stack:** Python 3.12, stdlib `sqlite3`/`hashlib`/`pathlib`, Pillow, PyTorch, ComfyUI custom-node APIs, aiohttp routes, browser-native JavaScript and CSS, pytest, Node-based frontend contract tests.

**Plan Status:** Active until implementation closeout; update the Plan Closeout section before PR ready/merge.

---

## Approved product decisions

- Collections are either `subject` or `environment`, with separate workflow selectors over one shared catalog.
- Imports are local managed copies; originals are never moved or modified.
- A content hash deduplicates one managed image that can belong to multiple collections.
- Tags are manual-first, batch editable, grouped, and attached to image membership so their meaning can differ by collection.
- Filtering supports include-all, include-any, and exclude sets.
- Each collection keeps four locked slots. A slot can be pinned; reroll fills only automatic slots by random, seeded, or sequential policy.
- Each collection has a Default profile and optional model-family profiles with positive/negative prompt additions and ordered LoRA stacks.
- Selector nodes follow the sidebar's active collection by default or pin a stable collection/profile ID.
- A separate node applies the selected profile's LoRAs to `MODEL` and `CLIP`; selectors also expose the manifest for advanced workflows.
- Personal images, thumbnails, and SQLite data stay under the already ignored `user/reference_library/` tree.
- Existing workflow JSON files are never modified by this lane.

## Scope boundaries

- Still images only in v1.
- Manual and batch tags only; no vision model or automatic tagging dependency.
- Single local ComfyUI user/process; no remote synchronization or multi-user permissions.
- Existing workflows require one-time explicit node wiring.
- SmartGallery may later add an import action, but is not a runtime dependency or source of truth.

### Task 1: Package skeleton and catalog schema

**Files:**
- Modify: `.gitignore`
- Create: `custom_nodes/comfyui_arch_reference_library/__init__.py`
- Create: `custom_nodes/comfyui_arch_reference_library/store.py`
- Create: `custom_nodes/comfyui_arch_reference_library/tests/conftest.py`
- Create: `custom_nodes/comfyui_arch_reference_library/tests/test_store.py`

**Step 1: Write the failing schema and collection tests**

Create tests that instantiate `ReferenceLibraryStore(tmp_path / "catalog.sqlite3")` and assert:

```python
def test_new_store_creates_versioned_schema_and_default_settings(store):
    assert store.schema_version() == 1
    assert store.get_active("subject") is None
    assert store.get_active("environment") is None

def test_collection_names_are_unique_per_kind_and_default_profile_is_created(store):
    subject = store.create_collection("subject", "Alice")
    environment = store.create_collection("environment", "Alice")
    assert subject["id"] != environment["id"]
    assert store.list_profiles(subject["id"])[0]["name"] == "Default"
    with pytest.raises(ValueError, match="already exists"):
        store.create_collection("subject", " alice ")
```

Also cover canonical UUIDs, allowed collection kinds, rename/update, active selection, foreign keys, and connection-local `PRAGMA foreign_keys = ON`.

**Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest custom_nodes/comfyui_arch_reference_library/tests/test_store.py -q
```

Expected: collection fails because `comfyui_arch_reference_library.store` does not exist.

**Step 3: Implement the minimal versioned store**

Implement a store with one connection per operation, `sqlite3.Row`, WAL mode, busy timeout, foreign keys, schema version 1, and these tables:

```sql
collections(id, kind, name, name_key, description, created_at, updated_at)
images(id, sha256, relative_path, original_filename, media_type, width, height, created_at)
collection_images(collection_id, image_id, notes, position, created_at)
tags(id, name, name_key, group_name, created_at, updated_at)
collection_image_tags(collection_id, image_id, tag_id)
profiles(id, collection_id, name, name_key, model_family, positive_prompt, negative_prompt, created_at, updated_at)
profile_loras(id, profile_id, position, lora_name, strength_model, strength_clip, enabled)
selection_state(collection_id, policy, seed, cursor, reroll_count, include_all_json, include_any_json, exclude_json)
selection_slots(collection_id, slot, image_id, pinned)
settings(key, value_json)
```

Use parameterized SQL only. Validate names and IDs before writes, use case-folded uniqueness keys, and create Default profile plus empty selection state in the same transaction as a collection.

**Step 4: Run tests and verify GREEN**

Run the same focused command; expected: all store schema/collection tests pass.

**Step 5: Commit the slice**

Selectively stage `.gitignore`, package initialization, store, and its tests.

### Task 2: Managed imports, membership tags, filters, and selections

**Files:**
- Create: `custom_nodes/comfyui_arch_reference_library/service.py`
- Extend: `custom_nodes/comfyui_arch_reference_library/store.py`
- Create: `custom_nodes/comfyui_arch_reference_library/tests/test_service.py`
- Extend: `custom_nodes/comfyui_arch_reference_library/tests/test_store.py`

**Step 1: Write failing managed-import tests**

Cover:

```python
def test_import_copies_without_changing_source_and_deduplicates_content(service, png_file):
    original = png_file.read_bytes()
    first = service.import_image(collection_a, png_file.name, "image/png", original)
    second = service.import_image(collection_b, "renamed.png", "image/png", original)
    assert first["image"]["id"] == second["image"]["id"]
    assert png_file.read_bytes() == original
    assert service.managed_path(first["image"]).read_bytes() == original

def test_failed_decode_leaves_no_catalog_row_or_managed_file(service):
    with pytest.raises(ValueError, match="valid image"):
        service.import_image(collection_a, "bad.png", "image/png", b"not an image")
    assert service.store.list_images(collection_a) == []
    assert list(service.images_root.rglob("*.*")) == []
```

Also test maximum upload size, allowed still-image formats, EXIF-safe dimension inspection, atomic temp replacement, and path confinement.

**Step 2: Run focused tests and verify RED**

Expected: failure because `ReferenceLibraryService` and import methods are absent.

**Step 3: Implement imports and thumbnail generation**

- Stream or spool uploads to a temporary file under the managed root while calculating SHA-256.
- Decode with Pillow before committing catalog state.
- Store one content-addressed file at `images/<first-two-hash>/<hash>.<safe-extension>`.
- Generate a locally cached 320-pixel JPEG thumbnail after import; a missing thumbnail is regenerated on demand.
- If content already exists, add only the requested membership.
- Roll back database membership and remove only newly created managed files if a transaction fails.

**Step 4: Write failing tag/filter/selection tests**

Cover editable tag vocabulary, batch add/remove, membership-specific tags, include-all/any/exclude queries, deterministic seeded ordering, sequential cursor advancement, random uniqueness, pinned slots surviving rerolls, and clear errors for empty pools.

```python
def test_reroll_keeps_pins_and_fills_automatic_slots_from_filtered_pool(service):
    service.set_selection(collection_id, filters={"include_all": [portrait_id]}, slots=[{"slot": 1, "image_id": face_id, "pinned": True}])
    result = service.reroll(collection_id, policy="seeded", seed=42)
    assert result["slots"][0]["image_id"] == face_id
    assert len({slot["image_id"] for slot in result["slots"]}) == 4
```

**Step 5: Implement the minimal tag/filter/selection behavior and verify GREEN**

Use indexed joins and `EXISTS`/`NOT EXISTS` clauses rather than loading thousands of rows into Python. Resolve rerolls in one write transaction and store the resulting image IDs so queue executions remain locked.

**Step 6: Commit the slice**

### Task 3: Profiles and local LoRA application

**Files:**
- Extend: `custom_nodes/comfyui_arch_reference_library/store.py`
- Create: `custom_nodes/comfyui_arch_reference_library/nodes.py`
- Create: `custom_nodes/comfyui_arch_reference_library/tests/test_nodes.py`

**Step 1: Write failing profile CRUD tests**

Test Default profile protection, unique profile names per collection, prompt persistence, ordered LoRA replacement, finite strengths, enabled state, and rejection of unknown fields.

**Step 2: Verify RED, implement profile CRUD, and verify GREEN**

Profile updates replace ordered LoRAs transactionally. LoRA names are stored as local catalog-relative names, never arbitrary filesystem paths.

**Step 3: Write failing selector-node tests**

Inject a temporary service and assert Subject and Environment selectors:

- Resolve either sidebar-active IDs or stable pinned IDs.
- Reject kind mismatches and missing/empty locked selections.
- Load four images with EXIF transpose and normalized RGB/RGBA tensors.
- Return four individual `IMAGE` outputs and one list-valued `IMAGE` output preserving original dimensions.
- Return positive/negative additions, collection/profile metadata, and a deterministic LoRA manifest.
- Use a catalog/selection fingerprint in `IS_CHANGED` so sidebar edits invalidate cached execution.

**Step 4: Verify RED, implement selectors, and verify GREEN**

Expose:

```text
arch-Subject Reference Selector
arch-Environment Reference Selector
```

Each node defaults to `Follow sidebar`; frontend code will maintain hidden stable collection/profile IDs when the user pins a selection.

**Step 5: Write failing LoRA applicator tests**

Use injected fake `folder_paths`, torch loader, and `load_lora_for_models` functions to prove ordered application, separate model/CLIP strengths, disabled-entry skips, empty-manifest passthrough, missing-local-file errors, invalid JSON rejection, and per-path/mtime caching.

**Step 6: Verify RED, implement the applicator, and verify GREEN**

Expose `arch-Apply Reference Profile LoRAs` with `MODEL`, `CLIP`, and manifest inputs and `MODEL`, `CLIP`, applied-metadata outputs. Resolve only through `folder_paths.get_full_path_or_raise("loras", name)` and load with `safe_load=True`.

**Step 7: Commit the slice**

### Task 4: Local HTTP API

**Files:**
- Create: `custom_nodes/comfyui_arch_reference_library/routes.py`
- Create: `custom_nodes/comfyui_arch_reference_library/tests/test_routes.py`
- Extend: `custom_nodes/comfyui_arch_reference_library/__init__.py`

**Step 1: Write failing route/validation tests**

Test request validators and handlers for:

```text
GET    /arch-reference-library/bootstrap
POST   /arch-reference-library/collections
PATCH  /arch-reference-library/collections/{id}
DELETE /arch-reference-library/collections/{id}
PUT    /arch-reference-library/active/{kind}
POST   /arch-reference-library/import/{collection_id}
DELETE /arch-reference-library/collections/{collection_id}/images/{image_id}
POST   /arch-reference-library/tags
PATCH  /arch-reference-library/tags/{id}
DELETE /arch-reference-library/tags/{id}
PATCH  /arch-reference-library/membership-tags
POST   /arch-reference-library/profiles
PATCH  /arch-reference-library/profiles/{id}
DELETE /arch-reference-library/profiles/{id}
PUT    /arch-reference-library/selections/{collection_id}
POST   /arch-reference-library/selections/{collection_id}/reroll
GET    /arch-reference-library/images/{image_id}/thumbnail
GET    /arch-reference-library/images/{image_id}/preview
```

Validation must reject unknown JSON fields, noncanonical IDs, invalid kinds, oversized uploads, traversal-like filenames, non-image bodies, foreign collection/image combinations, and unsafe permanent deletion. File routes resolve by catalog ID only and send `nosniff` plus private/no-store cache headers.

**Step 2: Verify RED, implement routes, and verify GREEN**

Register routes only when `PromptServer.instance` exists and guard duplicate registration. Use aiohttp multipart streaming; never accept a server filesystem path from the browser.

**Step 3: Commit the slice**

### Task 5: Sidebar manager and compact node integration

**Files:**
- Create: `custom_nodes/comfyui_arch_reference_library/web/reference_library.js`
- Create: `custom_nodes/comfyui_arch_reference_library/web/reference_library.css`
- Create: `custom_nodes/comfyui_arch_reference_library/tests/test_frontend_contract.py`

**Step 1: Write failing frontend contract tests**

Follow the existing Node-based custom-node contract-test pattern. Assert exported pure helpers for:

- API error normalization.
- Include-all/any/exclude filter serialization.
- Batch tag add/remove payloads.
- Slot pin/unpin and reroll state rendering.
- Stable collection/profile ID handling when display names change.
- Escaped text-only rendering for owner-supplied names and prompts.

Assert the extension registers one `Reference Library` custom sidebar tab and enhances both selector node classes without positional widget migration hazards.

**Step 2: Verify RED, implement the sidebar shell, and verify GREEN**

The sidebar contains:

1. Subject/Environment tabs and active collection chooser.
2. Create/rename/describe/delete collection controls.
3. Multi-file local import.
4. Editable grouped tag vocabulary and include-all/any/exclude filter chips.
5. Thumbnail grid with multi-select, batch tag add/remove, membership unlink, and slot pin buttons.
6. Four locked-slot cards plus random/seeded/sequential reroll controls.
7. Default/model-family profile editor with positive/negative prompt additions and ordered LoRA rows populated from the local Comfy catalog.

Use DOM `textContent`, not owner-data interpolation into `innerHTML`. Disable destructive actions while requests are active, show backend errors inline, and refresh authoritative server state after every mutation.

**Step 3: Implement compact node helpers**

Selector node widgets show Follow sidebar/Pin, current collection/profile labels, four local thumbnails, and an `Open Reference Library` control. Stable IDs remain serialized separately from display labels.

**Step 4: Commit the slice**

### Task 6: Documentation, integration, and live verification

**Files:**
- Create: `custom_nodes/comfyui_arch_reference_library/README.md`
- Extend: `custom_nodes/comfyui_arch_reference_library/tests/*`
- Update: `docs/plans/2026-08-28-reference-library.md`

**Step 1: Write the operator documentation**

Document local-only storage, backup/restore of `user/reference_library`, safe import/unlink/delete semantics, sidebar usage, selector outputs, LoRA application, one-time workflow integration, supported formats, and troubleshooting. State explicitly that personal images/catalog data are ignored and must never be committed.

**Step 2: Run focused package verification**

```powershell
python -m pytest custom_nodes/comfyui_arch_reference_library/tests -q
python -m ruff check custom_nodes/comfyui_arch_reference_library
```

Expected: zero failures and zero lint errors.

**Step 3: Run compatibility verification**

```powershell
python -m pytest custom_nodes/comfyui_random_reference_source/tests custom_nodes/comfyui_arch_prompt_tools/tests/test_nodes.py custom_nodes/comfyui_arch_prompt_tools/tests/test_store.py -q
```

Expected: no regressions in the related existing packages.

**Step 4: Perform live-install smoke verification**

- Make the feature package available to the live install without copying personal data into the worktree.
- Start or restart the local ComfyUI process using the existing machine launcher only after resolving the exact launcher/port.
- Verify `/object_info` contains all three nodes.
- Verify the bootstrap route responds and reports a data path under ignored `user/reference_library`.
- Through the local browser, create temporary test collections, import generated non-personal fixture images, assign/batch-remove tags, filter, pin/reroll slots, save a profile, and confirm selector previews.
- Queue the smallest safe selector-only workflow or directly execute the node against fixtures; do not run a costly generation unless required.
- Remove only the temporary test collection/data created by this verification.

**Step 5: Audit scope and privacy**

```powershell
git status --short
git diff --check
git ls-files user/reference_library
```

Expected: only package code/tests/docs and `.gitignore` are tracked; no workflow JSON, owner image, SQLite, or thumbnail is staged or tracked.

**Step 6: Close the plan before delivery**

Replace `Plan Status: Active` with `Plan Status: Complete`, record verification evidence below, and ensure no completed task remains described as future work.

**Step 7: Commit the final verified slice and update the draft PR**

Do not promote or merge without the owner's delivery authorization. Never target or contact upstream `comfyanonymous/ComfyUI`.

## Acceptance criteria

- [ ] Subject and environment collections can be created, edited, activated, and removed locally.
- [ ] Valid still images are copied, content-deduplicated, and associated with multiple collections without changing originals.
- [ ] Grouped tags support individual and batch add/remove plus include-all/any/exclude filtering at thousands-of-images scale.
- [ ] Four reference slots remain locked until explicit reroll; pins survive random, seeded, and sequential rerolls.
- [ ] Default and model-family profiles expose positive/negative prompt additions and ordered local LoRA manifests.
- [ ] Subject and Environment selector nodes expose four references, a combined list, prompt additions, and metadata.
- [ ] The LoRA applicator loads enabled local LoRAs in order and returns modified `MODEL`/`CLIP` plus evidence metadata.
- [ ] A ComfyUI sidebar provides the complete v1 management workflow without a second service.
- [ ] Existing saved workflows are untouched and existing related custom-node tests do not regress.
- [ ] All personal images, thumbnails, and catalog data remain ignored and local.

## Plan Closeout

- Status: Active.
- Verification evidence: Pending implementation.
- Deferred scope: automatic vision tagging and optional SmartGallery import integration.
