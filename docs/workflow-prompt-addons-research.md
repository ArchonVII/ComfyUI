# QoL addons for workflow + prompt management — research

Researched 2026-08-25. Target: this fork, ComfyUI **0.26.0** with
`comfyui-frontend-package==1.45.19`.

The frontend on 0.26.0 is recent enough that several classics people still
recommend are now redundant, and a couple of others have known friction with
Nodes 2.0 / subgraphs. This doc separates *already built in*, *worth
installing*, and *skip*.

---

## 1. What the stock frontend already does

Do not install an addon for any of these — 1.45.x ships them:

| Need | Built-in |
| --- | --- |
| Workflow browser, folders, tabs, open/save/switch | Workflows sidebar panel |
| Package a messy region into one reusable node | **Subgraphs** (frontend ≥ 1.24.3); "Edit Subgraph Widgets" panel controls which widgets are promoted and in what order |
| Starter workflows by model/task | Template Library (`Comfy-Org/workflow_templates`) |
| Node discovery | Node Library sidebar + search |
| Install/update/browse extensions | ComfyUI Manager (extensions manager, card layout) |

Subgraphs are the single biggest organization win available and cost nothing —
they are the native replacement for the old Group Nodes and for most of what
`comfyui-workspace-manager` used to do.

---

## 2. Recommended installs

Ranked by value-per-install for this repo, given what `custom_nodes/` already
covers (prompt composition, Civitai import, metadata extraction, reverse
prompting, model loading).

### Tier 1 — install these

**`rgthree/rgthree-comfy`** — ~3.4k★, MIT. The canonical workflow-QoL pack.
- **Bookmarks** — drop a marker anywhere on the canvas, jump to it with a
  shortcut key at a set zoom. Solves navigation on large graphs.
- **Fast Groups Muter / Bypasser** — auto-collecting panels that mute or bypass
  whole groups, with filtering and sorting. This is the main lever for "one
  workflow, several modes" instead of five near-duplicate workflow files.
- **Power Lora Loader** — many LoRAs in one condensed node with per-row toggles
  and strengths.
- **Context / Context Big** — bundle MODEL/CLIP/VAE/conditioning into one wire.
- Queue Selected Output Nodes, auto-nested subdirectory combo menus, group
  header mute/bypass toggles, top-window progress bar.
- Caveat: 266 open issues; it patches litegraph heavily, so pin a version and
  re-test after frontend bumps.

**`newtextdoc1111/ComfyUI-Autocomplete-Plus`** — ~182★. The best current tag
autocomplete.
- Danbooru + e621 tag sources with configurable priority; CSVs auto-download
  from HuggingFace on first launch; user CSVs supported.
- **Related-tag panel** — select a tag in any text field, get highly-related
  tags to click in. This is the feature `ComfyUI-Custom-Scripts` autocomplete
  does not have and it materially speeds up prompt building.
- LoRA and embedding autocomplete, auto comma/space formatting
  (Alt+Shift+F or automatic), JA/ZH/KO input, light+dark themes.
- Directly complements the existing `comfyui-prompt-composer` and `arch-pt`
  nodes — those structure a prompt, this one fills the slots.

**`Alectriciti/comfyui-adaptiveprompts`** — ~92★, GPL-3.0, v0.2.0 released
2026-07-08. Dynamic Prompts successor, actively maintained (adieyal's original
`comfyui-dynamicprompts` is effectively dormant).
- `{red|green|blue}` and `__wildcard__` syntax, `{5$$__fruit__}` multi-select,
  custom separators `{3$$ and $$__animal__}`.
- Wildcard files nest in subfolders (`__environments/cave__`), glob match
  (`__lighting*__`), carry comments and `%80%` chance weights, and can call each
  other recursively. That is a real on-disk organization scheme for a prompt
  library, versionable in git.
- Variables: assign `__fruit^a__`, reuse `__^a__` — keeps a randomized subject
  consistent across positive/negative/style nodes.
- **Adaptive RNG mode** generates from prompt *signatures*, so reordering the
  prompt does not change the result. Worth having on its own.
- Lora Tags Loader node for `<lora:name:model:clip:keyword>`.

### Tier 2 — install if the specific pain applies

**`willmiao/ComfyUI-Lora-Manager`** — ~1.4k★. Standalone page at
`/loras`. Browse/organize LoRAs *and* checkpoints with previews, Civitai
download, trigger words, personal notes, multi-folder filtering.
- **LoRA Recipes** — save a LoRA combination plus generation params, re-apply to
  a workflow in one click, import/export to share.
- Overlaps this fork's `comfyui_civitai_ingestor` / `comfyui_smart_model_loader`
  — check for duplicated Civitai metadata handling before adopting.

**`pythongosssss/ComfyUI-Custom-Scripts`** — ~3.2k★, MIT. Still useful for the
pieces rgthree does not cover: **Node Finder** (jump to node type / follow the
executing node), **Auto Arrange Graph** (lay out in execution order), Snap to
Grid, **Preset Text** nodes, String Function (append + regex replace), custom
node/group colors, favicon queue status, workflow→SVG/PNG export.
- Author states limited maintenance capacity. Its autocomplete is superseded by
  Autocomplete-Plus; install for the organization tools, and turn its
  autocomplete off to avoid double-binding the text widgets.

**`chrisgoringe/cg-use-everywhere`** — ~1k★, Apache-2.0. Broadcasts
MODEL/CLIP/VAE/anything to matching unconnected inputs — kills link spaghetti.
Restrict by node-title regex, input-name regex, group-name regex, color, or
priority.
- v8.0 is updated for Nodes 2.0. Known issues: inputs/outputs can no longer be
  renamed (workaround: convert to subgraph), export disabled, submenu closes on
  change. Broadcasting does **not** cross subgraph boundaries by design.
- Read that as: adopt it *or* lean on subgraphs, not both in the same region.

**`ComfyAssets/ComfyUI_PromptManager`** — ~161★. A real prompt database, if a
database is what is wanted.
- SQLite store, SHA256 dedupe, categories/tags/star ratings/notes, admin
  dashboard at `/prompt_manager/admin` with search + bulk ops, gallery that
  links generated images (and video) back to the prompt that made them, PNG
  metadata analyzer, "PM" button in the top bar.
- Nodes: `PromptManager` (CLIP-encode replacement → CONDITIONING),
  `PromptManagerText` (→ STRING), `PromptSearchList` (batch from a search).
- v3.2.1 adds LoRA Manager integration (trigger words, Civitai previews).
- **This is the direct upgrade path for our own `comfyui_prompt_library`**,
  which is currently ~290 lines with a flat store and two HTTP routes
  (`GET`/`POST /prompt-library/prompts`). Decision needed: adopt theirs, or port
  the ideas we want (dedupe hash, ratings/tags, image↔prompt linking) into ours.
  Adopting means a second prompt store alongside `comfyui-prompt-composer`'s
  `presets.json` — pick one system of record.

**`yolain/ComfyUI-Easy-Use`** — ~2.7k★. Large integration pack; take it for
**Alt+1–Alt+9 node-template paste shortcuts**, the Groups Map right-click panel,
recursive nested model subcategories with preview thumbnails, and right-click
node-type swapping on loaders/samplers. 561 open issues and a wide surface —
only worth it if several of those land.

### Tier 3 — narrower alternatives seen

- `Fictiverse/ComfyUI_Prompt_Manager` (22★) — categorized snippet library with
  reference images, drag-to-reorder sections, "always on"/solo flags,
  🎲 randomize-on-queue, server-side presets, base64 export/import. Feature
  overlap with our `arch-pt` + prompt-composer pair is near-total; useful mainly
  as a design reference for reference-image thumbnails and randomize-on-queue.
- `phazei/ComfyUI-Prompt-Stash` — lightweight save/recall, incl. LLM output.
- `fabbarix/comfyui-promptstore` — YAML datastore + text interpolation.
- `FranckyB/ComfyUI-Prompt-Manager` — llama.cpp prompt generation, image/video
  metadata → prompt, saves LoRA stacks and full "Recipes".
- `nkchocoai/ComfyUI-PromptUtilities` — small prompt helper nodes.
- `Tinuva88/Comfy-UmiAI` — variables, boolean logic, wildcards, native LoRA
  loading, local LLM + vision, tag autocomplete, all in one text box. Powerful
  but a large single-node dependency.

---

## 3. Skip

- **`11cafe/comfyui-workspace-manager`** — the obvious search hit for "workflow
  manager", but **deprecated as of 2025-04-16** and unmaintained; the author
  points at the frontend's built-in workspace management. Do not install.
- **"Node Organizer"** — surfaced only via low-quality aggregator articles with
  no locatable upstream repo. Treat as unverified.
- **`adieyal/comfyui-dynamicprompts`** — superseded by adaptiveprompts above.
- Any addon whose pitch is "browse and switch workflows" — that is the
  Workflows sidebar now.

---

## 4. Suggested adoption order

1. **Subgraph the existing workflows first.** Free, native, and it shrinks the
   problem the addons have to solve — including
   `user/default/workflows/agent/38 - Arch PT Prompt Builder.json`.
2. **rgthree-comfy** — bookmarks + fast group muters. Biggest single jump in
   navigating and mode-switching a large graph.
3. **Autocomplete-Plus** — immediate speedup on every text field, no workflow
   changes required.
4. **adaptiveprompts** — move the reusable prompt fragments into versioned
   wildcard files under a nested folder scheme.
5. Then decide the prompt **system of record**: extend `comfyui_prompt_library`,
   or adopt `ComfyUI_PromptManager` and migrate. Do not run three stores
   (`prompt_library` JSON, prompt-composer `presets.json`, and a new SQLite DB)
   in parallel.
6. Optional: LoRA Manager, Custom-Scripts (Node Finder / Auto Arrange / Preset
   Text), Use Everywhere.

### Compatibility notes

- rgthree, Custom-Scripts, and Use Everywhere all patch litegraph. Install them
  one at a time, pin versions, and re-verify after any
  `comfyui-frontend-package` bump.
- Use Everywhere and subgraphs partly conflict in intent — broadcasts stop at
  subgraph boundaries. Choose per region.
- Autocomplete-Plus and Custom-Scripts both bind text-widget autocomplete;
  disable one.

## Sources

- https://github.com/rgthree/rgthree-comfy
- https://github.com/pythongosssss/ComfyUI-Custom-Scripts
- https://github.com/newtextdoc1111/ComfyUI-Autocomplete-Plus
- https://github.com/Alectriciti/comfyui-adaptiveprompts
- https://github.com/chrisgoringe/cg-use-everywhere
- https://github.com/willmiao/ComfyUI-Lora-Manager
- https://github.com/ComfyAssets/ComfyUI_PromptManager
- https://github.com/Fictiverse/ComfyUI_Prompt_Manager
- https://github.com/yolain/ComfyUI-Easy-Use
- https://github.com/11cafe/comfyui-workspace-manager
- https://github.com/Comfy-Org/workflow_templates
