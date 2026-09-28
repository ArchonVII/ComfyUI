# Preset Studio Character Catalog and Discovery

Status: implemented and verified. Owner: Codex. Approved by the owner on
2026-09-27 and authorized for delivery on 2026-09-28 through fork PR #22.

## Goal and boundaries

Give characters a first-class Preset Studio workspace for creation, image
assignment, local face-match discovery, rapid visual review, exact-copy
quarantine, flexible image families, and source-to-output lineage. Extract the
domain behavior into a reusable local Python character-catalog package so
Preset Studio is its first client rather than its only possible integration.

Everything remains local. Images, embeddings, thumbnails, catalog databases,
and scan state stay under ignored `user/character_catalog/` or existing ignored
Preset Studio storage and never enter Git. Scans are manual by default. Optional
scheduled/watch scanning is an advanced opt-in. V1 scans still PNG, JPEG, WebP,
BMP, and TIFF images only; video scanning and automatic permanent deletion are
out of scope.

The target is a single-owner catalog of roughly 100,000 images. Work must use
bounded workers, indexed and paginated queries, streaming hashes, persistent
job checkpoints, and reusable cached analysis. Accepted human assignments,
family membership, and source choices always outrank machine recommendations.

## Approved architecture

Create a focused `tools/character_catalog/` Python package with an importable
domain interface and versioned loopback API adapters. It owns SQLite state,
filesystem reconciliation, stable asset identity, scan jobs, local face
analysis, recommendations, review decisions, image families, lineage, and
quarantine. Preset Studio mounts the API and supplies the first complete UI.
Future ComfyUI nodes or gallery adapters may use the Python interface or local
API without duplicating matching logic.

Preset Studio is refactored into Model-View-ViewModel:

- models contain immutable API/domain records;
- view models own navigation, filters, selection, pending operations, and
  display state;
- views render state and emit typed actions without fetching or making domain
  decisions;
- services own the typed local client, dialogs, notifications, progress, and
  persistence boundaries.

The application shell exposes Compose, Characters, Workflows, Results, and
Settings as full destinations. Characters uses a character rail plus a wide
workspace with Overview, Images, Families, Find New Pics, and Review surfaces.
Controls are compact row components; galleries and workspaces, not isolated
buttons, consume full width. Accent colors consistently distinguish primary,
recommended/confirmed, review, source/lineage, and quarantine states.

## Catalog model and invariants

- `asset` is stable image identity; `asset_location` records current and prior
  source, managed, missing, or quarantined paths.
- `content_blob.sha256` is definitive byte identity. Exact copies collapse in
  ordinary galleries while all locations remain reviewable.
- face detections and embeddings are versioned analyzer suggestions. Accepted
  face-to-character assignments and rejections are separate durable truth.
- one image may contain independently assigned faces and belong to multiple
  characters without duplicating the catalog asset.
- global scan roots are configured once; characters may add scoped roots.
- scan jobs are explicit, resumable, pausable, and cancellable. Opening Studio
  never starts a scan.
- character-scoped image families behave like flexible organizational tags.
  Membership is distinct from a mutable designated-source role.
- source replacement is always recommended for approval, never silently
  applied. Ranking uses resolution, usable face size, sharpness, compression,
  clipping, and provenance rather than resolution alone.
- Preset Studio runs create authoritative `generated_from` relationships using
  the exact chosen character source. Existing ComfyUI metadata may create
  reviewable lineage suggestions.
- exact-copy removals require review and move locations to recoverable local
  quarantine. No scan automatically deletes or permanently removes a file.

## Review experience

Find New Pics presents the character, roots, recursion policy, cached/new scope,
and optional watch state before starting. Results stream into a large-thumbnail
review grid grouped by recommendation. The queue supports group, shift, and
paint-style selection plus keyboard navigation. A sticky batch bar exposes
Assign Recommended, assign/reassign character, reject, defer, add to family,
designate source, and quarantine duplicate.

The normal pass should be one visual check followed by **Assign Recommended**.
Every recommendation shows concise evidence, confidence, and the matched face.
Multi-face records act on the selected face but image-level family/tag actions
deduplicate their underlying assets. Applied batches are idempotent and offer
undo or an explicit inverse where filesystem safety permits.

## Reliability and error behavior

Hashing snapshots file size and timestamps before and after streaming; changed
files return to pending rather than receiving stale identity. Missing files
become unavailable without losing accepted metadata. Corrupt files, no-face
results, model failures, and access errors remain visible non-destructive scan
outcomes. Cancellation stops after the current bounded item and persists the
checkpoint.

Quarantine uses a small operation journal (`planned`, `filesystem_done`,
`database_done`) so restart recovery cannot silently split filesystem and
catalog state. Restore never overwrites an occupied path and uses a deterministic
collision suffix. Analyzer upgrades mark recommendations stale and allow
rescoring; they do not replace accepted truth.

## Staged implementation

1. **Protect the baseline.** Keep the existing desktop-launch edits untouched;
   record the current passing suite before feature changes.
2. **MVVM behavior-parity shell.** Add testable navigation/application view
   models and component boundaries, then move existing Compose, Workflow,
   Results, and preset behavior without changing their contracts.
3. **Catalog foundation.** Add the versioned schema, stable assets/locations,
   characters, strict repository/service APIs, and additive import of existing
   Preset Studio character records and managed references.
4. **Characters workspace.** Add character CRUD, image assignment, folder-root
   management, galleries, and responsive full-tab UI.
5. **Manual discovery.** Add durable explicit scan jobs, incremental hashing,
   local face analysis/matching, progress, and grouped bulk review.
6. **Duplicates and quarantine.** Add location-level exact-copy review, keeper
   recommendations, journaled quarantine, restore, and recovery.
7. **Families and lineage.** Add family boards, source recommendations,
   merge/split and source controls, authoritative run lineage, and historical
   metadata suggestions.
8. **Advanced adapters.** Add disabled-by-default schedule/watch controls and
   optional gallery adapters without making SmartGallery a dependency.

Every stage is independently runnable and verified before the next begins.
Incomplete later controls remain hidden. Schema changes are additive or use a
transactional migration with a recoverable backup. Do not expose a half-working
screen to the normal navigation.

## Test-first verification contract

Production behavior is added only after a focused failing test demonstrates
the missing contract. Planned coverage includes stable identity and moves,
content changes at reused paths, multi-location exact copies, manual truth,
explicit scan start, cached rescans, pause/resume/cancel, multi-face matching,
rejection suppression, source ranking, family membership, lineage, quarantine
recovery, strict local APIs, pagination, idempotent batches, and MVVM state and
action behavior.

Each stage runs the affected Python unit/integration tests, Node view-model or
component tests, JavaScript syntax checks, and a generated-fixture live smoke.
The current baseline on 2026-09-27 is 65 passing Python tests, eleven passing
browser-module tests, and a passing `node --check` for `web/app.js`. Required
GitHub CI remains the final full-suite authority; do not repeat unrelated full
suites locally as delivery ceremony.

## Decision log

1. Port and consolidate proven Companion catalog, matching, duplicate, and
   family behavior instead of requiring Companion or rebuilding concepts.
2. Use a reusable Python core so standalone Preset Studio and future ComfyUI
   integrations share one implementation.
3. Refactor the full Preset Studio shell to MVVM before adding feature-heavy
   views; preserve behavior during the refactor.
4. Keep scans manual by default and advanced watching explicitly opt-in.
5. Require visual review while optimizing the queue for bulk Assign Recommended.
6. Separate family identity and membership from the designated source role.
7. Capture Studio lineage authoritatively and infer historical lineage only as
   a suggestion.
8. Preserve accepted assignments across rescans and analyzer changes.
9. Quarantine approved exact copies recoverably; never auto-delete.
10. Keep SmartGallery or another gallery optional and outside the core runtime.

## Delivered state

Stages 1-7 have working slices. Preset Studio now has the MVVM application shell,
full Characters destination and gallery, local catalog schema v10,
character/preset synchronization, explicit folder assignment, cancellable
user-started discovery jobs, local YuNet/SFace multi-face analysis, cached
embeddings, paginated score-sorted bulk review, durable face-level rejection,
defer/cancel controls, and idempotent Assign Recommended.

Byte-exact duplicate locations are reviewable and may be moved to recoverable
journaled quarantine; the last available copy is protected. Families are
tag-like many-to-many groups with a separate replaceable source role and a
higher-resolution source recommendation. Preset Studio runs record authoritative
source-to-output lineage and expose generated descendants from family members.
The QoL pass adds direct image-to-Compose handoff, bounded cached thumbnails,
paginated galleries, durable review and gallery selection, selection-to-family
creation, editable family membership/names, full-resolution inspection, recent
folder shortcuts, and visible recoverable quarantine history. Watching and
scheduling remain disabled. Schema-v1 migration is additive and covered.

Face-review cards now pair full context with the matched crop, large folder
assignment runs as a durable background job, the Sources view gathers all
designated generation anchors, and Assign All Pending works across unloaded
review pages. Gallery search and sorting are server-paginated, and per-file
scan failures are retained for inspection. Family similarity suggestions,
safely resumable scan cursors, scheduling/watch, and third-party gallery
adapters remain optional future work outside this delivered scope. The desktop
launcher is included in the same Preset Studio delivery.
