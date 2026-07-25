import json
from pathlib import Path

import pytest

from custom_nodes.comfyui_arch_prompt_tools.catalog import (
    CatalogError,
    CatalogValidationError,
    catalog_from_data,
    load_catalog,
)
from custom_nodes.comfyui_arch_prompt_tools.engine import assemble, replace_group_select


DATA_DIR = Path(__file__).parents[1] / "data"

APPROVED_FIELDS = {
    "identity": {
        "core_identity": ("subject_type", "age_group", "exact_age", "identity_specifics"),
        "body_structure": (
            "body_type",
            "height",
            "weight_build",
            "chest_breasts",
            "hips_butt",
            "waist",
            "body_snippets",
            "body_specifics",
        ),
        "appearance": (
            "skin_tone",
            "skin_details",
            "hair_length",
            "hair_texture",
            "hair_color",
            "hair_style",
            "hair_specifics",
            "eye_color",
            "eye_shape",
            "facial_features",
            "appearance_specifics",
        ),
        "expression": ("expression", "mouth", "gaze", "expression_specifics"),
    },
    "pose": {
        "overall_pose": ("base_pose", "pose_snippets", "action_specifics"),
        "frame_orientation": (
            "body_axis",
            "facing_direction",
            "depth_orientation",
            "orientation_specifics",
        ),
        "head_torso": (
            "head_position",
            "neck",
            "shoulders",
            "torso_spine",
            "hips_pelvis",
            "head_torso_specifics",
        ),
        "arms_hands": (
            "left_arm",
            "right_arm",
            "left_hand",
            "right_hand",
            "arms_hands_specifics",
        ),
        "legs_feet": (
            "left_leg",
            "right_leg",
            "left_foot",
            "right_foot",
            "balance_contact",
            "legs_feet_specifics",
        ),
    },
    "clothing": {
        "state_transfer": ("clothing_state", "clothing_modifiers", "state_specifics"),
        "upper_body": (
            "headwear",
            "facewear",
            "neckwear",
            "bra",
            "top",
            "outerwear",
            "sleeves",
            "gloves",
        ),
        "waist_lower_body": ("waist", "belt", "underwear", "bottom", "hosiery", "footwear"),
        "whole_outfit": ("outfit_type", "outfit_snippets", "outfit_specifics"),
        "materials_details": (
            "dominant_color",
            "secondary_color",
            "material",
            "pattern",
            "fit",
            "condition",
            "jewelry",
            "bags_accessories",
            "clothing_specifics",
        ),
    },
    "environment": {
        "scene_type": ("scene_type",),
        "location": (
            "location_type",
            "named_setting",
            "architecture",
            "terrain",
            "natural_features",
            "location_specifics",
        ),
        "scene_contents": (
            "foreground",
            "midground",
            "background",
            "furniture",
            "props",
            "plants_nature",
            "crowd_level",
            "scene_density",
            "contents_specifics",
        ),
        "time_conditions": (
            "time_of_day",
            "season",
            "weather",
            "atmospheric_conditions",
            "surface_condition",
            "conditions_specifics",
        ),
        "mood_character": (
            "mood",
            "color_palette",
            "environment_condition",
            "period",
            "regional_character",
            "environment_snippets",
            "environment_specifics",
        ),
    },
    "camera": {
        "framing_distance": ("framing", "subject_framing", "framing_specifics"),
        "viewpoint_angle": ("camera_angle", "horizontal_view", "viewpoint_specifics"),
        "lens_optics": (
            "focal_length",
            "lens_type",
            "aperture_character",
            "distortion",
            "compression",
            "lens_specifics",
        ),
        "focus_depth": ("focus_target", "depth_of_field", "focus_mode", "focus_specifics"),
        "composition_effects": ("composition", "optical_effects", "camera_specifics"),
    },
    "lighting": {
        "environment_illumination": (
            "environment_brightness",
            "exposure_character",
            "lighting_contrast",
        ),
        "light_sources": (
            "source_count",
            "primary_light",
            "fill_light",
            "practical_lights",
            "source_nature",
            "source_specifics",
        ),
        "primary_direction": (
            "primary_direction",
            "light_elevation",
            "direction_specifics",
        ),
        "color_temperature": (
            "primary_color",
            "fill_color",
            "color_temperature",
            "mixed_temperature",
            "color_specifics",
        ),
        "quality_shadows": (
            "light_softness",
            "shadow_hardness",
            "shadow_depth",
            "falloff",
            "contrast_ratio",
            "quality_specifics",
        ),
        "techniques_effects": ("lighting_techniques", "lighting_specifics"),
    },
}

EXACT_BUTTON_LABELS = {
    ("pose", "base_pose"): {
        "Standing",
        "Seated",
        "Kneeling",
        "Crouching",
        "Lying",
        "On all fours",
        "Airborne",
    },
    ("pose", "body_axis"): {
        "↑ Head up / feet down",
        "↗ Head upper-right / feet lower-left",
        "→ Head right / feet left",
        "↘ Head lower-right / feet upper-left",
        "↓ Head down / feet up",
        "↙ Head lower-left / feet upper-right",
        "← Head left / feet right",
        "↖ Head upper-left / feet lower-right",
    },
    ("pose", "facing_direction"): {
        "Front",
        "Three-quarter left",
        "Three-quarter right",
        "Profile left",
        "Profile right",
        "Back three-quarter",
        "Back",
    },
    ("pose", "depth_orientation"): {"Head closer", "Feet closer", "Parallel"},
    ("clothing", "clothing_state"): {
        "Fully clothed",
        "Keep source clothing",
        "Use reference clothing",
        "Nude",
    },
    ("clothing", "clothing_modifiers"): {
        "Topless",
        "Bottomless",
        "Partially undressed",
        "Underwear visible",
        "Open / unfastened",
    },
    ("environment", "scene_type"): {"Indoor", "Outdoor", "Mixed", "Studio", "Abstract"},
    ("environment", "season"): {"Spring", "Summer", "Autumn", "Winter"},
    ("camera", "framing"): {
        "Extreme close-up",
        "Close-up",
        "Medium",
        "Three-quarter",
        "Full-body",
        "Wide",
        "Extreme-wide",
    },
    ("camera", "focal_length"): {"14mm", "24mm", "35mm", "50mm", "85mm", "135mm", "200mm"},
    ("lighting", "source_count"): {"One", "Two", "Three", "Multiple"},
    ("lighting", "source_nature"): {"Natural", "Artificial", "Mixed"},
    ("lighting", "primary_direction"): {
        "Front (camera side)",
        "Front-left (frame left)",
        "Front-right (frame right)",
        "Side-left (frame left)",
        "Side-right (frame right)",
        "Back (far side)",
        "Back-left (frame left)",
        "Back-right (frame right)",
        "Above (frame top)",
        "Below (frame bottom)",
    },
    ("lighting", "light_elevation"): {"Low", "Level", "High"},
}

SPECTRUM_FIELDS = {
    ("environment", "scene_density"),
    ("camera", "depth_of_field"),
    ("lighting", "environment_brightness"),
    ("lighting", "exposure_character"),
    ("lighting", "lighting_contrast"),
    ("lighting", "color_temperature"),
    ("lighting", "light_softness"),
    ("lighting", "shadow_hardness"),
    ("lighting", "shadow_depth"),
    ("lighting", "falloff"),
    ("lighting", "contrast_ratio"),
}


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


def options_by_field(catalog, node, field):
    return [option for option in catalog.options if (option.node, option.field) == (node, field)]


def option_by_label(catalog, node, field, label):
    return next(option for option in options_by_field(catalog, node, field) if option.label == label)


def test_loads_matching_versioned_schema_and_builtin_catalog():
    catalog = load_default_catalog()

    assert catalog.version == "1.0"
    assert catalog.families == ("flux", "qwen")
    assert set(catalog.schemas_by_node) == set(APPROVED_FIELDS)


def test_load_catalog_converts_non_utf8_data_to_a_validation_error(tmp_path):
    schema_path = tmp_path / "schemas.json"
    options_path = tmp_path / "builtin_options.json"
    schema_path.write_bytes(b"\xff")
    options_path.write_text("{}", encoding="utf-8")

    with pytest.raises(CatalogValidationError, match="could not decode catalog file"):
        load_catalog(schema_path, options_path)


def test_schema_locks_exact_approved_node_section_field_order():
    catalog = load_default_catalog()

    actual = {
        node: {
            section.key: tuple(field.key for field in section.fields)
            for section in catalog.schemas_by_node[node].sections
        }
        for node in catalog.schemas_by_node
    }

    assert actual == APPROVED_FIELDS


def test_every_option_field_has_a_curated_protected_two_family_catalog():
    catalog = load_default_catalog()
    optional_fields = []

    for node, schema in catalog.schemas_by_node.items():
        for section in schema.sections:
            for field in section.fields:
                if field.control not in {"buttons", "searchable_options"}:
                    continue
                optional_fields.append((node, field.key))
                options = options_by_field(catalog, node, field.key)
                assert 3 <= len(options) <= 12, f"{node}.{field.key} has {len(options)} options"
                assert {option.group for option in options} <= set(field.groups)
                assert all(option.builtin for option in options)
                assert all(set(option.phrases) == {"flux", "qwen"} for option in options)
                assert all(all(phrase.strip() for phrase in option.phrases.values()) for option in options)

    assert optional_fields


def test_bounded_button_sets_have_approved_counts_and_exact_sets():
    catalog = load_default_catalog()
    count_exceptions = {("pose", "body_axis"), ("lighting", "primary_direction")}

    for node, schema in catalog.schemas_by_node.items():
        for section in schema.sections:
            for field in section.fields:
                if field.control != "buttons":
                    continue
                labels = {option.label for option in options_by_field(catalog, node, field.key)}
                if (node, field.key) in EXACT_BUTTON_LABELS:
                    assert labels == EXACT_BUTTON_LABELS[(node, field.key)]
                if (node, field.key) not in count_exceptions:
                    assert 3 <= len(labels) <= 7


def test_body_snippets_partition_additive_options_into_useful_groups():
    catalog = load_default_catalog()
    field_record = catalog.field("identity", "body_snippets")
    options = options_by_field(catalog, "identity", "body_snippets")

    assert len(field_record.groups) >= 4
    assert {option.group for option in options} == set(field_record.groups)
    assert any(
        sum(option.group == group for option in options) > 1
        for group in field_record.groups
    )


def test_each_clothing_modifier_survives_button_group_replacement_and_assembly():
    catalog = load_default_catalog()
    options = options_by_field(catalog, "clothing", "clothing_modifiers")
    state = {"version": 1, "node": "clothing", "model_family": "flux", "fields": {}}

    assert len({option.group for option in options}) == len(options) == 5
    assert set(catalog.field("clothing", "clothing_modifiers").groups) == {
        option.group for option in options
    }
    for index, option in enumerate(options):
        state = replace_group_select(
            state,
            {
                "instance_id": f"modifier-{index}",
                "source_option_id": option.id,
                "label": option.label,
                "node": option.node,
                "field": option.field,
                "group": option.group,
                "text": option.phrases["flux"],
                "model_family": "flux",
                "lora_enabled": False,
            },
        )

    result = assemble(catalog, state)

    fragments = next(
        field["fragments"]
        for field in result.bundle["fields"]
        if field["key"] == "clothing_modifiers"
    )
    assert [fragment["label"] for fragment in fragments] == [
        "Topless",
        "Bottomless",
        "Partially undressed",
        "Underwear visible",
        "Open / unfastened",
    ]


def test_horizontal_view_has_exact_pov_and_over_the_shoulder_coverage():
    catalog = load_default_catalog()
    options = options_by_field(catalog, "camera", "horizontal_view")

    assert {option.label for option in options} == {
        "Straight-on",
        "Left oblique",
        "Right oblique",
        "Side-on",
        "Rear oblique",
        "POV",
        "Over-the-shoulder",
    }
    assert all(
        "point-of-view" in phrase.lower()
        for phrase in option_by_label(catalog, "camera", "horizontal_view", "POV").phrases.values()
    )
    assert all(
        "over-the-shoulder" in phrase.lower()
        for phrase in option_by_label(
            catalog, "camera", "horizontal_view", "Over-the-shoulder"
        ).phrases.values()
    )


def test_primary_light_directions_are_explicitly_image_frame_relative():
    catalog = load_default_catalog()
    options = options_by_field(catalog, "lighting", "primary_direction")

    assert len(options) == 10
    assert {option.label for option in options} == EXACT_BUTTON_LABELS[
        ("lighting", "primary_direction")
    ]
    for option in options:
        for phrase in option.phrases.values():
            assert "image frame" in phrase.lower()
            assert "subject's" not in phrase.lower()


def test_builtin_option_ids_are_unique_provenant_and_protected():
    catalog = load_default_catalog()
    option_ids = [option.id for option in catalog.options]

    assert len(option_ids) == len(set(option_ids))
    assert all(option.id.startswith(f"{option.node}.{option.field}.") for option in catalog.options)
    assert all(option.builtin for option in catalog.options)


def test_age_presets_are_unambiguously_adult_only():
    options = options_by_field(load_default_catalog(), "identity", "age_group")
    text = " ".join(
        [option.label for option in options]
        + [phrase for option in options for phrase in option.phrases.values()]
    ).lower()

    assert {"Young adult 18+", "20s", "30s", "40s", "50s", "60s", "Elderly"} == {
        option.label for option in options
    }
    assert "18+" in text and "adult" in text
    assert not {"child", "teen", "minor", "boy", "girl", "adolescent"} & set(text.split())


def test_body_axis_has_all_eight_image_directions_with_explicit_head_and_feet_language():
    options = options_by_field(load_default_catalog(), "pose", "body_axis")

    assert {option.label for option in options} == EXACT_BUTTON_LABELS[("pose", "body_axis")]
    assert len(options) == 8
    for option in options:
        for phrase in option.phrases.values():
            lowered = phrase.lower()
            assert "head" in lowered and "feet" in lowered and "frame" in lowered


@pytest.mark.parametrize(
    ("left_field", "right_field"),
    [
        ("left_arm", "right_arm"),
        ("left_hand", "right_hand"),
        ("left_leg", "right_leg"),
        ("left_foot", "right_foot"),
    ],
)
def test_subject_anatomical_side_fields_offer_matching_actions(left_field, right_field):
    catalog = load_default_catalog()
    left = options_by_field(catalog, "pose", left_field)
    right = options_by_field(catalog, "pose", right_field)

    assert {option.label for option in left} == {option.label for option in right}
    assert all("the subject's left" in phrase.lower() for option in left for phrase in option.phrases.values())
    assert all("the subject's right" in phrase.lower() for option in right for phrase in option.phrases.values())


def test_side_catalog_includes_required_arm_hand_leg_and_foot_actions():
    catalog = load_default_catalog()

    assert {
        "Phone near face",
        "Raised",
        "Extended",
        "Bent",
        "Resting",
        "Behind back",
    } <= {option.label for option in options_by_field(catalog, "pose", "left_arm")}
    assert {"One knee down", "Planted", "Lifted", "Crossed", "Bent"} <= {
        option.label for option in options_by_field(catalog, "pose", "left_leg")
    }
    assert {"Tiptoe", "Planted", "Lifted"} <= {
        option.label for option in options_by_field(catalog, "pose", "left_foot")
    }


def test_source_and_reference_clothing_roles_are_distinct_and_modifiers_are_complete():
    catalog = load_default_catalog()
    source = option_by_label(catalog, "clothing", "clothing_state", "Keep source clothing")
    reference = option_by_label(catalog, "clothing", "clothing_state", "Use reference clothing")

    assert all("source image" in phrase.lower() for phrase in source.phrases.values())
    assert all("reference image" in phrase.lower() for phrase in reference.phrases.values())
    assert source.phrases != reference.phrases
    assert {option.label for option in options_by_field(catalog, "clothing", "clothing_modifiers")} == (
        EXACT_BUTTON_LABELS[("clothing", "clothing_modifiers")]
    )


def test_named_spectra_are_disabled_full_domain_semantic_and_two_family():
    catalog = load_default_catalog()
    actual = set()

    for node, schema in catalog.schemas_by_node.items():
        for section in schema.sections:
            for field in section.fields:
                if field.control != "semantic_spectrum":
                    continue
                actual.add((node, field.key))
                assert field.enabled_by_default is False
                assert 3 <= len(field.spectrum) <= 5
                assert field.spectrum[0].minimum == 0.0
                assert field.spectrum[-1].maximum == 1.0
                assert all(set(stop.phrases) == {"flux", "qwen"} for stop in field.spectrum)
                assert all(
                    current.minimum == previous.maximum
                    for previous, current in zip(field.spectrum, field.spectrum[1:])
                )

    assert actual == SPECTRUM_FIELDS


def test_required_lighting_techniques_are_present():
    labels = {
        option.label
        for option in options_by_field(load_default_catalog(), "lighting", "lighting_techniques")
    }

    assert {
        "Rim light",
        "Backlight",
        "Three-point lighting",
        "Rembrandt lighting",
        "Chiaroscuro",
        "Volumetric light",
        "God rays",
        "Caustics",
        "Bounced light",
        "Colored gels",
        "Silhouette",
    } <= labels


def test_catalog_has_no_camera_movement_or_negative_prompt_contracts():
    schemas, options = default_payloads()
    camera_schema = next(node for node in schemas["nodes"] if node["key"] == "camera")
    camera_text = json.dumps(camera_schema).lower()
    camera_options = json.dumps(
        [option for option in options["options"] if option["node"] == "camera"]
    ).lower()
    all_text = json.dumps([schemas, options]).lower()

    assert not {"camera_movement", "pan", "tilt", "dolly", "truck", "crane", "tracking_shot"} & {
        field["key"]
        for section in camera_schema["sections"]
        for field in section["fields"]
    }
    assert all(term not in camera_text + camera_options for term in ("camera movement", "dolly shot", "tracking shot"))
    assert all(term not in all_text for term in ('"negative"', '"negative_prompt"', '"negative_phrases"'))


def test_catalog_records_are_deeply_immutable():
    catalog = load_default_catalog()
    field = catalog.field("lighting", "light_softness")
    option = catalog.options[0]

    with pytest.raises(TypeError):
        catalog.schemas_by_node["identity"] = catalog.schemas_by_node["identity"]
    with pytest.raises(TypeError):
        field.spectrum[0].phrases["flux"] = "changed"
    with pytest.raises(TypeError):
        option.phrases["flux"] = "changed"


def test_semantic_spectrum_uses_lower_inclusive_upper_exclusive_boundaries():
    field = load_default_catalog().field("camera", "depth_of_field")

    assert field.spectrum_phrase_for(0.0, "flux") == field.spectrum[0].phrases["flux"]
    assert field.spectrum_phrase_for(field.spectrum[1].minimum, "flux") == field.spectrum[1].phrases["flux"]
    assert field.spectrum_phrase_for(1.0, "flux") == field.spectrum[-1].phrases["flux"]


@pytest.mark.parametrize(
    ("stops", "match"),
    [
        (
            [
                {"minimum": 0.5, "maximum": 1.0, "phrases": {"flux": "late", "qwen": "late"}},
                {"minimum": 0.0, "maximum": 0.5, "phrases": {"flux": "early", "qwen": "early"}},
            ],
            "ordered",
        ),
        (
            [
                {"minimum": 0.0, "maximum": 0.6, "phrases": {"flux": "first", "qwen": "first"}},
                {"minimum": 0.5, "maximum": 1.0, "phrases": {"flux": "second", "qwen": "second"}},
            ],
            "overlap",
        ),
        (
            [
                {"minimum": 0.0, "maximum": 0.4, "phrases": {"flux": "first", "qwen": "first"}},
                {"minimum": 0.5, "maximum": 1.0, "phrases": {"flux": "second", "qwen": "second"}},
            ],
            "gap",
        ),
    ],
)
def test_semantic_spectrum_rejects_unordered_overlapping_and_gapped_stops(stops, match):
    schemas, options = default_payloads()
    raw_field(schemas, "camera", "depth_of_field")["spectrum"] = stops

    with pytest.raises(CatalogValidationError, match=match):
        catalog_from_data(schemas, options)


def test_schema_records_are_canonically_sorted_even_when_source_arrays_are_not():
    schemas, options = default_payloads()
    identity = next(node for node in schemas["nodes"] if node["key"] == "identity")
    identity["sections"].reverse()
    identity["sections"][-1]["fields"].append(
        {"key": "extra_notes", "label": "Extra notes", "order": 90, "control": "free_text"}
    )
    identity["sections"][-1]["fields"].reverse()

    schema = catalog_from_data(schemas, options).schemas_by_node["identity"]

    assert [section.order for section in schema.sections] == [10, 20, 30, 40]
    assert [field.order for field in schema.sections[0].fields] == [10, 20, 30, 40, 90]


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda schemas, options: next(node for node in schemas["nodes"] if node["key"] == "identity")["sections"][1].update({"order": 10}),
            "section order",
        ),
        (
            lambda schemas, options: next(node for node in schemas["nodes"] if node["key"] == "identity")["sections"][0]["fields"].append(
                {"key": "duplicate_order", "label": "Duplicate order", "order": 10, "control": "free_text"}
            ),
            "field order",
        ),
    ],
)
def test_schema_rejects_duplicate_section_and_field_orders(mutation, match):
    schemas, options = default_payloads()
    mutation(schemas, options)

    with pytest.raises(CatalogValidationError, match=match):
        catalog_from_data(schemas, options)


def test_option_id_namespace_must_match_its_declared_node_and_field():
    schemas, options = default_payloads()
    options["options"][0]["id"] = "camera.framing.mismatch"

    with pytest.raises(CatalogValidationError, match="namespace"):
        catalog_from_data(schemas, options)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda schemas, options: options["options"].append(dict(options["options"][0])), "unique"),
        (lambda schemas, options: options["options"][0]["phrases"].update({"flux": "  "}), "phrase"),
        (lambda schemas, options: options["options"][0].update({"node": "unknown"}), "node"),
        (lambda schemas, options: options["options"][0].update({"field": "unknown"}), "field"),
        (lambda schemas, options: options["options"][0].update({"group": "unknown"}), "group"),
        (lambda schemas, options: options["options"][0].update({"builtin": False}), "protected"),
        (
            lambda schemas, options: raw_field(schemas, "camera", "depth_of_field").update(
                {"spectrum": [{"minimum": 0, "maximum": 1, "phrases": {"flux": "raw number"}}]}
            ),
            "qwen",
        ),
        (lambda schemas, options: options.update({"version": "2.0"}), "version"),
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


@pytest.mark.parametrize(
    ("node", "field", "match"),
    [
        ("identitty", "subject_type", "unknown node"),
        ("identity", "subject_typo", "unknown field"),
    ],
)
def test_options_for_rejects_unknown_schema_locations(node, field, match):
    with pytest.raises(CatalogError, match=match):
        load_default_catalog().options_for(node, field, "flux")


def test_optional_lora_metadata_is_immutable_and_does_not_change_source_data():
    schemas, options = default_payloads()
    options["options"][0]["lora"] = {"tags": ["portrait"]}

    option = catalog_from_data(schemas, options).options[0]

    assert option.lora == {"tags": ("portrait",)}
    with pytest.raises((AttributeError, TypeError)):
        option.lora["tags"].append("changed")
    assert options["options"][0]["lora"] == {"tags": ["portrait"]}
