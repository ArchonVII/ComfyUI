import sys
from pathlib import Path

import torch
from safetensors.torch import save_file


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_smart_model_loader.catalog import (
    build_catalog_payload,
    profile_from_file,
)


def test_profile_from_file_reads_safetensors_metadata_and_keys(tmp_path):
    lora_path = tmp_path / "ExcellentFullNude_F2K4B_1.safetensors"
    save_file(
        {
            "diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight": torch.zeros(1, 1),
            "diffusion_model.double_blocks.0.img_attn.qkv.lora_B.weight": torch.zeros(1, 1),
        },
        lora_path,
        metadata={"ss_base_model_version": "flux2_klein_4b"},
    )

    profile = profile_from_file(
        name="Flux\\4b\\ExcellentFullNude_F2K4B_1.safetensors",
        kind="lora",
        path=lora_path,
    )

    assert profile.family == "flux"
    assert profile.variant == "flux2_klein_4b"
    assert "metadata:ss_base_model_version" in profile.evidence


def test_profile_from_file_falls_back_when_safetensors_header_is_invalid(tmp_path):
    broken_path = tmp_path / "qwen_image_edit_2509_fp8_e4m3fn.safetensors"
    broken_path.write_bytes(b"")

    profile = profile_from_file(
        name="Qwen\\Qwen IE 2509\\qwen_image_edit_2509_fp8_e4m3fn.safetensors",
        kind="diffusion_model",
        path=broken_path,
    )

    assert profile.family == "qwen"
    assert "header:error" in profile.evidence


def test_build_catalog_payload_labels_compatible_and_uncertain_loras():
    payload = build_catalog_payload(
        profiles=[
            profile_from_file(
                name="Flux\\4b\\flux-2-klein-4b.safetensors",
                kind="diffusion_model",
                path=None,
                metadata={},
                tensor_keys=["double_blocks.0.img_attn.qkv.weight"],
            ),
            profile_from_file(
                name="Flux\\4b\\exact.safetensors",
                kind="lora",
                path=None,
                metadata={"ss_base_model_version": "flux2_klein_4b"},
                tensor_keys=[],
            ),
            profile_from_file(
                name="Flux\\unknown.safetensors",
                kind="lora",
                path=None,
                metadata={},
                tensor_keys=["diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight"],
            ),
            profile_from_file(
                name="Qwen\\wrong.safetensors",
                kind="lora",
                path=None,
                metadata={"ss_base_model_version": "qwen_image"},
                tensor_keys=[],
            ),
        ],
        selected_model="Flux\\4b\\flux-2-klein-4b.safetensors",
    )

    lora_options = payload["filtered"]["loras"]

    assert [item["status"] for item in lora_options] == ["compatible", "uncertain"]
    assert lora_options[0]["label"].startswith("[compatible] ")
    assert lora_options[1]["label"].startswith("[uncertain] ")
    assert all("wrong.safetensors" not in item["name"] for item in lora_options)


def test_build_catalog_payload_filters_text_encoders_and_vaes_by_family():
    payload = build_catalog_payload(
        profiles=[
            profile_from_file(
                name="Qwen\\Qwen IE 2509\\qwen_image_edit_2509_fp8_e4m3fn.safetensors",
                kind="diffusion_model",
                path=None,
                metadata={},
                tensor_keys=["model.diffusion_model.transformer_blocks.0.attn.to_q.weight"],
            ),
            profile_from_file(
                name="Qwen\\qwen_2.5_vl_7b_fp8_scaled.safetensors",
                kind="text_encoder",
                path=None,
                metadata={},
                tensor_keys=[],
            ),
            profile_from_file(
                name="Flux\\flux2-klein-qwen3-4b.safetensors",
                kind="text_encoder",
                path=None,
                metadata={},
                tensor_keys=[],
            ),
            profile_from_file(
                name="qwen_image_vae.safetensors",
                kind="vae",
                path=None,
                metadata={},
                tensor_keys=[],
            ),
            profile_from_file(
                name="flux2-vae.safetensors",
                kind="vae",
                path=None,
                metadata={},
                tensor_keys=[],
            ),
        ],
        selected_model="Qwen\\Qwen IE 2509\\qwen_image_edit_2509_fp8_e4m3fn.safetensors",
    )

    assert [item["name"] for item in payload["filtered"]["text_encoders"]] == [
        "Qwen\\qwen_2.5_vl_7b_fp8_scaled.safetensors"
    ]
    assert [item["name"] for item in payload["filtered"]["vae"]] == [
        "qwen_image_vae.safetensors"
    ]
