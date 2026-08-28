# Handoff: workflow library setup (local agent)

You are running on the desktop that holds the real ComfyUI install
(`C:\tools\image\ComfyUI`, several hundred saved workflows). A remote session
did the research and wrote the tooling; you are doing the execution that needs
the real library, real models and a running server.

Read this whole file before starting. The companion documents are
[`docs/workflow-prompt-addons-research.md`](workflow-prompt-addons-research.md)
(why these tools and not others) and
[`tools/workflow_library/README.md`](../tools/workflow_library/README.md)
(what the tooling does).

There is also a **[step-by-step runbook][runbook]** covering the same work as 22
manual steps. It is the owner's copy, written for a human at the keyboard, and
it is a private page you will not be able to fetch — do not try. It matters to
you only because the Track B items below are the steps in it that were never
delegated, so when you hand back, referring to them by number ("runbook steps
10–13") is the clearest way to say what is left.

[runbook]: https://claude.ai/code/artifact/effc0246-c4ae-4e6c-89f7-74c54c77722b

---

## 1. The problem you are solving

Workflow filenames are unreliable. Numeric prefixes (`31 - `, `35 - `) were
invented to force a new save, so the same graph exists many times over under
different numbers, and titles have drifted from what the graphs actually do.
Filename search — including ComfyUI's own Workflows sidebar — cannot find
anything. The fixes are to index by *content*, group the re-saved families by
graph shape, and tag from what each workflow actually contains.

Two tools are already written, tested and on this branch:

- `tools/workflow_library/index_workflows.py` — content index, duplicate
  detection, missing-node audit, `.tags.txt` sidecar seeding.
- `tools/workflow_library/export_wildcards.py` — converts the arch-pt catalog
  into adaptiveprompts wildcard files.

Both have 34 passing tests. Do not rewrite them. If something is wrong, fix the
specific defect and add a test.

---

## 2. Hard rules

These are not preferences. Breaking one is worse than not finishing.

1. **Never modify a workflow JSON file.** Not to reformat, not to "fix" a
   broken node reference, not to migrate anything. The indexer verifies mtimes
   after every run and exits `3` if one moved — if that happens, stop and
   report.
2. **Never delete or move a workflow file**, including obvious duplicates.
   Choosing a keeper is the owner's judgement call, not yours. You prepare the
   evidence; they decide.
3. **Never edit an existing saved workflow to test something.** Build a scratch
   workflow instead.
4. **Do not push to any branch other than
   `claude/workflow-addons-research-h8v30e`.** Do not open a pull request.
5. **Do not install addons beyond the three named in step B4.** The research
   deliberately rejected several popular ones; re-litigating that is out of
   scope.
6. **Do not disable, skip or weaken a test** to get a green run.

## 3. Before you start

Confirm all of these, and stop if any fails:

- `git status` is clean. If it is not, stop and ask — a checkout would carry
  uncommitted work across.
- You know which Python runs ComfyUI. The tooling is stdlib-only (any 3.10+
  works), but use the ComfyUI interpreter so paths and versions match. If
  ComfyUI runs from a venv, that is `.\venv\Scripts\python.exe`.
- You can start and stop the ComfyUI server.

Then:

```
git fetch origin claude/workflow-addons-research-h8v30e
git checkout claude/workflow-addons-research-h8v30e
python -m pytest tools/workflow_library/tests/ -q
```

34 tests should pass. If they do not, that is your first bug — report it before
going further.

---

## 4. Track A — do these unattended

### A1. Find every workflow root

Do not assume `user\default\workflows`. Search the ComfyUI tree, and any other
plausible location the owner may have saved to over time, for folders
containing workflow JSON. Report the list with file counts. Every later step
takes `--root` once per folder.

### A2. Index, read-only

```
python -m tools.workflow_library.index_workflows --root <each root>
```

Expected final lines:

```
indexed   N workflows from M root(s)
duplicates N families covering N files
unresolved N workflows reference missing nodes
wrote     tools/workflow_library/out/index.json
wrote     tools/workflow_library/out/report.md
verified  no workflow file was modified
```

Exit codes: `0` fine · `1` nothing parsed, check roots · `2` bad arguments or
a missing root · **`3` a workflow file was modified — stop immediately and
report.**

### A3. Exact missing-node audit

Start ComfyUI, then:

```
curl.exe -s http://127.0.0.1:8188/object_info -o object_info.json
python -m tools.workflow_library.index_workflows --root <each root> --object-info object_info.json
```

Use `curl.exe` with `-o`. In PowerShell, `curl` is an alias for
`Invoke-WebRequest` and `>` writes UTF-16. The loader tolerates both, but a
clean capture removes a variable.

The unresolved-nodes list should shrink sharply. What remains is genuinely
missing from this install.

### A4. Resolve the missing nodes to packs — the useful part

For each node type still unresolved, work out which custom node pack provides
it, and whether that pack is installed-but-broken, uninstalled, or dead
upstream. If ComfyUI-Manager is installed, its node-to-pack map is the fastest
source; otherwise search.

Produce a table: node type · owning pack · how many workflows need it · status ·
recommended action. Do **not** install anything as a result — this is a
findings table for the owner.

Note especially any pack that is installed but failing to register (check the
server console at startup for import errors). `comfyui_civitai_ingestor` is
known-unreliable and may be one of them.

### A5. Seed the tag sidecars

```
python -m tools.workflow_library.index_workflows --root <each root> --object-info object_info.json --write-tags
```

Writes `<workflow>.tags.txt` beside each workflow. Never inside them.
Re-running is idempotent.

### A6. Assess the tag quality — and propose better rules

This is the part with the most judgement in it, so do it properly. Read the
tag-frequency table, then sample ~20 workflows across different models and
compare their tags against what the graph actually does.

Look for: tags on nearly everything (useless for filtering), tags on almost
nothing (rules that never fire), model families present in the library with no
rule at all, and wrong attributions.

The rules are a plain data table in `tools/workflow_library/tagging.py`. Propose
concrete additions and changes as a diff, with the evidence for each. Apply
them, re-run, and show the before/after frequency tables. Add a test for any
rule with a non-obvious pattern.

Note the existing patterns anchor at word start but not word end, deliberately:
`\bflux` matches `flux1-dev.safetensors` where `\bflux\b` does not. Keep that.

### A7. Verify the wildcard export

```
python -m tools.workflow_library.export_wildcards --out wildcards
```

Expect 216 files / 1192 phrases across `flux` and `qwen`. If the owner has an
arch-pt user option store at `user/arch_prompt_tools/options.json`, it is merged
in automatically and the counts will be higher — say so if that happens.

### A8. Prove wildcard resolution actually works

Do not rely on the files merely existing. Verify adaptiveprompts resolves them.

Preferred: read the adaptiveprompts source, find its wildcard resolver, and call
it directly in Python against the installed `wildcards/` directory with a token
like `__archpt/flux/camera/focal_length__`. Deterministic, no GPU needed.

Fallback: build a **new scratch** API-format workflow with the Prompt Generator
node feeding a text preview node, POST it to `/prompt`, and read the result back
from `/history`.

Also verify the variable form — assign with `__archpt/flux/identity/hair_color^hair__`
and reuse as `__^hair__` — produces the same value in both positions. That
behaviour is the whole reason for adopting this over the node chain, so prove
it rather than assuming it.

### A9. Prepare the duplicate triage — prepare only

For each duplicate family in `report.md`, gather what the owner needs to choose
a keeper without opening every file: member paths, modification dates, file
sizes, and the differences that matter (which models, which seeds, resolution,
frame count, prompt text). Where the members differ only in widget values, say
which values.

Recommend a keeper per family with one line of reasoning. **Then stop.** Do not
move, rename, archive or delete anything.

---

## 5. Track B — needs the owner

Do not attempt these unattended. Prepare whatever you can, then hand over. The
numbers in brackets are the corresponding steps in the [owner's runbook][runbook].

- **B1. SmartGallery install and first index** (runbook 10–13). You may download the portable
  build from <https://github.com/biagiomaf/smart-comfyui-gallery> and unpack it,
  but the owner points it at the output folder and judges the results. The
  workflow-recovery test (select an image, `W` / `C`, paste onto canvas) is a
  human check.
- **B2. Duplicate deletion** (runbook 22). Prepared in A9, decided by the owner. Rule 2.
- **B3. Tag taste** (runbook 15). You propose rules in A6; the owner confirms the vocabulary
  matches how they actually think about their work.
- **B4. Addon install** (runbook 16–17), if they want you to run it rather than doing it
  themselves:
  ```
  powershell -ExecutionPolicy Bypass -File .\tools\workflow_library\install_addons.ps1 -ComfyRoot C:\tools\image\ComfyUI
  ```
  Installs adaptiveprompts, Autocomplete-Plus and g-workflows, and copies the
  wildcards into place. Ask first — it writes into `custom_nodes`. Afterwards
  the server needs a full restart and the browser a hard refresh (`Ctrl+F5`);
  you can do the former, not the latter.
- **B5. Browser-side verification** (runbook 18, 21). That the g-workflows button appears, that
  tag suggestions raise in a text widget. You can confirm the *backend* half —
  new node types present in a fresh `/object_info`, extension files on disk —
  and should, but the UI check is theirs.
- **B6. Disabling ComfyUI-Custom-Scripts autocomplete** (runbook 19), if that pack is
  installed. It binds the same text widgets as Autocomplete-Plus and the two
  conflict. Find the setting key in the pack's source and the settings file
  under `user/default/`, and propose the exact edit rather than making it blind.

---

## 6. Reporting back

Commit your work to `claude/workflow-addons-research-h8v30e` in small, focused
commits. Then write a single summary covering:

1. The four indexer summary lines, plus the workflow roots you found and their
   counts.
2. The missing-node table from A4, with recommended actions.
3. Tag rule changes you made and the before/after frequency tables.
4. Wildcard resolution: confirmed working, or what failed and why.
5. Duplicate families with your recommended keeper for each — as a decision
   list for the owner, not a completed action.
6. Anything that failed, threw, or silently did nothing. Especially any pack
   failing to register at server startup.

If the indexer ever exits `3`, that report is one line long and comes first.

## 7. Scope

Everything above is bounded by the hard rules in section 2. If you find a real
problem outside this scope — a broken pack, a corrupt workflow, a bad
assumption in the research — write it up in the report. Do not fix it on your
own initiative.
