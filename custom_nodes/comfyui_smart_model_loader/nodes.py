from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import torch

import folder_paths

from .catalog import AssetProfile, load_override_catalog, profile_from_file
from .compatibility import CompatibilityResult, classify_lora_for_model


CATEGORY = "arch-loaders/smart"
NONE_OPTION = "None"
LORA_SLOT_COUNT = 8
LORA_OPTION_GROUPS = (
    "age",
    "breast_size",
    "ass_size",
    "height",
    "weight",
    "hair_color",
)
LORA_OPTION_CATALOG_PATH = Path(__file__).with_name("lora_option_catalog.json")


class _FallbackCLIPType(Enum):
    STABLE_DIFFUSION = 1
    FLUX2 = 25
    QWEN_IMAGE = 18
    WAN = 11


def _comfy_runtime_missing(*_args, **_kwargs):
    raise RuntimeError("ComfyUI runtime module is not available in this context.")


comfy = SimpleNamespace(
    sd=SimpleNamespace(
        CLIPType=_FallbackCLIPType,
        load_checkpoint_guess_config=_comfy_runtime_missing,
        load_diffusion_model=_comfy_runtime_missing,
        load_clip=_comfy_runtime_missing,
        load_lora_for_models=_comfy_runtime_missing,
    ),
    utils=SimpleNamespace(),
)


def get_comfy_sd():
    if hasattr(comfy.sd, "load_diffusion_model"):
        return comfy.sd
    import comfy.sd as sd_module

    comfy.sd = sd_module
    return comfy.sd


def get_comfy_utils():
    if hasattr(comfy.utils, "load_torch_file"):
        return comfy.utils
    import comfy.utils as utils_module

    comfy.utils = utils_module
    return comfy.utils


def _with_none(values: list[str]) -> list[str]:
    return [NONE_OPTION] + [value for value in values if value != NONE_OPTION]


def infer_family(workflow_family: str, primary_model: str) -> str:
    if workflow_family and workflow_family != "auto":
        return workflow_family
    profile = profile_from_file(primary_model, "diffusion_model", None)
    return profile.family or "flux"


def infer_clip_type(workflow_family: str, primary_model: str, clip_type: str) -> str:
    if clip_type and clip_type != "auto":
        return clip_type
    family = infer_family(workflow_family, primary_model)
    if family == "flux":
        return "flux2"
    if family == "qwen":
        return "qwen_image"
    if family == "wan":
        return "wan"
    return "stable_diffusion"


def model_options_for_dtype(weight_dtype: str) -> dict[str, Any]:
    if weight_dtype == "fp8_e4m3fn":
        return {"dtype": torch.float8_e4m3fn}
    if weight_dtype == "fp8_e4m3fn_fast":
        return {"dtype": torch.float8_e4m3fn, "fp8_optimizations": True}
    if weight_dtype == "fp8_e5m2":
        return {"dtype": torch.float8_e5m2}
    return {}


def load_vae_by_name(vae_name: str):
    from nodes import VAELoader

    return VAELoader().load_vae(vae_name)[0]


def load_lora_file(path: str):
    return get_comfy_utils().load_torch_file(path, safe_load=True, return_metadata=True)


def load_lora_option_catalog(path: str | Path | None = None) -> dict[str, Any]:
    catalog_path = Path(path) if path is not None else LORA_OPTION_CATALOG_PATH
    if not catalog_path.exists():
        return {
            "version": 1,
            "groups": {group: {"neutral": {}} for group in LORA_OPTION_GROUPS},
        }
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"LoRA option catalog must be a JSON object: {catalog_path}")
    groups = data.setdefault("groups", {})
    if not isinstance(groups, dict):
        raise ValueError(f"LoRA option catalog groups must be an object: {catalog_path}")
    for group in LORA_OPTION_GROUPS:
        options = groups.setdefault(group, {})
        if not isinstance(options, dict):
            raise ValueError(f"LoRA option group must be an object: {group}")
        options.setdefault("neutral", {})
    return data


def _lora_option_group(catalog: dict[str, Any], group: str) -> dict[str, Any]:
    groups = catalog.get("groups", {})
    if not isinstance(groups, dict):
        return {"neutral": {}}
    options = groups.get(group, {})
    if not isinstance(options, dict):
        return {"neutral": {}}
    return options


def _option_names(group: str) -> list[str]:
    try:
        options = list(_lora_option_group(load_lora_option_catalog(), group).keys())
    except Exception:  # noqa: BLE001 - keep the node creatable if the catalog is bad
        options = ["neutral"]
    values = ["neutral"] + [option for option in options if option != "neutral"]
    return values or ["neutral"]


def _prompt_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _append_prompt(base: str, addition: Any, separator: str = ", ") -> str:
    addition_text = _prompt_text(addition)
    if not addition_text:
        return str(base or "")
    base_text = str(base or "").strip()
    if not base_text:
        return addition_text
    return f"{base_text}{separator}{addition_text}"


def _profile_for_selection(name: str, kind: str, folder: str) -> AssetProfile:
    try:
        path = folder_paths.get_full_path_or_raise(folder, name)
    except FileNotFoundError:
        path = None
    return profile_from_file(
        name=name,
        kind=kind,
        path=path,
        overrides=load_override_catalog(),
    )


def load_base_model_stack(
    workflow_family: str,
    primary_model: str,
    clip_name: str,
    vae_name: str,
    clip_type: str = "auto",
    weight_dtype: str = "default",
):
    family = infer_family(workflow_family, primary_model)
    primary_kind = "checkpoint" if family == "sdxl_checkpoint" else "diffusion_model"

    if primary_kind == "checkpoint":
        sd = get_comfy_sd()
        ckpt_path = folder_paths.get_full_path_or_raise("checkpoints", primary_model)
        model, clip, vae = sd.load_checkpoint_guess_config(
            ckpt_path,
            output_vae=True,
            output_clip=True,
            embedding_directory=folder_paths.get_folder_paths("embeddings"),
        )[:3]
    else:
        sd = get_comfy_sd()
        model_path = folder_paths.get_full_path_or_raise("diffusion_models", primary_model)
        model = sd.load_diffusion_model(
            model_path,
            model_options=model_options_for_dtype(weight_dtype),
        )
        resolved_clip_type = infer_clip_type(workflow_family, primary_model, clip_type)
        clip_enum = getattr(
            sd.CLIPType,
            resolved_clip_type.upper(),
            sd.CLIPType.STABLE_DIFFUSION,
        )
        clip_path = folder_paths.get_full_path_or_raise("text_encoders", clip_name)
        clip = sd.load_clip(
            ckpt_paths=[clip_path],
            embedding_directory=folder_paths.get_folder_paths("embeddings"),
            clip_type=clip_enum,
            model_options={},
        )
        vae = load_vae_by_name(vae_name)

    resolved_clip_type = infer_clip_type(workflow_family, primary_model, clip_type)
    metadata = {
        "family": family,
        "primary_model": primary_model,
        "primary_kind": primary_kind,
        "clip_name": clip_name,
        "clip_type": resolved_clip_type,
        "vae_name": vae_name,
        "loras": [],
    }
    return model, clip, vae, metadata


def _enabled_lora_slots(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    slots = []
    for index in range(1, LORA_SLOT_COUNT + 1):
        name = normalize_option_name(kwargs.get(f"lora_{index}", NONE_OPTION))
        enabled = bool(kwargs.get(f"lora_{index}_enabled", True))
        strength_model = float(kwargs.get(f"lora_{index}_strength_model", 1.0))
        strength_clip = float(kwargs.get(f"lora_{index}_strength_clip", strength_model))
        if enabled and name and name != NONE_OPTION and (strength_model != 0 or strength_clip != 0):
            slots.append(
                {
                    "name": name,
                    "strength_model": strength_model,
                    "strength_clip": strength_clip,
                }
            )
    return slots


def normalize_option_name(value: Any) -> str:
    if value is None:
        return NONE_OPTION
    return re.sub(r"^\[(compatible|uncertain)\]\s+", "", str(value))


def _validate_loras(
    model_profile: AssetProfile,
    lora_slots: list[dict[str, Any]],
    allow_uncertain_loras: bool,
    strict_validation: bool,
) -> list[tuple[dict[str, Any], AssetProfile, CompatibilityResult]]:
    validated = []
    for slot in lora_slots:
        lora_profile = _profile_for_selection(slot["name"], "lora", "loras")
        result = classify_lora_for_model(model_profile, lora_profile)
        if result.status == "incompatible":
            raise ValueError(f"LoRA {slot['name']} is incompatible: {result.reason}")
        if result.status == "uncertain" and (strict_validation or not allow_uncertain_loras):
            raise ValueError(f"LoRA {slot['name']} is uncertain: {result.reason}")
        validated.append((slot, lora_profile, result))
    return validated


class SmartModelLoraLoader:
    @classmethod
    def INPUT_TYPES(cls):
        required: dict[str, Any] = {
            "workflow_family": (["auto", "flux", "qwen", "wan", "sdxl_checkpoint"],),
            "primary_model": (
                folder_paths.get_filename_list("diffusion_models")
                + folder_paths.get_filename_list("checkpoints"),
            ),
            "clip_name": (folder_paths.get_filename_list("text_encoders"),),
            "vae_name": (folder_paths.get_filename_list("vae"),),
            "clip_type": (["auto", "flux2", "qwen_image", "wan", "stable_diffusion"], {"advanced": True}),
            "weight_dtype": (
                ["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"],
                {"advanced": True},
            ),
            "allow_uncertain_loras": ("BOOLEAN", {"default": True, "advanced": True}),
            "strict_validation": ("BOOLEAN", {"default": False, "advanced": True}),
        }
        loras = _with_none(folder_paths.get_filename_list("loras"))
        for index in range(1, LORA_SLOT_COUNT + 1):
            required[f"lora_{index}"] = (loras,)
            required[f"lora_{index}_enabled"] = ("BOOLEAN", {"default": False})
            required[f"lora_{index}_strength_model"] = (
                "FLOAT",
                {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01},
            )
            required[f"lora_{index}_strength_clip"] = (
                "FLOAT",
                {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01},
            )
        return {"required": required}

    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "STRING")
    RETURN_NAMES = ("model", "clip", "vae", "metadata_json")
    FUNCTION = "load_smart_model"
    CATEGORY = CATEGORY
    DESCRIPTION = "Loads a compatible model, text encoder, VAE, and filtered LoRA stack."

    def load_smart_model(
        self,
        workflow_family,
        primary_model,
        clip_name,
        vae_name,
        clip_type="auto",
        weight_dtype="default",
        allow_uncertain_loras=True,
        strict_validation=False,
        **kwargs,
    ):
        family = infer_family(workflow_family, primary_model)
        primary_kind = "checkpoint" if family == "sdxl_checkpoint" else "diffusion_model"
        primary_folder = "checkpoints" if primary_kind == "checkpoint" else "diffusion_models"
        model_profile = _profile_for_selection(primary_model, primary_kind, primary_folder)
        lora_slots = _enabled_lora_slots(kwargs)
        validated_loras = _validate_loras(
            model_profile,
            lora_slots,
            bool(allow_uncertain_loras),
            bool(strict_validation),
        )

        model, clip, vae, metadata = load_base_model_stack(
            workflow_family=workflow_family,
            primary_model=primary_model,
            clip_name=clip_name,
            vae_name=vae_name,
            clip_type=clip_type,
            weight_dtype=weight_dtype,
        )

        applied_loras = []
        for slot, lora_profile, result in validated_loras:
            sd = get_comfy_sd()
            lora_path = folder_paths.get_full_path_or_raise("loras", slot["name"])
            lora, lora_metadata = load_lora_file(lora_path)
            model, clip = sd.load_lora_for_models(
                model,
                clip,
                lora,
                slot["strength_model"],
                slot["strength_clip"],
                lora_metadata=lora_metadata,
            )
            applied_loras.append(
                {
                    "name": slot["name"],
                    "strength_model": slot["strength_model"],
                    "strength_clip": slot["strength_clip"],
                    "status": result.status,
                    "reason": result.reason,
                    "family": lora_profile.family,
                    "variant": lora_profile.variant,
                }
            )

        metadata["loras"] = applied_loras
        return (model, clip, vae, json.dumps(metadata, ensure_ascii=False))


class ArchModelStackLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "workflow_family": (["auto", "flux", "qwen", "wan", "sdxl_checkpoint"],),
                "primary_model": (
                    folder_paths.get_filename_list("diffusion_models")
                    + folder_paths.get_filename_list("checkpoints"),
                ),
                "clip_name": (folder_paths.get_filename_list("text_encoders"),),
                "vae_name": (folder_paths.get_filename_list("vae"),),
                "clip_type": (["auto", "flux2", "qwen_image", "wan", "stable_diffusion"], {"advanced": True}),
                "weight_dtype": (
                    ["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"],
                    {"advanced": True},
                ),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "STRING")
    RETURN_NAMES = ("model", "clip", "vae", "metadata_json")
    FUNCTION = "load_model_stack"
    CATEGORY = CATEGORY
    DESCRIPTION = "Loads the base model, text encoder, and VAE without applying LoRAs."

    def load_model_stack(
        self,
        workflow_family,
        primary_model,
        clip_name,
        vae_name,
        clip_type="auto",
        weight_dtype="default",
    ):
        model, clip, vae, metadata = load_base_model_stack(
            workflow_family=workflow_family,
            primary_model=primary_model,
            clip_name=clip_name,
            vae_name=vae_name,
            clip_type=clip_type,
            weight_dtype=weight_dtype,
        )
        return (model, clip, vae, json.dumps(metadata, ensure_ascii=False))


class ArchPromptLoraOptionStack:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "positive_prompt": (
                    "STRING",
                    {"default": "", "multiline": True, "forceInput": True},
                ),
                "negative_prompt": (
                    "STRING",
                    {"default": "", "multiline": True, "forceInput": True},
                ),
                "age": (_option_names("age"),),
                "breast_size": (_option_names("breast_size"),),
                "ass_size": (_option_names("ass_size"),),
                "height": (_option_names("height"),),
                "weight": (_option_names("weight"),),
                "hair_color": (_option_names("hair_color"),),
                "allow_missing_loras": ("BOOLEAN", {"default": True}),
                "prompt_separator": ("STRING", {"default": ", ", "advanced": True}),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "model",
        "clip",
        "positive_prompt",
        "negative_prompt",
        "metadata_json",
    )
    FUNCTION = "apply_options"
    CATEGORY = CATEGORY
    DESCRIPTION = "Applies named body/style options as prompt fragments and optional LoRAs."

    def apply_options(
        self,
        model,
        clip,
        positive_prompt,
        negative_prompt,
        age,
        breast_size,
        ass_size,
        height,
        weight,
        hair_color,
        allow_missing_loras=True,
        prompt_separator=", ",
    ):
        catalog = load_lora_option_catalog()
        selected_options = {
            "age": age,
            "breast_size": breast_size,
            "ass_size": ass_size,
            "height": height,
            "weight": weight,
            "hair_color": hair_color,
        }
        positive = str(positive_prompt or "").strip()
        negative = str(negative_prompt or "").strip()
        applied_loras = []
        missing_loras = []
        prompt_additions: dict[str, dict[str, str]] = {}

        for group, option_name in selected_options.items():
            options = _lora_option_group(catalog, group)
            option = options.get(str(option_name), {})
            if not isinstance(option, dict):
                option = {}

            option_positive = _prompt_text(option.get("positive"))
            option_negative = _prompt_text(option.get("negative"))
            positive = _append_prompt(positive, option_positive, prompt_separator)
            negative = _append_prompt(negative, option_negative, prompt_separator)
            prompt_additions[group] = {
                "positive": option_positive,
                "negative": option_negative,
            }

            for lora_config in option.get("loras", []) or []:
                if not isinstance(lora_config, dict):
                    continue
                lora_name = str(lora_config.get("name", "")).strip()
                if not lora_name:
                    continue
                strength_model = float(lora_config.get("strength_model", 1.0))
                strength_clip = float(lora_config.get("strength_clip", strength_model))
                try:
                    lora_path = folder_paths.get_full_path_or_raise("loras", lora_name)
                    lora, lora_metadata = load_lora_file(lora_path)
                except FileNotFoundError as exc:
                    if not allow_missing_loras:
                        raise
                    missing_loras.append(
                        {
                            "group": group,
                            "option": option_name,
                            "name": lora_name,
                            "error": str(exc),
                        }
                    )
                    continue

                sd = get_comfy_sd()
                model, clip = sd.load_lora_for_models(
                    model,
                    clip,
                    lora,
                    strength_model,
                    strength_clip,
                    lora_metadata=lora_metadata,
                )
                applied_loras.append(
                    {
                        "group": group,
                        "option": option_name,
                        "name": lora_name,
                        "strength_model": strength_model,
                        "strength_clip": strength_clip,
                    }
                )

        metadata = {
            "catalog_version": catalog.get("version"),
            "selected_options": selected_options,
            "prompt_additions": prompt_additions,
            "applied_loras": applied_loras,
            "missing_loras": missing_loras,
        }
        return (
            model,
            clip,
            positive,
            negative,
            json.dumps(metadata, ensure_ascii=False),
        )


NODE_CLASS_MAPPINGS = {
    "SmartModelLoraLoader": SmartModelLoraLoader,
    "ArchModelStackLoader": ArchModelStackLoader,
    "ArchPromptLoraOptionStack": ArchPromptLoraOptionStack,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SmartModelLoraLoader": "arch-Smart Model + LoRA Loader",
    "ArchModelStackLoader": "arch-Model + CLIP + VAE Loader",
    "ArchPromptLoraOptionStack": "arch-Prompt LoRA Option Stack",
}
