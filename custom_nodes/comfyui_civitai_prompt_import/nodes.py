from __future__ import annotations

import json
from typing import Any

from .metadata import analyze_civitai_image_url


CATEGORY = "arch-metadata/civitai"


def parse_model_roots(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def default_comfy_model_roots() -> list[str]:
    try:
        import folder_paths
    except Exception:
        return []

    roots: list[str] = []
    for folder_name in ("checkpoints", "diffusion_models", "loras", "vae", "text_encoders", "embeddings"):
        try:
            roots.extend(str(path) for path in folder_paths.get_folder_paths(folder_name))
        except Exception:
            continue
    deduped: list[str] = []
    seen: set[str] = set()
    for root in roots:
        key = root.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return deduped


def resolve_model_roots(model_roots: str | list[str] | None, scan_comfy_models: bool = True) -> list[str]:
    roots = parse_model_roots(model_roots)
    if scan_comfy_models:
        roots.extend(default_comfy_model_roots())
    deduped: list[str] = []
    seen: set[str] = set()
    for root in roots:
        key = root.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(root)
    return deduped


class CivitaiPromptMetadataImport:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "url": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "https://civitai.red/images/12097475",
                    },
                ),
                "scan_comfy_models": ("BOOLEAN", {"default": True}),
                "model_roots": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "placeholder": "Optional extra model folders, one per line",
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "negative_prompt", "settings_json", "models_json", "report_json")
    FUNCTION = "analyze"
    CATEGORY = CATEGORY
    DESCRIPTION = "Extracts prompt, settings, and model metadata from a Civitai image URL."

    def analyze(self, url: str, scan_comfy_models: bool = True, model_roots: str = ""):
        roots = resolve_model_roots(model_roots, scan_comfy_models=bool(scan_comfy_models))
        report = analyze_civitai_image_url(url, roots).to_dict()
        settings_json = json.dumps(report["settings"], ensure_ascii=False, indent=2)
        models_json = json.dumps(report["resources"], ensure_ascii=False, indent=2)
        report_json = json.dumps(report, ensure_ascii=False, indent=2)
        return (
            report.get("prompt") or "",
            report.get("negative_prompt") or "",
            settings_json,
            models_json,
            report_json,
        )


NODE_CLASS_MAPPINGS = {
    "CivitaiPromptMetadataImport": CivitaiPromptMetadataImport,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CivitaiPromptMetadataImport": "arch-Civitai Prompt Metadata Import",
}
