import importlib.util
import json
import re
from pathlib import Path

from custom_nodes.comfyui_arch_prompt_tools import (
    NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS,
)


REPO_ROOT = Path(__file__).parents[3]
PACKAGE_DIR = Path(__file__).parents[1]
README = PACKAGE_DIR / "README.md"
WORKFLOW_DIR = REPO_ROOT / "user" / "default" / "workflows" / "agent"
WORKFLOW = WORKFLOW_DIR / "38 - Arch PT Prompt Builder.json"

FOCUSED_CLASSES = {
    node_type: node_class
    for node_type, node_class in NODE_CLASS_MAPPINGS.items()
    if getattr(node_class, "NODE_KEY", "")
}
FOCUSED_TYPES = {
    node_type: node_class.NODE_KEY
    for node_type, node_class in FOCUSED_CLASSES.items()
}
COMBINE_TYPES = {
    node_type: node_class
    for node_type, node_class in NODE_CLASS_MAPPINGS.items()
    if not getattr(node_class, "NODE_KEY", "")
}
assert len(COMBINE_TYPES) == 1
COMBINE_TYPE, COMBINE_CLASS = next(iter(COMBINE_TYPES.items()))
ALLOWED_TYPES = {
    *FOCUSED_TYPES,
    COMBINE_TYPE,
    "PrimitiveStringMultiline",
    "PreviewAny",
    "MarkdownNote",
}


def load_workflow():
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def nodes_by_id(workflow):
    return {node["id"]: node for node in workflow["nodes"]}


def workflow_input_type(input_definition):
    declared = input_definition[0]
    return "COMBO" if isinstance(declared, list) else declared


def input_definitions(node_class):
    schema = node_class.INPUT_TYPES()
    return {
        **schema.get("required", {}),
        **schema.get("optional", {}),
    }


def test_readme_and_exactly_one_arch_pt_example_workflow_exist():
    assert README.is_file()
    matching = sorted(WORKFLOW_DIR.glob("*Arch PT Prompt Builder*.json"))
    assert matching == [WORKFLOW]


def test_workflow_is_current_editor_format_with_unique_graph_identifiers():
    workflow = load_workflow()
    assert workflow["version"] == 0.4
    assert workflow["revision"] == 0
    assert workflow["extra"]["frontendVersion"] == "1.45.19"
    assert workflow["extra"]["workflowRendererVersion"] == "LG"
    assert workflow["extra"]["arch_pt_prompt_builder"]["version"] == 1
    assert isinstance(workflow["id"], str) and workflow["id"]

    node_ids = [node["id"] for node in workflow["nodes"]]
    link_ids = [link[0] for link in workflow["links"]]
    group_ids = [group["id"] for group in workflow["groups"]]
    assert len(node_ids) == len(set(node_ids))
    assert len(link_ids) == len(set(link_ids))
    assert len(group_ids) == len(set(group_ids))
    assert workflow["last_node_id"] == max(node_ids)
    assert workflow["last_link_id"] == max(link_ids)
    assert sorted(node["order"] for node in workflow["nodes"]) == list(
        range(len(workflow["nodes"]))
    )


def test_graph_contains_only_the_prompt_builder_and_native_text_helpers():
    workflow = load_workflow()
    types = [node["type"] for node in workflow["nodes"]]
    assert set(types) <= ALLOWED_TYPES
    assert {node_type: types.count(node_type) for node_type in FOCUSED_TYPES} == {
        node_type: 1 for node_type in FOCUSED_TYPES
    }
    assert types.count(COMBINE_TYPE) == 1
    assert types.count("PrimitiveStringMultiline") == 2
    assert types.count("PreviewAny") == 3
    assert types.count("MarkdownNote") >= 4

    forbidden_words = ("checkpoint", "loader", "sampler", "latent", "vae", "clip")
    assert not any(
        word in node["type"].casefold()
        for node in workflow["nodes"]
        for word in forbidden_words
    )


def test_arch_nodes_match_the_live_package_display_and_io_contracts():
    workflow = load_workflow()
    arch_nodes = [
        node for node in workflow["nodes"] if node["type"] in NODE_CLASS_MAPPINGS
    ]
    assert {node["type"] for node in arch_nodes} == set(NODE_CLASS_MAPPINGS)

    for node in arch_nodes:
        node_class = NODE_CLASS_MAPPINGS[node["type"]]
        expected_inputs = input_definitions(node_class)
        assert node["title"] == NODE_DISPLAY_NAME_MAPPINGS[node["type"]]
        assert [item["name"] for item in node["inputs"]] == list(expected_inputs)
        assert [item["type"] for item in node["inputs"]] == [
            workflow_input_type(definition)
            for definition in expected_inputs.values()
        ]
        assert [item["name"] for item in node["outputs"]] == list(
            node_class.RETURN_NAMES
        )
        assert [item["type"] for item in node["outputs"]] == list(
            node_class.RETURN_TYPES
        )
        assert [item["slot_index"] for item in node["outputs"]] == list(
            range(len(node_class.RETURN_NAMES))
        )


def test_every_focused_node_starts_blank_and_defaults_to_flux():
    workflow = load_workflow()
    for node in workflow["nodes"]:
        node_key = FOCUSED_TYPES.get(node["type"])
        if node_key is None:
            continue
        node_class = FOCUSED_CLASSES[node["type"]]
        required = node_class.INPUT_TYPES()["required"]
        assert list(required) == ["model_family", "state_json"]
        assert node["widgets_values"][0] == required["model_family"][1]["default"]
        assert json.loads(node["widgets_values"][1]) == json.loads(
            required["state_json"][1]["default"]
        ) == {
            "version": 1,
            "node": node_key,
            "model_family": "flux",
            "fields": {},
        }
        prompt_slot = node_class.RETURN_NAMES.index("prompt")
        bundle_slot = node_class.RETURN_NAMES.index("prompt_bundle")
        assert node["outputs"][prompt_slot]["links"] in (None, [])
        assert len(node["outputs"][bundle_slot]["links"]) == 1


def test_all_six_bundles_and_both_text_inputs_feed_the_combiner():
    workflow = load_workflow()
    by_id = nodes_by_id(workflow)
    combine = next(node for node in workflow["nodes"] if node["type"] == COMBINE_TYPE)
    inputs = {item["name"]: item for item in combine["inputs"]}
    combine_schema = COMBINE_CLASS.INPUT_TYPES()
    combine_definitions = input_definitions(COMBINE_CLASS)
    assert list(inputs) == list(combine_definitions)
    assert combine["widgets_values"] == [
        definition[1]["default"]
        for definition in combine_schema["required"].values()
    ]

    links = {link[0]: link for link in workflow["links"]}
    for node_type, node_key in FOCUSED_TYPES.items():
        source = next(node for node in workflow["nodes"] if node["type"] == node_type)
        source_class = FOCUSED_CLASSES[node_type]
        bundle_slot = source_class.RETURN_NAMES.index("prompt_bundle")
        target_slot = list(combine_definitions).index(node_key)
        bundle_type = source_class.RETURN_TYPES[bundle_slot]
        assert combine_definitions[node_key][0] == bundle_type
        link = links[inputs[node_key]["link"]]
        assert link[1:6] == [
            source["id"],
            bundle_slot,
            combine["id"],
            target_slot,
            bundle_type,
        ]

    for input_name, expected_title in (
        ("base_prompt", "Base prompt"),
        ("extra_prompt", "Extra prompt"),
    ):
        link = links[inputs[input_name]["link"]]
        source = by_id[link[1]]
        assert source["type"] == "PrimitiveStringMultiline"
        assert source["title"] == expected_title
        assert link[2] == 0
        assert link[3] == combine["id"]
        assert link[4] == list(combine_definitions).index(input_name)
        assert link[5] == combine_definitions[input_name][0]


def test_combiner_outputs_are_wired_to_three_named_previews():
    workflow = load_workflow()
    by_id = nodes_by_id(workflow)
    combine = next(node for node in workflow["nodes"] if node["type"] == COMBINE_TYPE)
    links = {link[0]: link for link in workflow["links"]}
    preview_titles = {
        "positive_prompt": "Combined positive prompt preview",
        "metadata_json": "Metadata JSON preview",
        "lora_requests_json": "Future LoRA requests JSON preview",
    }

    assert set(preview_titles) == set(COMBINE_CLASS.RETURN_NAMES)
    for slot, (output_name, output_type) in enumerate(
        zip(COMBINE_CLASS.RETURN_NAMES, COMBINE_CLASS.RETURN_TYPES)
    ):
        output_links = combine["outputs"][slot]["links"]
        assert len(output_links) == 1
        link = links[output_links[0]]
        preview = by_id[link[3]]
        assert link[1:3] == [combine["id"], slot]
        assert link[4:] == [0, output_type]
        assert preview["type"] == "PreviewAny"
        assert preview["title"] == preview_titles[output_name]
        assert preview["inputs"][0]["link"] == link[0]


def test_every_link_and_slot_is_bidirectionally_consistent():
    workflow = load_workflow()
    by_id = nodes_by_id(workflow)

    for link_id, origin_id, origin_slot, target_id, target_slot, link_type in workflow[
        "links"
    ]:
        origin = by_id[origin_id]
        target = by_id[target_id]
        assert link_id in origin["outputs"][origin_slot]["links"]
        assert target["inputs"][target_slot]["link"] == link_id
        assert origin["outputs"][origin_slot]["type"] in (link_type, "*")
        assert target["inputs"][target_slot]["type"] in (link_type, "*")

    referenced_outputs = {
        link_id
        for node in workflow["nodes"]
        for output in node.get("outputs", [])
        for link_id in (output.get("links") or [])
    }
    referenced_inputs = {
        item["link"]
        for node in workflow["nodes"]
        for item in node.get("inputs", [])
        if item.get("link") is not None
    }
    link_ids = {link[0] for link in workflow["links"]}
    assert referenced_outputs == referenced_inputs == link_ids


def test_layout_is_grouped_color_coded_and_non_overlapping_by_lane():
    workflow = load_workflow()
    groups = {group["title"]: group for group in workflow["groups"]}
    assert set(groups) == {
        "ARCH-PT START HERE",
        "ARCH-PT FOCUSED PROMPTS",
        "ARCH-PT COMBINE",
        "ARCH-PT PREVIEWS",
    }
    for group in groups.values():
        x, y, width, height = group["bounding"]
        assert width > 0 and height > 0
        assert isinstance(group["color"], str) and group["color"].startswith("#")
        assert group["flags"] == {}

    operational = [
        node for node in workflow["nodes"] if node["type"] != "MarkdownNote"
    ]
    assert all("color" in node and "bgcolor" in node for node in operational)
    assert len({tuple(node["pos"]) for node in operational}) == len(operational)

    focused = sorted(
        (node for node in operational if node["type"] in FOCUSED_TYPES),
        key=lambda node: node["pos"][1],
    )
    assert [node["pos"][1] for node in focused] == sorted(
        node["pos"][1] for node in focused
    )
    assert all(node["pos"][0] == focused[0]["pos"][0] for node in focused)


def test_visible_notes_explain_the_state_and_safety_contracts():
    workflow = load_workflow()
    notes = "\n".join(
        str(node["widgets_values"][0])
        for node in workflow["nodes"]
        if node["type"] == "MarkdownNote"
    ).casefold()
    for phrase in (
        "blank until",
        "copied into this workflow",
        "future selections",
        "protected",
        "duplicate",
        "lora",
        "metadata",
        "does not load",
        "save as",
        "do not overwrite",
    ):
        assert phrase in notes


def test_native_helper_types_are_registered_in_local_installed_sources():
    primitive_source = (REPO_ROOT / "comfy_extras" / "nodes_primitive.py").read_text(
        encoding="utf-8"
    )
    preview_source = (REPO_ROOT / "comfy_extras" / "nodes_preview_any.py").read_text(
        encoding="utf-8"
    )
    assert re.search(
        r'node_id\s*=\s*["\']PrimitiveStringMultiline["\']',
        primitive_source,
    )
    assert re.search(
        r'["\']PreviewAny["\']\s*:\s*PreviewAny',
        preview_source,
    )

    frontend_spec = importlib.util.find_spec("comfyui_frontend_package")
    assert frontend_spec is not None
    assert frontend_spec.submodule_search_locations
    frontend_root = Path(next(iter(frontend_spec.submodule_search_locations)))
    core_assets = tuple((frontend_root / "static" / "assets").glob("core-*.js"))
    assert core_assets
    markdown_registration = re.compile(
        r"registerNodeType\(\s*[`\"']MarkdownNote[`\"']"
    )
    assert any(
        markdown_registration.search(asset.read_text(encoding="utf-8"))
        for asset in core_assets
    )


def test_example_has_no_provenance_or_reference_to_an_existing_workflow():
    workflow = load_workflow()
    assert "converted_from_api_prompt" not in workflow["extra"]
    assert "source_workflow" not in workflow["extra"]
    serialized = json.dumps(workflow).casefold()
    assert "workflow 29" not in serialized
    assert "workflow 35" not in serialized
    assert "legacy" not in serialized


def test_readme_explains_plain_english_workflow_and_persistence_contracts():
    text = README.read_text(encoding="utf-8").casefold()
    flat_text = " ".join(text.split())
    for heading in (
        "# arch-pt prompt builder",
        "## quickest workflow",
        "## what each node controls",
        "## choosing and editing",
        "## saved choices",
        "## combine outputs",
        "## safety and recovery",
    ):
        assert heading in text

    for phrase in (
        "blank by default",
        "quick buttons",
        "search",
        "type",
        "one choice",
        "additive",
        "copied into the workflow",
        "editable",
        "remove",
        "subject's anatomical left",
        "image frame",
        "enable",
        "slider",
        "flux",
        "qwen",
        "future selections",
        "clothing source",
        "reference subject",
        "arch_prompt_tools/options.json",
        "create",
        "edit",
        "delete",
        "duplicate",
        "protected",
        "base prompt",
        "extra prompt",
        "dedupe",
        "positive-only",
        "still images",
        "optics",
        "lora",
        "metadata",
        "does not load",
        "invalid",
        "backup",
        "legacy",
        "save as",
        "never overwrite",
    ):
        assert phrase in text

    assert (
        "<configured comfyui user root>/arch_prompt_tools/options.json" in text
    )
    assert "user/arch_prompt_tools/options.json" in text
    assert "user/default/arch_prompt_tools/options.json" not in text
    assert "back up the file at that configured user-root path" in flat_text
