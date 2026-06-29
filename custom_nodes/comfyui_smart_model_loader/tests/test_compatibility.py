import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_smart_model_loader.catalog import AssetProfile
from comfyui_smart_model_loader.compatibility import classify_lora_for_model


def test_compatible_when_family_and_variant_match():
    model = AssetProfile(
        name="Flux\\4b\\flux-2-klein-4b.safetensors",
        kind="diffusion_model",
        family="flux",
        variant="flux2_klein_4b",
        confidence="high",
        evidence=[],
    )
    lora = AssetProfile(
        name="Flux\\4b\\ExcellentFullNude_F2K4B_1.safetensors",
        kind="lora",
        family="flux",
        variant="flux2_klein_4b",
        confidence="high",
        evidence=[],
    )

    result = classify_lora_for_model(model, lora)

    assert result.status == "compatible"
    assert result.reason == "family and variant match"


def test_uncertain_when_lora_family_matches_but_variant_is_unknown():
    model = AssetProfile(
        name="Wan\\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        kind="diffusion_model",
        family="wan",
        variant="wan2.2_i2v_high_noise",
        confidence="high",
        evidence=[],
    )
    lora = AssetProfile(
        name="Wan\\unknown_wan_lora.safetensors",
        kind="lora",
        family="wan",
        variant=None,
        confidence="medium",
        evidence=[],
    )

    result = classify_lora_for_model(model, lora)

    assert result.status == "uncertain"
    assert result.reason == "family matches but variant is unknown"


def test_incompatible_when_families_conflict():
    model = AssetProfile(
        name="Qwen\\qwen_image_edit_2509_fp8_e4m3fn.safetensors",
        kind="diffusion_model",
        family="qwen",
        variant="qwen_image_edit_2509",
        confidence="high",
        evidence=[],
    )
    lora = AssetProfile(
        name="Flux\\4b\\ExcellentFullNude_F2K4B_1.safetensors",
        kind="lora",
        family="flux",
        variant="flux2_klein_4b",
        confidence="high",
        evidence=[],
    )

    result = classify_lora_for_model(model, lora)

    assert result.status == "incompatible"
    assert result.reason == "family mismatch: qwen != flux"
