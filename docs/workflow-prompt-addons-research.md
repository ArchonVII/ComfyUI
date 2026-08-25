# Organizing a large workflow library + prompt tooling — research

Researched 2026-08-25. Revised after correction: the first pass aimed at
organization *within* a single graph (subgraphs, bookmarks, group muters). That
was the wrong problem. This pass is about **hundreds of workflow files** and
about **prompt tooling with fewer steps**.

## Constraints this is written against

- **Hundreds of saved workflows.** The repo slice has 23; the real install has
  far more.
- **Filenames are not trustworthy.** Numeric prefixes are made up to get a new
  file saved, so the same workflow exists many times under different numbers.
  Even in the 23-file sample there are already two `35 -` and two `40 -`.
  **Anything that searches by filename is dead on arrival.**
- **Do not edit existing workflows.** Tools that rewrite workflow JSON are
  disqualified; sidecar metadata or read-only indexing only.
- **Built-ins are not assumed to work.** Several things assumed present in the
  first pass do not behave as intended in practice, and
  `comfyui_civitai_ingestor` has never worked right. Nothing below is
  recommended on the basis of "you already have this".

Given those, the only three things that can actually find a workflow are:

1. **What's inside it** — node types, model/LoRA filenames, prompt text.
2. **What it looks like** — a thumbnail or graph preview.
3. **What it produced** — the output image, traced back to its workflow.

Sorting and renaming are not on that list. Neither is the native Workflows
sidebar, which searches filenames.

---

## Part 1 — Workflow library at scale

### Tier 1

**`biagiomaf/smart-comfyui-gallery`** (SmartGallery DAM) — 372★, MIT,
v2.22.1, Python 3.10+, portable Windows build, runs **independently of
ComfyUI**. The most mature project in this whole survey and the best answer to
unreliable filenames, because it ignores them entirely.

- Filter by **prompt, checkpoint, LoRA, date, comment** with fuzzy
  autocomplete. Every generated asset is indexed by what made it.
- **OmniQuery** — plain-English questions over the library; an LLM writes the
  SQL.
- **Workflow recovery**: with an asset selected, `W` downloads its raw workflow
  JSON, `C` copies it to the clipboard to paste straight into ComfyUI. This is
  the escape hatch from the naming problem — find the *picture* you liked, get
  the *workflow* back, regardless of what the file was called.
- **Smart Asset Clustering (`Shift+C`)** groups generations by identical node
  architecture or prompt text. This is the closest thing that exists to
  duplicate detection for the save-as-a-new-number problem: it shows you which
  of your files are actually the same graph.
- **Hash Inspector** shows the node pipeline as chips
  (`CheckpointLoader → LoraLoader → KSampler → VAEDecode`) with the exact
  checkpoint and LoRA files used.
- Status tags (`1`–`5`), star ratings, virtual collections that span physical
  folders, client sharing, mobile-friendly, Docker-ready.
- **Risk: low.** Separate app, local-first, no cloud, does not touch ComfyUI or
  the workflow files. If it disappoints, delete it.

**`AI4VFX/comfyui-g-workflows`** — 25★, MIT, 64 commits. A real file manager
for workflows, opened from a button in the ComfyUI top bar.

- **Thumbnail gallery** plus a resizable **list view** with sortable
  Name / Date / Description / Tags / Path / Size columns.
- **Tags** with a dedicated pane and cross-root filtering; **favorites**;
  **descriptions**; focused *or* global search; drag-and-drop.
- **Multiple roots** — add as many folders from anywhere on disk as you like,
  all behaving the same. Useful if workflows have sprawled beyond
  `user/default/workflows/`.
- **Metadata is sidecar-only**: `.desc.txt`, `.tags.txt` (one tag per line,
  lowercased and deduped), `.fav` markers. It reads and writes the native
  workflows folder but **does not modify workflow JSON** — which satisfies the
  do-not-edit constraint exactly, and means tags are greppable and
  git-versionable.
- Dependencies are stdlib plus `aiohttp` and `Pillow`, both already shipped
  with ComfyUI. Needs a full restart, not just a refresh.
- **Risk: moderate — small project.** But the sidecar design means the worst
  case is stray `.tags.txt` files, not damaged workflows.
- **Caveat:** tagging hundreds of files is manual. Budget a session for it, or
  seed the tags from a script (see Part 3).

### Tier 2

**`gregowahoo/comfyui-workflow-finder`** — 74★, MIT, Python 3.10+, a
**standalone tkinter app**, not a custom node. Only 10 commits, so treat it as
early.

- **Parses workflow JSON** and matches against a built-in node capability map
  (~100 node types). This is content search, which is the thing that actually
  works when names don't.
- **Node Pack Filter** scans `custom_nodes/` and reports which packages each
  workflow requires, and how many workflows use each pack. That doubles as a
  dependency audit: it tells you which of your hundreds of workflows still
  depend on something broken.
- Multiple install locations, each toggleable without a rescan.
- Fast mode is local keyword matching, no internet. **AI mode sends workflow
  fingerprints to the Claude API** (needs the `anthropic` package and a key) for
  semantic matching. Wild Search goes further and searches YouTube/CivitAI/
  GitHub/Reddit for downloadable workflows — that one is unrelated to organizing
  what you already have.
- **Risk: low to the install** (separate process, read-only), **high on
  polish** (10 commits). Worth 20 minutes to see if the node-pack audit alone
  pays for itself.

**`talesofai/comfyui-browser`** — 675★, Svelte + aiohttp. Image/video/workflow
browser with a "Saves" collection, keyword search, and **git sync of the Saves
folder to a remote repo**, plus subscribing to workflow sources by git.

- Git sync is the only real *versioning* answer found. If the underlying problem
  is "I save a new numbered copy because I'm scared to overwrite", version
  control removes the reason to do that.
- **Caveat:** the project's peak activity predates the current frontend; verify
  it loads against 1.45.x before relying on it. Author notes limited Windows
  testing.

### Noted, not recommended

- `ketle-man/ComfyUI-Workflow-Studio` — 8★. Workflow tab with thumbnail/table
  views, badge filtering and full-text search, plus gallery/prompt/models/tagger
  tabs. Right ideas, far too immature to depend on.
- `PanicTitan/ComfyUI-Gallery` — real-time output gallery with metadata
  inspection. Narrower than SmartGallery.
- `11cafe/comfyui-workspace-manager` — **deprecated since 2025-04-16**,
  unmaintained. Still the top search hit for "ComfyUI workflow manager". Skip.
- "Node Organizer" — appears only in low-quality aggregator articles; the
  locatable repo (`PBandDev/comfyui-node-organizer`) aligns nodes *within* a
  graph, which is not this problem.

### Nothing found for

**Workflow-file deduplication.** No tool compares saved workflow JSONs and
groups near-identical ones. SmartGallery's clustering is the closest, and it
works on outputs rather than files. This is the clearest gap, and it is also the
easiest thing to close ourselves — see Part 3.

---

## Part 2 — Prompt tooling: fewer steps, fewer disconnects

The current stack is three disconnected systems: `arch-pt` (six focused nodes
each emitting `ARCH_PT_BUNDLE`, all seven wired into `arch-pt-Combine`),
`comfyui-prompt-composer` (its own `presets.json`), and `comfyui_prompt_library`
(~290 lines, flat store, two HTTP routes). Building one prompt costs seven nodes
and manual wiring, and none of the three share a store.

The fix is not another node pack. It is moving prompt work **out of the graph**
and **into text plus files**.

### Tier 1

**`Alectriciti/comfyui-adaptiveprompts`** — 92★, GPL-3.0, v0.2.0 released
2026-07-08. Actively maintained successor to Dynamic Prompts, which is dormant.

- **Wildcard files replace the seven-node chain.** `__identity__`, `__pose__`,
  `__clothing__`, `__environment__`, `__camera__`, `__lighting__` — the same six
  concerns, as `.txt` files in nested folders, referenced from one text box.
  Subfolders (`__environments/cave__`), glob matching (`__lighting*__`), inline
  comments, `%80%` chance weights, and files that call other files recursively.
- **This also solves the storage problem**: wildcard files live on disk, in git,
  diffable and greppable. One system of record instead of three.
- **Variables** — assign `__fruit^a__`, reuse as `__^a__`. Keeps a randomized
  subject consistent across positive, negative and style text without wiring
  anything between them. This is the direct answer to "disconnects".
- **Adaptive RNG** generates from prompt *signatures*, so reordering a prompt no
  longer changes the image. Legacy mode is available if you want the old
  behavior.
- Multi-select `{5$$__fruit__}`, custom separators `{3$$ and $$__animal__}`,
  and a Lora Tags Loader for `<lora:name:model:clip:keyword>`.

**`newtextdoc1111/ComfyUI-Autocomplete-Plus`** — 182★, 287 commits.
Zero wiring: it enhances every text widget already in the graph.

- Danbooru + e621 sources with configurable priority; CSVs auto-download on
  first launch; custom CSVs supported.
- **Related-tag panel** — select a tag in any text field and get closely-related
  tags to click in. This is the feature that removes the "go look something up"
  step, and it is what `ComfyUI-Custom-Scripts` autocomplete lacks.
- LoRA and embedding autocomplete, auto comma/space formatting (automatic or
  Alt+Shift+F), JA/ZH/KO input, light and dark themes.
- **Conflict:** do not run this alongside Custom-Scripts autocomplete; both bind
  the same text widgets. Disable one.

### Tier 2

**`1038lab/ComfyUI-WildPromptor`** — 97★, Apache-2.0, v1.1.0 (2025-07-12),
102 commits. The structured-picker counterpart to adaptiveprompts.

- Folder-based `data` directory; **each folder automatically becomes a node**
  with dropdown keyword selection, and the node UI updates when the folders
  change. Default categories are Subject, Environment, Virtual (effects,
  lighting, styles), Custom, Styles, Negative — close to the arch-pt split.
- Prompt Builder, Concat and Picker tools, plus random selection.
- Consider it if dropdowns are wanted over raw wildcard syntax. It is still
  node-based, so it reduces the *wiring* problem less than adaptiveprompts does.

**`Tinuva88/Comfy-UmiAI`** — 27★. The most aggressive answer to "too many
steps": variables, boolean logic, wildcards, LoRA loading, local LLM, vision
models and tag autocomplete **in one node**.

- A full setup is Checkpoint Loader → `UmiAIWildcardNode` → CLIP Text Encode →
  KSampler → Empty Latent. Model and CLIP pass *through* it so `<lora:file:str>`
  in the text applies LoRAs with no loader chain.
- Persistent variables (`$hair={Red|Blue}`), bidirectional boolean logic
  (`__[logic]__` filtering and `[if cond : True | False]` in text).
- **Risk: high.** 27★ and a single large node holding the whole prompt path. It
  is the right *shape* for the complaint but the wrong maturity to build on.
  Worth reading for design ideas.

### Noted, not recommended

- `Kinglord/ComfyUI_Prompt_Gallery` — 76★, GPL-3.0. Visual prompt selector **in
  the sidebar**, not the graph: browse categorized images, click to send tags to
  whichever node is selected. Exactly the right interaction model, but **last
  updated 2024-09-24** and unlikely to work against the current frontend. Use as
  a design reference for the sidebar approach.
- `ComfyAssets/ComfyUI_PromptManager` — SQLite store, dedupe hashing,
  tags/ratings, gallery linking images back to prompts. A good design reference
  for our own `comfyui_prompt_library`, but adopting it adds a *fourth* prompt
  store. SmartGallery already covers the image-to-prompt link.
- `phazei/ComfyUI-Prompt-Stash`, `fabbarix/comfyui-promptstore` (YAML),
  `FranckyB/ComfyUI-Prompt-Manager` (llama.cpp + recipes),
  `nkchocoai/ComfyUI-PromptUtilities` — all narrower than adaptiveprompts.

---

## Part 3 — The gap, now built

Nothing surveyed indexes a workflow *library* by content and reports
near-duplicates, and that is precisely the shape of the problem here. So it is
built, in [`tools/workflow_library/`](../tools/workflow_library/README.md):

- `index_workflows.py` walks every workflow root, parses each JSON, and extracts
  node types, model and LoRA filenames, and prompt text.
- It hashes the graph structure — node types plus edges, ignoring widget values,
  ids, positions and titles — to group the save-as-a-new-number families, and
  reports each family with its members and mtimes so a keeper can be chosen. A
  second, looser hash catches variants where the same nodes were re-wired.
- Every family member gets a shared `dup:<hash>` tag, and `--write-tags` emits
  `.tags.txt` sidecars in the g-workflows format, seeded from detected models
  and node packs. Hundreds of manual tagging decisions become one review pass.
- It flags workflows referencing node types this install cannot resolve. The
  offline scan reads both `NODE_CLASS_MAPPINGS` and V3 `node_id=`
  registrations; `--object-info` takes a dump from a running ComfyUI and makes
  the audit exact.
- `export_wildcards.py` converts the 596-option arch-pt catalog into 216
  adaptiveprompts wildcard files, so the six-node chain becomes one text field.

Read-only over the workflow files, writing only sidecars and reports —
consistent with the do-not-edit constraint. It also makes whichever browser gets
adopted immediately useful instead of empty.

On the 25 workflows present in this repo it finds one duplicate family
(`31 - WAN Q4 FAST Preview 17f` and `32 - WAN Q4 Prompt Camera 49f` are the same
graph with different widget values) and derives tags such as `wan-2.2`,
`quantized`, `i2v`, `pulid` and `reactor`.

---

## Suggested order

1. **SmartGallery DAM.** Standalone, mature, zero risk to the install, and it
   makes the naming problem irrelevant for anything already generated.
   Immediate payoff, no migration.
2. **adaptiveprompts**, and start moving prompt fragments into wildcard files.
   Reduces both the node count and the number of prompt stores.
3. **Autocomplete-Plus.** No workflow changes, helps in every text field.
   Disable Custom-Scripts autocomplete if it is installed.
4. **The indexer** from Part 3 — content index, structural dedupe report,
   seeded tags. Already written; just needs pointing at the real library.
5. **g-workflows**, pointed at the seeded tags, if a browser inside ComfyUI is
   still wanted after 1 and 4.
6. Evaluate **workflow-finder** for its node-pack dependency audit; evaluate
   **comfyui-browser** only if git-backed versioning is wanted, and verify
   frontend compatibility first.

### Verification before adopting anything

Given the history with `comfyui_civitai_ingestor`, test each on a **copy** of
the workflow folder before pointing it at the real one, and confirm no workflow
JSON's mtime changes. The two Tier-1 workflow tools are designed for this:
SmartGallery runs as a separate process, and g-workflows writes sidecars only.

## Sources

- https://github.com/biagiomaf/smart-comfyui-gallery
- https://github.com/AI4VFX/comfyui-g-workflows
- https://github.com/gregowahoo/comfyui-workflow-finder
- https://github.com/talesofai/comfyui-browser
- https://github.com/ketle-man/ComfyUI-Workflow-Studio
- https://github.com/PanicTitan/ComfyUI-Gallery
- https://github.com/Alectriciti/comfyui-adaptiveprompts
- https://github.com/newtextdoc1111/ComfyUI-Autocomplete-Plus
- https://github.com/1038lab/ComfyUI-WildPromptor
- https://github.com/Tinuva88/Comfy-UmiAI
- https://github.com/Kinglord/ComfyUI_Prompt_Gallery
- https://github.com/ComfyAssets/ComfyUI_PromptManager
- https://github.com/11cafe/comfyui-workspace-manager
