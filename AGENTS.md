# AGENTS.md — ComfyUI (ArchonVII fork)

This is the canonical agent rule set and decision log for this repo. One rule,
one place: link here, do not copy these rules elsewhere.

This is a **live ComfyUI install** tracked in git, not a normal source repo:
the working tree at `C:\tools\image\ComfyUI` is the running product.

## Owner decisions

- **2026-08-25 — no upstream; images never leave the machine.** Owner: "WE do
  not do anything upstream", "everything stays local to the machine or our
  repo, and all images are local to the machine only". Upstream
  `comfyanonymous/ComfyUI` (`origin`) is consume-only: fetching updates is
  fine; never push, open PRs, or file issues there (`origin` push URL is set
  to a disabled placeholder to enforce this). The fork
  `github.com/ArchonVII/ComfyUI` (`fork`) is the only remote target, and
  delivery is merge to `master`. **Owner-generated or personal images (and
  video) are never committed or pushed anywhere** — not even to the fork;
  upstream/pack documentation images that ship with code are exempt.
- **2026-08-25 — saved workflows are owner data.** Owner: "never modify, move
  or delete a workflow file" (saved workflow JSONs under `user/`,
  `blueprints/`, `input*/`). Agents may read them, write sidecars beside them
  (`.tags.txt`), and add new workflow files. Changing or removing an existing
  saved workflow requires an explicit per-file owner decision — the pending
  duplicate-keeper decisions live in `docs/workflow-duplicate-triage.md`.
- **2026-08-25 — single-lane repo.** Owner: the codex agent is not active,
  there are no per-agent restrictions here, and agents may edit what the task
  needs. The main worktree runs on `master`; feature branches merge back to
  `master` when the owner says to land.

## Tooling map

- `tools/workflow_library/` — content indexer, duplicate detection, tag
  sidecars, wildcard export (docs: `docs/workflow-prompt-addons-research.md`,
  `docs/workflow-addons-buildout.md`).
- `custom_nodes/comfyui_arch_prompt_tools/` — the prompt-builder node suite
  (incl. `arch-pt-Random`); the option catalog in `data/builtin_options.json`
  is the single source the wildcard export derives from.
- Off-task observations go to `.claude/noticed.md`.
