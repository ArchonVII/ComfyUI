from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


def default_workflow_root() -> Path:
    import folder_paths

    return Path(folder_paths.get_system_user_directory("civitai_ingestor")) / "workflow_drafts"


def build_workflow_draft(
    image: dict[str, Any],
    resources: list[dict[str, Any]],
    image_resources: list[dict[str, Any]],
) -> dict[str, Any]:
    warnings: list[str] = []
    image_id = image.get("image_id")
    if not image.get("has_meta") or not image.get("prompt"):
        warnings.append("Image does not include generation metadata.")
        return {
            "image_id": image_id,
            "collection_id": image.get("collection_id"),
            "runnable": False,
            "warnings": warnings,
            "api_prompt": None,
            "source": image,
        }

    resource_by_version = {
        int(resource["model_version_id"]): resource
        for resource in resources
        if resource.get("model_version_id") is not None
    }
    linked = [
        link
        for link in image_resources
        if int(link.get("image_id", image_id) or 0) == int(image_id or 0)
    ]
    checkpoint = _first_checkpoint_resource(linked, resource_by_version)
    if checkpoint is None:
        checkpoint = _first_checkpoint_by_model_type(resources)
    if checkpoint is None:
        warnings.append("No checkpoint resource was linked to this image.")
        return _draft(image, None, resources, image_resources, warnings, False)

    loras = _linked_loras(linked, resource_by_version)
    for item in [checkpoint, *[entry["resource"] for entry in loras]]:
        if not _is_present(item):
            warnings.append(f"Model file is not locally available: {item.get('file_name')}")

    sampler_name, scheduler = sampler_to_comfy(image.get("sampler"))
    api_prompt: dict[str, dict[str, Any]] = {}
    node_id = 1
    checkpoint_id = str(node_id)
    api_prompt[checkpoint_id] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": _comfy_file_name(checkpoint)},
    }
    model_ref = [checkpoint_id, 0]
    clip_ref = [checkpoint_id, 1]
    vae_ref = [checkpoint_id, 2]

    for entry in loras:
        node_id += 1
        lora_id = str(node_id)
        weight = _float(entry.get("weight"), 1.0)
        api_prompt[lora_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": model_ref,
                "clip": clip_ref,
                "lora_name": _comfy_file_name(entry["resource"]),
                "strength_model": weight,
                "strength_clip": weight,
            },
        }
        model_ref = [lora_id, 0]
        clip_ref = [lora_id, 1]

    node_id += 1
    positive_id = str(node_id)
    api_prompt[positive_id] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": image.get("prompt") or "", "clip": clip_ref},
    }
    node_id += 1
    negative_id = str(node_id)
    api_prompt[negative_id] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": image.get("negative_prompt") or "", "clip": clip_ref},
    }
    node_id += 1
    latent_id = str(node_id)
    api_prompt[latent_id] = {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": _int(image.get("width"), 1024),
            "height": _int(image.get("height"), 1024),
            "batch_size": 1,
        },
    }
    node_id += 1
    sampler_id = str(node_id)
    api_prompt[sampler_id] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": _int(image.get("seed"), 0),
            "steps": _int(image.get("steps"), 20),
            "cfg": _float(image.get("cfg_scale"), 7.0),
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "denoise": 1.0,
            "model": model_ref,
            "positive": [positive_id, 0],
            "negative": [negative_id, 0],
            "latent_image": [latent_id, 0],
        },
    }
    node_id += 1
    decode_id = str(node_id)
    api_prompt[decode_id] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": [sampler_id, 0], "vae": vae_ref},
    }
    node_id += 1
    api_prompt[str(node_id)] = {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": f"civitai_image_{image_id}",
            "images": [decode_id, 0],
        },
    }

    return _draft(image, api_prompt, resources, image_resources, warnings, not warnings)


def save_draft_file(
    draft: dict[str, Any],
    *,
    output_root: str | Path | None = None,
    collection_id: int | None = None,
    readonly: bool = True,
) -> Path:
    root = Path(output_root) if output_root is not None else default_workflow_root()
    collection = collection_id or draft.get("collection_id") or "unknown"
    image_id = draft.get("image_id") or "unknown"
    target_dir = root / f"collection-{collection}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"image-{image_id}.workflow-draft.json"
    if target_path.exists():
        os.chmod(target_path, stat.S_IREAD | stat.S_IWRITE)
    target_path.write_text(json.dumps(draft, indent=2, sort_keys=True), encoding="utf-8")
    if readonly:
        os.chmod(target_path, stat.S_IREAD)
    return target_path


def sampler_to_comfy(value: Any) -> tuple[str, str]:
    text = str(value or "").strip().lower()
    scheduler = "normal"
    if "karras" in text:
        scheduler = "karras"
    elif "exponential" in text:
        scheduler = "exponential"
    elif "sgm" in text and "uniform" in text:
        scheduler = "sgm_uniform"
    elif "simple" in text:
        scheduler = "simple"

    compact = text.replace("+", "p").replace("-", " ").replace("_", " ")
    if "dpmpp" in compact and "2m" in compact and "sde" in compact:
        return "dpmpp_2m_sde", scheduler
    if "dpmpp" in compact and "2m" in compact:
        return "dpmpp_2m", scheduler
    if "dpmpp" in compact and "sde" in compact:
        return "dpmpp_sde", scheduler
    if "euler a" in compact or "euler ancestral" in compact:
        return "euler_ancestral", scheduler
    if "euler" in compact:
        return "euler", scheduler
    if "ddim" in compact:
        return "ddim", scheduler
    return "euler", scheduler


def _draft(
    image: dict[str, Any],
    api_prompt: dict[str, Any] | None,
    resources: list[dict[str, Any]],
    image_resources: list[dict[str, Any]],
    warnings: list[str],
    runnable: bool,
) -> dict[str, Any]:
    return {
        "image_id": image.get("image_id"),
        "collection_id": image.get("collection_id"),
        "runnable": runnable,
        "warnings": warnings,
        "api_prompt": api_prompt,
        "source": {
            "prompt": image.get("prompt"),
            "negative_prompt": image.get("negative_prompt"),
            "seed": image.get("seed"),
            "steps": image.get("steps"),
            "sampler": image.get("sampler"),
            "cfg_scale": image.get("cfg_scale"),
            "width": image.get("width"),
            "height": image.get("height"),
            "base_model": image.get("base_model"),
        },
        "resources": resources,
        "image_resources": image_resources,
    }


def _first_checkpoint_resource(
    links: list[dict[str, Any]],
    resources: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    for link in links:
        resource = resources.get(int(link.get("model_version_id") or 0))
        if resource is None:
            continue
        link_type = str(link.get("resource_type") or resource.get("model_type") or "").strip().lower()
        if _is_checkpoint_candidate(link_type, resource):
            return resource
    return None


def _first_checkpoint_by_model_type(resources: list[dict[str, Any]]) -> dict[str, Any] | None:
    for resource in resources:
        model_type = str(resource.get("model_type") or "").strip().lower()
        if _is_checkpoint_candidate(model_type, resource):
            return resource
    return None


def _is_checkpoint_candidate(link_type: str, resource: dict[str, Any]) -> bool:
    target_folder = str(resource.get("target_folder") or "").strip().lower()
    model_type = str(resource.get("model_type") or "").strip().lower()
    if target_folder not in {"checkpoints", "diffusion_models"}:
        return False
    return link_type in {"checkpoint", "model", "base model"} or model_type == "checkpoint"


def _linked_loras(
    links: list[dict[str, Any]],
    resources: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    loras: list[dict[str, Any]] = []
    seen: set[int] = set()
    for link in links:
        version_id = int(link.get("model_version_id") or 0)
        resource = resources.get(version_id)
        if resource is None or version_id in seen:
            continue
        link_type = str(link.get("resource_type") or resource.get("model_type") or "").strip().lower()
        model_type = str(resource.get("model_type") or "").strip().lower()
        if "lora" in link_type or "lora" in model_type:
            loras.append({"resource": resource, "weight": link.get("weight")})
            seen.add(version_id)
    return loras


def _is_present(resource: dict[str, Any]) -> bool:
    return str(resource.get("local_status") or "").startswith("present")


def _comfy_file_name(resource: dict[str, Any]) -> str:
    return Path(str(resource.get("file_name") or resource.get("local_path") or "")).name


def _int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
