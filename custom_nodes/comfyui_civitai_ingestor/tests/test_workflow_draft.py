import json
import stat
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_civitai_ingestor.workflow_draft import build_workflow_draft, save_draft_file


def test_build_workflow_draft_creates_checkpoint_lora_api_prompt():
    image = {
        "image_id": 100,
        "has_meta": True,
        "prompt": "score_9, portrait",
        "negative_prompt": "low quality",
        "seed": "12345",
        "steps": "30",
        "sampler": "DPM++ 2M Karras",
        "cfg_scale": "7",
        "width": 832,
        "height": 1216,
        "base_model": "Pony",
    }
    resources = [
        {
            "model_version_id": 1,
            "model_name": "Pony Diffusion",
            "model_type": "Checkpoint",
            "file_name": "pony.safetensors",
            "target_folder": "checkpoints",
            "local_status": "present",
            "local_path": "C:/tools/image/ComfyUI/models/checkpoints/pony.safetensors",
        },
        {
            "model_version_id": 2,
            "model_name": "Style LoRA",
            "model_type": "LORA",
            "file_name": "style.safetensors",
            "target_folder": "loras",
            "local_status": "present",
            "local_path": "C:/tools/image/ComfyUI/models/loras/style.safetensors",
        },
    ]
    image_resources = [
        {"image_id": 100, "model_version_id": 1, "resource_type": "checkpoint"},
        {"image_id": 100, "model_version_id": 2, "resource_type": "lora", "weight": 0.8},
    ]

    draft = build_workflow_draft(image, resources, image_resources)
    api_prompt = draft["api_prompt"]
    nodes = list(api_prompt.values())

    assert draft["runnable"] is True
    assert draft["warnings"] == []
    assert nodes[0]["class_type"] == "CheckpointLoaderSimple"
    assert nodes[0]["inputs"]["ckpt_name"] == "pony.safetensors"
    assert any(node["class_type"] == "LoraLoader" for node in nodes)
    lora = next(node for node in nodes if node["class_type"] == "LoraLoader")
    assert lora["inputs"]["lora_name"] == "style.safetensors"
    assert lora["inputs"]["strength_model"] == 0.8
    sampler = next(node for node in nodes if node["class_type"] == "KSampler")
    assert sampler["inputs"]["seed"] == 12345
    assert sampler["inputs"]["steps"] == 30
    assert sampler["inputs"]["cfg"] == 7.0
    assert sampler["inputs"]["sampler_name"] == "dpmpp_2m"
    assert sampler["inputs"]["scheduler"] == "karras"


def test_build_workflow_draft_marks_missing_metadata_not_runnable():
    draft = build_workflow_draft(
        {"image_id": 101, "has_meta": False, "prompt": None},
        [],
        [],
    )

    assert draft["runnable"] is False
    assert draft["api_prompt"] is None
    assert "Image does not include generation metadata." in draft["warnings"]


def test_build_workflow_draft_does_not_use_vae_target_as_checkpoint():
    image = {
        "image_id": 102,
        "has_meta": True,
        "prompt": "portrait",
        "width": 1024,
        "height": 1024,
    }
    resources = [
        {
            "model_version_id": 3,
            "model_name": "SDXL VAE",
            "model_type": "Checkpoint",
            "file_name": "sdxl_vae.safetensors",
            "target_folder": "vae",
            "local_status": "present",
            "local_path": "C:/tools/image/ComfyUI/models/vae/sdxl_vae.safetensors",
        }
    ]
    image_resources = [
        {"image_id": 102, "model_version_id": 3, "resource_type": "checkpoint"},
    ]

    draft = build_workflow_draft(image, resources, image_resources)

    assert draft["runnable"] is False
    assert draft["api_prompt"] is None
    assert "No checkpoint resource was linked to this image." in draft["warnings"]


def test_save_draft_file_writes_read_only_json(tmp_path):
    draft = {
        "image_id": 100,
        "runnable": False,
        "warnings": ["missing model"],
        "api_prompt": None,
    }

    path = save_draft_file(
        draft,
        output_root=tmp_path,
        collection_id=8081491,
        readonly=True,
    )

    assert path.name == "image-100.workflow-draft.json"
    assert path.parent.name == "collection-8081491"
    assert json.loads(path.read_text())["warnings"] == ["missing model"]
    assert path.stat().st_mode & stat.S_IWRITE == 0
