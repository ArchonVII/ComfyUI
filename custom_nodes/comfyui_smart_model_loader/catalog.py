from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from safetensors import safe_open


DEFAULT_OVERRIDE_CATALOG: dict[str, Any] = {
    "version": 1,
    "diffusion_models": {},
    "checkpoints": {},
    "text_encoders": {},
    "vae": {},
    "loras": {},
}


@dataclass(frozen=True)
class AssetProfile:
    name: str
    kind: str
    family: str | None
    variant: str | None
    confidence: str
    evidence: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "family": self.family,
            "variant": self.variant,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


def _fold(value: str | None) -> str:
    return str(value or "").replace("/", "\\").lower()


def _family_from_text(value: str) -> str | None:
    folded = _fold(value)
    if "flux" in folded:
        return "flux"
    if "qwen" in folded:
        return "qwen"
    if "wan" in folded:
        return "wan"
    if "sdxl" in folded or "stable-diffusion-xl" in folded or "sd_xl" in folded:
        return "sdxl"
    return None


def _variant_from_text(family: str | None, value: str) -> str | None:
    folded = _fold(value)

    if family == "flux":
        if "flux2_klein_4b" in folded:
            return "flux2_klein_4b"
        if "flux2_klein_9b" in folded:
            return "flux2_klein_9b"
        if ("flux-2" in folded or "flux2" in folded) and "klein" in folded and "4b" in folded:
            return "flux2_klein_4b"
        if ("flux-2" in folded or "flux2" in folded) and "klein" in folded and "9b" in folded:
            return "flux2_klein_9b"
        if "flux1" in folded or "flux.1" in folded:
            return "flux1"
        if "flux2" in folded or "flux-2" in folded:
            return "flux2"

    if family == "qwen":
        if "2511" in folded:
            return "qwen_image_edit_2511"
        if "2509" in folded:
            return "qwen_image_edit_2509"
        if "qwen_image_edit" in folded or "qwen image edit" in folded:
            return "qwen_image_edit"
        if "qwen_image" in folded or "qwen-image" in folded or "qwen image" in folded:
            return "qwen_image"

    if family == "wan":
        version = None
        if "wan2.2" in folded or "wan22" in folded or "wan_2.2" in folded:
            version = "wan2.2"
        elif "wan2.1" in folded or "wan21" in folded or "wan_2.1" in folded:
            version = "wan2.1"
        if version:
            mode = "_i2v" if "i2v" in folded else "_t2v" if "t2v" in folded else ""
            noise = ""
            if "high_noise" in folded or "high-noise" in folded or "high noise" in folded:
                noise = "_high_noise"
            elif "low_noise" in folded or "low-noise" in folded or "low noise" in folded:
                noise = "_low_noise"
            return f"{version}{mode}{noise}"

    if family == "sdxl":
        if "refiner" in folded:
            return "sdxl_refiner"
        return "sdxl_base"

    return None


def infer_asset_profile(
    name: str,
    kind: str,
    metadata: dict[str, Any] | None = None,
    tensor_keys: Iterable[str] | None = None,
) -> AssetProfile:
    metadata = metadata or {}
    keys = list(tensor_keys or [])
    evidence: list[str] = []
    family: str | None = None
    variant: str | None = None
    confidence = "low"

    base_model_version = metadata.get("ss_base_model_version")
    if base_model_version:
        family = _family_from_text(str(base_model_version))
        variant = _variant_from_text(family, str(base_model_version))
        confidence = "high" if family else "medium"
        evidence.append("metadata:ss_base_model_version")

    architecture = metadata.get("modelspec.architecture")
    if family is None and architecture:
        family = _family_from_text(str(architecture))
        variant = _variant_from_text(family, str(architecture))
        confidence = "high" if family else "medium"
        evidence.append("metadata:modelspec.architecture")

    folded_keys = [_fold(key) for key in keys]
    key_blob = "\n".join(folded_keys[:200])

    if family is None:
        if "double_blocks." in key_blob or "single_blocks." in key_blob:
            family = "flux"
            confidence = "high"
            evidence.append("keys:flux_blocks")
        elif "transformer_blocks." in key_blob:
            family = "qwen"
            confidence = "high"
            evidence.append("keys:qwen_transformer_blocks")
        elif "blocks.0.cross_attn" in key_blob or ".cross_attn." in key_blob:
            family = "wan"
            confidence = "high"
            evidence.append("keys:wan_cross_attention")
        elif "conditioner.embedders." in key_blob:
            family = "sdxl"
            confidence = "high"
            evidence.append("keys:sdxl_conditioner")

    if family is None:
        family = _family_from_text(name)
        if family:
            confidence = "medium"
            evidence.append("path:family")

    if variant is None:
        variant = _variant_from_text(family, name)

    if family and not evidence:
        evidence.append("inference:family")

    return AssetProfile(
        name=name,
        kind=kind,
        family=family,
        variant=variant,
        confidence=confidence,
        evidence=evidence,
    )


def _read_safetensors_header(path: Path) -> tuple[dict[str, Any], list[str]]:
    with safe_open(str(path), framework="pt", device="cpu") as handle:
        return handle.metadata() or {}, list(handle.keys())


def profile_from_file(
    name: str,
    kind: str,
    path: str | Path | None,
    metadata: dict[str, Any] | None = None,
    tensor_keys: Iterable[str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> AssetProfile:
    if metadata is None:
        metadata = {}
    if tensor_keys is None:
        tensor_keys = []

    path_obj = Path(path) if path is not None else None
    header_error = False
    if path_obj is not None and path_obj.suffix.lower() == ".safetensors" and path_obj.is_file():
        try:
            metadata, tensor_keys = _read_safetensors_header(path_obj)
        except Exception:
            metadata, tensor_keys = {}, []
            header_error = True

    profile = infer_asset_profile(
        name=name,
        kind=kind,
        metadata=metadata,
        tensor_keys=tensor_keys,
    )
    if header_error:
        profile = replace(profile, evidence=[*profile.evidence, "header:error"])
    return apply_overrides(profile, overrides)


def _profiles_by_kind(profiles: Iterable[AssetProfile]) -> dict[str, list[AssetProfile]]:
    grouped: dict[str, list[AssetProfile]] = {}
    for profile in profiles:
        grouped.setdefault(profile.kind, []).append(profile)
    return grouped


def _asset_status_for_model(model: AssetProfile, asset: AssetProfile) -> tuple[str, str]:
    if model.family is None or asset.family is None:
        return "uncertain", "missing family metadata"
    if model.family != asset.family:
        return "incompatible", f"family mismatch: {model.family} != {asset.family}"
    if model.variant and asset.variant and model.variant == asset.variant:
        return "compatible", "family and variant match"
    return "compatible", "family match"


def _filtered_assets(
    selected_profile: AssetProfile | None,
    assets: Iterable[AssetProfile],
) -> list[dict[str, Any]]:
    if selected_profile is None:
        return []

    filtered = []
    for asset in assets:
        status, reason = _asset_status_for_model(selected_profile, asset)
        if status == "incompatible":
            continue
        item = asset.as_dict()
        item["status"] = status
        item["reason"] = reason
        item["label"] = f"[{status}] {asset.name}"
        filtered.append(item)
    filtered.sort(key=lambda item: (0 if item["status"] == "compatible" else 1, item["name"].lower()))
    return filtered


def build_catalog_payload(
    profiles: Iterable[AssetProfile],
    selected_model: str | None = None,
) -> dict[str, Any]:
    from .compatibility import classify_lora_for_model

    profile_list = list(profiles)
    grouped = _profiles_by_kind(profile_list)
    selected_profile = next(
        (
            profile
            for profile in profile_list
            if profile.name == selected_model and profile.kind in {"diffusion_model", "checkpoint"}
        ),
        None,
    )

    filtered_loras: list[dict[str, Any]] = []
    if selected_profile is not None:
        for lora in grouped.get("lora", []):
            compatibility = classify_lora_for_model(selected_profile, lora)
            if compatibility.status == "incompatible":
                continue
            item = lora.as_dict()
            item["status"] = compatibility.status
            item["reason"] = compatibility.reason
            item["label"] = f"[{compatibility.status}] {lora.name}"
            filtered_loras.append(item)

    filtered_loras.sort(key=lambda item: (0 if item["status"] == "compatible" else 1, item["name"].lower()))

    return {
        "profiles": [profile.as_dict() for profile in profile_list],
        "by_kind": {
            kind: [profile.as_dict() for profile in items]
            for kind, items in grouped.items()
        },
        "selected_model": selected_profile.as_dict() if selected_profile else None,
        "filtered": {
            "text_encoders": _filtered_assets(selected_profile, grouped.get("text_encoder", [])),
            "vae": _filtered_assets(selected_profile, grouped.get("vae", [])),
            "loras": filtered_loras,
        },
    }


SCAN_FOLDERS: tuple[tuple[str, str], ...] = (
    ("diffusion_models", "diffusion_model"),
    ("checkpoints", "checkpoint"),
    ("text_encoders", "text_encoder"),
    ("vae", "vae"),
    ("loras", "lora"),
)


def scan_local_profiles(
    folder_paths_module=None,
    overrides: dict[str, Any] | None = None,
) -> list[AssetProfile]:
    if overrides is None:
        overrides = load_override_catalog()
    if folder_paths_module is None:
        import folder_paths as folder_paths_module

    profiles: list[AssetProfile] = []
    for folder_name, kind in SCAN_FOLDERS:
        try:
            names = folder_paths_module.get_filename_list(folder_name)
        except Exception:
            names = []
        for name in names:
            path = None
            get_full_path = getattr(folder_paths_module, "get_full_path", None)
            if get_full_path is not None:
                try:
                    path = get_full_path(folder_name, name)
                except Exception:
                    path = None
            profiles.append(
                profile_from_file(
                    name=name,
                    kind=kind,
                    path=path,
                    overrides=overrides,
                )
            )
    return profiles


def apply_overrides(profile: AssetProfile, overrides: dict[str, Any] | None) -> AssetProfile:
    overrides = overrides or {}
    bucket = f"{profile.kind}s"
    data = overrides.get(bucket, {}).get(profile.name)
    if not data:
        return profile

    evidence = list(profile.evidence)
    evidence.append(f"override:{bucket}")
    return replace(
        profile,
        family=data.get("family", profile.family),
        variant=data.get("variant", profile.variant),
        confidence=data.get("confidence", profile.confidence),
        evidence=evidence,
    )


def load_override_catalog(path: str | Path | None = None) -> dict[str, Any]:
    catalog = copy.deepcopy(DEFAULT_OVERRIDE_CATALOG)
    if path is None:
        path = Path(__file__).with_name("smart_model_catalog.json")
    path = Path(path)
    if not path.is_file():
        return catalog

    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        return catalog

    for key, value in loaded.items():
        catalog[key] = value
    for key, value in DEFAULT_OVERRIDE_CATALOG.items():
        if key not in catalog:
            catalog[key] = copy.deepcopy(value)
    return catalog
