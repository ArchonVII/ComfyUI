"""Workflow nodes for local subject and environment reference collections."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path, PureWindowsPath
from typing import Any

import numpy as np
from PIL import Image, ImageOps
import torch

from .service import ReferenceLibraryService


CATEGORY = "arch-reference/library"
FOLLOW_SIDEBAR = "follow_sidebar"
PINNED = "pinned"
_SERVICE: ReferenceLibraryService | None = None


def default_library_root() -> Path:
    import folder_paths

    return Path(folder_paths.get_user_directory()) / "reference_library"


def get_service() -> ReferenceLibraryService:
    global _SERVICE
    root = default_library_root().resolve()
    if _SERVICE is None or _SERVICE.root != root:
        _SERVICE = ReferenceLibraryService(root)
    return _SERVICE


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _load_image(path: Path) -> torch.Tensor:
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            array = np.asarray(image, dtype=np.float32) / 255.0
    except (OSError, ValueError) as exc:
        raise ValueError(f"reference image is not readable: {path.name}") from exc
    return torch.from_numpy(array.copy()).unsqueeze(0)


class _ReferenceSelector:
    COLLECTION_KIND = ""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "selection_mode": (
                    [FOLLOW_SIDEBAR, PINNED],
                    {
                        "tooltip": "Follow the Reference Library sidebar, or pin stable local IDs."
                    },
                ),
                "collection_id": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Stable collection ID used only in pinned mode.",
                    },
                ),
                "profile_id": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Optional stable profile ID used only in pinned mode.",
                    },
                ),
            }
        }

    RETURN_TYPES = (
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "IMAGE",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
        "STRING",
    )
    RETURN_NAMES = (
        "reference_1",
        "reference_2",
        "reference_3",
        "reference_4",
        "reference_images",
        "positive_addition",
        "negative_addition",
        "lora_manifest_json",
        "metadata_json",
        "collection_id",
    )
    OUTPUT_IS_LIST = (
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
    )
    FUNCTION = "select"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, selection_mode, collection_id, profile_id):
        service = get_service()
        return f"{selection_mode}:{collection_id}:{profile_id}:{service.store.fingerprint()}"

    def select(self, selection_mode, collection_id="", profile_id=""):
        service = get_service()
        if selection_mode == FOLLOW_SIDEBAR:
            collection = service.store.get_active(self.COLLECTION_KIND)
            if collection is None:
                raise ValueError(
                    f"no active {self.COLLECTION_KIND} is selected in the Reference Library sidebar"
                )
            profile = service.store.get_active_profile(collection["id"])
        elif selection_mode == PINNED:
            if not collection_id:
                raise ValueError("pinned selection requires a collection ID")
            collection = service.store.get_collection(collection_id)
            if collection["kind"] != self.COLLECTION_KIND:
                raise ValueError(
                    f"pinned collection kind is {collection['kind']}, expected {self.COLLECTION_KIND}"
                )
            profile = (
                service.store.get_profile(profile_id)
                if profile_id
                else service.store.get_active_profile(collection["id"])
            )
            if profile["collection_id"] != collection["id"]:
                raise ValueError(
                    "pinned profile does not belong to the pinned collection"
                )
        else:
            raise ValueError("selection mode must be follow_sidebar or pinned")

        selection = service.store.get_selection(collection["id"])
        slots = sorted(selection["slots"], key=lambda item: item["slot"])
        if len(slots) != 4 or any(slot["image_id"] is None for slot in slots):
            raise ValueError(
                f"{collection['name']} needs four locked references; use Reroll references in the sidebar"
            )
        try:
            records = [
                service.store.get_collection_image(collection["id"], slot["image_id"])
                for slot in slots
            ]
        except KeyError as exc:
            raise ValueError(
                "one or more locked references no longer belong to this collection"
            ) from exc
        images = [_load_image(service.managed_path(record)) for record in records]
        loras = [
            {
                "name": item["name"],
                "strength_model": item["strength_model"],
                "strength_clip": item["strength_clip"],
                "enabled": item["enabled"],
                "position": item["position"],
            }
            for item in profile["loras"]
        ]
        manifest = {
            "version": 1,
            "collection": {
                "id": collection["id"],
                "kind": collection["kind"],
                "name": collection["name"],
            },
            "profile": {
                "id": profile["id"],
                "name": profile["name"],
                "model_family": profile["model_family"],
            },
            "loras": loras,
        }
        metadata = {
            "version": 1,
            "collection": collection,
            "profile": {
                "id": profile["id"],
                "name": profile["name"],
                "model_family": profile["model_family"],
            },
            "selection": selection,
            "references": [
                {
                    "slot": slot["slot"],
                    "id": record["id"],
                    "original_filename": record["original_filename"],
                    "managed_relative_path": record["relative_path"],
                    "width": record["width"],
                    "height": record["height"],
                    "tags": record["tags"],
                }
                for slot, record in zip(slots, records, strict=True)
            ],
        }
        return (
            images[0],
            images[1],
            images[2],
            images[3],
            images,
            profile["positive_prompt"],
            profile["negative_prompt"],
            _json(manifest),
            _json(metadata),
            collection["id"],
        )


class SubjectReferenceSelector(_ReferenceSelector):
    COLLECTION_KIND = "subject"
    DESCRIPTION = (
        "Load the four locked references and prompt/LoRA profile for a local subject."
    )


class EnvironmentReferenceSelector(_ReferenceSelector):
    COLLECTION_KIND = "environment"
    DESCRIPTION = "Load the four locked references and prompt/LoRA profile for a local environment."


class ApplyReferenceProfileLoras:
    """Apply an ordered selector LoRA manifest to an existing MODEL/CLIP pair."""

    def __init__(
        self,
        *,
        folder_paths_module=None,
        load_torch_file=None,
        apply_lora=None,
    ):
        if folder_paths_module is None:
            import folder_paths as folder_paths_module
        if load_torch_file is None or apply_lora is None:
            import comfy.sd
            import comfy.utils

            load_torch_file = load_torch_file or comfy.utils.load_torch_file
            apply_lora = apply_lora or comfy.sd.load_lora_for_models
        self.folder_paths = folder_paths_module
        self.load_torch_file = load_torch_file
        self.apply_lora = apply_lora
        self._cache: dict[tuple[str, int, int], tuple[Any, Any]] = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "lora_manifest_json": (
                    "STRING",
                    {
                        "default": '{"version":1,"loras":[]}',
                        "multiline": True,
                        "dynamicPrompts": False,
                    },
                ),
                "strict_missing": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Fail when an enabled LoRA is not installed locally.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING")
    RETURN_NAMES = ("model", "clip", "applied_metadata_json")
    FUNCTION = "apply"
    CATEGORY = CATEGORY
    DESCRIPTION = (
        "Apply the ordered local LoRAs emitted by a Reference Library selector."
    )

    def apply(self, model, clip, lora_manifest_json, strict_missing=True):
        if not isinstance(strict_missing, bool):
            raise ValueError("strict_missing must be boolean")
        loras = _parse_lora_manifest(lora_manifest_json)
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for item in loras:
            if not item["enabled"]:
                skipped.append({"name": item["name"], "reason": "disabled"})
                continue
            if item["strength_model"] == 0 and item["strength_clip"] == 0:
                skipped.append({"name": item["name"], "reason": "zero_strength"})
                continue
            try:
                path_text = self.folder_paths.get_full_path_or_raise(
                    "loras", item["name"]
                )
            except (FileNotFoundError, KeyError, ValueError) as exc:
                if strict_missing:
                    raise ValueError(
                        f"LoRA is not available in the local catalog: {item['name']}"
                    ) from exc
                skipped.append({"name": item["name"], "reason": "missing"})
                continue
            path = Path(path_text).resolve()
            try:
                stat = path.stat()
            except OSError as exc:
                if strict_missing:
                    raise ValueError(
                        f"LoRA is not available in the local catalog: {item['name']}"
                    ) from exc
                skipped.append({"name": item["name"], "reason": "missing"})
                continue
            cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
            loaded = self._cache.get(cache_key)
            if loaded is None:
                loaded = self.load_torch_file(
                    str(path), safe_load=True, return_metadata=True
                )
                if not isinstance(loaded, tuple) or len(loaded) != 2:
                    raise ValueError(
                        f"LoRA loader returned an invalid result for {item['name']}"
                    )
                self._cache = {
                    key: value
                    for key, value in self._cache.items()
                    if key[0] != str(path)
                }
                self._cache[cache_key] = loaded
                while len(self._cache) > 16:
                    self._cache.pop(next(iter(self._cache)))
            lora, metadata = loaded
            model, clip = self.apply_lora(
                model,
                clip,
                lora,
                item["strength_model"],
                item["strength_clip"],
                lora_metadata=metadata,
            )
            applied.append(
                {
                    "name": item["name"],
                    "strength_model": item["strength_model"],
                    "strength_clip": item["strength_clip"],
                }
            )
        return (
            model,
            clip,
            _json({"version": 1, "applied": applied, "skipped": skipped}),
        )


def _parse_lora_manifest(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        raise ValueError("LoRA manifest must be valid JSON text")
    try:
        manifest = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("LoRA manifest must be valid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("LoRA manifest must be a JSON object")
    allowed_manifest = {"version", "collection", "profile", "loras"}
    unknown_manifest = set(manifest) - allowed_manifest
    if unknown_manifest:
        raise ValueError(
            f"LoRA manifest contains unknown fields: {', '.join(sorted(unknown_manifest))}"
        )
    if manifest.get("version") != 1 or not isinstance(manifest.get("loras"), list):
        raise ValueError("LoRA manifest requires version 1 and a loras array")
    result: list[dict[str, Any]] = []
    allowed_entry = {"name", "strength_model", "strength_clip", "enabled", "position"}
    required_entry = {"name", "strength_model", "strength_clip", "enabled"}
    for raw in manifest["loras"]:
        if not isinstance(raw, dict):
            raise ValueError("LoRA manifest entry must be an object")
        unknown = set(raw) - allowed_entry
        if unknown:
            raise ValueError(
                f"LoRA manifest entry contains unknown fields: {', '.join(sorted(unknown))}"
            )
        if not required_entry <= set(raw):
            raise ValueError("LoRA manifest entry is missing required fields")
        name = raw["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("LoRA manifest name must be a non-empty relative path")
        normalized_name = name.strip().replace("\\", "/")
        windows = PureWindowsPath(normalized_name)
        if (
            normalized_name.startswith("/")
            or windows.is_absolute()
            or windows.drive
            or ".." in normalized_name.split("/")
        ):
            raise ValueError("LoRA manifest name must be a safe relative path")
        strengths: dict[str, float] = {}
        for key in ("strength_model", "strength_clip"):
            raw_strength = raw[key]
            if (
                isinstance(raw_strength, bool)
                or not isinstance(raw_strength, (int, float))
                or not isfinite(raw_strength)
            ):
                raise ValueError("LoRA manifest strengths must be finite numbers")
            if not -100 <= raw_strength <= 100:
                raise ValueError("LoRA manifest strengths must be between -100 and 100")
            strengths[key] = float(raw_strength)
        if not isinstance(raw["enabled"], bool):
            raise ValueError("LoRA manifest enabled must be boolean")
        result.append(
            {
                "name": normalized_name,
                **strengths,
                "enabled": raw["enabled"],
                "position": int(raw.get("position", len(result))),
            }
        )
    return sorted(result, key=lambda item: item["position"])
