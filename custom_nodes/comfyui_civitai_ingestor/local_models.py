from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


SUPPORTED_TARGETS = (
    "checkpoints",
    "diffusion_models",
    "loras",
    "vae",
    "text_encoders",
    "embeddings",
    "controlnet",
    "upscale_models",
)


def normalize_name(value: str | None) -> str:
    return str(value or "").replace("/", "\\").lower()


def target_folder_for_file(version: dict[str, Any], file_item: dict[str, Any]) -> str:
    model_type = str((version.get("model") or {}).get("type") or "").lower()
    file_type = str(file_item.get("type") or "").lower()
    file_name = str(file_item.get("name") or "").lower()

    if file_type == "vae" or model_type == "vae" or looks_like_vae(file_name):
        return "vae"
    if model_type in {"lora", "locon", "dora"}:
        return "loras"
    if "controlnet" in model_type:
        return "controlnet"
    if "textual inversion" in model_type or "embedding" in model_type:
        return "embeddings"
    if "upscaler" in model_type or file_type == "upscaler":
        return "upscale_models"
    if model_type == "checkpoint":
        return "checkpoints"
    if file_name.endswith((".ckpt", ".safetensors", ".pt", ".pth")):
        return "checkpoints"
    return "checkpoints"


def looks_like_vae(file_name: str) -> bool:
    stem = Path(str(file_name).replace("\\", "/")).stem.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", stem) if token]
    return "vae" in tokens


def _folder_paths_module(folder_paths_module=None):
    if folder_paths_module is not None:
        return folder_paths_module
    import folder_paths as folder_paths_module

    return folder_paths_module


def scan_folder_names(folder: str, folder_paths_module=None) -> list[dict[str, Any]]:
    fp = _folder_paths_module(folder_paths_module)
    try:
        names = fp.get_filename_list(folder)
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for name in names:
        path = None
        try:
            path = fp.get_full_path(folder, name)
        except Exception:
            path = None
        size = None
        if path and os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = None
        rows.append({"folder": folder, "name": name, "path": path, "size_bytes": size})
    return rows


def find_local_match(
    file_name: str,
    target_folder: str,
    *,
    folder_paths_module=None,
) -> dict[str, Any]:
    folders = [target_folder] if target_folder in SUPPORTED_TARGETS else []
    folders.extend(folder for folder in SUPPORTED_TARGETS if folder not in folders)
    wanted = normalize_name(file_name)

    for index, folder in enumerate(folders):
        for row in scan_folder_names(folder, folder_paths_module=folder_paths_module):
            current = normalize_name(row["name"])
            if current == wanted:
                return {
                    "status": "present" if index == 0 else "present_elsewhere",
                    "match_type": "exact_name",
                    "local_path": row.get("path"),
                    "local_folder": folder,
                    "local_name": row.get("name"),
                }

    base = normalize_name(Path(file_name).name)
    for index, folder in enumerate(folders):
        for row in scan_folder_names(folder, folder_paths_module=folder_paths_module):
            if normalize_name(Path(str(row["name"])).name) == base:
                return {
                    "status": "present" if index == 0 else "present_elsewhere",
                    "match_type": "basename",
                    "local_path": row.get("path"),
                    "local_folder": folder,
                    "local_name": row.get("name"),
                }

    return {
        "status": "missing",
        "match_type": None,
        "local_path": None,
        "local_folder": None,
        "local_name": None,
    }


def first_folder_path(folder: str, folder_paths_module=None) -> str:
    fp = _folder_paths_module(folder_paths_module)
    try:
        paths = fp.get_folder_paths(folder)
    except Exception:
        paths = []
    if paths:
        return paths[0]

    try:
        base = fp.models_dir
    except AttributeError:
        base = os.path.join(os.getcwd(), "models")
    return os.path.join(base, folder)
