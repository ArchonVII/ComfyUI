"""Export the arch-pt option catalog as adaptiveprompts wildcard files.

Building one prompt through arch-pt costs six focused nodes plus Combine, all
wired by hand, and the catalog behind those nodes lives in a JSON blob that is
awkward to diff. The same 596 phrases work as plain wildcard files, callable
from a single text box::

    __archpt/flux/camera/focal_length__, __archpt/flux/lighting/primary_color__

Output layout, one file per catalog field::

    <out>/archpt/<family>/<node>/<field>.txt

so ``__archpt/flux/camera/*__`` draws from any camera field and
``__archpt/flux/*/*__`` from the whole catalog. Nothing under
``custom_nodes/comfyui_arch_prompt_tools/`` is modified -- the catalog is read
only, and the arch-pt nodes keep working exactly as before.

    python -m tools.workflow_library.export_wildcards --out wildcards
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

DEFAULT_CATALOG = Path(
    "custom_nodes/comfyui_arch_prompt_tools/data/builtin_options.json"
)
DEFAULT_OUT = Path("wildcards")
NAMESPACE = "archpt"

_HEADER = "## {node}/{field} -- exported from arch-pt, {count} options ##"


def load_options(catalog: Path, user_options: Path | None = None) -> list[dict[str, Any]]:
    """Read catalog options, plus any user-added options if a store exists."""
    data = json.loads(catalog.read_text(encoding="utf-8"))
    options = list(data.get("options", []))

    if user_options is not None and user_options.is_file():
        extra = json.loads(user_options.read_text(encoding="utf-8"))
        if isinstance(extra, dict):
            extra = extra.get("options", [])
        if isinstance(extra, list):
            options.extend(o for o in extra if isinstance(o, dict))

    return [o for o in options if isinstance(o, dict)]


def group_options(
    options: Sequence[dict[str, Any]],
) -> dict[tuple[str, str, str], list[str]]:
    """Bucket phrases by ``(family, node, field)``, preserving catalog order."""
    grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for option in options:
        node = _slug(option.get("node"))
        field = _slug(option.get("field"))
        phrases = option.get("phrases")
        if not node or not field or not isinstance(phrases, dict):
            continue
        for family, phrase in phrases.items():
            if not isinstance(phrase, str):
                continue
            text = " ".join(phrase.split())
            if not text:
                continue
            bucket = grouped[(_slug(family), node, field)]
            if text not in bucket:
                bucket.append(text)
    return grouped


def render_file(node: str, field: str, phrases: Sequence[str]) -> str:
    """One phrase per line, with a provenance comment adaptiveprompts ignores."""
    header = _HEADER.format(node=node, field=field, count=len(phrases))
    return "\n".join([header, *phrases]) + "\n"


def write_tree(
    grouped: dict[tuple[str, str, str], list[str]],
    out_root: Path,
    namespace: str = NAMESPACE,
) -> list[Path]:
    written: list[Path] = []
    for (family, node, field), phrases in sorted(grouped.items()):
        target = out_root / namespace / family / node / f"{field}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_file(node, field, phrases), encoding="utf-8")
        written.append(target)
    return written


def render_cheatsheet(
    grouped: dict[tuple[str, str, str], list[str]], namespace: str = NAMESPACE
) -> str:
    """A copy-paste reference: every wildcard token this export produced."""
    families = sorted({family for family, _, _ in grouped})
    lines = [
        "# arch-pt wildcards",
        "",
        "Exported by `tools/workflow_library/export_wildcards.py`. Re-run it after",
        "editing the arch-pt catalog; edits made directly to these files are",
        "overwritten.",
        "",
        f"Families: {', '.join(f'`{f}`' for f in families)}",
        "",
    ]

    for family in families:
        lines.append(f"## `{family}`")
        lines.append("")
        by_node: dict[str, list[str]] = defaultdict(list)
        for (fam, node, field), phrases in sorted(grouped.items()):
            if fam == family:
                by_node[node].append(f"`__{namespace}/{fam}/{node}/{field}__` ({len(phrases)})")
        for node, tokens in sorted(by_node.items()):
            lines.append(f"### {node}")
            lines.append("")
            lines.extend(f"- {token}" for token in tokens)
            lines.append("")

        lines.append("Whole-node draw:")
        lines.append("")
        lines.extend(
            f"- `__{namespace}/{family}/{node}/*__`" for node in sorted(by_node)
        )
        lines.append("")

    lines.extend(
        [
            "## Example",
            "",
            "The six-node arch-pt chain, as one text field:",
            "",
            "```",
            f"__{NAMESPACE}/flux/identity/*__, __{NAMESPACE}/flux/pose/base_pose__,",
            f"__{NAMESPACE}/flux/clothing/outfit_type__, __{NAMESPACE}/flux/environment/location_type__,",
            f"__{NAMESPACE}/flux/camera/focal_length__, __{NAMESPACE}/flux/lighting/primary_direction__",
            "```",
            "",
            "Hold a value steady across positive, negative and style fields by",
            "assigning it once and reusing the variable:",
            "",
            "```",
            f"__{NAMESPACE}/flux/identity/hair_color^hair__ ... later ... __^hair__",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _slug(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace(" ", "_").replace("/", "_")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the arch-pt catalog as adaptiveprompts wildcard files.",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--user-options",
        type=Path,
        default=Path("user/arch_prompt_tools/options.json"),
        help="Optional arch-pt user option store to merge in, if it exists.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=(
            "Destination root. Locally this is "
            "custom_nodes/comfyui-adaptiveprompts/wildcards."
        ),
    )
    parser.add_argument("--namespace", default=NAMESPACE)
    args = parser.parse_args(argv)

    if not args.catalog.is_file():
        print(f"error: no such catalog: {args.catalog}", file=sys.stderr)
        return 2

    options = load_options(args.catalog, args.user_options)
    grouped = group_options(options)
    if not grouped:
        print("error: catalog produced no phrases", file=sys.stderr)
        return 1

    written = write_tree(grouped, args.out, args.namespace)
    cheatsheet = args.out / args.namespace / "README.md"
    cheatsheet.write_text(render_cheatsheet(grouped, args.namespace), encoding="utf-8")

    families = sorted({family for family, _, _ in grouped})
    phrases = sum(len(v) for v in grouped.values())
    print(f"read      {len(options)} catalog options")
    print(f"families  {', '.join(families)}")
    print(f"wrote     {len(written)} wildcard files ({phrases} phrases) under {args.out / args.namespace}")
    print(f"wrote     {cheatsheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
