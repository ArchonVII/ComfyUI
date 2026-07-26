"""Pure, versioned prompt-state normalization and deterministic assembly.

The engine deliberately works only from workflow snapshots.  It validates a
snapshot's node/field location against the catalog, but never consults current
catalog option wording while assembling a prompt.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .catalog import Catalog, CatalogError


STATE_VERSION = 1
BUNDLE_VERSION = 1
DEFAULT_MODEL_FAMILY = "flux"
SUPPORTED_MODEL_FAMILIES = frozenset({"flux", "qwen"})
_WHITESPACE = re.compile(r"\s+")


class StateValidationError(ValueError):
    """Raised when prompt-builder workflow state violates version 1."""


@dataclass(frozen=True)
class AssemblyResult:
    """Serializable prompt assembly output; ``bundle`` is plain JSON data."""

    prompt: str
    bundle: dict[str, Any]
    metadata: dict[str, Any]


def default_state(node: str = "identity", model_family: str = DEFAULT_MODEL_FAMILY) -> dict[str, Any]:
    """Return an empty version-1 node state suitable for UI initialization."""
    return {"version": STATE_VERSION, "node": node, "model_family": model_family, "fields": {}}


def normalize_state(raw_state: str | Mapping[str, Any], catalog: Catalog) -> dict[str, Any]:
    """Parse and validate a JSON/mapping node state without changing its copies."""
    state = _normalize_state_structure(raw_state)
    node = state["node"]
    if node not in catalog.schemas_by_node:
        raise StateValidationError(f"unknown node: {node}")
    for field_key in state["fields"]:
        try:
            catalog.field(node, field_key)
        except CatalogError as error:
            raise StateValidationError(str(error)) from error
    return state


def additive_select(state: Mapping[str, Any], copied_fragment: Mapping[str, Any]) -> dict[str, Any]:
    """Append a copied option snapshot, leaving all manual specifics untouched."""
    result = _state_copy(state)
    fragment = _normalize_fragment(copied_fragment)
    _assert_fragment_belongs_to_state(result, fragment)
    _assert_new_instance_id(result, fragment["instance_id"])
    field = result["fields"].setdefault(fragment["field"], {"fragments": [], "specifics": ""})
    field.setdefault("fragments", []).append(fragment)
    field.setdefault("specifics", "")
    return result


def replace_group_select(state: Mapping[str, Any], copied_fragment: Mapping[str, Any]) -> dict[str, Any]:
    """Replace copies in one field/group while preserving other copies and text."""
    result = _state_copy(state)
    fragment = _normalize_fragment(copied_fragment)
    _assert_fragment_belongs_to_state(result, fragment)
    _assert_new_instance_id(result, fragment["instance_id"])
    field = result["fields"].setdefault(fragment["field"], {"fragments": [], "specifics": ""})
    field["fragments"] = [
        existing
        for existing in field.setdefault("fragments", [])
        if existing.get("group") != fragment["group"]
    ]
    field["fragments"].append(fragment)
    field.setdefault("specifics", "")
    return result


def edit_fragment(state: Mapping[str, Any], instance_id: str, text: str) -> dict[str, Any]:
    """Edit one workflow copy; it cannot edit the catalog source option."""
    if not isinstance(instance_id, str) or not instance_id:
        raise StateValidationError("instance_id must be a non-empty string")
    text = _normalized_text(text, "fragment text")
    result = _state_copy(state)
    for field in result.get("fields", {}).values():
        for fragment in field.get("fragments", []):
            if fragment.get("instance_id") == instance_id:
                fragment["text"] = text
                return result
    raise StateValidationError(f"unknown fragment instance_id: {instance_id}")


def remove_fragment(state: Mapping[str, Any], instance_id: str) -> dict[str, Any]:
    """Remove exactly one copied workflow fragment by its stable instance id."""
    if not isinstance(instance_id, str) or not instance_id:
        raise StateValidationError("instance_id must be a non-empty string")
    result = _state_copy(state)
    for field in result.get("fields", {}).values():
        fragments = field.get("fragments", [])
        for index, fragment in enumerate(fragments):
            if fragment.get("instance_id") == instance_id:
                del fragments[index]
                return result
    raise StateValidationError(f"unknown fragment instance_id: {instance_id}")


def assemble(catalog: Catalog, raw_state: str | Mapping[str, Any]) -> AssemblyResult:
    """Assemble a deterministic prompt and bundle from a validated state copy."""
    state = normalize_state(raw_state, catalog)
    schema = catalog.schemas_by_node[state["node"]]
    ordered_fields: list[dict[str, Any]] = []
    ordered_text: list[str] = []
    lora_requests: list[dict[str, Any]] = []

    for section in schema.sections:
        for field_record in section.fields:
            field_state = state["fields"].get(field_record.key, {"fragments": [], "specifics": ""})
            fragments = [_json_copy(fragment) for fragment in field_state["fragments"]]
            field_text: list[str] = [fragment["text"] for fragment in fragments]
            field_text.append(field_state["specifics"])
            ordered_text.extend(field_text)
            ordered_fields.append(
                {
                    "section": section.key,
                    "section_label": section.label,
                    "section_order": section.order,
                    "key": field_record.key,
                    "label": field_record.label,
                    "order": field_record.order,
                    "control": field_record.control,
                    "fragments": fragments,
                    "specifics": field_state["specifics"],
                }
            )
            for fragment in fragments:
                if fragment.get("lora") is not None and fragment["lora_enabled"]:
                    lora_requests.append(
                        {
                            "lora": _json_copy(fragment["lora"]),
                            "origin": {
                                "instance_id": fragment["instance_id"],
                                "source_option_id": fragment["source_option_id"],
                                "node": fragment["node"],
                                "field": fragment["field"],
                                "group": fragment["group"],
                            },
                        }
                    )

    prompt = ", ".join(_dedupe_text(ordered_text))
    metadata = _metadata(schema, state["model_family"])
    bundle = {
        "version": BUNDLE_VERSION,
        "node": state["node"],
        "model_family": state["model_family"],
        "prompt": prompt,
        "fields": ordered_fields,
        "lora_requests": lora_requests,
    }
    return AssemblyResult(prompt=prompt, bundle=bundle, metadata=metadata)


def _parse_state(raw_state: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(raw_state, str):
        try:
            raw_state = json.loads(raw_state)
        except json.JSONDecodeError as error:
            raise StateValidationError("state must be valid JSON") from error
    if not isinstance(raw_state, Mapping):
        raise StateValidationError("state must be an object or JSON object string")
    return raw_state


def _normalize_state_structure(raw_state: str | Mapping[str, Any]) -> dict[str, Any]:
    """Normalize every invariant mutation helpers can enforce without a catalog."""
    state = _parse_state(raw_state)
    version = state.get("version")
    if type(version) is not int or version != STATE_VERSION:
        raise StateValidationError(f"unsupported state version: {version!r}")
    node = _required_string(state, "node")
    model_family = _model_family(_required_string(state, "model_family"))
    raw_fields = state.get("fields")
    if not isinstance(raw_fields, Mapping):
        raise StateValidationError("fields must be an object")

    fields: dict[str, dict[str, Any]] = {}
    instance_ids: set[str] = set()
    for field_key, raw_field in raw_fields.items():
        if not isinstance(field_key, str) or not field_key.strip():
            raise StateValidationError("field keys must be non-empty strings")
        fields[field_key] = _normalize_field(raw_field, node, field_key, instance_ids)
    return {"version": STATE_VERSION, "node": node, "model_family": model_family, "fields": fields}


def _normalize_field(raw_field: Any, node: str, field_key: str, instance_ids: set[str]) -> dict[str, Any]:
    if not isinstance(raw_field, Mapping):
        raise StateValidationError(f"field {field_key} must be an object")
    raw_fragments = raw_field.get("fragments", [])
    if not isinstance(raw_fragments, list):
        raise StateValidationError(f"field {field_key} fragments must be a list")
    specifics = _normalized_text(raw_field.get("specifics", ""), f"field {field_key} specifics")
    fragments: list[dict[str, Any]] = []
    for raw_fragment in raw_fragments:
        fragment = _normalize_fragment(raw_fragment)
        if fragment["node"] != node or fragment["field"] != field_key:
            raise StateValidationError("fragment node and field must match its containing state field")
        if fragment["instance_id"] in instance_ids:
            raise StateValidationError(f"duplicate fragment instance_id: {fragment['instance_id']}")
        instance_ids.add(fragment["instance_id"])
        fragments.append(fragment)
    return {"fragments": fragments, "specifics": specifics}


def _normalize_fragment(raw_fragment: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_fragment, Mapping):
        raise StateValidationError("fragment must be an object")
    text = raw_fragment.get("text", raw_fragment.get("copied_text"))
    model_family = raw_fragment.get("model_family", raw_fragment.get("copied_model_family"))
    fragment = {
        "instance_id": _required_string(raw_fragment, "instance_id"),
        "source_option_id": _required_string(raw_fragment, "source_option_id"),
        "label": _required_string(raw_fragment, "label"),
        "node": _required_string(raw_fragment, "node"),
        "field": _required_string(raw_fragment, "field"),
        "group": _required_string(raw_fragment, "group"),
        "text": _normalized_text(text, "fragment text"),
        "model_family": _model_family(_string_value(model_family, "fragment model_family")),
        "lora_enabled": _boolean(raw_fragment.get("lora_enabled", False), "lora_enabled"),
    }
    if "lora" in raw_fragment and raw_fragment["lora"] is not None:
        if not isinstance(raw_fragment["lora"], Mapping):
            raise StateValidationError("lora metadata must be an object")
        fragment["lora"] = _json_copy(raw_fragment["lora"])
    return fragment


def _metadata(schema: Any, model_family: str) -> dict[str, Any]:
    return {
        "version": BUNDLE_VERSION,
        "node": schema.key,
        "model_family": model_family,
        "sections": [
            {
                "key": section.key,
                "label": section.label,
                "order": section.order,
                "fields": [
                    {
                        "key": field.key,
                        "label": field.label,
                        "order": field.order,
                        "control": field.control,
                    }
                    for field in section.fields
                ],
            }
            for section in schema.sections
        ],
    }


def _dedupe_text(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _WHITESPACE.sub(" ", value.strip())
        if not normalized:
            continue
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def _state_copy(state: Mapping[str, Any]) -> dict[str, Any]:
    return _normalize_state_structure(state)


def _assert_fragment_belongs_to_state(state: Mapping[str, Any], fragment: Mapping[str, Any]) -> None:
    if state.get("node") != fragment["node"]:
        raise StateValidationError("fragment node must match state node")


def _assert_new_instance_id(state: Mapping[str, Any], instance_id: str) -> None:
    for field in state.get("fields", {}).values():
        for fragment in field.get("fragments", []):
            if fragment.get("instance_id") == instance_id:
                raise StateValidationError(f"duplicate fragment instance_id: {instance_id}")


def _required_string(mapping: Mapping[str, Any], key: str) -> str:
    return _string_value(mapping.get(key), key)


def _string_value(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateValidationError(f"{name} must be a non-empty string")
    return value


def _normalized_text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise StateValidationError(f"{name} must be a string")
    return _WHITESPACE.sub(" ", value.strip())


def _model_family(value: str) -> str:
    if value not in SUPPORTED_MODEL_FAMILIES:
        raise StateValidationError(f"unsupported model_family: {value}")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise StateValidationError(f"{name} must be boolean")
    return value


def _json_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise StateValidationError("state object keys must be strings")
            result[key] = _json_copy(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_copy(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise StateValidationError("state must contain finite JSON numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise StateValidationError("state must contain JSON-serializable data")
