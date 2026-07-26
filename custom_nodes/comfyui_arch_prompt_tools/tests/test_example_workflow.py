import json
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
PACKAGE_DIR = Path(__file__).parents[1]
README = PACKAGE_DIR / "README.md"
WORKFLOW_DIR = REPO_ROOT / "user" / "default" / "workflows" / "agent"
WORKFLOW = WORKFLOW_DIR / "38 - Arch PT Prompt Builder.json"

FOCUSED_TYPES = {
    "ArchPtIdentity": "identity",
    "ArchPtPose": "pose",
    "ArchPtClothing": "clothing",
    "ArchPtEnvironment": "environment",
    "ArchPtCamera": "camera",
    "ArchPtLighting": "lighting",
}
ALLOWED_TYPES = {
    *FOCUSED_TYPES,
    "ArchPtCombine",
    "PrimitiveStringMultiline",
    "PreviewAny",
    "MarkdownNote",
}


def load_workflow():
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def nodes_by_id(workflow):
    return {node["id"]: node for node in workflow["nodes"]}


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
    assert types.count("ArchPtCombine") == 1
    assert types.count("PrimitiveStringMultiline") == 2
    assert types.count("PreviewAny") == 3
    assert types.count("MarkdownNote") >= 4

    forbidden_words = ("checkpoint", "loader", "sampler", "latent", "vae", "clip")
    assert not any(
        word in node["type"].casefold()
        for node in workflow["nodes"]
        for word in forbidden_words
    )


def test_every_focused_node_starts_blank_and_defaults_to_flux():
    workflow = load_workflow()
    for node in workflow["nodes"]:
        node_key = FOCUSED_TYPES.get(node["type"])
        if node_key is None:
            continue
        assert node["widgets_values"][0] == "flux"
        assert json.loads(node["widgets_values"][1]) == {
            "version": 1,
            "node": node_key,
            "model_family": "flux",
            "fields": {},
        }
        assert [output["name"] for output in node["outputs"]] == [
            "prompt",
            "prompt_bundle",
        ]
        assert node["outputs"][0]["links"] in (None, [])
        assert len(node["outputs"][1]["links"]) == 1


def test_all_six_bundles_and_both_text_inputs_feed_the_combiner():
    workflow = load_workflow()
    by_id = nodes_by_id(workflow)
    combine = next(node for node in workflow["nodes"] if node["type"] == "ArchPtCombine")
    inputs = {item["name"]: item for item in combine["inputs"]}
    assert set(inputs) == {
        "separator",
        "dedupe",
        "base_prompt",
        "extra_prompt",
        *FOCUSED_TYPES.values(),
    }
    assert combine["widgets_values"] == [", ", True]

    links = {link[0]: link for link in workflow["links"]}
    for node_type, node_key in FOCUSED_TYPES.items():
        source = next(node for node in workflow["nodes"] if node["type"] == node_type)
        link = links[inputs[node_key]["link"]]
        assert link[1:6] == [
            source["id"],
            1,
            combine["id"],
            next(
                index
                for index, item in enumerate(combine["inputs"])
                if item["name"] == node_key
            ),
            "ARCH_PT_BUNDLE",
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
        assert link[4] == next(
            index
            for index, item in enumerate(combine["inputs"])
            if item["name"] == input_name
        )
        assert link[5] == "STRING"


def test_combiner_outputs_are_wired_to_three_named_previews():
    workflow = load_workflow()
    by_id = nodes_by_id(workflow)
    combine = next(node for node in workflow["nodes"] if node["type"] == "ArchPtCombine")
    links = {link[0]: link for link in workflow["links"]}
    expected = (
        ("positive_prompt", "Combined positive prompt preview"),
        ("metadata_json", "Metadata JSON preview"),
        ("lora_requests_json", "Future LoRA requests JSON preview"),
    )

    assert [output["name"] for output in combine["outputs"]] == [
        name for name, _ in expected
    ]
    for slot, (_, title) in enumerate(expected):
        output_links = combine["outputs"][slot]["links"]
        assert len(output_links) == 1
        link = links[output_links[0]]
        preview = by_id[link[3]]
        assert link[1:3] == [combine["id"], slot]
        assert link[4:] == [0, "STRING"]
        assert preview["type"] == "PreviewAny"
        assert preview["title"] == title
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
