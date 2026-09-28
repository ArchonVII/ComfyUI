"""Versioned local documents for Preset Studio's prompt/workflow builder."""

from __future__ import annotations

import copy
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core import compile_graph, suggest_adapter, validate_graph


CURATED_NODE_TYPES = {
    "CheckpointLoaderSimple": "model", "UNETLoader": "model",
    "CLIPLoader": "model", "DualCLIPLoader": "model",
    "LoraLoader": "lora", "LoraLoaderModelOnly": "lora",
    "LoadImage": "reference", "CLIPTextEncode": "conditioning",
    "KSampler": "sampler", "KSamplerAdvanced": "sampler",
    "EmptyLatentImage": "latent", "VAEDecode": "decode",
    "SaveImage": "output", "PreviewImage": "output",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _name(value: Any) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 160 or any(character in value for character in "\r\n\0"):
        raise ValueError("Builder name must be 1-160 characters on one line")
    return value


def _normalize_board(board: Mapping[str, Any] | None) -> dict[str, Any]:
    blocks = []
    seen = set()
    for raw in (board or {}).get("blocks", []):
        block_id = str(raw.get("id") or uuid.uuid4().hex)
        if block_id in seen:
            raise ValueError(f"Duplicate prompt block ID: {block_id}")
        seen.add(block_id)
        lane = raw.get("lane")
        if lane not in {"positive", "negative"}:
            raise ValueError("Prompt block lane must be positive or negative")
        text = str(raw.get("text") or "").strip()
        if not text:
            raise ValueError("Prompt blocks require text")
        weight = float(raw.get("weight", 1))
        if not 0 < weight <= 4:
            raise ValueError("Prompt block weight must be greater than 0 and at most 4")
        blocks.append({
            **copy.deepcopy(dict(raw)), "id": block_id, "lane": lane,
            "text": text, "weight": weight,
            "enabled": bool(raw.get("enabled", True)),
        })
    return {"blocks": blocks}


def _normalize_resources(resources: Mapping[str, Any] | None) -> dict[str, Any]:
    if resources is None:
        resources = {}
    if not isinstance(resources, Mapping):
        raise ValueError("Builder resources must be an object")
    model = resources.get("model")
    if model is not None:
        model = str(model).strip() or None
    references = resources.get("references") or []
    if not isinstance(references, list) or any(
        not isinstance(value, str) or not value.strip() for value in references
    ):
        raise ValueError("Builder references must be nonempty string IDs")
    references = list(dict.fromkeys(references))
    normalized_loras = []
    loras = resources.get("loras") or []
    if not isinstance(loras, list):
        raise ValueError("Builder LoRAs must be a list")
    for source in loras:
        if not isinstance(source, Mapping):
            raise ValueError("Builder LoRAs must be objects")
        name = str(source.get("name") or "").strip()
        if not name:
            raise ValueError("A Builder LoRA needs a filename")
        item = {
            "name": name, "model": float(source.get("model", 1)),
            "clip": float(source.get("clip", 1)),
        }
        if not all(
            math.isfinite(item[key]) and -10 <= item[key] <= 10
            for key in ("model", "clip")
        ):
            raise ValueError("LoRA strengths must be finite and between -10 and 10")
        normalized_loras.append(item)
    return {"model": model, "loras": normalized_loras, "references": references}


def render_prompt_board(board: Mapping[str, Any]) -> dict[str, str]:
    normalized = _normalize_board(board)
    rendered = {"positive": [], "negative": []}
    for block in normalized["blocks"]:
        if not block["enabled"]:
            continue
        value = block["text"]
        if block["weight"] != 1:
            value = f"({value}:{block['weight']:g})"
        rendered[block["lane"]].append(value)
    return {lane: ", ".join(values) for lane, values in rendered.items()}


def build_prompt_catalog(
    builtin_path: Path, presets: list[Mapping[str, Any]],
    wildcard_roots: list[Path], *, query: str = ""
) -> list[dict[str, Any]]:
    """Read linked sources on demand and return one searchable item shape."""
    items = []
    path = Path(builtin_path)
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        for option in payload.get("options", []):
            phrases = option.get("phrases") or {}
            text = phrases.get("flux") or next(iter(phrases.values()), "")
            if text:
                items.append({
                    "id": f"builtin:{option['id']}", "label": option.get("label") or text,
                    "text": text, "category": option.get("node", "builtin"),
                    "group": option.get("group") or option.get("field"), "source": "builtin",
                })
    for preset in presets:
        for lane in ("positive", "negative"):
            text = str(preset.get(lane) or "").strip()
            if text:
                items.append({
                    "id": f"preset:{preset.get('id')}:{lane}",
                    "label": f"{preset.get('name', 'Preset')} · {lane}", "text": text,
                    "category": "presets", "group": lane, "source": "preset",
                })
    for root_value in wildcard_roots:
        root = Path(root_value)
        if not root.is_dir():
            continue
        for wildcard in sorted(root.rglob("*.txt"), key=lambda item: str(item).casefold()):
            relative = wildcard.relative_to(root).with_suffix("").as_posix()
            for index, line in enumerate(wildcard.read_text(encoding="utf-8-sig").splitlines()):
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                items.append({
                    "id": f"wildcard:{root}:{relative}:{index}", "label": text,
                    "text": text, "category": "wildcards", "group": relative,
                    "source": "wildcard", "linked_path": str(wildcard.resolve()),
                })
    needle = str(query).strip().casefold()
    if needle:
        items = [
            item for item in items
            if needle in " ".join(str(value) for value in item.values()).casefold()
        ]
    return items


def import_workflow_document(
    graph: Mapping[str, Any], adapter: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    validate_graph(graph)
    source = copy.deepcopy(dict(graph))
    blocks = []
    advanced = {}
    for node_id, node in source.items():
        class_type = node["class_type"]
        kind = CURATED_NODE_TYPES.get(class_type)
        block = {
            "id": f"node:{node_id}", "node_id": node_id,
            "label": node.get("_meta", {}).get("title") or class_type,
            "class_type": class_type, "kind": kind or "advanced",
            "collapsed": not bool(kind),
        }
        blocks.append(block)
        if not kind:
            advanced[node_id] = copy.deepcopy(node)
    return {
        "blocks": blocks, "connections": [], "advanced_nodes": advanced,
        "source_graph": source, "adapter": copy.deepcopy(dict(adapter or suggest_adapter(source))),
    }


def create_basic_image_workflow() -> dict[str, Any]:
    graph = {
        "model": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "choose-a-model.safetensors"}},
        "positive": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive Prompt"}, "inputs": {"text": "", "clip": ["model", 1]}},
        "negative": {"class_type": "CLIPTextEncode", "_meta": {"title": "Negative Prompt"}, "inputs": {"text": "", "clip": ["model", 1]}},
        "latent": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "sampler": {"class_type": "KSampler", "inputs": {
            "seed": 1, "steps": 25, "cfg": 7.0, "sampler_name": "euler",
            "scheduler": "normal", "denoise": 1.0, "model": ["model", 0],
            "positive": ["positive", 0], "negative": ["negative", 0],
            "latent_image": ["latent", 0],
        }},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": ["model", 2]}},
        "output": {"class_type": "SaveImage", "inputs": {"filename_prefix": "PresetStudio", "images": ["decode", 0]}},
    }
    return import_workflow_document(graph, {
        "positive": ["positive.text"], "negative": ["negative.text"],
        "references": [], "seed": ["sampler.seed"], "model": ["model", 0],
        "clip": ["model", 1],
    })


def compile_builder_option(option: Mapping[str, Any]) -> dict[str, Any]:
    workflow = option.get("workflow_graph") or {}
    source = workflow.get("source_graph")
    if not isinstance(source, Mapping) or not source:
        raise ValueError("Builder option needs an imported or constructed workflow graph")
    graph = copy.deepcopy(dict(source))
    adapter = workflow.get("adapter") or suggest_adapter(graph)
    prompts = render_prompt_board(option.get("prompt_board") or {"blocks": []})
    seed = int((option.get("settings") or {}).get("seed", 1))
    resources = _normalize_resources(option.get("resources"))
    composition = {
        **prompts, "references": list(resources.get("references") or []),
        "loras": copy.deepcopy(resources.get("loras") or []),
    }
    model = resources.get("model")
    if model:
        for node in graph.values():
            if node["class_type"] == "CheckpointLoaderSimple" and "ckpt_name" in node["inputs"]:
                node["inputs"]["ckpt_name"] = model
    return compile_graph(graph, adapter, composition, seed)


def _new_option(name: str = "Option A") -> dict[str, Any]:
    now = _now()
    return {
        "id": uuid.uuid4().hex, "name": _name(name), "parent_option_id": None,
        "prompt_board": {"blocks": []},
        "workflow_graph": {"blocks": [], "connections": [], "advanced_nodes": {}},
        "resources": {"model": None, "loras": [], "references": []},
        "settings": {}, "revision_ids": [], "created_at": now, "updated_at": now,
    }


class BuilderStore:
    VERSION = 1

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "builder-state.json"
        if self.path.exists():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            if self.state.get("version") != self.VERSION:
                raise ValueError("Unsupported Builder state version")
        else:
            self.state = {"version": self.VERSION, "experiments": [], "revisions": [], "favorites": [], "bundles": []}
        self.state.setdefault("favorites", [])
        self.state.setdefault("bundles", [])

    def _persist(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        content = json.dumps(self.state, ensure_ascii=False, indent=2, allow_nan=False)
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def create_experiment(self, name: Any) -> dict[str, Any]:
        option = _new_option()
        experiment = {
            "id": uuid.uuid4().hex, "name": _name(name), "options": [option],
            "created_at": _now(), "updated_at": _now(),
        }
        self.state["experiments"].append(experiment)
        self._persist()
        return copy.deepcopy(experiment)

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    def toggle_favorite(self, item_id: str) -> list[str]:
        item_id = str(item_id).strip()
        if not item_id:
            raise ValueError("Favorite item ID required")
        favorites = self.state["favorites"]
        if item_id in favorites:
            favorites.remove(item_id)
        else:
            favorites.append(item_id)
        self._persist()
        return copy.deepcopy(favorites)

    def save_bundle(self, name: Any, prompt_board: Mapping[str, Any]) -> dict[str, Any]:
        bundle = {
            "id": uuid.uuid4().hex, "name": _name(name),
            "prompt_board": _normalize_board(prompt_board), "created_at": _now(),
        }
        self.state["bundles"].append(bundle)
        self._persist()
        return copy.deepcopy(bundle)

    def _option(self, option_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        for experiment in self.state["experiments"]:
            for option in experiment["options"]:
                if option["id"] == option_id:
                    return experiment, option
        raise ValueError(f"Unknown Builder option: {option_id}")

    def get_option(self, option_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._option(option_id)[1])

    def update_option(self, option_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        experiment, option = self._option(option_id)
        allowed = {"name", "prompt_board", "workflow_graph", "resources", "settings"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("Unknown option fields: " + ", ".join(sorted(unknown)))
        for key, value in changes.items():
            if key == "name":
                option[key] = _name(value)
            elif key == "prompt_board":
                option[key] = _normalize_board(value)
            elif key == "resources":
                option[key] = _normalize_resources(value)
            else:
                option[key] = copy.deepcopy(value)
        option["updated_at"] = experiment["updated_at"] = _now()
        self._persist()
        return copy.deepcopy(option)

    def branch_option(self, option_id: str, name: Any) -> dict[str, Any]:
        experiment, source = self._option(option_id)
        branch = copy.deepcopy(source)
        branch.update(
            id=uuid.uuid4().hex, name=_name(name), parent_option_id=source["id"],
            revision_ids=[], created_at=_now(), updated_at=_now(),
        )
        experiment["options"].append(branch)
        experiment["updated_at"] = _now()
        self._persist()
        return copy.deepcopy(branch)

    def delete_option(self, option_id: str) -> dict[str, Any]:
        experiment, option = self._option(option_id)
        experiment["options"] = [
            item for item in experiment["options"] if item["id"] != option["id"]
        ]
        deleted_experiment_id = None
        if experiment["options"]:
            experiment["updated_at"] = _now()
        else:
            deleted_experiment_id = experiment["id"]
            self.state["experiments"] = [
                item for item in self.state["experiments"]
                if item["id"] != experiment["id"]
            ]
        self._persist()
        return {
            "deleted_option_id": option["id"],
            "deleted_experiment_id": deleted_experiment_id,
        }

    def create_revision(
        self, option_id: str, compiled_graph: Mapping[str, Any]
    ) -> dict[str, Any]:
        experiment, option = self._option(option_id)
        snapshot = copy.deepcopy(option)
        revision = {
            "id": uuid.uuid4().hex, "experiment_id": experiment["id"],
            "option_id": option_id, "option_snapshot": snapshot,
            "compiled_graph": copy.deepcopy(dict(compiled_graph)),
            "outputs": [], "created_at": _now(),
        }
        self.state["revisions"].append(revision)
        option["revision_ids"].append(revision["id"])
        self._persist()
        return copy.deepcopy(revision)

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        revision = next(
            (item for item in self.state["revisions"] if item["id"] == revision_id),
            None,
        )
        if revision is None:
            raise ValueError(f"Unknown Builder revision: {revision_id}")
        return copy.deepcopy(revision)

    def attach_revision_outputs(
        self, revision_id: str, outputs: list[Mapping[str, Any]]
    ) -> dict[str, Any]:
        revision = next(
            (item for item in self.state["revisions"] if item["id"] == revision_id), None
        )
        if revision is None:
            raise ValueError(f"Unknown Builder revision: {revision_id}")
        revision["outputs"] = copy.deepcopy(list(outputs))
        self._persist()
        return copy.deepcopy(revision)
