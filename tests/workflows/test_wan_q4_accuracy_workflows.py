import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / "user" / "default" / "workflows" / "agent"

HIGH_MODEL = "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KMH.gguf"
LOW_MODEL = "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KML.gguf"

WORKFLOWS = {
    "31 - WAN Q4 FAST Preview 17f.json": {
        "frames": 17,
        "megapixels": 0.10,
        "steps": 4,
        "split": 2,
        "conditioning": "WanImageToVideo",
    },
    "32 - WAN Q4 Prompt Camera 49f.json": {
        "frames": 49,
        "megapixels": 0.25,
        "steps": 5,
        "split": 2,
        "conditioning": "WanImageToVideo",
        "timeline_prompt": True,
    },
    "33 - WAN Q4 Identity Audit 81f.json": {
        "frames": 81,
        "megapixels": 0.40,
        "steps": 5,
        "split": 2,
        "conditioning": "WanImageToVideo",
        "identity_indices": (40, 80),
    },
    "34 - WAN Q4 First Last Control 81f.json": {
        "frames": 81,
        "megapixels": 0.40,
        "steps": 5,
        "split": 2,
        "conditioning": "WanFirstLastFrameToVideo",
        "start_end": True,
    },
}

FORBIDDEN_NODE_TYPES = {
    "LoraLoaderModelOnly",
    "EasyCache",
    "WanVideoEnhanceAVideoKJ",
    "ApplyRifleXRoPE_WanVideo",
    "WanVideoNAG",
    "PathchSageAttentionKJ",
    "PatchSageAttentionKJ",
}


def load_workflow(name):
    path = WORKFLOW_DIR / name
    assert path.is_file(), f"missing workflow: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def nodes_of_type(workflow, node_type):
    return [node for node in workflow["nodes"] if node["type"] == node_type]


def node_of_type(workflow, node_type, *, title=None):
    matches = nodes_of_type(workflow, node_type)
    if title is not None:
        matches = [node for node in matches if node.get("title") == title]
    assert len(matches) == 1, (
        f"expected one {node_type!r} ({title or 'any title'}), found {len(matches)}"
    )
    return matches[0]


def input_slot(node, name):
    return next(index for index, item in enumerate(node["inputs"]) if item["name"] == name)


def has_link(workflow, source, source_slot, target, target_input):
    target_slot = input_slot(target, target_input)
    return any(
        link[1] == source["id"]
        and link[2] == source_slot
        and link[3] == target["id"]
        and link[4] == target_slot
        for link in workflow["links"]
    )


@pytest.mark.parametrize(("name", "spec"), WORKFLOWS.items())
def test_workflow_uses_author_aligned_q4_lightning_recipe(name, spec):
    workflow = load_workflow(name)
    loaders = nodes_of_type(workflow, "UnetLoaderGGUF")
    assert [node["widgets_values"][0] for node in loaders] == [HIGH_MODEL, LOW_MODEL]

    sampling = nodes_of_type(workflow, "ModelSamplingSD3")
    assert len(sampling) == 2
    assert all(node["widgets_values"] == [5] for node in sampling)

    high = node_of_type(workflow, "KSamplerAdvanced", title="Sample high-noise pass")
    low = node_of_type(workflow, "KSamplerAdvanced", title="Sample low-noise pass")
    assert high["widgets_values"] == [
        "enable",
        283090201,
        "fixed",
        spec["steps"],
        1.0,
        "euler",
        "simple",
        0,
        spec["split"],
        "enable",
    ]
    assert low["widgets_values"] == [
        "disable",
        0,
        "fixed",
        spec["steps"],
        1.0,
        "euler",
        "simple",
        spec["split"],
        spec["steps"],
        "disable",
    ]

    present_types = {node["type"] for node in workflow["nodes"]}
    assert present_types.isdisjoint(FORBIDDEN_NODE_TYPES)


@pytest.mark.parametrize(("name", "spec"), WORKFLOWS.items())
def test_workflow_has_honest_cost_and_output_defaults(name, spec):
    workflow = load_workflow(name)
    source = node_of_type(workflow, "LoadImage", title="Image 1 - start frame")
    scaler = node_of_type(workflow, "ImageScaleToTotalPixels")
    dimensions = node_of_type(workflow, "GetImageSize")
    conditioning = node_of_type(workflow, spec["conditioning"])

    assert scaler["widgets_values"] == ["lanczos", spec["megapixels"], 32]
    assert conditioning["widgets_values"][-2:] == [spec["frames"], 1]
    assert (spec["frames"] - 1) % 4 == 0
    assert has_link(workflow, source, 0, scaler, "image")
    assert has_link(workflow, scaler, 0, dimensions, "image")
    assert has_link(workflow, dimensions, 0, conditioning, "width")
    assert has_link(workflow, dimensions, 1, conditioning, "height")
    assert node_of_type(workflow, "CreateVideo")["widgets_values"][0] == 16
    assert node_of_type(workflow, "SaveVideo")["widgets_values"][1:] == ["mp4", "h264"]


def test_prompt_camera_workflow_uses_timeline_prompting():
    workflow = load_workflow("32 - WAN Q4 Prompt Camera 49f.json")
    prompt = node_of_type(workflow, "CLIPTextEncode", title="Positive prompt")
    text = prompt["widgets_values"][0]
    assert "(At 0 seconds:" in text
    assert "(At 1 second:" in text
    assert "(At 3 seconds:" in text


def test_identity_workflow_scores_middle_and_final_frames():
    workflow = load_workflow("33 - WAN Q4 Identity Audit 81f.json")
    source = node_of_type(workflow, "LoadImage", title="Image 1 - start frame")
    decode = node_of_type(workflow, "VAEDecodeTiled")
    selectors = nodes_of_type(workflow, "ImageFromBatch")
    scorers = nodes_of_type(workflow, "OpenCVIdentityScore")

    assert [node["widgets_values"] for node in selectors] == [[40, 1], [80, 1]]
    assert len(scorers) == 2
    for selector, scorer in zip(selectors, scorers, strict=True):
        assert has_link(workflow, decode, 0, selector, "image")
        assert has_link(workflow, source, 0, scorer, "reference_image")
        assert has_link(workflow, selector, 0, scorer, "generated_image")


def test_first_last_workflow_conditions_on_scaled_end_frame():
    workflow = load_workflow("34 - WAN Q4 First Last Control 81f.json")
    conditioning = node_of_type(workflow, "WanFirstLastFrameToVideo")
    dimensions = node_of_type(workflow, "GetImageSize")
    end_image = node_of_type(workflow, "LoadImage", title="Image 2 - end frame guide")
    end_scaler = node_of_type(workflow, "ImageScale")

    assert has_link(workflow, end_image, 0, end_scaler, "image")
    assert has_link(workflow, dimensions, 0, end_scaler, "width")
    assert has_link(workflow, dimensions, 1, end_scaler, "height")
    assert has_link(workflow, end_scaler, 0, conditioning, "end_image")


@pytest.mark.parametrize("name", WORKFLOWS)
def test_image_loader_defaults_use_the_local_neutral_placeholder(name):
    workflow = load_workflow(name)
    image_nodes = nodes_of_type(workflow, "LoadImage")
    assert image_nodes
    for image_node in image_nodes:
        assert image_node["widgets_values"][0] == "wan_q4_placeholder.ppm"
        assert (REPO_ROOT / "input" / "wan_q4_placeholder.ppm").is_file()
