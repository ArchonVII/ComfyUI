import json
from pathlib import Path

import pytest

from custom_nodes.comfyui_arch_prompt_tools.catalog import (
    CatalogValidationError,
    catalog_from_data,
    load_catalog,
)


DATA_DIR = Path(__file__).parents[1] / "data"


def load_default_catalog():
    return load_catalog(DATA_DIR / "schemas.json", DATA_DIR / "builtin_options.json")


def default_payloads():
    return (
        json.loads((DATA_DIR / "schemas.json").read_text(encoding="utf-8")),
        json.loads((DATA_DIR / "builtin_options.json").read_text(encoding="utf-8")),
    )


def raw_field(schemas, node_key, field_key):
    return next(
        field
        for node in schemas["nodes"]
        if node["key"] == node_key
        for section in node["sections"]
        for field in section["fields"]
        if field["key"] == field_key
    )


def test_loads_matching_versioned_schema_and_builtin_catalog():
    catalog = load_default_catalog()

    assert catalog.version == "1.0"
    assert catalog.families == ("flux", "qwen")
    assert set(catalog.schemas_by_node) == {
        "identity",
        "pose",
        "clothing",
        "environment",
        "camera",
        "lighting",
    }


def test_builtin_option_ids_are_stable_unique_and_protected():
    catalog = load_default_catalog()
    option_ids = [option.id for option in catalog.options]

    assert len(option_ids) == len(set(option_ids))
    assert all(option.id.count(".") >= 2 for option in catalog.options)
    assert all(option.builtin for option in catalog.options)


def test_options_expose_valid_flux_and_qwen_phrases():
    catalog = load_default_catalog()

    for option in catalog.options:
        for family, phrase in option.phrases.items():
            assert family in {"flux", "qwen"}
            assert isinstance(phrase, str) and phrase.strip()
        assert option.phrase_for(next(iter(option.phrases))) == next(iter(option.phrases.values()))


def test_schema_defines_all_nodes_fields_groups_and_control_types():
    catalog = load_default_catalog()
    controls = {
        field.control
        for schema in catalog.schemas_by_node.values()
        for section in schema.sections
        for field in section.fields
    }

    assert {"buttons", "searchable_options", "semantic_spectrum", "free_text"} <= controls
    assert catalog.field("pose", "hand_position").catalog_scope == "side_aware"
    assert catalog.field("clothing", "garment").catalog_scope == "shared"
    assert catalog.options_for("identity", "gender", "flux")


def test_schema_covers_every_approved_section_for_each_node():
    catalog = load_default_catalog()

    assert {
        node: tuple(section.key for section in catalog.schemas_by_node[node].sections)
        for node in catalog.schemas_by_node
    } == {
        "identity": ("core_identity", "body_structure", "appearance", "expression"),
        "pose": ("overall_pose", "frame_orientation", "head_torso", "arms_hands", "legs_feet"),
        "clothing": (
            "state_transfer",
            "upper_body",
            "waist_lower_body",
            "whole_outfit",
            "materials_details",
        ),
        "environment": (
            "scene_type",
            "location",
            "scene_contents",
            "time_conditions",
            "mood_character",
        ),
        "camera": (
            "framing_distance",
            "viewpoint_angle",
            "lens_optics",
            "focus_depth",
            "composition_effects",
        ),
        "lighting": (
            "environment_illumination",
            "light_sources",
            "primary_direction",
            "color_temperature",
            "quality_shadows",
            "techniques_effects",
        ),
    }


def test_options_filter_to_the_current_model_family():
    catalog = load_default_catalog()

    flux_ids = {option.id for option in catalog.options_for("environment", "weather", "flux")}
    qwen_ids = {option.id for option in catalog.options_for("environment", "weather", "qwen")}

    assert "environment.weather.misty" in flux_ids
    assert "environment.weather.misty" not in qwen_ids
    assert "environment.weather.rainy" in qwen_ids


def test_optional_lora_metadata_is_immutable_and_does_not_change_source_data():
    schemas, options = default_payloads()
    options["options"][0]["lora"] = {"tags": ["portrait"]}

    option = catalog_from_data(schemas, options).options[0]

    assert option.lora == {"tags": ("portrait",)}
    with pytest.raises((AttributeError, TypeError)):
        option.lora["tags"].append("changed")
    assert options["options"][0]["lora"] == {"tags": ["portrait"]}


def test_semantic_spectra_are_disabled_and_map_authored_phrases():
    field = load_default_catalog().field("environment", "atmosphere")

    assert field.control == "semantic_spectrum"
    assert field.enabled_by_default is False
    assert [(stop.minimum, stop.maximum, stop.phrases["flux"]) for stop in field.spectrum] == [
        (0.0, 0.33, "calm atmosphere"),
        (0.34, 0.66, "tense atmosphere"),
        (0.67, 1.0, "dramatic atmosphere"),
    ]


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda schemas, options: options["options"].append(dict(options["options"][0])),
            "unique",
        ),
        (
            lambda schemas, options: options["options"][0]["phrases"].update({"flux": "  "}),
            "phrase",
        ),
        (
            lambda schemas, options: options["options"][0].update({"node": "unknown"}),
            "node",
        ),
        (
            lambda schemas, options: options["options"][0].update({"field": "unknown"}),
            "field",
        ),
        (
            lambda schemas, options: options["options"][0].update({"group": "unknown"}),
            "group",
        ),
        (
            lambda schemas, options: options["options"][0].update({"builtin": False}),
            "protected",
        ),
        (
            lambda schemas, options: raw_field(schemas, "environment", "atmosphere").update(
                {"spectrum": [{"minimum": 0, "maximum": 1, "phrases": {"flux": "raw number"}}]}
            ),
            "qwen",
        ),
        (
            lambda schemas, options: options.update({"version": "2.0"}),
            "version",
        ),
    ],
)
def test_rejects_invalid_catalog_contracts_without_mutating_source(mutation, match):
    schemas, options = default_payloads()
    mutation(schemas, options)
    expected_schemas = json.loads(json.dumps(schemas))
    expected_options = json.loads(json.dumps(options))

    with pytest.raises(CatalogValidationError, match=match):
        catalog_from_data(schemas, options)

    assert schemas == expected_schemas
    assert options == expected_options
