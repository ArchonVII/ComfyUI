import json
import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / "user" / "default" / "workflows" / "agent"
RUNTIME_BASE = Path(os.environ.get("COMFY_RUNTIME_BASE", REPO_ROOT))

WORKFLOWS = {
    "22 - HQ LTXV I2V - Fast Draft 97f.json": {
        "family": "ltx",
        "conditioning": "LTXVImgToVideo",
        "frames": 97,
        "megapixels": 0.40,
    },
    "23 - HQ LTXV I2V - Quality 121f.json": {
        "family": "ltx",
        "conditioning": "LTXVImgToVideo",
        "frames": 121,
        "megapixels": 0.55,
    },
    "24 - HQ LTXV I2V - Start End Guide 121f.json": {
        "family": "ltx",
        "conditioning": "LTXVImgToVideo",
        "frames": 121,
        "megapixels": 0.55,
        "start_end": True,
    },
    "25 - HQ Wan 2.2 I2V - Fast Draft 81f.json": {
        "family": "wan",
        "conditioning": "WanImageToVideo",
        "frames": 81,
        "megapixels": 0.40,
        "accelerated": True,
    },
    "26 - HQ Wan 2.2 I2V - Quality 81f.json": {
        "family": "wan",
        "conditioning": "WanImageToVideo",
        "frames": 81,
        "megapixels": 0.60,
    },
    "27 - HQ Wan 2.2 I2V - Start End Guide 81f.json": {
        "family": "wan",
        "conditioning": "WanFirstLastFrameToVideo",
        "frames": 81,
        "megapixels": 0.60,
        "start_end": True,
    },
}

MODEL_FOLDERS = {
    "UNETLoader": ("models/diffusion_models", 0),
    "UnetLoaderGGUF": ("models/unet", 0),
    "VAELoader": ("models/vae", 0),
    "CLIPLoader": ("models/text_encoders", 0),
    "LoraLoaderModelOnly": ("models/loras", 0),
}


def load_workflow(name):
    path = WORKFLOW_DIR / name
    assert path.is_file(), f"missing workflow: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def node_of_type(workflow, node_type, *, title=None):
    matches = [node for node in workflow["nodes"] if node["type"] == node_type]
    if title is not None:
        matches = [node for node in matches if node.get("title") == title]
    assert matches, f"missing {node_type!r} node ({title or 'any title'})"
    assert len(matches) == 1, f"expected one {node_type!r}, found {len(matches)}"
    return matches[0]


def nodes_of_type(workflow, node_type):
    return [node for node in workflow["nodes"] if node["type"] == node_type]


def input_slot(node, name):
    for index, entry in enumerate(node.get("inputs", [])):
        if entry["name"] == name:
            return index
    raise AssertionError(f"node {node['id']} ({node['type']}) has no input {name!r}")


def has_link(workflow, source, source_slot, target, target_slot):
    return any(
        link[1] == source["id"]
        and link[2] == source_slot
        and link[3] == target["id"]
        and link[4] == target_slot
        for link in workflow["links"]
    )


@pytest.mark.parametrize(("name", "spec"), WORKFLOWS.items())
def test_workflow_uses_source_aware_pixel_budget(name, spec):
    workflow = load_workflow(name)
    source = node_of_type(workflow, "LoadImage", title="Image 1 - start frame")
    scaler = node_of_type(workflow, "ImageScaleToTotalPixels")
    dimensions = node_of_type(workflow, "GetImageSize")
    conditioning = node_of_type(workflow, spec["conditioning"])

    assert scaler["widgets_values"] == ["lanczos", spec["megapixels"], 32]
    assert has_link(workflow, source, 0, scaler, input_slot(scaler, "image"))
    assert has_link(workflow, scaler, 0, dimensions, input_slot(dimensions, "image"))
    assert has_link(workflow, dimensions, 0, conditioning, input_slot(conditioning, "width"))
    assert has_link(workflow, dimensions, 1, conditioning, input_slot(conditioning, "height"))


@pytest.mark.parametrize(("name", "spec"), WORKFLOWS.items())
def test_frame_count_and_mp4_output_contract(name, spec):
    workflow = load_workflow(name)
    conditioning = node_of_type(workflow, spec["conditioning"])
    widgets = conditioning["widgets_values"]
    frame_count = spec["frames"]

    assert frame_count in widgets
    modulus = 8 if spec["family"] == "ltx" else 4
    assert (frame_count - 1) % modulus == 0
    assert nodes_of_type(workflow, "VAEDecodeTiled")
    assert node_of_type(workflow, "CreateVideo")["widgets_values"][0] == 24
    save = node_of_type(workflow, "SaveVideo")
    assert save["widgets_values"][1:] == ["mp4", "h264"]


@pytest.mark.parametrize(("name", "spec"), WORKFLOWS.items())
def test_loader_defaults_resolve_in_main_runtime(name, spec):
    workflow = load_workflow(name)
    for node in workflow["nodes"]:
        if node["type"] not in MODEL_FOLDERS:
            continue
        folder, widget_index = MODEL_FOLDERS[node["type"]]
        relative_name = node["widgets_values"][widget_index]
        model_path = RUNTIME_BASE / folder / Path(relative_name.replace("\\", "/"))
        assert model_path.is_file(), f"{name}: missing local asset {model_path}"

    for image_node in nodes_of_type(workflow, "LoadImage"):
        image_path = RUNTIME_BASE / "input" / image_node["widgets_values"][0]
        assert image_path.is_file(), f"{name}: missing placeholder {image_path}"


@pytest.mark.parametrize(
    "name",
    [name for name, spec in WORKFLOWS.items() if spec["family"] == "wan"],
)
def test_wan_uses_installed_dual_gguf_experts_with_clean_handoff(name):
    workflow = load_workflow(name)
    loaders = nodes_of_type(workflow, "UnetLoaderGGUF")
    assert [node["widgets_values"][0] for node in loaders] == [
        "Wan\\Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf",
        "Wan\\Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf",
    ]

    samplers = nodes_of_type(workflow, "KSamplerAdvanced")
    assert len(samplers) == 2
    high = next(node for node in samplers if "high-noise" in node["title"].lower())
    low = next(node for node in samplers if "low-noise" in node["title"].lower())
    assert high["widgets_values"][-1] == "enable"
    assert low["widgets_values"][0] == "disable"
    assert has_link(workflow, high, 0, low, input_slot(low, "latent_image"))


def test_wan_draft_uses_a_paired_four_step_lora_set():
    workflow = load_workflow("25 - HQ Wan 2.2 I2V - Fast Draft 81f.json")
    loras = nodes_of_type(workflow, "LoraLoaderModelOnly")
    assert [node["widgets_values"][0] for node in loras] == [
        "Wan\\wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors",
        "Wan\\wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors",
    ]


@pytest.mark.parametrize(
    "name",
    [name for name, spec in WORKFLOWS.items() if spec["family"] == "wan"],
)
def test_wan_exposes_current_quality_extensions_as_safe_opt_ins(name):
    workflow = load_workflow(name)
    conditioning_type = WORKFLOWS[name]["conditioning"]
    conditioning = node_of_type(workflow, conditioning_type)

    for node_type in (
        "EasyCache",
        "WanVideoEnhanceAVideoKJ",
        "ApplyRifleXRoPE_WanVideo",
        "WanVideoNAG",
    ):
        extensions = nodes_of_type(workflow, node_type)
        assert len(extensions) == 2, f"{name}: expected one {node_type} per Wan expert"
        assert all(item["mode"] == 4 for item in extensions), (
            f"{name}: {node_type} must default to bypass on the stable 16 GB path"
        )

    for item in nodes_of_type(workflow, "WanVideoEnhanceAVideoKJ"):
        assert has_link(workflow, conditioning, 2, item, input_slot(item, "latent"))
    for item in nodes_of_type(workflow, "ApplyRifleXRoPE_WanVideo"):
        assert has_link(workflow, conditioning, 2, item, input_slot(item, "latent"))
    for item in nodes_of_type(workflow, "WanVideoNAG"):
        assert has_link(workflow, conditioning, 1, item, input_slot(item, "conditioning"))


@pytest.mark.parametrize(
    "name",
    [name for name, spec in WORKFLOWS.items() if spec.get("start_end")],
)
def test_start_end_workflows_match_end_frame_to_start_dimensions(name):
    workflow = load_workflow(name)
    end_image = node_of_type(workflow, "LoadImage", title="Image 2 - end frame guide")
    end_scaler = node_of_type(workflow, "ImageScale")
    dimensions = node_of_type(workflow, "GetImageSize")

    assert has_link(workflow, end_image, 0, end_scaler, input_slot(end_scaler, "image"))
    assert has_link(workflow, dimensions, 0, end_scaler, input_slot(end_scaler, "width"))
    assert has_link(workflow, dimensions, 1, end_scaler, input_slot(end_scaler, "height"))


def test_legacy_wan_demo_files_are_retired():
    for name in (
        "wan-2-2-gguf-image-to-video - test 1.json",
        "wan-2-2-gguf-image-to-video.json",
        "wan-2-2-image-to-video.json",
    ):
        assert not (WORKFLOW_DIR / name).exists()
