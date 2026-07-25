"""ComfyUI nodes for versioned arch prompt-builder snapshots.

The nodes remain import-safe outside ComfyUI: they only use the package's pure
catalog and assembly engine, and return ordinary JSON-compatible values.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .catalog import load_catalog
from .engine import BUNDLE_VERSION, DEFAULT_MODEL_FAMILY, SUPPORTED_MODEL_FAMILIES, assemble, default_state, normalize_state


_DATA_DIRECTORY = Path(__file__).with_name("data")
_WHITESPACE = re.compile(r"\s+")
_FOCUSED_NODE_KEYS = ("identity", "pose", "clothing", "environment", "camera", "lighting")


def _catalog():
    return load_catalog(_DATA_DIRECTORY / "schemas.json", _DATA_DIRECTORY / "builtin_options.json")


def _blank_state_json(node_key: str) -> str:
    return json.dumps(default_state(node_key), separators=(",", ":"), sort_keys=True)


class _ArchPtFocusedNode:
    CATEGORY = "arch-pt/prompt"
    RETURN_TYPES = ("STRING", "ARCH_PT_BUNDLE")
    RETURN_NAMES = ("prompt", "prompt_bundle")
    FUNCTION = "build"
    NODE_KEY = ""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_family": (["flux", "qwen"], {"default": DEFAULT_MODEL_FAMILY}),
                "state_json": (
                    "STRING",
                    {"default": _blank_state_json(cls.NODE_KEY), "multiline": True, "dynamicPrompts": False},
                ),
            }
        }

    def build(self, model_family: str, state_json: str):
        catalog = _catalog()
        state = normalize_state(state_json, catalog)
        if state["node"] != self.NODE_KEY:
            raise ValueError(f"state node must be {self.NODE_KEY}")
        state["model_family"] = model_family
        result = assemble(catalog, state)
        bundle = result.bundle
        bundle["metadata"] = result.metadata
        return (result.prompt, bundle)


class ArchPtIdentity(_ArchPtFocusedNode):
    NODE_KEY = "identity"


class ArchPtPose(_ArchPtFocusedNode):
    NODE_KEY = "pose"


class ArchPtClothing(_ArchPtFocusedNode):
    NODE_KEY = "clothing"


class ArchPtEnvironment(_ArchPtFocusedNode):
    NODE_KEY = "environment"


class ArchPtCamera(_ArchPtFocusedNode):
    NODE_KEY = "camera"


class ArchPtLighting(_ArchPtFocusedNode):
    NODE_KEY = "lighting"


class ArchPtCombine:
    """Merge optional focused-node bundles in a fixed conceptual order."""

    CATEGORY = "arch-pt/prompt"
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "metadata_json", "lora_requests_json")
    FUNCTION = "combine"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "separator": ("STRING", {"default": ", "}),
                "dedupe": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "base_prompt": ("STRING", {"forceInput": True}),
                "extra_prompt": ("STRING", {"forceInput": True}),
                **{node_key: ("ARCH_PT_BUNDLE",) for node_key in _FOCUSED_NODE_KEYS},
            },
        }

    def combine(
        self,
        separator: str,
        dedupe: bool,
        base_prompt: str | None = None,
        extra_prompt: str | None = None,
        identity: Mapping[str, Any] | None = None,
        pose: Mapping[str, Any] | None = None,
        clothing: Mapping[str, Any] | None = None,
        environment: Mapping[str, Any] | None = None,
        camera: Mapping[str, Any] | None = None,
        lighting: Mapping[str, Any] | None = None,
    ):
        if not isinstance(separator, str):
            raise ValueError("separator must be a string")
        if not isinstance(dedupe, bool):
            raise ValueError("dedupe must be boolean")

        bundle_inputs = {
            "identity": identity,
            "pose": pose,
            "clothing": clothing,
            "environment": environment,
            "camera": camera,
            "lighting": lighting,
        }
        fragments = _optional_text(base_prompt, "base_prompt")
        metadata_bundles: list[dict[str, Any]] = []
        lora_requests: list[dict[str, Any]] = []

        for node_key in _FOCUSED_NODE_KEYS:
            bundle = bundle_inputs[node_key]
            if bundle is None:
                continue
            _validate_bundle(bundle, node_key)
            bundle_text = _normalized_texts(_bundle_text_fragments(bundle))
            bundle_loras = bundle["lora_requests"]
            if not bundle_text and not bundle_loras:
                continue
            fragments.extend(bundle_text)
            metadata_bundles.append(
                {
                    "node": bundle["node"],
                    "model_family": bundle["model_family"],
                    "metadata": bundle["metadata"],
                }
            )
            lora_requests.extend(bundle_loras)

        fragments.extend(_optional_text(extra_prompt, "extra_prompt"))
        normalized_fragments = _dedupe_text(fragments) if dedupe else _normalized_texts(fragments)
        metadata = {"version": BUNDLE_VERSION, "bundles": metadata_bundles}
        unique_loras = _dedupe_records(lora_requests)
        return (
            separator.join(normalized_fragments),
            _json_dump(metadata),
            _json_dump(unique_loras),
        )


def _validate_bundle(bundle: Any, expected_node: str) -> None:
    if not isinstance(bundle, Mapping):
        raise ValueError(f"{expected_node} bundle must be an object")
    if type(bundle.get("version")) is not int or bundle["version"] != BUNDLE_VERSION:
        raise ValueError(f"{expected_node} bundle has unsupported version")
    if bundle.get("node") != expected_node:
        raise ValueError(f"{expected_node} bundle node must be {expected_node}")
    if bundle.get("model_family") not in SUPPORTED_MODEL_FAMILIES:
        raise ValueError(f"{expected_node} bundle has unsupported model_family")
    if not isinstance(bundle.get("prompt"), str):
        raise ValueError(f"{expected_node} bundle prompt must be a string")
    if not isinstance(bundle.get("fields"), list):
        raise ValueError(f"{expected_node} bundle fields must be a list")
    if not isinstance(bundle.get("lora_requests"), list):
        raise ValueError(f"{expected_node} bundle lora_requests must be a list")
    if not isinstance(bundle.get("metadata"), Mapping):
        raise ValueError(f"{expected_node} bundle metadata must be an object")
    for field in bundle["fields"]:
        if not isinstance(field, Mapping):
            raise ValueError(f"{expected_node} bundle field must be an object")
        if not isinstance(field.get("fragments"), list) or not isinstance(field.get("specifics"), str):
            raise ValueError(f"{expected_node} bundle field shape is invalid")
        for fragment in field["fragments"]:
            if not isinstance(fragment, Mapping) or not isinstance(fragment.get("text"), str):
                raise ValueError(f"{expected_node} bundle fragment shape is invalid")
    for request in bundle["lora_requests"]:
        if not isinstance(request, Mapping):
            raise ValueError(f"{expected_node} bundle lora request must be an object")
    _json_dump(bundle)


def _bundle_text_fragments(bundle: Mapping[str, Any]) -> list[str]:
    texts: list[str] = []
    for field in bundle["fields"]:
        texts.extend(fragment["text"] for fragment in field["fragments"])
        texts.append(field["specifics"])
    return texts


def _optional_text(value: str | None, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return [value]


def _normalized_texts(values: list[str]) -> list[str]:
    return [normalized for value in values if (normalized := _normalize_text(value))]


def _dedupe_text(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in _normalized_texts(values):
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _normalize_text(value: str) -> str:
    return _WHITESPACE.sub(" ", value.strip())


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        canonical = _json_dump(record)
        if canonical not in seen:
            seen.add(canonical)
            unique.append(record)
    return unique


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("bundle must be JSON-serializable") from error
