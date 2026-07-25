import builtins
import importlib
import json

import pytest

from custom_nodes.comfyui_arch_prompt_tools.engine import default_state
from custom_nodes.comfyui_arch_prompt_tools.nodes import (
    ArchPtCamera,
    ArchPtClothing,
    ArchPtCombine,
    ArchPtEnvironment,
    ArchPtIdentity,
    ArchPtLighting,
    ArchPtPose,
)
from custom_nodes.comfyui_arch_prompt_tools import (
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
)


FOCUSED_NODES = {
    "ArchPtIdentity": (ArchPtIdentity, "identity", "arch-pt-Identity"),
    "ArchPtPose": (ArchPtPose, "pose", "arch-pt-Pose"),
    "ArchPtClothing": (ArchPtClothing, "clothing", "arch-pt-Clothing"),
    "ArchPtEnvironment": (ArchPtEnvironment, "environment", "arch-pt-Environment"),
    "ArchPtCamera": (ArchPtCamera, "camera", "arch-pt-Camera"),
    "ArchPtLighting": (ArchPtLighting, "lighting", "arch-pt-Lighting"),
    "ArchPtCombine": (ArchPtCombine, None, "arch-pt-Combine"),
}


def make_state(node, *, model_family="flux", field="notes", text=""):
    fields = {} if not text else {field: {"fragments": [], "specifics": text}}
    return json.dumps({"version": 1, "node": node, "model_family": model_family, "fields": fields})


def make_bundle(node, text, *, lora_requests=None):
    return {
        "version": 1,
        "node": node,
        "model_family": "flux",
        "prompt": text,
        "fields": [
            {
                "section": "section",
                "section_label": "Section",
                "section_order": 10,
                "key": "notes",
                "label": "Notes",
                "order": 10,
                "control": "free_text",
                "fragments": [],
                "specifics": text,
            }
        ],
        "lora_requests": lora_requests or [],
        "metadata": {"node": node, "label": node.title()},
    }


def test_exactly_the_seven_arch_pt_node_mappings_and_display_names_are_exported():
    assert set(NODE_CLASS_MAPPINGS) == set(FOCUSED_NODES)
    assert set(NODE_DISPLAY_NAME_MAPPINGS) == set(FOCUSED_NODES)
    for mapping_name, (node_class, _, display_name) in FOCUSED_NODES.items():
        assert NODE_CLASS_MAPPINGS[mapping_name] is node_class
        assert NODE_DISPLAY_NAME_MAPPINGS[mapping_name] == display_name
        assert node_class.CATEGORY.startswith("arch-pt")


@pytest.mark.parametrize("mapping_name", list(FOCUSED_NODES))
def test_node_categories_are_arch_pt_prefixed(mapping_name):
    assert NODE_CLASS_MAPPINGS[mapping_name].CATEGORY.startswith("arch-pt")


@pytest.mark.parametrize("mapping_name", [name for name, (_, node, _) in FOCUSED_NODES.items() if node])
def test_focused_input_schema_has_serializable_node_specific_v1_state(mapping_name):
    node_class, node_key, _ = FOCUSED_NODES[mapping_name]
    required = node_class.INPUT_TYPES()["required"]

    assert required["model_family"] == (["flux", "qwen"], {"default": "flux"})
    assert required["state_json"][0] == "STRING"
    assert required["state_json"][1]["dynamicPrompts"] is False
    assert json.loads(required["state_json"][1]["default"]) == default_state(node_key)
    assert node_class.RETURN_TYPES == ("STRING", "ARCH_PT_BUNDLE")
    assert node_class.RETURN_NAMES == ("prompt", "prompt_bundle")


def test_combiner_schema_exposes_required_controls_and_optional_typed_inputs():
    schema = ArchPtCombine.INPUT_TYPES()

    assert schema["required"] == {
        "separator": ("STRING", {"default": ", "}),
        "dedupe": ("BOOLEAN", {"default": True}),
    }
    assert schema["optional"] == {
        "base_prompt": ("STRING", {"forceInput": True}),
        "extra_prompt": ("STRING", {"forceInput": True}),
        "identity": ("ARCH_PT_BUNDLE",),
        "pose": ("ARCH_PT_BUNDLE",),
        "clothing": ("ARCH_PT_BUNDLE",),
        "environment": ("ARCH_PT_BUNDLE",),
        "camera": ("ARCH_PT_BUNDLE",),
        "lighting": ("ARCH_PT_BUNDLE",),
    }
    assert ArchPtCombine.RETURN_TYPES == ("STRING", "STRING", "STRING")
    assert ArchPtCombine.RETURN_NAMES == ("positive_prompt", "metadata_json", "lora_requests_json")


def test_blank_focused_node_outputs_empty_prompt_and_serializable_bundle():
    prompt, bundle = ArchPtIdentity().build("flux", make_state("identity"))

    assert prompt == ""
    assert bundle["version"] == 1
    assert bundle["node"] == "identity"
    assert bundle["prompt"] == ""
    assert bundle["lora_requests"] == []
    assert bundle["metadata"]["node"] == "identity"
    assert json.loads(json.dumps(bundle)) == bundle


def test_focused_node_uses_the_copied_engine_state_to_assemble_a_prompt():
    copied = {
        "instance_id": "copied-gender",
        "source_option_id": "identity.gender.feminine",
        "label": "Feminine",
        "node": "identity",
        "field": "gender",
        "group": "gender",
        "text": "woman",
        "model_family": "flux",
        "lora_enabled": False,
    }
    state = {
        "version": 1,
        "node": "identity",
        "model_family": "flux",
        "fields": {"gender": {"fragments": [copied], "specifics": "portrait subject"}},
    }

    prompt, bundle = ArchPtIdentity().build("flux", json.dumps(state))

    assert prompt == "woman, portrait subject"
    assert bundle["fields"][0]["fragments"][0] == copied


def test_model_selector_changes_only_top_level_family_not_copied_fragment_snapshots_or_text():
    copied = {
        "instance_id": "copied-gender",
        "source_option_id": "identity.gender.feminine",
        "label": "Feminine",
        "node": "identity",
        "field": "gender",
        "group": "gender",
        "text": "original copied wording",
        "model_family": "qwen",
        "lora_enabled": False,
    }
    state = {"version": 1, "node": "identity", "model_family": "qwen", "fields": {"gender": {"fragments": [copied]}}}

    prompt, bundle = ArchPtIdentity().build("flux", json.dumps(state))

    assert prompt == "original copied wording"
    assert bundle["model_family"] == "flux"
    assert bundle["fields"][0]["fragments"][0]["model_family"] == "qwen"
    assert bundle["fields"][0]["fragments"][0]["text"] == "original copied wording"


def test_focused_node_rejects_a_state_for_a_different_node():
    with pytest.raises(ValueError, match="state node must be identity"):
        ArchPtIdentity().build("flux", make_state("pose"))


def test_combiner_uses_the_fixed_conceptual_order_with_optional_strings():
    result = ArchPtCombine().combine(
        separator=" | ",
        dedupe=True,
        extra_prompt="extra",
        camera=make_bundle("camera", "camera"),
        identity=make_bundle("identity", "identity"),
        base_prompt="base",
        lighting=make_bundle("lighting", "lighting"),
        pose=make_bundle("pose", "pose"),
        clothing=make_bundle("clothing", "clothing"),
        environment=make_bundle("environment", "environment"),
    )

    assert result[0] == "base | identity | pose | clothing | environment | camera | lighting | extra"


def test_combiner_exact_dedupe_is_case_insensitive_and_whitespace_normalized_only_when_enabled():
    identity = make_bundle("identity", "  Woman   with hat ")
    pose = make_bundle("pose", "woman with hat")

    deduped = ArchPtCombine().combine(", ", True, base_prompt="woman with a hat", identity=identity, pose=pose)
    preserved = ArchPtCombine().combine(", ", False, base_prompt="woman with a hat", identity=identity, pose=pose)

    assert deduped[0] == "woman with a hat, Woman with hat"
    assert preserved[0] == "woman with a hat, Woman with hat, woman with hat"


def test_combiner_rejects_wrong_version_node_and_invalid_bundle_shapes():
    with pytest.raises(ValueError, match="identity bundle.*version"):
        ArchPtCombine().combine(", ", True, identity={**make_bundle("identity", "ok"), "version": 2})
    with pytest.raises(ValueError, match="identity bundle.*node"):
        ArchPtCombine().combine(", ", True, identity=make_bundle("pose", "wrong socket"))
    with pytest.raises(ValueError, match="identity bundle.*fields"):
        ArchPtCombine().combine(", ", True, identity={**make_bundle("identity", "ok"), "fields": "invalid"})


@pytest.mark.parametrize("invalid_bundle", ["not a bundle", ["not", "a", "bundle"]])
def test_combiner_rejects_non_object_bundle_inputs_with_a_clear_error(invalid_bundle):
    with pytest.raises(ValueError, match="identity bundle must be an object"):
        ArchPtCombine().combine(", ", True, identity=invalid_bundle)


def test_combiner_preserves_per_node_metadata_and_dedupes_only_identical_lora_records():
    request = {"lora": {"name": "portrait", "strength": 0.8}, "origin": {"node": "identity", "instance_id": "one"}}
    distinct = {"lora": {"name": "portrait", "strength": 1.0}, "origin": {"node": "identity", "instance_id": "one"}}
    identity = make_bundle("identity", "subject", lora_requests=[request, request, distinct])

    _, metadata_json, loras_json = ArchPtCombine().combine(", ", True, identity=identity)

    metadata = json.loads(metadata_json)
    loras = json.loads(loras_json)
    assert metadata == {"bundles": [{"metadata": identity["metadata"], "model_family": "flux", "node": "identity"}], "version": 1}
    assert loras == [request, distinct]
    assert metadata_json == json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert loras_json == json.dumps(loras, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def test_combiner_unicode_json_is_literal_and_byte_deterministic():
    request = {
        "lora": {"name": "café style", "strength": 0.8},
        "origin": {"node": "identity", "instance_id": "髪", "label": "光"},
    }
    identity = make_bundle("identity", "portrait with 髪", lora_requests=[request])
    identity["metadata"] = {"label": "café", "detail": "光"}

    first = ArchPtCombine().combine(", ", True, identity=identity)
    second = ArchPtCombine().combine(", ", True, identity=identity)

    assert "café" in first[1]
    assert "髪" in first[2]
    assert "光" in first[1]
    assert "\\u" not in first[1]
    assert "\\u" not in first[2]
    assert second[1:] == first[1:]


def test_combiner_retains_distinct_lora_origins_but_dedupes_exact_records():
    first_origin = {"lora": {"name": "portrait", "strength": 0.8}, "origin": {"node": "identity", "instance_id": "one"}}
    second_origin = {"lora": {"name": "portrait", "strength": 0.8}, "origin": {"node": "identity", "instance_id": "two"}}
    identity = make_bundle("identity", "subject", lora_requests=[first_origin, first_origin, second_origin])

    _, _, loras_json = ArchPtCombine().combine(", ", True, identity=identity)

    assert json.loads(loras_json) == [first_origin, second_origin]


def test_nodes_import_does_not_import_legacy_prompt_packages(monkeypatch):
    legacy_modules = (
        "custom_nodes.comfyui_prompt_library",
        "custom_nodes.comfyui_reverse_prompter",
        "custom_nodes.comfyui_civitai_prompt_import",
        "custom_nodes.comfyui_smart_model_loader",
    )
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if any(name == legacy or name.startswith(f"{legacy}.") for legacy in legacy_modules):
            raise AssertionError(f"nodes must not import legacy prompt package: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    module = importlib.import_module("custom_nodes.comfyui_arch_prompt_tools.nodes")

    importlib.reload(module)


def test_combiner_ignores_empty_optional_bundles_and_is_deterministic():
    empty = make_bundle("identity", "")
    first = ArchPtCombine().combine(", ", True, identity=empty, pose=None, base_prompt="  base  ")
    second = ArchPtCombine().combine(", ", True, identity=empty, pose=None, base_prompt="  base  ")

    assert first == ("base", '{"bundles":[],"version":1}', "[]")
    assert second == first
