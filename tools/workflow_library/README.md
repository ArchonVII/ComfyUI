# workflow_library

Tooling for the problems in
[`docs/workflow-prompt-addons-research.md`](../../docs/workflow-prompt-addons-research.md):
a workflow library too large to navigate by filename, and a prompt stack that
costs seven wired nodes per prompt.

Nothing here modifies a workflow file. The indexer reads them and writes
reports plus optional `.tags.txt` sidecars; the exporter reads the arch-pt
catalog and writes wildcard files. Both verify or avoid touching their inputs,
and `test_index_never_writes_to_workflow_files` holds that guarantee.

## `index_workflows.py` — find a workflow by what's in it

Filenames in this library are save-as artefacts, so the index is built from
graph contents instead.

```bash
python -m tools.workflow_library.index_workflows \
    --root user/default/workflows \
    --root user/default/api_workflows
```

Writes `tools/workflow_library/out/`:

- **`report.md`** — duplicate families, near-duplicates, workflows referencing
  unavailable nodes, pack usage, tag frequency.
- **`index.json`** — per workflow: node types, models, prompt excerpts, both
  hashes, derived tags, owning packs, unresolved nodes.

### Duplicate detection

Two hashes, because the re-saves come in two shapes:

| hash | ignores | catches |
| --- | --- | --- |
| `structural_hash` | node ids, positions, titles, colours, **all widget values** | the same graph saved again under a new number with a new seed or prompt |
| `composition_hash` | all of the above **plus wiring** | a variant where the same nodes were re-connected |

Every member of a family gets a shared `dup:<hash>` tag, so a browser that can
filter by tag can show the whole family at once.

### Seeding tags

```bash
python -m tools.workflow_library.index_workflows --root <dir> --write-tags
```

Writes `<workflow>.tags.txt` next to each workflow in the format g-workflows
reads — one lowercased tag per line. Re-running is idempotent: unchanged
sidecars are not rewritten. Tags are derived from model filenames and node
types by the rules in [`tagging.py`](tagging.py); add a row there and the whole
library re-tags on the next run.

### Exact missing-node audit

The offline scan reads `NODE_CLASS_MAPPINGS` and V3 `node_id=` registrations
statically, so packs that build their mappings dynamically look missing. A
running ComfyUI knows the truth:

```bash
curl -s http://127.0.0.1:8188/object_info > object_info.json
python -m tools.workflow_library.index_workflows --root <dir> --object-info object_info.json
```

## `export_wildcards.py` — arch-pt catalog as wildcard files

Turns the 596-option arch-pt catalog into adaptiveprompts wildcard files, so a
prompt that needed six focused nodes plus Combine becomes one text field.

```bash
python -m tools.workflow_library.export_wildcards --out wildcards
```

Produces `wildcards/archpt/<family>/<node>/<field>.txt` — 216 files, 1192
phrases across the `flux` and `qwen` families — plus
[`wildcards/archpt/README.md`](../../wildcards/archpt/README.md) listing every
token. Usage:

```
__archpt/flux/camera/focal_length__      one field
__archpt/flux/camera/*__                 any camera field
__archpt/flux/identity/hair_color^hair__ assign, then reuse as __^hair__
```

That last form is what closes the disconnect: a value picked once stays
consistent across positive, negative and style fields with no wire between
them.

The arch-pt nodes keep working unchanged — this reads their catalog, it does
not replace them. Re-run after editing the catalog; hand edits to the generated
files are overwritten.

## `install_addons.ps1` / `install_addons.sh` — the local half

Clones adaptiveprompts, Autocomplete-Plus and g-workflows into `custom_nodes`,
installs their requirements, and copies the wildcard export into place.

```powershell
.\tools\workflow_library\install_addons.ps1 -ComfyRoot C:\tools\image\ComfyUI
```

```bash
./tools/workflow_library/install_addons.sh /path/to/ComfyUI
```

Existing clones are skipped unless `-Update` / `UPDATE=1`. Nothing is deleted.
SmartGallery is not installed by these scripts — it is a separate application.

## Tests

```bash
python -m pytest tools/workflow_library/tests/ -q
```
