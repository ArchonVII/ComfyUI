import json
from pathlib import Path

import pytest

from custom_nodes.comfyui_arch_prompt_tools.catalog import catalog_from_data, load_catalog
from custom_nodes.comfyui_arch_prompt_tools.engine import (
    StateValidationError,
    additive_select,
    assemble,
    edit_fragment,
    normalize_state,
    remove_fragment,
    replace_group_select,
)


DATA_DIR = Path(__file__).parents[1] / "data"


def catalog():
    return load_catalog(DATA_DIR / "schemas.json", DATA_DIR / "builtin_options.json")


def catalog_with_frozen_lora():
    schemas = json.loads((DATA_DIR / "schemas.json").read_text(encoding="utf-8"))
    options = json.loads((DATA_DIR / "builtin_options.json").read_text(encoding="utf-8"))
    options["options"][0]["lora"] = {"name": "portrait-style", "tags": ["portrait"]}
    return catalog_from_data(schemas, options)


def state(node="identity", model_family="flux", fields=None):
    return {
        "version": 1,
        "node": node,
        "model_family": model_family,
        "fields": fields or {},
    }


def fragment(
    instance_id="fragment-1",
    *,
    node="identity",
    field="gender",
    group="gender",
    text="woman",
    model_family="flux",
    source_option_id="identity.gender.feminine",
    lora=None,
    lora_enabled=False,
):
    result = {
        "instance_id": instance_id,
        "source_option_id": source_option_id,
        "label": "Example",
        "node": node,
        "field": field,
        "group": group,
        "text": text,
        "model_family": model_family,
        "lora_enabled": lora_enabled,
    }
    if lora is not None:
        result["lora"] = lora
    return result


def test_blank_default_state_emits_empty_prompt_and_serializable_bundle():
    result = assemble(catalog(), state())

    assert result.prompt == ""
    assert result.bundle["version"] == 1
    assert result.bundle["node"] == "identity"
    assert result.bundle["model_family"] == "flux"
    assert result.bundle["prompt"] == ""
    assert result.bundle["lora_requests"] == []
    assert json.loads(json.dumps(result.bundle)) == result.bundle


def test_assembly_uses_approved_schema_section_and_field_order():
    result = assemble(
        catalog(),
        state(
            fields={
                "expression_notes": {"specifics": "smiling"},
                "gender": {"fragments": [fragment(text="woman")]},
                "body_notes": {"specifics": "tall"},
            }
        ),
    )

    assert result.prompt == "woman, tall, smiling"
    assert [item["key"] for item in result.bundle["fields"]] == [
        "gender",
        "body_notes",
        "appearance_notes",
        "expression_notes",
    ]
    assert [item["section"] for item in result.bundle["fields"]] == [
        "core_identity",
        "body_structure",
        "appearance",
        "expression",
    ]


def test_additive_selection_appends_copied_fragment_and_preserves_specifics():
    initial = state(fields={"gender": {"specifics": "portrait subject"}})
    updated = additive_select(initial, fragment("one"))
    updated = additive_select(updated, fragment("two", text="freckles", group="details"))

    assert [item["instance_id"] for item in updated["fields"]["gender"]["fragments"]] == ["one", "two"]
    assert updated["fields"]["gender"]["specifics"] == "portrait subject"


def test_exclusive_selection_replaces_only_matching_field_and_group():
    initial = state(
        fields={
            "gender": {
                "fragments": [
                    fragment("old", text="woman"),
                    fragment("detail", text="freckles", group="details"),
                ],
                "specifics": "manual note",
            }
        }
    )

    updated = replace_group_select(initial, fragment("new", text="man"))

    assert [item["instance_id"] for item in updated["fields"]["gender"]["fragments"]] == ["detail", "new"]
    assert updated["fields"]["gender"]["specifics"] == "manual note"


def test_editing_and_removing_affect_only_the_workflow_copy_instance():
    initial = state(
        fields={
            "gender": {"fragments": [fragment("one", text="woman"), fragment("two", text="freckles", group="details")]}
        }
    )
    edited = edit_fragment(initial, "one", "heroine")
    removed = remove_fragment(edited, "two")

    assert [item["text"] for item in edited["fields"]["gender"]["fragments"]] == ["heroine", "freckles"]
    assert [item["instance_id"] for item in removed["fields"]["gender"]["fragments"]] == ["one"]
    assert initial["fields"]["gender"]["fragments"][0]["text"] == "woman"


def test_copied_fragment_and_model_family_snapshot_are_never_rewritten_from_catalog():
    copied = fragment(text="original copied wording", model_family="qwen")
    result = assemble(catalog(), state(model_family="flux", fields={"gender": {"fragments": [copied]}}))

    assert result.prompt == "original copied wording"
    assert result.bundle["fields"][0]["fragments"][0]["model_family"] == "qwen"
    assert result.bundle["model_family"] == "flux"


def test_semantic_slider_copy_is_assembled_as_ordinary_copied_text():
    slider_copy = fragment(
        node="environment",
        field="atmosphere",
        group="atmosphere",
        text="dramatic atmosphere",
        source_option_id="environment.atmosphere.slider.0.9",
    )

    result = assemble(catalog(), state(node="environment", fields={"atmosphere": {"fragments": [slider_copy]}}))

    assert result.prompt == "dramatic atmosphere"


def test_assembly_dedupes_only_exact_case_insensitive_normalized_text():
    result = assemble(
        catalog(),
        state(
            fields={
                "gender": {
                    "fragments": [fragment("one", text="  Woman   with  hat "), fragment("two", text="woman with hat", group="details")],
                    "specifics": "woman with a hat",
                }
            }
        ),
    )

    assert result.prompt == "Woman with hat, woman with a hat"
    assert result.bundle["fields"][0]["fragments"][0]["text"] == "Woman with hat"
    assert result.bundle["fields"][0]["specifics"] == "woman with a hat"


def test_collects_only_enabled_copied_lora_requests_with_origin_metadata():
    lora = {"name": "portrait-style", "strength": 0.8}
    result = assemble(
        catalog(),
        state(
            fields={
                "gender": {
                    "fragments": [
                        fragment("enabled", lora=lora, lora_enabled=True),
                        fragment("disabled", text="freckles", group="details", lora=lora, lora_enabled=False),
                        fragment("none", text="blue eyes", group="eyes", lora_enabled=True),
                    ]
                }
            }
        ),
    )

    assert result.bundle["lora_requests"] == [
        {
            "lora": lora,
            "origin": {
                "instance_id": "enabled",
                "source_option_id": "identity.gender.feminine",
                "node": "identity",
                "field": "gender",
                "group": "gender",
            },
        }
    ]


def test_frozen_catalog_lora_metadata_is_thawed_into_a_serializable_workflow_bundle():
    source_option = catalog_with_frozen_lora().options[0]
    result = assemble(
        catalog(),
        state(fields={"gender": {"fragments": [fragment(lora=source_option.lora, lora_enabled=True)]}}),
    )

    copied_lora = result.bundle["fields"][0]["fragments"][0]["lora"]
    assert copied_lora == {"name": "portrait-style", "tags": ["portrait"]}
    assert isinstance(copied_lora, dict)
    assert json.loads(json.dumps(result.bundle)) == result.bundle


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (state(node="unknown"), "unknown node"),
        (state(fields={"unknown": {}}), "unknown field"),
        ({"version": 2, "node": "identity", "model_family": "flux", "fields": {}}, "version"),
        ({"version": True, "node": "identity", "model_family": "flux", "fields": {}}, "version"),
        ({"version": 1.0, "node": "identity", "model_family": "flux", "fields": {}}, "version"),
    ],
)
def test_normalization_rejects_unknown_or_unsupported_state(payload, match):
    with pytest.raises(StateValidationError, match=match):
        normalize_state(payload, catalog())


@pytest.mark.parametrize(
    "operation",
    [
        lambda payload: additive_select(payload, fragment("new")),
        lambda payload: replace_group_select(payload, fragment("new")),
        lambda payload: edit_fragment(payload, "one", "edited"),
        lambda payload: remove_fragment(payload, "one"),
    ],
)
@pytest.mark.parametrize(
    "payload",
    [
        {"version": True, "node": "identity", "model_family": "flux", "fields": {}},
        {"version": 1, "node": "identity", "model_family": "unsupported", "fields": {}},
        {"version": 1, "node": "identity", "model_family": "flux", "fields": {"gender": {"specifics": 9}}},
        {"version": 1, "node": "identity", "model_family": "flux", "fields": {"gender": {"fragments": [{}]}}},
    ],
)
def test_mutation_helpers_reject_malformed_state_before_mutating(operation, payload):
    with pytest.raises(StateValidationError):
        operation(payload)
