from __future__ import annotations

import csv
import base64
import json
import os
import random
import time
from io import BytesIO
from pathlib import Path
from typing import Mapping

import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

import folder_paths
import node_helpers

from .presets import (
    compose_favorite_prompt,
    load_presets,
    normalize_preset,
)


VALID_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
ARCH_CATEGORY = "arch-image/random reference"
NONE_FAVORITE = "None"
SOURCE_MODES = ["auto", "folder", "selection"]
SELECTION_POLICIES = ["random_each_queue", "seeded", "sequential"]
REFERENCE_LANES = [
    "primary_subject",
    "reference_subject",
    "environment",
    "clothes",
    "extra_subject",
    "generic",
]
PACK_LANES = [
    "primary_subject",
    "reference_subject",
    "environment",
    "clothes",
    "extra_subject_1",
    "extra_subject_2",
    "extra_subject_3",
    "extra_subject_4",
]

CONFIG_DIR = Path(__file__).resolve().parent / "config"
FAVORITES_PATH = CONFIG_DIR / "favorites.json"


def _strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _expand_path_text(path_text: str) -> str:
    return os.path.expandvars(
        os.path.expanduser(_strip_wrapping_quotes(str(path_text or "")))
    )


def _input_directory() -> Path:
    return Path(folder_paths.get_input_directory()).resolve()


def _resolve_path(path_text: str, relative_base: Path) -> Path:
    expanded = _expand_path_text(path_text)
    path = Path(expanded or ".")
    if not path.is_absolute():
        path = relative_base / path
    return path.resolve()


def load_favorites(config_path: str | os.PathLike[str] | None = None) -> dict[str, str]:
    path = Path(config_path) if config_path is not None else FAVORITES_PATH
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid favorites JSON: {path}") from exc

    if isinstance(data, Mapping) and isinstance(data.get("favorites"), Mapping):
        data = data["favorites"]
    if not isinstance(data, Mapping):
        raise ValueError(
            "Favorites config must be an object or an object with a 'favorites' object"
        )

    favorites: dict[str, str] = {}
    for name, folder in data.items():
        name_text = str(name).strip()
        folder_text = str(folder).strip()
        if name_text and folder_text:
            favorites[name_text] = folder_text
    return favorites


def favorite_options() -> list[str]:
    try:
        names = sorted(load_presets().keys(), key=str.casefold)
    except ValueError:
        names = []
    return [NONE_FAVORITE] + names


def _favorite_preset(
    favorite: str, favorites: Mapping[str, object]
) -> dict[str, object] | None:
    favorite_name = str(favorite or NONE_FAVORITE)
    if not favorite_name or favorite_name == NONE_FAVORITE:
        return None
    if favorite_name not in favorites:
        raise ValueError(f"Favorite not found: {favorite_name}")
    return normalize_preset(favorites[favorite_name])


def _resolved_source_values(
    source_mode: str,
    folder: str,
    favorite: str,
    selected_images: str,
    include_subfolders: bool,
    favorites: Mapping[str, object],
) -> tuple[str, str, str, bool]:
    preset = _favorite_preset(favorite, favorites)
    if preset is not None:
        return (
            str(preset["kind"]),
            str(preset["folder"]),
            "\n".join(str(path) for path in preset["images"]),
            bool(preset["include_subfolders"]),
        )
    normalized_mode = str(source_mode or "").strip().lower().replace(" ", "_")
    if normalized_mode in {"selected", "selected_files"}:
        normalized_mode = "selection"
    return normalized_mode, folder, selected_images, include_subfolders


def parse_selected_images(selected_images: str) -> list[str]:
    selected: list[str] = []
    for raw_line in str(selected_images or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for token in next(csv.reader([line], skipinitialspace=True)):
            clean = _strip_wrapping_quotes(token)
            if clean:
                selected.append(clean)
    return selected


def resolve_source_folder(
    folder: str,
    favorite: str,
    favorites: Mapping[str, object] | None = None,
) -> Path:
    favorites = favorites or {}
    favorite_name = str(favorite or NONE_FAVORITE)
    if favorite_name and favorite_name != NONE_FAVORITE:
        if favorite_name not in favorites:
            raise ValueError(f"Favorite not found: {favorite_name}")
        folder_text = str(normalize_preset(favorites[favorite_name])["folder"])
    else:
        folder_text = folder or "."

    folder_path = _resolve_path(folder_text, _input_directory())
    if not folder_path.is_dir():
        raise ValueError(f"Source folder not found: {folder_path}")
    return folder_path


def find_image_files(folder_path: Path, include_subfolders: bool = False) -> list[Path]:
    candidates = folder_path.rglob("*") if include_subfolders else folder_path.iterdir()
    image_files = [
        path
        for path in candidates
        if path.is_file() and path.suffix.lower() in VALID_IMAGE_EXTENSIONS
    ]
    return sorted(image_files, key=lambda path: path.as_posix().casefold())


def _resolve_selected_image_files(
    selected_images: str, base_folder: Path
) -> list[Path]:
    selected_names = parse_selected_images(selected_images)
    if not selected_names:
        raise ValueError("selected_images is required when source_mode is selection")

    resolved: list[Path] = []
    for selected_name in selected_names:
        image_path = _resolve_path(selected_name, base_folder)
        if not image_path.is_file():
            raise ValueError(f"Selected image file not found: {selected_name}")
        if image_path.suffix.lower() not in VALID_IMAGE_EXTENSIONS:
            raise ValueError(f"Selected file is not a supported image: {selected_name}")
        resolved.append(image_path)
    return resolved


def build_image_pool(
    source_mode: str,
    folder: str,
    favorite: str,
    selected_images: str,
    include_subfolders: bool,
    favorites: Mapping[str, object] | None = None,
) -> list[Path]:
    favorites = favorites or {}
    normalized_mode, folder, selected_images, include_subfolders = (
        _resolved_source_values(
            source_mode,
            folder,
            favorite,
            selected_images,
            include_subfolders,
            favorites,
        )
    )
    if normalized_mode == "auto":
        normalized_mode = (
            "selection" if parse_selected_images(selected_images) else "folder"
        )
    if normalized_mode not in SOURCE_MODES:
        raise ValueError(f"Unsupported source_mode: {source_mode}")

    source_folder = resolve_source_folder(folder, favorite, favorites)
    if normalized_mode == "selection":
        return _resolve_selected_image_files(selected_images, source_folder)

    image_files = find_image_files(source_folder, include_subfolders)
    if not image_files:
        raise ValueError(f"No supported images found in source folder: {source_folder}")
    return image_files


def _thumbnail_data_url(image_path: Path, max_size: int = 192) -> str:
    img = node_helpers.pillow(Image.open, image_path)
    try:
        frame = next(ImageSequence.Iterator(img))
        frame = node_helpers.pillow(ImageOps.exif_transpose, frame).convert("RGB")
        frame.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        frame.save(buffer, format="PNG", optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
    finally:
        img.close()


def build_reference_preview_payload(
    source_mode: str,
    folder: str,
    favorite: str,
    selected_images: str,
    selection_policy: str,
    seed: int,
    include_subfolders: bool,
    favorites: Mapping[str, object] | None = None,
    max_images: int = 8,
) -> dict[str, object]:
    favorites = favorites or {}
    image_pool = build_image_pool(
        source_mode=source_mode,
        folder=folder,
        favorite=favorite,
        selected_images=selected_images,
        include_subfolders=include_subfolders,
        favorites=favorites,
    )
    normalized_mode, resolved_folder, resolved_images, _resolved_subfolders = (
        _resolved_source_values(
            source_mode,
            folder,
            favorite,
            selected_images,
            include_subfolders,
            favorites,
        )
    )
    if normalized_mode == "auto":
        normalized_mode = (
            "selection" if parse_selected_images(resolved_images) else "folder"
        )

    if normalized_mode == "selection":
        preview_paths = image_pool[:max_images]
    elif str(selection_policy or "").strip().lower() == "seeded":
        preview_paths = [choose_image(image_pool, seed, selection_policy)]
    else:
        preview_paths = image_pool[:max_images]

    source_folder = resolve_source_folder(resolved_folder, favorite, favorites)
    return {
        "mode": normalized_mode,
        "source_folder": str(source_folder),
        "pool_size": len(image_pool),
        "preview_is_exact_next": normalized_mode == "selection"
        or str(selection_policy or "").strip().lower() == "seeded",
        "images": [
            {
                "path": str(path),
                "name": path.name,
                "thumbnail_data_url": _thumbnail_data_url(path),
            }
            for path in preview_paths
        ],
    }


def choose_image(
    image_pool: list[Path],
    seed: int,
    selection_policy: str = "random_each_queue",
) -> Path:
    if not image_pool:
        raise ValueError("No images available to choose from")

    normalized_policy = str(selection_policy or "random_each_queue").strip().lower()
    if normalized_policy == "seeded":
        normalized_seed = max(1, int(seed))
        return random.Random(normalized_seed).choice(list(image_pool))
    if normalized_policy == "sequential":
        normalized_seed = max(1, int(seed))
        return image_pool[(normalized_seed - 1) % len(image_pool)]
    if normalized_policy == "random_each_queue":
        return random.SystemRandom().choice(list(image_pool))
    raise ValueError(f"Unsupported selection_policy: {selection_policy}")


def load_image_and_mask(image_path: Path) -> tuple[torch.Tensor, torch.Tensor]:
    img = node_helpers.pillow(Image.open, image_path)
    try:
        frame = next(ImageSequence.Iterator(img))
        frame = node_helpers.pillow(ImageOps.exif_transpose, frame)

        image = frame.convert("RGB")
        image = np.array(image).astype(np.float32) / 255.0
        image_tensor = torch.from_numpy(image)[None,]

        if "A" in frame.getbands():
            mask = np.array(frame.getchannel("A")).astype(np.float32) / 255.0
            mask_tensor = 1.0 - torch.from_numpy(mask)
        else:
            mask_tensor = torch.zeros((64, 64), dtype=torch.float32)
        return image_tensor, mask_tensor.unsqueeze(0)
    finally:
        img.close()


class RandomReferenceImageSource:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lane": (REFERENCE_LANES,),
                "source_mode": (SOURCE_MODES,),
                "favorite": (favorite_options(),),
                "folder": (
                    "STRING",
                    {
                        "default": ".",
                        "multiline": False,
                        "tooltip": "Manual source folder. Relative paths resolve under ComfyUI/input; absolute paths are allowed.",
                    },
                ),
                "selected_images": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "Optional newline or comma separated filenames. Relative names resolve under the chosen folder/favorite.",
                    },
                ),
                "selection_policy": (
                    SELECTION_POLICIES,
                    {
                        "tooltip": "random_each_queue ignores seed and rerolls every prompt; seeded is reproducible for the same seed; sequential uses seed as a stable pool index and advances it after each prompt.",
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 0xFFFFFFFFFFFFFFFF,
                        "control_after_generate": True,
                        "tooltip": "Used by seeded and sequential policies. Sequential selects (seed - 1) modulo pool size.",
                    },
                ),
                "include_subfolders": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "advanced": True,
                        "tooltip": "Include nested images when source_mode is folder.",
                    },
                ),
            },
            "optional": {
                "favorite_prompt": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "Prompt text stored with the selected favorite. Save or update the favorite to persist edits.",
                    },
                ),
                "prompt": (
                    "STRING",
                    {
                        "forceInput": True,
                        "tooltip": "Incoming prompt. The selected favorite's text is prepended to this value.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "image",
        "mask",
        "selected_file",
        "lane",
        "metadata_json",
        "prompt_with_favorite",
    )
    FUNCTION = "load_random_reference"
    CATEGORY = ARCH_CATEGORY
    DESCRIPTION = "Load one random or sequential reference image from a folder, selected filename pool, or favorite source folder."

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        lane,
        source_mode,
        favorite,
        folder,
        selected_images,
        selection_policy,
        seed,
        include_subfolders,
        favorite_prompt="",
        prompt="",
    ):
        try:
            build_image_pool(
                source_mode=source_mode,
                folder=folder,
                favorite=favorite,
                selected_images=selected_images,
                include_subfolders=include_subfolders,
                favorites=load_presets(),
            )
            choose_image([Path("placeholder.png")], seed, selection_policy)
        except ValueError as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(
        cls,
        lane,
        source_mode,
        favorite,
        folder,
        selected_images,
        selection_policy,
        seed,
        include_subfolders,
        favorite_prompt="",
        prompt="",
    ):
        return time.time()

    def load_random_reference(
        self,
        lane,
        source_mode,
        favorite,
        folder,
        selected_images,
        selection_policy,
        seed,
        include_subfolders,
        favorite_prompt="",
        prompt="",
    ):
        favorites = load_presets()
        image_pool = build_image_pool(
            source_mode=source_mode,
            folder=folder,
            favorite=favorite,
            selected_images=selected_images,
            include_subfolders=include_subfolders,
            favorites=favorites,
        )
        selected_path = choose_image(image_pool, seed, selection_policy)
        image, mask = load_image_and_mask(selected_path)
        source_folder = resolve_source_folder(folder, favorite, favorites)
        preset = _favorite_preset(favorite, favorites)
        favorite_text = str(preset["prompt_text"]) if preset is not None else ""
        combined_prompt = compose_favorite_prompt(favorite_text, prompt)
        metadata = {
            "lane": lane,
            "selected_file": str(selected_path),
            "selected_name": selected_path.name,
            "source_folder": str(source_folder),
            "source_mode": source_mode,
            "favorite": favorite,
            "pool_size": len(image_pool),
            "selection_policy": selection_policy,
            "favorite_prompt_text": favorite_text,
        }
        return (
            image,
            mask,
            str(selected_path),
            lane,
            json.dumps(metadata, ensure_ascii=False),
            combined_prompt,
        )


class ReferenceLanePack:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "primary_subject": ("IMAGE",),
                "reference_subject": ("IMAGE",),
                "environment": ("IMAGE",),
                "clothes": ("IMAGE",),
                "extra_subject_1": ("IMAGE",),
                "extra_subject_2": ("IMAGE",),
                "extra_subject_3": ("IMAGE",),
                "extra_subject_4": ("IMAGE",),
            }
        }

    RETURN_TYPES = (
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "STRING",
    )
    RETURN_NAMES = (
        "primary_subject",
        "reference_subject",
        "environment",
        "clothes",
        "extra_subject_1",
        "extra_subject_2",
        "extra_subject_3",
        "extra_subject_4",
        "metadata_json",
    )
    FUNCTION = "pack"
    CATEGORY = ARCH_CATEGORY
    DESCRIPTION = "Pass named reference-image lanes through one node so downstream workflows have stable lane outputs."

    def pack(
        self,
        primary_subject=None,
        reference_subject=None,
        environment=None,
        clothes=None,
        extra_subject_1=None,
        extra_subject_2=None,
        extra_subject_3=None,
        extra_subject_4=None,
    ):
        values = {
            "primary_subject": primary_subject,
            "reference_subject": reference_subject,
            "environment": environment,
            "clothes": clothes,
            "extra_subject_1": extra_subject_1,
            "extra_subject_2": extra_subject_2,
            "extra_subject_3": extra_subject_3,
            "extra_subject_4": extra_subject_4,
        }
        metadata = {
            "present_lanes": [name for name in PACK_LANES if values[name] is not None],
        }
        return (
            primary_subject,
            reference_subject,
            environment,
            clothes,
            extra_subject_1,
            extra_subject_2,
            extra_subject_3,
            extra_subject_4,
            json.dumps(metadata, ensure_ascii=False),
        )


NODE_CLASS_MAPPINGS = {
    "RandomReferenceImageSource": RandomReferenceImageSource,
    "ReferenceLanePack": ReferenceLanePack,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RandomReferenceImageSource": "arch-Random Reference Image Source",
    "ReferenceLanePack": "arch-Reference Lane Pack",
}
