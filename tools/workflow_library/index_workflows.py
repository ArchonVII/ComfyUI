"""Index a ComfyUI workflow library by content, and report its duplicates.

Filename search is useless in a library where numeric prefixes are invented
just to force a new save. This walks the workflow roots, reads what each graph
actually contains, groups the re-saved families by graph shape, flags graphs
whose node packs are missing, and can seed ``.tags.txt`` sidecars so a browser
like g-workflows is useful on first launch instead of empty.

Workflow files are only ever read. Tag sidecars are written beside them, and
only when ``--write-tags`` is passed; the run verifies afterwards that no
workflow's modification time moved.

    python -m tools.workflow_library.index_workflows --root user/default/workflows
    python -m tools.workflow_library.index_workflows --root <dir> --write-tags
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

if __package__ in (None, ""):  # allow `python tools/workflow_library/index_workflows.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.workflow_library.tagging import derive_tags, format_sidecar
    from tools.workflow_library.workflow_scan import (
        Workflow,
        WorkflowParseError,
        collect_known_nodes,
        iter_workflow_files,
        load_object_info,
        parse_workflow,
    )
else:
    from .tagging import derive_tags, format_sidecar
    from .workflow_scan import (
        Workflow,
        WorkflowParseError,
        collect_known_nodes,
        iter_workflow_files,
        load_object_info,
        parse_workflow,
    )

DEFAULT_ROOT = Path("user/default/workflows")


@dataclass
class Entry:
    workflow: Workflow
    packs: list[str]
    unresolved: list[str]
    tags: list[str]
    structural: str
    composition: str
    mtime: float
    size: int


def build_index(
    roots: Sequence[Path],
    comfy_root: Path,
    object_info: Path | None = None,
) -> tuple[list[Entry], list[tuple[Path, str]]]:
    known = collect_known_nodes(comfy_root)
    if object_info is not None:
        # An /object_info dump is authoritative: it comes from the running
        # server, so it overrides anything the static scan guessed.
        known.update(load_object_info(object_info))
    entries: list[Entry] = []
    skipped: list[tuple[Path, str]] = []

    parsed: list[Workflow] = []
    for path in iter_workflow_files(roots):
        try:
            parsed.append(parse_workflow(path))
        except WorkflowParseError as exc:
            skipped.append((path, str(exc)))

    # Duplicate keys must be known before tags are derived, so that every
    # member of a family carries the same dup: tag.
    families: dict[str, list[Workflow]] = defaultdict(list)
    for workflow in parsed:
        families[workflow.structural_hash()].append(workflow)

    for workflow in parsed:
        structural = workflow.structural_hash()
        packs: list[str] = []
        unresolved: list[str] = []
        for node_type in sorted(set(workflow.node_types)):
            if node_type in workflow.local_types:
                # A subgraph instance; its definition travels inside the same
                # file, so no pack needs to provide it.
                continue
            owner = known.get(node_type)
            if owner is None:
                unresolved.append(node_type)
            elif owner not in packs:
                packs.append(owner)

        duplicate_key = structural if len(families[structural]) > 1 else None
        stat = workflow.path.stat()
        entries.append(
            Entry(
                workflow=workflow,
                packs=packs,
                unresolved=unresolved,
                tags=derive_tags(
                    workflow,
                    packs=packs,
                    duplicate_key=duplicate_key,
                    unresolved=unresolved,
                ),
                structural=structural,
                composition=workflow.composition_hash(),
                mtime=stat.st_mtime,
                size=stat.st_size,
            )
        )

    entries.sort(key=lambda e: str(e.workflow.path))
    return entries, skipped


def group_families(entries: Sequence[Entry], key: str) -> list[list[Entry]]:
    buckets: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        buckets[getattr(entry, key)].append(entry)
    families = [sorted(v, key=lambda e: e.mtime) for v in buckets.values() if len(v) > 1]
    families.sort(key=lambda group: (-len(group), str(group[0].workflow.path)))
    return families


def index_payload(entries: Sequence[Entry], skipped: Sequence[tuple[Path, str]]) -> dict:
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(entries),
        "workflows": [
            {
                "path": str(entry.workflow.path),
                "format": entry.workflow.fmt,
                "title": entry.workflow.title,
                "nodes": entry.workflow.node_count,
                "structural_hash": entry.structural,
                "composition_hash": entry.composition,
                "tags": entry.tags,
                "packs": entry.packs,
                "unresolved_nodes": entry.unresolved,
                "models": entry.workflow.models,
                "node_types": sorted(set(entry.workflow.node_types)),
                "prompt_excerpts": [p[:280] for p in entry.workflow.prompts[:5]],
                "mtime": entry.mtime,
                "size": entry.size,
            }
            for entry in entries
        ],
        "skipped": [{"path": str(p), "reason": r} for p, r in skipped],
    }


def _stamp(entry: Entry) -> str:
    return datetime.fromtimestamp(entry.mtime, tz=timezone.utc).strftime("%Y-%m-%d")


def render_report(entries: Sequence[Entry], skipped: Sequence[tuple[Path, str]]) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Workflow library report")
    add("")
    add(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.")
    add(f"Indexed **{len(entries)}** workflows.")
    if skipped:
        add(f"Skipped {len(skipped)} file(s) that did not parse as workflows.")
    add("")

    exact = group_families(entries, "structural")
    add("## Duplicate families (identical graph shape)")
    add("")
    add(
        "Same node types wired the same way. Widget values, seeds, prompts, "
        "positions and titles are ignored, so these are the same workflow "
        "re-saved -- whatever the filenames claim."
    )
    add("")
    if not exact:
        add("_None found._")
    else:
        covered = sum(len(f) for f in exact)
        add(f"**{len(exact)} families covering {covered} files.**")
        add("")
        for family in exact:
            add(f"### `dup:{family[0].structural}` &mdash; {len(family)} files")
            add("")
            add("| modified | size | file |")
            add("| --- | --- | --- |")
            for entry in family:
                add(
                    f"| {_stamp(entry)} | {entry.size:,} | "
                    f"`{entry.workflow.path}` |"
                )
            add("")
            add(f"Newest: `{family[-1].workflow.path}`")
            add("")

    loose = [
        family
        for family in group_families(entries, "composition")
        if len({e.structural for e in family}) > 1
    ]
    add("## Near-duplicates (same nodes, different wiring)")
    add("")
    add("Same node inventory, wired differently -- a variant rather than a re-save.")
    add("")
    if not loose:
        add("_None found._")
    else:
        for family in loose:
            add(f"### `{family[0].composition}` &mdash; {len(family)} files")
            add("")
            for entry in family:
                add(f"- `{entry.workflow.path}` ({_stamp(entry)})")
            add("")

    broken = [e for e in entries if e.unresolved]
    add("## Workflows referencing unavailable nodes")
    add("")
    add(
        "Node types with no `NODE_CLASS_MAPPINGS` entry anywhere in this install. "
        "Packs that build their mappings dynamically are invisible to a static "
        "scan, so treat this as a shortlist to check rather than proof."
    )
    add("")
    if not broken:
        add("_None found._")
    else:
        for entry in broken:
            add(f"- `{entry.workflow.path}`")
            add(f"  - missing: {', '.join(f'`{n}`' for n in entry.unresolved)}")
        add("")

    add("## Pack usage")
    add("")
    counts = Counter(pack for entry in entries for pack in entry.packs)
    if not counts:
        add("_No packs resolved._")
    else:
        add("| pack | workflows |")
        add("| --- | ---: |")
        for pack, count in counts.most_common():
            add(f"| `{pack}` | {count} |")
    add("")

    add("## Tag frequency")
    add("")
    tag_counts = Counter(
        tag for entry in entries for tag in entry.tags if not tag.startswith("dup:")
    )
    if not tag_counts:
        add("_No tags derived._")
    else:
        add("| tag | workflows |")
        add("| --- | ---: |")
        for tag, count in tag_counts.most_common():
            add(f"| `{tag}` | {count} |")
    add("")

    if skipped:
        add("## Skipped files")
        add("")
        for path, reason in skipped:
            add(f"- `{path}` &mdash; {reason}")
        add("")

    return "\n".join(lines)


def write_tag_sidecars(entries: Iterable[Entry]) -> list[Path]:
    written: list[Path] = []
    for entry in entries:
        sidecar = entry.workflow.path.with_suffix(".tags.txt")
        content = format_sidecar(entry.tags)
        if sidecar.exists() and sidecar.read_text(encoding="utf-8") == content:
            continue
        sidecar.write_text(content, encoding="utf-8")
        written.append(sidecar)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Index a ComfyUI workflow library by content and report duplicates.",
    )
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        help="Workflow folder to scan. Repeatable. Defaults to user/default/workflows.",
    )
    parser.add_argument(
        "--comfy-root",
        type=Path,
        default=Path.cwd(),
        help="ComfyUI install root, used to resolve which pack owns each node type.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("tools/workflow_library/out"),
        help="Directory for index.json and report.md.",
    )
    parser.add_argument(
        "--object-info",
        type=Path,
        help=(
            "Path to a /object_info dump from a running ComfyUI "
            "(curl -s http://127.0.0.1:8188/object_info > object_info.json). "
            "Makes the missing-node audit exact instead of best-effort."
        ),
    )
    parser.add_argument(
        "--write-tags",
        action="store_true",
        help="Write .tags.txt sidecars next to each workflow (g-workflows format).",
    )
    args = parser.parse_args(argv)

    roots = args.root or [DEFAULT_ROOT]
    missing = [r for r in roots if not Path(r).exists()]
    if missing:
        for root in missing:
            print(f"error: no such workflow root: {root}", file=sys.stderr)
        return 2

    if args.object_info is not None and not args.object_info.is_file():
        print(f"error: no such object_info dump: {args.object_info}", file=sys.stderr)
        return 2

    entries, skipped = build_index(roots, args.comfy_root, args.object_info)
    if not entries:
        print("error: no workflows parsed; check --root", file=sys.stderr)
        return 1

    before = {e.workflow.path: e.workflow.path.stat().st_mtime_ns for e in entries}

    args.out.mkdir(parents=True, exist_ok=True)
    index_path = args.out / "index.json"
    report_path = args.out / "report.md"
    index_path.write_text(
        json.dumps(index_payload(entries, skipped), indent=2) + "\n", encoding="utf-8"
    )
    report_path.write_text(render_report(entries, skipped) + "\n", encoding="utf-8")

    written: list[Path] = []
    if args.write_tags:
        written = write_tag_sidecars(entries)

    # The whole point of this tool is that it does not disturb the library.
    touched = [
        str(path)
        for path, stamp in before.items()
        if path.stat().st_mtime_ns != stamp
    ]
    if touched:
        print(
            "error: workflow files were modified: " + ", ".join(touched), file=sys.stderr
        )
        return 3

    families = group_families(entries, "structural")
    duplicate_files = sum(len(f) for f in families)
    print(f"indexed   {len(entries)} workflows from {len(roots)} root(s)")
    print(f"duplicates {len(families)} families covering {duplicate_files} files")
    print(f"unresolved {sum(1 for e in entries if e.unresolved)} workflows reference missing nodes")
    if skipped:
        print(f"skipped   {len(skipped)} unparseable file(s)")
    print(f"wrote     {index_path}")
    print(f"wrote     {report_path}")
    if args.write_tags:
        print(f"wrote     {len(written)} tag sidecar(s)")
    else:
        print("note      re-run with --write-tags to emit .tags.txt sidecars")
    print("verified  no workflow file was modified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
