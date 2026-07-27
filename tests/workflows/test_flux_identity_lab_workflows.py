"""Contract tests for the deterministic Flux 9B identity-lab templates."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / "user" / "default" / "workflows" / "agent"
BUILDER = REPO_ROOT / "scripts" / "build_flux_identity_lab_workflows.py"
PLACEHOLDER = "wan_q4_placeholder.ppm"

FACE_SWAP = "39 - Flux 9B Identity Lab - Face Swap.json"
IDENTITY_I2I = "40 - Flux 9B Identity Lab - Identity I2I.json"
WORKFLOWS = {FACE_SWAP: "face_swap", IDENTITY_I2I: "identity_i2i"}

MODEL = r"Flux\9b\DarkBeast-Klein9b-V2-BFS-FP8-ComfyUI.safetensors"
CLIP = r"Qwen\qwen_3_8b_fp8mixed.safetensors"
VAE = "flux2-vae.safetensors"
LORAS = (
    r"Flux\9b\1 ------ Helper\Flux2-Klein-9B-consistency-V2.safetensors",
    r"Flux\9b\1 ------ Helper\Flux2-Klein-Image-RestoreV1.safetensors",
    r"Flux\9b\1 ------ Helper\better_skin_darkbeast2_lora.safetensors",
)
PULID = "pulid_flux2_klein_v2.safetensors"

ROLES = {
    "IDENTITY_LAB_BASE_IMAGE": "LoadImage",
    "IDENTITY_LAB_REFERENCE_IMAGE": "LoadImage",
    "IDENTITY_LAB_MODEL": "UNETLoader",
    "IDENTITY_LAB_LORA_1": "LoraLoaderModelOnly",
    "IDENTITY_LAB_LORA_2": "LoraLoaderModelOnly",
    "IDENTITY_LAB_LORA_3": "LoraLoaderModelOnly",
    "IDENTITY_LAB_SAMPLER": "KSampler",
    "IDENTITY_LAB_PIXEL_BUDGET": "ImageScaleToTotalPixels",
    "IDENTITY_LAB_SCORE": "DualIdentityScore",
}

# Captured from the running ComfyUI /object_info endpoint on the target runtime.
# DualIdentityScore is intentionally local until the isolated server restart.
NODE_SCHEMAS = {
    "LoadImage": (("image",), ("IMAGE", "MASK")),
    "UNETLoader": (("unet_name", "weight_dtype"), ("MODEL",)),
    "LoraLoaderModelOnly": (("model", "lora_name", "strength_model"), ("MODEL",)),
    "CLIPLoader": (("clip_name", "type", "device"), ("CLIP",)),
    "VAELoader": (("vae_name",), ("VAE",)),
    "CLIPTextEncode": (("clip", "text"), ("CONDITIONING",)),
    "KSampler": (("model", "positive", "negative", "latent_image", "seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"), ("LATENT",)),
    "ImageScaleToTotalPixels": (("image", "upscale_method", "megapixels", "resolution_steps"), ("IMAGE",)),
    "VAEEncode": (("pixels", "vae"), ("LATENT",)),
    "VAEDecode": (("samples", "vae"), ("IMAGE",)),
    "ReferenceLatent": (("conditioning", "latent"), ("CONDITIONING",)),
    "EmptyFlux2LatentImage": (("width", "height", "batch_size"), ("LATENT",)),
    "GetImageSize": (("image",), ("INT", "INT", "INT")),
    "UltralyticsDetectorProvider": (("model_name",), ("BBOX_DETECTOR", "SEGM_DETECTOR")),
    "BboxDetectorSEGS": (("bbox_detector", "image", "detailer_hook", "threshold", "dilation", "crop_factor", "drop_size", "labels"), ("SEGS",)),
    "SAMLoader": (("model_name", "device_mode"), ("SAM_MODEL",)),
    "SAMDetectorCombined": (("sam_model", "segs", "image", "detection_hint", "dilation", "threshold", "bbox_expansion", "mask_hint_threshold", "mask_hint_use_negative"), ("MASK",)),
    "BatchCropFromMaskAdvanced": (("original_images", "masks", "crop_size_mult", "bbox_smooth_alpha"), ("IMAGE", "IMAGE", "MASK", "IMAGE", "MASK", "BBOX", "BBOX", "INT", "INT")),
    "BatchUncropAdvanced": (("original_images", "cropped_images", "cropped_masks", "combined_crop_mask", "bboxes", "combined_bounding_box", "border_blending", "crop_rescale", "use_combined_mask", "use_square_mask"), ("IMAGE",)),
    "PuLIDInsightFaceLoader": (("provider",), ("INSIGHTFACE",)),
    "PuLIDEVACLIPLoader": ((), ("EVA_CLIP",)),
    "PuLIDModelLoader": (("pulid_file",), ("PULID_MODEL",)),
    "ApplyPuLIDFlux2": (("model", "pulid_model", "eva_clip", "face_analysis", "image", "strength", "face_index", "debug_mode"), ("MODEL",)),
    "DualIdentityScore": (("base_image", "reference_image", "generated_image", "experiment_id", "run_id", "extra_metadata", "experiment_mode", "face_score_threshold", "same_identity_threshold", "face_selection", "write_manifest", "manifest_dir", "run_label", "metadata_key"), ("FLOAT", "BOOLEAN", "BOOLEAN", "FLOAT", "BOOLEAN", "BOOLEAN", "BOOLEAN", "FLOAT", "BOOLEAN", "BOOLEAN", "STRING", "EXTRA_METADATA")),
    "SaveImage": (("images", "filename_prefix"), ("IMAGE",)),
    "PreviewImage": (("images",), ("IMAGE",)),
    "MarkdownNote": ((), ()),
}

OPTIONAL_EDITOR_SOCKETS = {
    "CLIPLoader": (("device", "COMBO"),),
    "BboxDetectorSEGS": (("detailer_hook", "DETAILER_HOOK"),),
    "DualIdentityScore": (("extra_metadata", "EXTRA_METADATA"),),
}

# Frontend/editor ordering is socket-first, which differs from several backend
# INPUT_TYPES declaration orders. The trailing entries are editor widgets.
EDITOR_SOCKET_PREFIXES = {
    "LoadImage": (), "UNETLoader": (), "LoraLoaderModelOnly": ("model",),
    "CLIPLoader": (), "VAELoader": (), "CLIPTextEncode": ("clip",),
    "KSampler": ("model", "positive", "negative", "latent_image"),
    "ImageScaleToTotalPixels": ("image",), "VAEEncode": ("pixels", "vae"),
    "VAEDecode": ("samples", "vae"), "ReferenceLatent": ("conditioning", "latent"),
    "EmptyFlux2LatentImage": (), "GetImageSize": ("image",),
    "UltralyticsDetectorProvider": (),
    "BboxDetectorSEGS": ("bbox_detector", "image", "detailer_hook"),
    "SAMLoader": (), "SAMDetectorCombined": ("sam_model", "segs", "image"),
    "BatchCropFromMaskAdvanced": ("original_images", "masks"),
    "BatchUncropAdvanced": ("original_images", "cropped_images", "cropped_masks", "combined_crop_mask", "bboxes", "combined_bounding_box"),
    "PuLIDInsightFaceLoader": (), "PuLIDEVACLIPLoader": (), "PuLIDModelLoader": (),
    "ApplyPuLIDFlux2": ("model", "pulid_model", "eva_clip", "face_analysis", "image"),
    "DualIdentityScore": ("base_image", "reference_image", "generated_image", "experiment_id", "run_id", "extra_metadata"),
    "SaveImage": ("images",), "PreviewImage": ("images",), "MarkdownNote": (),
}

EDITOR_TRAILING_FORCE_INPUTS = {}
EDITOR_WIDGET_VALUE_COUNTS = {
    "LoadImage": 1, "UNETLoader": 2, "LoraLoaderModelOnly": 2, "CLIPLoader": 3,
    "VAELoader": 1, "CLIPTextEncode": 1, "KSampler": 7,
    "ImageScaleToTotalPixels": 3, "VAEEncode": 0, "VAEDecode": 0,
    "ReferenceLatent": 0, "EmptyFlux2LatentImage": 3, "GetImageSize": 0,
    "UltralyticsDetectorProvider": 1, "BboxDetectorSEGS": 5, "SAMLoader": 2,
    "SAMDetectorCombined": 6, "BatchCropFromMaskAdvanced": 2,
    "BatchUncropAdvanced": 4, "PuLIDInsightFaceLoader": 1,
    "PuLIDEVACLIPLoader": 0, "PuLIDModelLoader": 1, "ApplyPuLIDFlux2": 3,
    "DualIdentityScore": 8, "SaveImage": 1, "PreviewImage": 0, "MarkdownNote": 1,
}


def load_workflow(name: str) -> dict:
    path = WORKFLOW_DIR / name
    assert path.is_file(), f"missing workflow: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def node(workflow: dict, title: str) -> dict:
    found = [item for item in workflow["nodes"] if item.get("title") == title]
    assert len(found) == 1, f"expected exactly one role {title}, got {len(found)}"
    return found[0]


def widget(node_: dict, name: str):
    values = node_.get("widgets_values", {})
    if isinstance(values, dict):
        return values[name]
    index = {
        "LoadImage": {"image": 0},
        "UNETLoader": {"unet_name": 0},
        "LoraLoaderModelOnly": {"lora_name": 0, "strength_model": 1},
        "PuLIDModelLoader": {"pulid_file": 0},
        "DualIdentityScore": {"experiment_mode": 0},
    }[node_["type"]][name]
    return values[index]


def input_slot(node_: dict, name: str) -> int:
    return [item["name"] for item in node_["inputs"]].index(name)


def source(workflow: dict, target: dict, input_name: str) -> tuple[dict, int]:
    slot = input_slot(target, input_name)
    link_id = target["inputs"][slot].get("link")
    assert link_id is not None, f"{target['title']}.{input_name} is not linked"
    link = next(item for item in workflow["links"] if item[0] == link_id)
    return next(item for item in workflow["nodes"] if item["id"] == link[1]), link[2]


def assert_link_targets_slot(workflow: dict, target: dict, input_name: str, expected_slot: int) -> None:
    actual_slot = input_slot(target, input_name)
    assert actual_slot == expected_slot
    link_id = target["inputs"][actual_slot]["link"]
    assert link_id is not None
    link = next(item for item in workflow["links"] if item[0] == link_id)
    assert link[3:5] == [target["id"], expected_slot]


def assert_link_integrity_and_schemas(workflow: dict) -> None:
    nodes = {item["id"]: item for item in workflow["nodes"]}
    assert len(nodes) == len(workflow["nodes"])
    links = {item[0]: item for item in workflow["links"]}
    assert len(links) == len(workflow["links"])
    for item in workflow["nodes"]:
        assert item["type"] in NODE_SCHEMAS, f"uncaptured node schema: {item['type']}"
        expected_inputs, expected_outputs = NODE_SCHEMAS[item["type"]]
        assert tuple(value["name"] for value in item.get("inputs", ())) == expected_inputs
        assert tuple(value["type"] for value in item.get("outputs", ())) == expected_outputs
    for link_id, source_id, source_slot, target_id, target_slot, value_type in workflow["links"]:
        assert source_id in nodes and target_id in nodes
        source_node, target_node = nodes[source_id], nodes[target_id]
        assert source_node["outputs"][source_slot]["type"] == value_type
        assert target_node["inputs"][target_slot]["type"] == value_type
        assert link_id in source_node["outputs"][source_slot]["links"]
        assert target_node["inputs"][target_slot]["link"] == link_id


def test_builder_and_editor_files_are_initially_missing_for_the_new_suite():
    assert BUILDER.is_file(), "missing deterministic Flux identity-lab builder"
    for name in WORKFLOWS:
        load_workflow(name)


def test_builder_is_byte_identical_and_preserves_stable_editor_ids(tmp_path):
    subprocess.run([sys.executable, str(BUILDER), "--output-root", str(tmp_path)], check=True)
    first = {name: (tmp_path / name).read_bytes() for name in WORKFLOWS}
    subprocess.run([sys.executable, str(BUILDER), "--output-root", str(tmp_path)], check=True)
    assert {name: (tmp_path / name).read_bytes() for name in WORKFLOWS} == first
    for name in WORKFLOWS:
        workflow = json.loads(first[name])
        assert workflow["last_node_id"] == max(item["id"] for item in workflow["nodes"])
        assert workflow["last_link_id"] == max(item[0] for item in workflow["links"])
        assert_link_integrity_and_schemas(workflow)


@pytest.mark.parametrize("name", WORKFLOWS)
def test_templates_preserve_captured_optional_editor_sockets(name):
    workflow = load_workflow(name)
    for node_type, expected in OPTIONAL_EDITOR_SOCKETS.items():
        nodes = [item for item in workflow["nodes"] if item["type"] == node_type]
        if node_type in {"CLIPLoader", "DualIdentityScore"}:
            assert nodes, f"{name} is missing {node_type}"
        for item in nodes:
            actual = tuple(
                (input_["name"], input_["type"])
                for input_ in item["inputs"]
                if input_["name"] in {socket_name for socket_name, _type in expected}
            )
            assert actual == expected


@pytest.mark.parametrize("name", WORKFLOWS)
def test_sampler_links_target_actual_editor_slots(name):
    sampler = node(load_workflow(name), "IDENTITY_LAB_SAMPLER")
    assert tuple(item["name"] for item in sampler["inputs"]) == NODE_SCHEMAS["KSampler"][0]
    for input_name, expected_slot in (("model", 0), ("positive", 1), ("negative", 2), ("latent_image", 3)):
        assert_link_targets_slot(load_workflow(name), sampler, input_name, expected_slot)


def test_pulid_links_target_actual_editor_slots():
    workflow = load_workflow(IDENTITY_I2I)
    pulid = next(item for item in workflow["nodes"] if item["type"] == "ApplyPuLIDFlux2")
    assert tuple(item["name"] for item in pulid["inputs"]) == NODE_SCHEMAS["ApplyPuLIDFlux2"][0]
    for input_name, expected_slot in (("model", 0), ("pulid_model", 1), ("eva_clip", 2), ("face_analysis", 3), ("image", 4)):
        assert_link_targets_slot(workflow, pulid, input_name, expected_slot)


@pytest.mark.parametrize("name", WORKFLOWS)
def test_every_generated_node_uses_socket_first_editor_order_and_widget_serialization(name):
    for item in load_workflow(name)["nodes"]:
        node_type = item["type"]
        prefix = EDITOR_SOCKET_PREFIXES[node_type]
        trailing = EDITOR_TRAILING_FORCE_INPUTS.get(node_type, ())
        input_names = tuple(input_["name"] for input_ in item["inputs"])
        assert input_names[:len(prefix)] == prefix
        if trailing:
            assert input_names[-len(trailing):] == trailing
        widget_names = input_names[len(prefix):len(input_names) - len(trailing) if trailing else None]
        assert len(item["widgets_values"]) == EDITOR_WIDGET_VALUE_COUNTS[node_type], (
            f"{node_type} widgets must serialize in editor order after {prefix}; "
            f"found widget inputs {widget_names}"
        )


@pytest.mark.parametrize("name", WORKFLOWS)
def test_dual_identity_score_force_input_sockets_have_exact_editor_slots(name):
    score = node(load_workflow(name), "IDENTITY_LAB_SCORE")
    for input_name, expected_slot in (("experiment_id", 3), ("run_id", 4), ("extra_metadata", 5)):
        assert input_slot(score, input_name) == expected_slot
        assert score["inputs"][expected_slot]["link"] is None


@pytest.mark.parametrize(("name", "mode"), WORKFLOWS.items())
def test_templates_have_editor_metadata_stable_roles_and_safe_runtime_defaults(name, mode):
    workflow = load_workflow(name)
    assert workflow["version"] == 0.4
    assert workflow["extra"]["identity_lab_template"] == {"mode": mode, "version": 1, "target_model": "Flux2-Klein-9B"}
    assert (REPO_ROOT / "input" / PLACEHOLDER).is_file()
    for title, expected_type in ROLES.items():
        assert node(workflow, title)["type"] == expected_type
    assert [widget(node(workflow, title), "image") for title in ("IDENTITY_LAB_BASE_IMAGE", "IDENTITY_LAB_REFERENCE_IMAGE")] == [PLACEHOLDER, PLACEHOLDER]
    assert widget(node(workflow, "IDENTITY_LAB_MODEL"), "unet_name") == MODEL
    assert [widget(node(workflow, f"IDENTITY_LAB_LORA_{index}"), "lora_name") for index in range(1, 4)] == list(LORAS)
    assert [widget(node(workflow, f"IDENTITY_LAB_LORA_{index}"), "strength_model") for index in range(1, 4)] == [0.0, 0.0, 0.0]
    sampler = node(workflow, "IDENTITY_LAB_SAMPLER")
    assert all(item["link"] is None for item in sampler["inputs"] if item["name"] in {"seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"})
    assert widget(node(workflow, "IDENTITY_LAB_SCORE"), "experiment_mode") == mode
    notes = "\n".join(str(item.get("widgets_values", "")) for item in workflow["nodes"] if item["type"] == "MarkdownNote").casefold()
    assert mode.replace("_", "-") in notes and "identity" in notes


def test_runtime_loader_defaults_are_real_installed_assets():
    runtime_base = os.environ.get("COMFY_RUNTIME_BASE")
    if not runtime_base:
        pytest.skip("set COMFY_RUNTIME_BASE to run installed runtime asset checks")
    runtime = Path(runtime_base)
    assert (runtime / "models" / "diffusion_models" / MODEL).is_file()
    assert (runtime / "models" / "text_encoders" / CLIP).is_file()
    assert (runtime / "models" / "vae" / VAE).is_file()
    assert all((runtime / "models" / "loras" / lora).is_file() for lora in LORAS)
    assert (runtime / "models" / "pulid" / PULID).is_file()
    assert (runtime / "models" / "ultralytics" / "bbox" / "face_yolov8m.pt").is_file()
    assert (runtime / "models" / "sams" / "sam_vit_b_01ec64.pth").is_file()


def test_face_swap_has_detect_refine_crop_reference_and_uncrop_composite_path():
    workflow = load_workflow(FACE_SWAP)
    base, reference = node(workflow, "IDENTITY_LAB_BASE_IMAGE"), node(workflow, "IDENTITY_LAB_REFERENCE_IMAGE")
    detector = next(item for item in workflow["nodes"] if item["type"] == "UltralyticsDetectorProvider")
    target_detect, source_detect = [item for item in workflow["nodes"] if item["type"] == "BboxDetectorSEGS"]
    target_sam, source_sam = [item for item in workflow["nodes"] if item["type"] == "SAMDetectorCombined"]
    target_crop, source_crop = [item for item in workflow["nodes"] if item["type"] == "BatchCropFromMaskAdvanced"]
    uncrop = next(item for item in workflow["nodes"] if item["type"] == "BatchUncropAdvanced")
    assert source(workflow, target_detect, "bbox_detector")[0] == detector and source(workflow, source_detect, "bbox_detector")[0] == detector
    assert source(workflow, target_detect, "image")[0] == base and source(workflow, source_detect, "image")[0] == reference
    assert source(workflow, target_sam, "segs")[0] == target_detect and source(workflow, source_sam, "segs")[0] == source_detect
    assert source(workflow, target_crop, "original_images")[0] == base and source(workflow, source_crop, "original_images")[0] == reference
    assert source(workflow, target_crop, "masks")[0] == target_sam and source(workflow, source_crop, "masks")[0] == source_sam
    sampler = node(workflow, "IDENTITY_LAB_SAMPLER")
    assert source(workflow, sampler, "positive")[0]["type"] == "ReferenceLatent"
    decoded = next(item for item in workflow["nodes"] if item["type"] == "VAEDecode")
    assert source(workflow, uncrop, "original_images")[0] == base and source(workflow, uncrop, "cropped_images")[0] == decoded
    score = node(workflow, "IDENTITY_LAB_SCORE")
    assert source(workflow, score, "base_image")[0] == base and source(workflow, score, "reference_image")[0] == reference and source(workflow, score, "generated_image")[0] == uncrop


def test_identity_i2i_scales_base_applies_pulid_and_scores_final_decode():
    workflow = load_workflow(IDENTITY_I2I)
    base, reference = node(workflow, "IDENTITY_LAB_BASE_IMAGE"), node(workflow, "IDENTITY_LAB_REFERENCE_IMAGE")
    scale = node(workflow, "IDENTITY_LAB_PIXEL_BUDGET")
    assert source(workflow, scale, "image")[0] == base
    pulid = next(item for item in workflow["nodes"] if item["type"] == "ApplyPuLIDFlux2")
    assert widget(next(item for item in workflow["nodes"] if item["type"] == "PuLIDModelLoader"), "pulid_file") == PULID
    assert source(workflow, pulid, "image")[0] == reference
    sampler = node(workflow, "IDENTITY_LAB_SAMPLER")
    assert source(workflow, sampler, "model")[0] == pulid
    assert source(workflow, sampler, "positive")[0]["type"] == "ReferenceLatent"
    decoded = next(item for item in workflow["nodes"] if item["type"] == "VAEDecode")
    score = node(workflow, "IDENTITY_LAB_SCORE")
    assert source(workflow, score, "base_image")[0] == base and source(workflow, score, "reference_image")[0] == reference and source(workflow, score, "generated_image")[0] == decoded
