from __future__ import annotations

from dataclasses import dataclass

from .catalog import AssetProfile


@dataclass(frozen=True)
class CompatibilityResult:
    status: str
    reason: str


def classify_lora_for_model(model: AssetProfile, lora: AssetProfile) -> CompatibilityResult:
    if model.family is None or lora.family is None:
        return CompatibilityResult("uncertain", "missing family metadata")

    if model.family != lora.family:
        return CompatibilityResult(
            "incompatible",
            f"family mismatch: {model.family} != {lora.family}",
        )

    if model.variant and lora.variant and model.variant == lora.variant:
        return CompatibilityResult("compatible", "family and variant match")

    if lora.variant is None:
        return CompatibilityResult("uncertain", "family matches but variant is unknown")

    if model.variant is None:
        return CompatibilityResult("uncertain", "family matches but model variant is unknown")

    return CompatibilityResult("uncertain", "family matches but variants differ")
