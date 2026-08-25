"""Read-only inspection of saved ComfyUI workflow files.

Everything here treats workflow JSON as immutable input. Nothing in this
module opens a workflow file for writing; the only files the package ever
writes are sidecars and reports, and that happens in the CLI layer.

Two workflow serialisations are understood:

``ui``
    What the editor saves -- a ``nodes`` list plus a ``links`` table.
``api``
    What ``Save (API Format)`` produces -- a flat mapping of node id to
    ``{"class_type": ..., "inputs": {...}}``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

MODEL_SUFFIXES = (
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".gguf",
    ".sft",
    ".onnx",
)

# A widget string has to look like prose before it counts as a prompt: bare
# filenames, enum values and sampler names all live in the same widget list.
_PROMPT_MIN_LEN = 16
_PROMPT_MIN_WORDS = 3

_SKIPPED_DIR_NAMES = {"__pycache__", ".git", "node_modules"}


class WorkflowParseError(ValueError):
    """Raised when a JSON file is not a workflow we can read."""


@dataclass(frozen=True)
class Edge:
    """One link, described by the node *types* it joins rather than their ids."""

    source_type: str
    source_slot: int
    target_type: str
    target_slot: int

    def key(self) -> tuple[str, int, str, int]:
        return (self.source_type, self.source_slot, self.target_type, self.target_slot)


@dataclass
class Workflow:
    path: Path
    fmt: str
    node_types: list[str] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    title: str | None = None

    @property
    def node_count(self) -> int:
        return len(self.node_types)

    def structural_hash(self) -> str:
        """Identity of the graph's *shape*.

        Node ids, canvas positions, titles, colours and every widget value are
        excluded, so a workflow re-saved under a new number with a different
        seed or prompt hashes identically to its original.
        """
        payload = {
            "nodes": sorted(self.node_types),
            "edges": sorted(edge.key() for edge in self.edges),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]

    def composition_hash(self) -> str:
        """Identity of the node *inventory* alone, ignoring how it is wired.

        Looser than :meth:`structural_hash`: it still groups two saves whose
        wiring was nudged between them.
        """
        blob = json.dumps(sorted(self.node_types), separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def iter_workflow_files(roots: Iterable[Path]) -> Iterator[Path]:
    """Yield every ``.json`` under *roots*, skipping caches and VCS folders."""
    for root in roots:
        root = Path(root)
        if root.is_file():
            if root.suffix.lower() == ".json":
                yield root
            continue
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.json")):
            if any(part in _SKIPPED_DIR_NAMES for part in path.parts):
                continue
            yield path


def detect_format(data: Any) -> str:
    if isinstance(data, dict) and isinstance(data.get("nodes"), list):
        return "ui"
    if isinstance(data, dict) and data and _looks_like_api(data):
        return "api"
    raise WorkflowParseError("not a ComfyUI workflow")


def _looks_like_api(data: dict[str, Any]) -> bool:
    for value in data.values():
        if isinstance(value, dict) and "class_type" in value:
            return True
    return False


def parse_workflow(path: Path) -> Workflow:
    """Parse one workflow file. Never opens the file for writing."""
    try:
        # utf-8-sig: workflows exported through Windows tooling often carry a
        # BOM, which json.loads rejects as an invalid leading character.
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:  # pragma: no cover - depends on disk state
        raise WorkflowParseError(f"not utf-8: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkflowParseError(f"invalid json: {exc}") from exc

    fmt = detect_format(data)
    if fmt == "ui":
        return _parse_ui(path, data)
    return _parse_api(path, data)


def _parse_ui(path: Path, data: dict[str, Any]) -> Workflow:
    nodes = [n for n in data.get("nodes", []) if isinstance(n, dict)]
    # Subgraph definitions carry their own node lists; count them too, so a
    # workflow that merely wraps its graph in a subgraph does not read as empty.
    for subgraph in _iter_subgraph_defs(data):
        nodes.extend(n for n in subgraph.get("nodes", []) if isinstance(n, dict))

    by_id: dict[Any, str] = {}
    node_types: list[str] = []
    models: list[str] = []
    prompts: list[str] = []

    for node in nodes:
        node_type = node.get("type") or node.get("class_type")
        if not isinstance(node_type, str):
            continue
        node_types.append(node_type)
        by_id[node.get("id")] = node_type
        for value in _iter_scalars(node.get("widgets_values")):
            _classify_scalar(value, models, prompts)

    edges: list[Edge] = []
    for link in _iter_ui_links(data):
        source_type = by_id.get(link[0])
        target_type = by_id.get(link[2])
        if source_type is None or target_type is None:
            continue
        edges.append(Edge(source_type, link[1], target_type, link[3]))

    return Workflow(
        path=path,
        fmt="ui",
        node_types=node_types,
        edges=edges,
        models=_dedupe(models),
        prompts=_dedupe(prompts),
        title=_ui_title(data),
    )


def _iter_subgraph_defs(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    definitions = data.get("definitions")
    if not isinstance(definitions, dict):
        return
    subgraphs = definitions.get("subgraphs")
    if not isinstance(subgraphs, list):
        return
    for subgraph in subgraphs:
        if isinstance(subgraph, dict):
            yield subgraph


def _iter_ui_links(data: dict[str, Any]) -> Iterator[tuple[Any, int, Any, int]]:
    """Normalise both link encodings to ``(src_id, src_slot, dst_id, dst_slot)``.

    Older saves use ``[link_id, src_id, src_slot, dst_id, dst_slot, type]``
    arrays; newer ones use objects. Subgraph definitions carry their own tables.
    """
    tables: list[Any] = [data.get("links")]
    for subgraph in _iter_subgraph_defs(data):
        tables.append(subgraph.get("links"))

    for links in tables:
        if not isinstance(links, list):
            continue
        for link in links:
            if isinstance(link, list) and len(link) >= 5:
                yield (link[1], _as_int(link[2]), link[3], _as_int(link[4]))
            elif isinstance(link, dict):
                origin = link.get("origin_id", link.get("source_id"))
                target = link.get("target_id")
                if origin is None or target is None:
                    continue
                yield (
                    origin,
                    _as_int(link.get("origin_slot", link.get("source_slot"))),
                    target,
                    _as_int(link.get("target_slot")),
                )


def _parse_api(path: Path, data: dict[str, Any]) -> Workflow:
    by_id: dict[str, str] = {}
    node_types: list[str] = []
    models: list[str] = []
    prompts: list[str] = []

    for node_id, node in data.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if not isinstance(class_type, str):
            continue
        by_id[str(node_id)] = class_type
        node_types.append(class_type)
        inputs = node.get("inputs")
        if isinstance(inputs, dict):
            for value in inputs.values():
                if isinstance(value, (str, int, float)):
                    _classify_scalar(value, models, prompts)

    edges: list[Edge] = []
    for node_id, node in data.items():
        if not isinstance(node, dict):
            continue
        target_type = by_id.get(str(node_id))
        inputs = node.get("inputs")
        if target_type is None or not isinstance(inputs, dict):
            continue
        # An API-format connection is ``[source_node_id, source_slot]``.
        for slot_index, value in enumerate(inputs.values()):
            if not (isinstance(value, list) and len(value) == 2):
                continue
            source_type = by_id.get(str(value[0]))
            if source_type is None:
                continue
            edges.append(Edge(source_type, _as_int(value[1]), target_type, slot_index))

    return Workflow(
        path=path,
        fmt="api",
        node_types=node_types,
        edges=edges,
        models=_dedupe(models),
        prompts=_dedupe(prompts),
        title=None,
    )


def _ui_title(data: dict[str, Any]) -> str | None:
    extra = data.get("extra")
    if isinstance(extra, dict):
        for key in ("workflow_name", "name", "title"):
            value = extra.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _iter_scalars(value: Any) -> Iterator[Any]:
    """Flatten widget values, which nest arbitrarily in newer saves."""
    if isinstance(value, (str, int, float)):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_scalars(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_scalars(item)


def _classify_scalar(value: Any, models: list[str], prompts: list[str]) -> None:
    if not isinstance(value, str):
        return
    text = value.strip()
    if not text:
        return
    if text.lower().endswith(MODEL_SUFFIXES):
        models.append(text.replace("\\", "/"))
        return
    if len(text) >= _PROMPT_MIN_LEN and len(text.split()) >= _PROMPT_MIN_WORDS:
        prompts.append(text)


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


# --------------------------------------------------------------------------
# Which pack owns a node type
# --------------------------------------------------------------------------

_MAPPING_BLOCK = re.compile(
    r"NODE_CLASS_MAPPINGS(?:\s*\.\s*update\s*\(|\s*=\s*|\s*\|=\s*)\s*\{(.*?)\n\}",
    re.DOTALL,
)
_MAPPING_KEY = re.compile(r"""["']([^"'\n]{1,120})["']\s*:""")

# ComfyUI's V3 schema API registers a node by ``io.Schema(node_id="...")``
# inside ``define_schema`` rather than by a NODE_CLASS_MAPPINGS entry. Most of
# comfy_extras uses this form, so a scan that only reads the legacy dict finds a
# small fraction of the real node set and reports the rest as missing.
_SCHEMA_NODE_ID = re.compile(r"""node_id\s*=\s*["']([^"'\n]{1,120})["']""")

# Nodes the frontend implements on its own. They appear in saved graphs but no
# Python class backs them, so they must not be reported as unavailable.
FRONTEND_VIRTUAL_NODES = frozenset(
    {
        "Note",
        "MarkdownNote",
        "Reroute",
        "PrimitiveNode",
        "PrimitiveInt",
        "PrimitiveFloat",
        "PrimitiveString",
        "PrimitiveStringMultiline",
        "PrimitiveBoolean",
    }
)


def collect_known_nodes(comfy_root: Path) -> dict[str, str]:
    """Map node type -> owning pack, by static reading of ``NODE_CLASS_MAPPINGS``.

    This parses source text rather than importing anything, so it stays safe to
    run against packs with missing dependencies -- which is the whole point,
    since the packs we most want to identify are the broken ones. The trade-off
    is that mappings built dynamically (comprehensions, loops) are invisible;
    unresolved node types are reported as unknown rather than silently dropped.
    """
    owners: dict[str, str] = {name: "comfyui-frontend" for name in FRONTEND_VIRTUAL_NODES}

    for source in ("nodes.py",):
        path = comfy_root / source
        if path.is_file():
            for name in _mapping_keys(path):
                owners.setdefault(name, "comfyui-core")

    extras = comfy_root / "comfy_extras"
    if extras.is_dir():
        for path in sorted(extras.glob("nodes_*.py")):
            for name in _mapping_keys(path):
                owners.setdefault(name, "comfyui-core")

    custom_nodes = comfy_root / "custom_nodes"
    if custom_nodes.is_dir():
        for pack_dir in sorted(p for p in custom_nodes.iterdir() if p.is_dir()):
            if pack_dir.name in _SKIPPED_DIR_NAMES:
                continue
            for path in sorted(pack_dir.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                for name in _mapping_keys(path):
                    owners.setdefault(name, pack_dir.name)

    return owners


def load_object_info(path: Path) -> dict[str, str]:
    """Map node type -> owning pack from a ComfyUI ``/object_info`` dump.

    The static scan cannot see mappings built by comprehensions or loops. A
    running ComfyUI knows the real answer, so exporting it once gives an exact
    audit::

        curl -s http://127.0.0.1:8188/object_info > object_info.json

    Each entry carries ``python_module`` such as ``nodes``,
    ``comfy_extras.nodes_video`` or ``custom_nodes.ComfyUI-GGUF``.
    """
    # PowerShell's `>` redirect writes UTF-16 and `Out-File` adds a BOM, so a
    # dump captured the obvious way is rarely plain UTF-8.
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            data = json.loads(raw.decode(encoding))
            break
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    else:
        raise WorkflowParseError(
            "could not read object_info dump as JSON; capture it with "
            "`curl.exe -s <url> -o object_info.json` rather than a `>` redirect"
        )
    if not isinstance(data, dict):
        raise WorkflowParseError("object_info dump is not a JSON object")

    owners: dict[str, str] = {}
    for name, info in data.items():
        module = ""
        if isinstance(info, dict):
            module = str(info.get("python_module") or "")
        if module.startswith("custom_nodes."):
            owner = module.split(".", 2)[1]
        elif module:
            owner = "comfyui-core"
        else:
            owner = "unknown"
        owners[name] = owner
    return owners


def _mapping_keys(path: Path) -> Iterator[str]:
    """Yield every node type *path* registers, in either registration style."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:  # pragma: no cover - depends on disk state
        return
    if "NODE_CLASS_MAPPINGS" in text:
        for block in _MAPPING_BLOCK.findall(text):
            for key in _MAPPING_KEY.findall(block):
                yield key
    if "node_id" in text:
        yield from _SCHEMA_NODE_ID.findall(text)
