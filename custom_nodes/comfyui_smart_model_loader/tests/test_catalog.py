import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_smart_model_loader.catalog import apply_overrides, infer_asset_profile


def test_infers_flux_lora_variant_from_metadata():
    profile = infer_asset_profile(
        name="Flux\\4b\\ExcellentFullNude_F2K4B_1.safetensors",
        kind="lora",
        metadata={"ss_base_model_version": "flux2_klein_4b"},
        tensor_keys=[
            "diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight",
            "diffusion_model.double_blocks.0.img_attn.qkv.lora_B.weight",
        ],
    )

    assert profile.family == "flux"
    assert profile.variant == "flux2_klein_4b"
    assert profile.confidence == "high"
    assert "metadata:ss_base_model_version" in profile.evidence


def test_infers_qwen_lora_from_tensor_keys_without_metadata():
    profile = infer_asset_profile(
        name="Qwen\\Perky_tits-qwen.safetensors",
        kind="lora",
        metadata={},
        tensor_keys=[
            "diffusion_model.transformer_blocks.0.attn.to_q.lora_A.weight",
            "diffusion_model.transformer_blocks.0.attn.to_q.lora_B.weight",
        ],
    )

    assert profile.family == "qwen"
    assert profile.confidence == "high"
    assert "keys:qwen_transformer_blocks" in profile.evidence


def test_infers_wan_model_from_tensor_keys_without_metadata():
    profile = infer_asset_profile(
        name="Wan\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        kind="diffusion_model",
        metadata={},
        tensor_keys=[
            "blocks.0.cross_attn.k.weight",
            "blocks.0.cross_attn.o.weight",
        ],
    )

    assert profile.family == "wan"
    assert profile.variant == "wan2.2_i2v_high_noise"
    assert profile.confidence == "high"


def test_manual_overrides_win_over_inference():
    profile = infer_asset_profile(
        name="Qwen\\misleading_flux_name.safetensors",
        kind="lora",
        metadata={"ss_base_model_version": "flux2_klein_4b"},
        tensor_keys=["diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight"],
    )

    overridden = apply_overrides(
        profile,
        {
            "loras": {
                "Qwen\\misleading_flux_name.safetensors": {
                    "family": "qwen",
                    "variant": "qwen_image",
                    "confidence": "manual",
                }
            }
        },
    )

    assert overridden.family == "qwen"
    assert overridden.variant == "qwen_image"
    assert overridden.confidence == "manual"
    assert "override:loras" in overridden.evidence
