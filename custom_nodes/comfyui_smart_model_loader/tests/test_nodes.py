import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_smart_model_loader import nodes


def test_base_model_stack_loader_loads_model_clip_and_vae_without_loras(monkeypatch):
    monkeypatch.setattr(
        nodes.folder_paths,
        "get_full_path_or_raise",
        lambda folder, name: f"{folder}/{name}",
    )
    monkeypatch.setattr(nodes.folder_paths, "get_folder_paths", lambda folder: [folder])
    monkeypatch.setattr(
        nodes.comfy.sd,
        "load_diffusion_model",
        lambda path, model_options=None: f"model:{path}:{model_options or {}}",
    )
    monkeypatch.setattr(
        nodes.comfy.sd,
        "load_clip",
        lambda ckpt_paths, embedding_directory, clip_type, model_options=None: (
            f"clip:{ckpt_paths[0]}:{clip_type.name}"
        ),
    )
    monkeypatch.setattr(nodes, "load_vae_by_name", lambda name: f"vae:{name}")

    model, clip, vae, metadata_json = nodes.ArchModelStackLoader().load_model_stack(
        workflow_family="flux",
        primary_model="Flux\\9b\\model.safetensors",
        clip_name="Qwen\\qwen.safetensors",
        vae_name="flux2-vae.safetensors",
        clip_type="auto",
        weight_dtype="default",
    )

    metadata = json.loads(metadata_json)
    assert model.startswith("model:diffusion_models/Flux\\9b\\model.safetensors")
    assert clip == "clip:text_encoders/Qwen\\qwen.safetensors:FLUX2"
    assert vae == "vae:flux2-vae.safetensors"
    assert metadata["loras"] == []


def test_prompt_lora_option_stack_applies_selected_lora_and_appends_prompt(monkeypatch):
    catalog = {
        "version": 1,
        "groups": {
            "breast_size": {
                "neutral": {},
                "flat": {
                    "positive": "small flat chest",
                    "negative": "large breasts",
                    "loras": [
                        {
                            "name": "Flux\\9b\\Boobs\\flat.safetensors",
                            "strength_model": 0.6,
                            "strength_clip": 0.4,
                        }
                    ],
                },
            },
            "age": {"neutral": {}},
            "ass_size": {"neutral": {}},
            "height": {"neutral": {}},
            "weight": {"neutral": {}},
            "hair_color": {"neutral": {}},
        },
    }
    calls = []
    monkeypatch.setattr(nodes, "load_lora_option_catalog", lambda _path=None: catalog)
    monkeypatch.setattr(
        nodes.folder_paths,
        "get_full_path_or_raise",
        lambda folder, name: f"{folder}/{name}",
    )
    monkeypatch.setattr(
        nodes,
        "load_lora_file",
        lambda path: ({"name": path}, {"source": "test"}),
    )

    def fake_apply_lora(model, clip, lora, strength_model, strength_clip, lora_metadata=None):
        calls.append((lora["name"], strength_model, strength_clip, lora_metadata))
        return (f"{model}+flat", f"{clip}+flat")

    monkeypatch.setattr(nodes.comfy.sd, "load_lora_for_models", fake_apply_lora)

    model, clip, positive, negative, metadata_json = nodes.ArchPromptLoraOptionStack().apply_options(
        model="model",
        clip="clip",
        positive_prompt="portrait",
        negative_prompt="watermark",
        age="neutral",
        breast_size="flat",
        ass_size="neutral",
        height="neutral",
        weight="neutral",
        hair_color="neutral",
        allow_missing_loras=False,
    )

    metadata = json.loads(metadata_json)
    assert model == "model+flat"
    assert clip == "clip+flat"
    assert positive == "portrait, small flat chest"
    assert negative == "watermark, large breasts"
    assert metadata["selected_options"]["breast_size"] == "flat"
    assert metadata["applied_loras"][0]["name"] == "Flux\\9b\\Boobs\\flat.safetensors"
    assert calls == [
        ("loras/Flux\\9b\\Boobs\\flat.safetensors", 0.6, 0.4, {"source": "test"})
    ]


def test_smart_loader_loads_separate_model_stack_and_applies_enabled_lora(monkeypatch):
    calls = []

    monkeypatch.setattr(
        nodes.folder_paths,
        "get_full_path_or_raise",
        lambda folder, name: f"{folder}/{name}",
    )
    monkeypatch.setattr(nodes.folder_paths, "get_folder_paths", lambda folder: [folder])
    monkeypatch.setattr(
        nodes.comfy.sd,
        "load_diffusion_model",
        lambda path, model_options=None: f"model:{path}:{model_options or {}}",
    )
    monkeypatch.setattr(
        nodes.comfy.sd,
        "load_clip",
        lambda ckpt_paths, embedding_directory, clip_type, model_options=None: (
            f"clip:{ckpt_paths[0]}:{clip_type.name}"
        ),
    )
    monkeypatch.setattr(nodes, "load_vae_by_name", lambda name: f"vae:{name}")

    def fake_load_lora_file(path):
        calls.append(("load_lora_file", path))
        return {"name": path}, {"source": "test"}

    def fake_apply_lora(model, clip, lora, strength_model, strength_clip, lora_metadata=None):
        calls.append(("apply_lora", lora["name"], strength_model, strength_clip, lora_metadata))
        return (f"{model}+lora", f"{clip}+lora")

    monkeypatch.setattr(nodes, "load_lora_file", fake_load_lora_file)
    monkeypatch.setattr(nodes.comfy.sd, "load_lora_for_models", fake_apply_lora)

    model, clip, vae, metadata_json = nodes.SmartModelLoraLoader().load_smart_model(
        workflow_family="flux",
        primary_model="Flux\\4b\\flux-2-klein-4b.safetensors",
        clip_name="Flux\\flux2-klein-qwen3-4b.safetensors",
        vae_name="flux2-vae.safetensors",
        clip_type="auto",
        weight_dtype="default",
        allow_uncertain_loras=True,
        strict_validation=False,
        lora_1="[compatible] Flux\\4b\\exact.safetensors",
        lora_1_enabled=True,
        lora_1_strength_model=0.7,
        lora_1_strength_clip=0.3,
        lora_2="None",
        lora_2_enabled=True,
        lora_2_strength_model=1.0,
        lora_2_strength_clip=1.0,
    )

    metadata = json.loads(metadata_json)

    assert model.endswith("+lora")
    assert clip.endswith("+lora")
    assert vae == "vae:flux2-vae.safetensors"
    assert metadata["family"] == "flux"
    assert metadata["clip_type"] == "flux2"
    assert metadata["loras"][0]["name"] == "Flux\\4b\\exact.safetensors"
    assert calls == [
        ("load_lora_file", "loras/Flux\\4b\\exact.safetensors"),
        ("apply_lora", "loras/Flux\\4b\\exact.safetensors", 0.7, 0.3, {"source": "test"}),
    ]


def test_smart_loader_blocks_clearly_incompatible_lora_before_loading(monkeypatch):
    monkeypatch.setattr(
        nodes.folder_paths,
        "get_full_path_or_raise",
        lambda folder, name: f"{folder}/{name}",
    )
    monkeypatch.setattr(nodes.folder_paths, "get_folder_paths", lambda folder: [folder])
    monkeypatch.setattr(nodes, "load_vae_by_name", lambda name: f"vae:{name}")
    monkeypatch.setattr(nodes, "load_lora_file", lambda path: pytest.fail("LoRA should not load"))
    monkeypatch.setattr(
        nodes.comfy.sd,
        "load_diffusion_model",
        lambda path, model_options=None: f"model:{path}",
    )
    monkeypatch.setattr(
        nodes.comfy.sd,
        "load_clip",
        lambda ckpt_paths, embedding_directory, clip_type, model_options=None: "clip",
    )

    with pytest.raises(ValueError, match="incompatible"):
        nodes.SmartModelLoraLoader().load_smart_model(
            workflow_family="qwen",
            primary_model="Qwen\\Qwen IE 2509\\qwen_image_edit_2509_fp8_e4m3fn.safetensors",
            clip_name="Qwen\\qwen_2.5_vl_7b_fp8_scaled.safetensors",
            vae_name="qwen_image_vae.safetensors",
            clip_type="auto",
            weight_dtype="default",
            allow_uncertain_loras=True,
            strict_validation=False,
            lora_1="Flux\\4b\\wrong.safetensors",
            lora_1_enabled=True,
            lora_1_strength_model=1.0,
            lora_1_strength_clip=1.0,
        )
