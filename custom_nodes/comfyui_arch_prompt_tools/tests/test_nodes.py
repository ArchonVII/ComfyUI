import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from custom_nodes.comfyui_arch_prompt_tools.catalog import CatalogValidationError
from custom_nodes.comfyui_arch_prompt_tools.engine import default_state
from custom_nodes.comfyui_arch_prompt_tools import nodes as nodes_module
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


TEXT_FIELD_BY_NODE = {
    "identity": "identity_specifics",
    "pose": "action_specifics",
    "clothing": "state_specifics",
    "environment": "named_setting",
    "camera": "framing_specifics",
    "lighting": "source_specifics",
}


def make_bundle(node, text):
    node_class = next(node_class for node_class, node_key, _ in FOCUSED_NODES.values() if node_key == node)
    return node_class().build("flux", make_state(node, field=TEXT_FIELD_BY_NODE[node], text=text))[1]


def identity_bundle_with_lora(*, text="woman", lora=None, instance_id="fragment-1"):
    copied = {
        "instance_id": instance_id,
        "source_option_id": "identity.subject_type.single_person",
        "label": "Single person",
        "node": "identity",
        "field": "subject_type",
        "group": "subject_type",
        "text": text,
        "model_family": "flux",
        "lora_enabled": True,
        "lora": lora or {"name": "portrait", "strength": 0.8},
    }
    state = {"version": 1, "node": "identity", "model_family": "flux", "fields": {"subject_type": {"fragments": [copied]}}}
    return ArchPtIdentity().build("flux", json.dumps(state))[1]


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
        "instance_id": "copied-subject",
        "source_option_id": "identity.subject_type.single_person",
        "label": "Single person",
        "node": "identity",
        "field": "subject_type",
        "group": "subject_type",
        "text": "woman",
        "model_family": "flux",
        "lora_enabled": False,
    }
    state = {
        "version": 1,
        "node": "identity",
        "model_family": "flux",
        "fields": {"subject_type": {"fragments": [copied], "specifics": "portrait subject"}},
    }

    prompt, bundle = ArchPtIdentity().build("flux", json.dumps(state))

    assert prompt == "woman, portrait subject"
    assert bundle["fields"][0]["fragments"][0] == copied


def test_model_selector_changes_only_top_level_family_not_copied_fragment_snapshots_or_text():
    copied = {
        "instance_id": "copied-subject",
        "source_option_id": "identity.subject_type.single_person",
        "label": "Single person",
        "node": "identity",
        "field": "subject_type",
        "group": "subject_type",
        "text": "original copied wording",
        "model_family": "qwen",
        "lora_enabled": False,
    }
    state = {"version": 1, "node": "identity", "model_family": "qwen", "fields": {"subject_type": {"fragments": [copied]}}}

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


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda bundle: bundle["fields"].__setitem__(0, {**bundle["fields"][0], "key": "unknown"}), "field"),
        (lambda bundle: bundle["fields"].reverse(), "field"),
        (lambda bundle: bundle["fields"].__setitem__(1, copy.deepcopy(bundle["fields"][0])), "field"),
        (lambda bundle: bundle["fields"][0].update({"section": "wrong"}), "field"),
        (lambda bundle: bundle["fields"][0].update({"label": "Wrong"}), "field"),
        (lambda bundle: bundle["fields"][0].update({"control": "free_text"}), "field"),
        (lambda bundle: bundle.update({"prompt": "tampered prompt"}), "prompt"),
        (lambda bundle: bundle["metadata"].update({"node": "pose"}), "metadata"),
        (lambda bundle: bundle["metadata"].update({"model_family": "qwen"}), "metadata"),
        (lambda bundle: bundle["metadata"].update({"sections": []}), "metadata"),
    ],
)
def test_combiner_rejects_noncanonical_bundle_fields_prompt_and_metadata(mutation, match):
    bundle = make_bundle("identity", "subject")
    mutation(bundle)

    with pytest.raises(ValueError, match=match):
        ArchPtCombine().combine(", ", True, identity=bundle)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda bundle: bundle["fields"][0]["fragments"][0].update({"node": "pose"}), "fragment"),
        (lambda bundle: bundle["fields"][0]["fragments"][0].update({"field": "body_type"}), "fragment"),
        (lambda bundle: bundle["fields"][0]["fragments"][0].update({"model_family": "unsupported"}), "fragment"),
        (lambda bundle: bundle.update({"lora_requests": [{"arbitrary": "request"}]}), "lora request"),
        (lambda bundle: bundle["lora_requests"][0]["origin"].update({"instance_id": "not-the-fragment"}), "lora request"),
    ],
)
def test_combiner_rejects_mismatched_fragments_and_unverified_lora_requests(mutation, match):
    bundle = identity_bundle_with_lora()
    mutation(bundle)

    with pytest.raises(ValueError, match=match):
        ArchPtCombine().combine(", ", True, identity=bundle)


@pytest.mark.parametrize("invalid_bundle", ["not a bundle", ["not", "a", "bundle"]])
def test_combiner_rejects_non_object_bundle_inputs_with_a_clear_error(invalid_bundle):
    with pytest.raises(ValueError, match="identity bundle must be an object"):
        ArchPtCombine().combine(", ", True, identity=invalid_bundle)


def test_combiner_preserves_per_node_metadata_and_dedupes_only_identical_lora_records():
    identity = identity_bundle_with_lora()
    request = identity["lora_requests"][0]

    _, metadata_json, loras_json = ArchPtCombine().combine(", ", True, identity=identity)

    metadata = json.loads(metadata_json)
    loras = json.loads(loras_json)
    assert metadata == {"bundles": [{"metadata": identity["metadata"], "model_family": "flux", "node": "identity"}], "version": 1}
    assert loras == [request]
    assert metadata_json == json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert loras_json == json.dumps(loras, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def test_combiner_unicode_json_is_literal_and_byte_deterministic():
    identity = identity_bundle_with_lora(text="portrait with 髪", instance_id="髪", lora={"name": "café 光", "strength": 0.8})
    identity["metadata"]["note"] = "café 光"

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

    assert nodes_module._dedupe_records([first_origin, first_origin, second_origin]) == [first_origin, second_origin]


def test_combiner_retains_distinct_enabled_lora_origins_through_its_public_interface():
    first = identity_bundle_with_lora(instance_id="first")
    second_fragment = copy.deepcopy(first["fields"][0]["fragments"][0])
    second_fragment["instance_id"] = "second"
    first["fields"][0]["fragments"].append(second_fragment)
    second_request = copy.deepcopy(first["lora_requests"][0])
    second_request["origin"]["instance_id"] = "second"
    first["lora_requests"].append(second_request)
    first["prompt"] = "woman"

    _, _, loras_json = ArchPtCombine().combine(", ", True, identity=first)

    assert json.loads(loras_json) == first["lora_requests"]
    assert [request["origin"]["instance_id"] for request in json.loads(loras_json)] == ["first", "second"]


def test_fresh_nodes_import_avoids_legacy_packages_and_catalog_file_reads():
    workspace = Path(__file__).parents[3]
    program = '''
import builtins
import pathlib

legacy = {
    "custom_nodes.comfyui_prompt_library",
    "custom_nodes.comfyui_reverse_prompter",
    "custom_nodes.comfyui_civitai_prompt_import",
    "custom_nodes.comfyui_smart_model_loader",
}
original_import = builtins.__import__
original_open = pathlib.Path.open

def guarded_import(name, *args, **kwargs):
    if any(name == package or name.startswith(package + ".") for package in legacy):
        raise AssertionError("legacy prompt import: " + name)
    return original_import(name, *args, **kwargs)

def guarded_open(path, *args, **kwargs):
    if path.name in {"schemas.json", "builtin_options.json"}:
        raise AssertionError("catalog data read during import")
    return original_open(path, *args, **kwargs)

builtins.__import__ = guarded_import
pathlib.Path.open = guarded_open
import custom_nodes.comfyui_arch_prompt_tools.nodes
'''

    result = subprocess.run([sys.executable, "-c", program], cwd=workspace, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


@pytest.fixture
def isolated_catalog_data(tmp_path, monkeypatch):
    source_data = Path(__file__).parents[1] / "data"
    for filename in ("schemas.json", "builtin_options.json"):
        (tmp_path / filename).write_bytes((source_data / filename).read_bytes())
    monkeypatch.setattr(nodes_module, "_DATA_DIRECTORY", tmp_path)
    nodes_module._reset_catalog_cache()
    yield tmp_path
    nodes_module._reset_catalog_cache()


def test_default_catalog_cache_reuses_one_load_for_six_focused_builds(isolated_catalog_data, monkeypatch):
    calls = 0
    original_load_catalog = nodes_module.load_catalog

    def counted_load_catalog(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_load_catalog(*args, **kwargs)

    monkeypatch.setattr(nodes_module, "load_catalog", counted_load_catalog)
    for _, node_key, _ in FOCUSED_NODES.values():
        if node_key is None:
            continue
        node_class = next(node_class for node_class, candidate, _ in FOCUSED_NODES.values() if candidate == node_key)
        node_class().build("flux", make_state(node_key))

    assert calls == 1


def test_default_catalog_cache_invalidates_when_either_data_file_changes(isolated_catalog_data, monkeypatch):
    calls = 0
    original_load_catalog = nodes_module.load_catalog

    def counted_load_catalog(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_load_catalog(*args, **kwargs)

    monkeypatch.setattr(nodes_module, "load_catalog", counted_load_catalog)
    ArchPtIdentity().build("flux", make_state("identity"))
    for filename in ("schemas.json", "builtin_options.json"):
        path = isolated_catalog_data / filename
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        ArchPtIdentity().build("flux", make_state("identity"))

    assert calls == 3


def test_invalid_catalog_reload_preserves_prior_cache_and_surfaces_its_error(isolated_catalog_data):
    original = nodes_module._catalog()
    (isolated_catalog_data / "schemas.json").write_text(
        '{"version":"1.0","families":["flux"],"nodes":"invalid"}', encoding="utf-8"
    )

    with pytest.raises(CatalogValidationError, match="nodes must be a list"):
        nodes_module._catalog()

    assert nodes_module._DEFAULT_CATALOG_CACHE[1] is original


def test_cold_catalog_cache_wraps_missing_files_as_catalog_validation_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes_module, "_DATA_DIRECTORY", tmp_path)
    nodes_module._reset_catalog_cache()

    with pytest.raises(CatalogValidationError, match="could not access default catalog"):
        nodes_module._catalog()


def test_warm_catalog_cache_does_not_serve_stale_data_when_stat_fails(isolated_catalog_data, monkeypatch):
    original = nodes_module._catalog()

    def denied_fingerprint():
        raise PermissionError("denied")

    monkeypatch.setattr(nodes_module, "_catalog_fingerprint", denied_fingerprint)
    with pytest.raises(CatalogValidationError, match="could not access default catalog"):
        nodes_module._catalog()

    assert nodes_module._DEFAULT_CATALOG_CACHE[1] is original


def test_warm_catalog_cache_wraps_load_permission_errors_without_serving_stale_data(isolated_catalog_data, monkeypatch):
    original = nodes_module._catalog()
    original_fingerprint = nodes_module._catalog_fingerprint()
    changed_fingerprint = ((original_fingerprint[0][0] + 1, original_fingerprint[0][1]), original_fingerprint[1])
    monkeypatch.setattr(nodes_module, "_catalog_fingerprint", lambda: changed_fingerprint)

    def denied_load(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(nodes_module, "load_catalog", denied_load)
    with pytest.raises(CatalogValidationError, match="could not access default catalog"):
        nodes_module._catalog()

    assert nodes_module._DEFAULT_CATALOG_CACHE[1] is original


def test_catalog_cache_retries_when_files_change_during_load(isolated_catalog_data, monkeypatch):
    old_fingerprint = ((1, 1), (1, 1))
    new_fingerprint = ((2, 1), (2, 1))
    fingerprints = iter((old_fingerprint, new_fingerprint, new_fingerprint, new_fingerprint))
    loaded_catalogs = [object(), object()]
    nodes_module._reset_catalog_cache()
    monkeypatch.setattr(nodes_module, "_catalog_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(nodes_module, "load_catalog", lambda *args, **kwargs: loaded_catalogs.pop(0))

    catalog = nodes_module._catalog()

    assert catalog is not None
    assert nodes_module._DEFAULT_CATALOG_CACHE == (new_fingerprint, catalog)
    assert loaded_catalogs == []


def test_combiner_ignores_empty_optional_bundles_and_is_deterministic():
    empty = make_bundle("identity", "")
    first = ArchPtCombine().combine(", ", True, identity=empty, pose=None, base_prompt="  base  ")
    second = ArchPtCombine().combine(", ", True, identity=empty, pose=None, base_prompt="  base  ")

    assert first == ("base", '{"bundles":[],"version":1}', "[]")
    assert second == first
