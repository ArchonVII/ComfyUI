"""Pure loaders and immutable records for arch prompt-builder catalog data.

Semantic spectra use a [minimum, maximum) policy; only the final stop includes
its maximum.  Adjacent stops therefore share a boundary without overlapping.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


APPROVED_NODE_KEYS = frozenset(
    {"identity", "pose", "clothing", "environment", "camera", "lighting"}
)
CONTROL_TYPES = frozenset(
    {"buttons", "searchable_options", "semantic_spectrum", "free_text"}
)
CATALOG_SCOPES = frozenset({"shared", "side_aware"})
OPTION_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+){2,}$")
SPECTRUM_DOMAIN = (0.0, 1.0)


class CatalogError(ValueError):
    """Base error for catalog lookup and validation failures."""


class CatalogValidationError(CatalogError):
    """Raised when catalog JSON cannot satisfy the prompt-builder contract."""


@dataclass(frozen=True)
class SpectrumStop:
    minimum: float
    maximum: float
    phrases: Mapping[str, str]


@dataclass(frozen=True)
class FieldRecord:
    key: str
    label: str
    order: int
    control: str
    groups: tuple[str, ...] = ()
    catalog_scope: str | None = None
    enabled_by_default: bool = True
    spectrum: tuple[SpectrumStop, ...] = ()

    def spectrum_phrase_for(self, value: float, family: str) -> str:
        """Return the authored phrase for a value using the documented policy."""
        if self.control != "semantic_spectrum":
            raise CatalogError(f"field {self.key} is not a semantic spectrum")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CatalogError("spectrum value must be a number")
        numeric_value = float(value)
        minimum, maximum = SPECTRUM_DOMAIN
        if not minimum <= numeric_value <= maximum:
            raise CatalogError("spectrum value is outside the supported domain")
        for index, stop in enumerate(self.spectrum):
            is_final_stop = index == len(self.spectrum) - 1
            if stop.minimum <= numeric_value < stop.maximum or (
                is_final_stop and numeric_value == stop.maximum
            ):
                try:
                    return stop.phrases[family]
                except KeyError as error:
                    raise CatalogError(f"unknown model family: {family}") from error
        raise CatalogError("spectrum value does not map to a stop")


@dataclass(frozen=True)
class SectionRecord:
    key: str
    label: str
    order: int
    fields: tuple[FieldRecord, ...]


@dataclass(frozen=True)
class NodeSchema:
    key: str
    label: str
    sections: tuple[SectionRecord, ...]


@dataclass(frozen=True)
class OptionRecord:
    id: str
    label: str
    node: str
    field: str
    group: str
    phrases: Mapping[str, str]
    builtin: bool
    lora: Mapping[str, Any] | None = None

    def phrase_for(self, family: str) -> str | None:
        return self.phrases.get(family)


@dataclass(frozen=True)
class Catalog:
    version: str
    families: tuple[str, ...]
    schemas_by_node: Mapping[str, NodeSchema]
    options: tuple[OptionRecord, ...]
    _fields: Mapping[tuple[str, str], FieldRecord]
    _options_by_node_field_family: Mapping[tuple[str, str, str], tuple[OptionRecord, ...]]

    def field(self, node: str, field: str) -> FieldRecord:
        if node not in self.schemas_by_node:
            raise CatalogError(f"unknown node: {node}")
        try:
            return self._fields[(node, field)]
        except KeyError as error:
            raise CatalogError(f"unknown field: {node}.{field}") from error

    def options_for(self, node: str, field: str, family: str) -> tuple[OptionRecord, ...]:
        self.field(node, field)
        if family not in self.families:
            raise CatalogError(f"unknown model family: {family}")
        return self._options_by_node_field_family.get((node, field, family), ())


def load_catalog(schema_path: str | Path, options_path: str | Path) -> Catalog:
    """Load a versioned catalog from JSON files without importing ComfyUI."""
    return catalog_from_data(_read_json(schema_path), _read_json(options_path))


def catalog_from_data(schema_data: Mapping[str, Any], options_data: Mapping[str, Any]) -> Catalog:
    """Validate JSON-compatible mappings and return immutable catalog records."""
    schemas = _mapping(schema_data, "schemas")
    options_root = _mapping(options_data, "options")
    version = _string(schemas.get("version"), "schema version")
    if _string(options_root.get("version"), "options version") != version:
        raise CatalogValidationError("schema and options version must match")
    families = _string_tuple(schemas.get("families"), "families")
    if len(set(families)) != len(families):
        raise CatalogValidationError("families must be unique")

    nodes, fields = _parse_schemas(schemas.get("nodes"), families)
    options = _parse_options(options_root.get("options"), families, fields)
    return _make_catalog(version, families, nodes, fields, options)


def _read_json(path: str | Path) -> Mapping[str, Any]:
    try:
        with Path(path).open(encoding="utf-8") as source:
            return _mapping(json.load(source), f"JSON file {path}")
    except OSError as error:
        raise CatalogValidationError(f"could not read catalog file: {path}") from error
    except UnicodeError as error:
        raise CatalogValidationError(f"could not decode catalog file: {path}") from error
    except json.JSONDecodeError as error:
        raise CatalogValidationError(f"invalid JSON in catalog file: {path}") from error


def _parse_schemas(raw_nodes: Any, families: tuple[str, ...]) -> tuple[dict[str, NodeSchema], dict[tuple[str, str], FieldRecord]]:
    if not isinstance(raw_nodes, list):
        raise CatalogValidationError("nodes must be a list")
    nodes: dict[str, NodeSchema] = {}
    fields: dict[tuple[str, str], FieldRecord] = {}
    for raw_node in raw_nodes:
        node = _mapping(raw_node, "node")
        node_key = _string(node.get("key"), "node key")
        if node_key not in APPROVED_NODE_KEYS:
            raise CatalogValidationError(f"unknown node: {node_key}")
        if node_key in nodes:
            raise CatalogValidationError(f"node keys must be unique: {node_key}")
        raw_sections = node.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise CatalogValidationError(f"node {node_key} must define sections")
        sections: list[SectionRecord] = []
        section_keys: set[str] = set()
        for raw_section in raw_sections:
            section = _mapping(raw_section, f"section in {node_key}")
            section_key = _string(section.get("key"), "section key")
            if section_key in section_keys:
                raise CatalogValidationError(f"section keys must be unique in {node_key}")
            section_keys.add(section_key)
            raw_fields = section.get("fields")
            if not isinstance(raw_fields, list) or not raw_fields:
                raise CatalogValidationError(f"section {section_key} must define fields")
            parsed_fields: list[FieldRecord] = []
            for raw_field in raw_fields:
                field = _parse_field(raw_field, families)
                key = (node_key, field.key)
                if key in fields:
                    raise CatalogValidationError(f"field keys must be unique in {node_key}: {field.key}")
                fields[key] = field
                parsed_fields.append(field)
            if len({field.order for field in parsed_fields}) != len(parsed_fields):
                raise CatalogValidationError(f"field order values must be unique in {node_key}.{section_key}")
            parsed_fields.sort(key=lambda field: field.order)
            sections.append(
                SectionRecord(
                    key=section_key,
                    label=_string(section.get("label"), "section label"),
                    order=_integer(section.get("order"), "section order"),
                    fields=tuple(parsed_fields),
                )
            )
        if len({section.order for section in sections}) != len(sections):
            raise CatalogValidationError(f"section order values must be unique in {node_key}")
        sections.sort(key=lambda section: section.order)
        nodes[node_key] = NodeSchema(
            key=node_key,
            label=_string(node.get("label"), "node label"),
            sections=tuple(sections),
        )
    if set(nodes) != APPROVED_NODE_KEYS:
        raise CatalogValidationError("schemas must define every approved node")
    return nodes, fields


def _parse_field(raw_field: Any, families: tuple[str, ...]) -> FieldRecord:
    raw = _mapping(raw_field, "field")
    control = _string(raw.get("control"), "field control")
    if control not in CONTROL_TYPES:
        raise CatalogValidationError(f"unsupported control type: {control}")
    groups = _string_tuple(raw.get("groups", []), "field groups", allow_empty=True)
    if len(set(groups)) != len(groups):
        raise CatalogValidationError("field groups must be unique")
    if control in {"buttons", "searchable_options"} and not groups:
        raise CatalogValidationError(f"{control} fields must define groups")
    scope = raw.get("catalog_scope")
    if scope is not None and scope not in CATALOG_SCOPES:
        raise CatalogValidationError(f"unsupported catalog scope: {scope}")
    enabled = raw.get("enabled_by_default", True)
    if not isinstance(enabled, bool):
        raise CatalogValidationError("enabled_by_default must be boolean")
    spectrum = _parse_spectrum(raw.get("spectrum", []), families)
    if control == "semantic_spectrum":
        if enabled:
            raise CatalogValidationError("semantic spectra must be disabled by default")
        if not spectrum:
            raise CatalogValidationError("semantic spectra must define stops")
    elif spectrum:
        raise CatalogValidationError("only semantic spectra may define stops")
    return FieldRecord(
        key=_string(raw.get("key"), "field key"),
        label=_string(raw.get("label"), "field label"),
        order=_integer(raw.get("order"), "field order"),
        control=control,
        groups=groups,
        catalog_scope=scope,
        enabled_by_default=enabled,
        spectrum=spectrum,
    )


def _parse_spectrum(raw_stops: Any, families: tuple[str, ...]) -> tuple[SpectrumStop, ...]:
    if not isinstance(raw_stops, list):
        raise CatalogValidationError("spectrum must be a list")
    stops: list[SpectrumStop] = []
    for raw_stop in raw_stops:
        stop = _mapping(raw_stop, "spectrum stop")
        minimum = _number(stop.get("minimum"), "spectrum minimum")
        maximum = _number(stop.get("maximum"), "spectrum maximum")
        domain_minimum, domain_maximum = SPECTRUM_DOMAIN
        if not domain_minimum <= minimum < maximum <= domain_maximum:
            raise CatalogValidationError("spectrum ranges must stay between 0 and 1")
        phrases = _phrases(stop.get("phrases"), families, "spectrum phrase", require_all=True)
        stops.append(SpectrumStop(minimum, maximum, phrases))
    if stops:
        domain_minimum, domain_maximum = SPECTRUM_DOMAIN
        for previous, current in zip(stops, stops[1:]):
            if current.minimum < previous.minimum:
                raise CatalogValidationError("semantic spectrum stops must be ordered")
            if current.minimum < previous.maximum:
                raise CatalogValidationError("semantic spectrum stops must not overlap")
            if current.minimum > previous.maximum:
                raise CatalogValidationError("semantic spectrum stops must not have a gap")
        if stops[0].minimum != domain_minimum or stops[-1].maximum != domain_maximum:
            raise CatalogValidationError("semantic spectrum stops must cover the supported domain")
    return tuple(stops)


def _parse_options(raw_options: Any, families: tuple[str, ...], fields: Mapping[tuple[str, str], FieldRecord]) -> tuple[OptionRecord, ...]:
    if not isinstance(raw_options, list):
        raise CatalogValidationError("options must be a list")
    parsed: list[OptionRecord] = []
    ids: set[str] = set()
    for raw_option in raw_options:
        option = _mapping(raw_option, "option")
        option_id = _string(option.get("id"), "option id")
        if not OPTION_ID_PATTERN.fullmatch(option_id):
            raise CatalogValidationError(f"option id must be stable and namespaced: {option_id}")
        if option_id in ids:
            raise CatalogValidationError("option ids must be unique")
        ids.add(option_id)
        node = _string(option.get("node"), "option node")
        field_key = _string(option.get("field"), "option field")
        field = fields.get((node, field_key))
        if field is None:
            if node not in APPROVED_NODE_KEYS:
                raise CatalogValidationError(f"unknown node: {node}")
            raise CatalogValidationError(f"unknown field: {node}.{field_key}")
        id_node, id_field, _ = option_id.split(".", 2)
        if (id_node, id_field) != (node, field_key):
            raise CatalogValidationError(
                f"option id namespace must match declared node and field: {option_id}"
            )
        group = _string(option.get("group"), "option group")
        if group not in field.groups:
            raise CatalogValidationError(f"unknown group: {node}.{field_key}.{group}")
        if option.get("builtin") is not True:
            raise CatalogValidationError("built-in options are protected")
        lora = option.get("lora")
        if lora is not None:
            lora = _freeze_json(_mapping(lora, "lora metadata"))
        parsed.append(
            OptionRecord(
                id=option_id,
                label=_string(option.get("label"), "option label"),
                node=node,
                field=field_key,
                group=group,
                phrases=_phrases(option.get("phrases"), families, "option phrase", require_all=False),
                builtin=True,
                lora=lora,
            )
        )
    return tuple(parsed)


def _make_catalog(version: str, families: tuple[str, ...], nodes: dict[str, NodeSchema], fields: dict[tuple[str, str], FieldRecord], options: tuple[OptionRecord, ...]) -> Catalog:
    index: dict[tuple[str, str, str], list[OptionRecord]] = {}
    for option in options:
        for family in option.phrases:
            index.setdefault((option.node, option.field, family), []).append(option)
    return Catalog(
        version=version,
        families=families,
        schemas_by_node=MappingProxyType(dict(nodes)),
        options=options,
        _fields=MappingProxyType(dict(fields)),
        _options_by_node_field_family=MappingProxyType(
            {key: tuple(value) for key, value in index.items()}
        ),
    )


def _phrases(raw: Any, families: tuple[str, ...], name: str, *, require_all: bool) -> Mapping[str, str]:
    phrases = _mapping(raw, name)
    if not phrases:
        raise CatalogValidationError(f"{name} must not be empty")
    unknown = set(phrases) - set(families)
    if unknown:
        raise CatalogValidationError(f"unknown model family in {name}: {sorted(unknown)[0]}")
    if require_all and set(phrases) != set(families):
        missing = set(families) - set(phrases)
        raise CatalogValidationError(f"missing {sorted(missing)[0]} {name}")
    normalized = {family: _string(phrase, f"{family} {name}") for family, phrase in phrases.items()}
    return MappingProxyType(normalized)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogValidationError(f"{name} must be an object")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogValidationError(f"{name} must be a non-empty string")
    return value


def _string_tuple(value: Any, name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise CatalogValidationError(f"{name} must be a non-empty list")
    return tuple(_string(item, name) for item in value)


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CatalogValidationError(f"{name} must be an integer")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CatalogValidationError(f"{name} must be a number")
    return float(value)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value
