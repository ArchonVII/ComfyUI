from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

PRESET_STORE_VERSION = 1
PACKAGE_DIR = Path(__file__).resolve().parent
LEGACY_FAVORITES_PATH = PACKAGE_DIR / "config" / "favorites.json"


def preset_store_path() -> Path:
    return PACKAGE_DIR / "config" / "presets.json"


def normalize_preset(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = {"kind": "folder", "folder": value}
    if not isinstance(value, Mapping):
        raise ValueError("Favorite preset must be an object")

    kind = str(value.get("kind", "folder")).strip().lower()
    if kind not in {"folder", "selection"}:
        raise ValueError("Favorite kind must be 'folder' or 'selection'")

    folder = str(value.get("folder", ".")).strip() or "."
    raw_images = value.get("images", [])
    if not isinstance(raw_images, list):
        raise ValueError("Favorite images must be a list")
    images = [str(item).strip() for item in raw_images if str(item).strip()]
    if kind == "selection" and not images:
        raise ValueError("A selection favorite requires at least one image")

    return {
        "kind": kind,
        "folder": folder,
        "images": images,
        "include_subfolders": bool(value.get("include_subfolders", False)),
        "prompt_text": str(value.get("prompt_text", "")).strip(),
    }


def _read_presets(path: Path) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid favorites JSON: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("Favorites config must be an object")

    if "presets" in payload:
        version = payload.get("version")
        if version != PRESET_STORE_VERSION:
            raise ValueError(f"Unsupported favorites version: {version}")
        raw_presets = payload["presets"]
    elif "favorites" in payload:
        raw_presets = payload["favorites"]
    else:
        raw_presets = payload
    if not isinstance(raw_presets, Mapping):
        raise ValueError("Favorites must be an object")

    presets: dict[str, dict[str, object]] = {}
    for raw_name, raw_value in raw_presets.items():
        name = str(raw_name).strip()
        if name:
            presets[name] = normalize_preset(raw_value)
    return presets


def load_presets(
    store_path: str | os.PathLike[str] | None = None,
    *,
    legacy_path: str | os.PathLike[str] | None = None,
) -> dict[str, dict[str, object]]:
    store = Path(store_path) if store_path is not None else preset_store_path()
    if store.is_file():
        return _read_presets(store)
    legacy = Path(legacy_path) if legacy_path is not None else LEGACY_FAVORITES_PATH
    return _read_presets(legacy) if legacy.is_file() else {}


def _write_presets(path: Path, presets: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {
        name: normalize_preset(value)
        for name, value in sorted(presets.items(), key=lambda item: item[0].casefold())
    }
    payload = {"version": PRESET_STORE_VERSION, "presets": normalized}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def save_preset(
    name: str,
    preset: object,
    *,
    store_path: str | os.PathLike[str] | None = None,
    legacy_path: str | os.PathLike[str] | None = None,
    mode: str = "upsert",
    original_name: str | None = None,
) -> dict[str, object]:
    clean_name = str(name).strip()
    if not clean_name or clean_name == "None":
        raise ValueError("Favorite name is required and cannot be 'None'")
    store = Path(store_path) if store_path is not None else preset_store_path()
    presets = load_presets(store, legacy_path=legacy_path)
    existing_name = next(
        (current for current in presets if current.casefold() == clean_name.casefold()),
        None,
    )
    if mode not in {"upsert", "create", "update"}:
        raise ValueError("Unknown favorite save action")
    if mode == "create" and existing_name:
        raise ValueError("That favorite name already exists. Choose a new name.")
    if mode == "update" and not existing_name:
        if original_name is None:
            raise ValueError("That favorite no longer exists. Use Save as new.")
    if original_name is not None:
        if mode != "update":
            raise ValueError("Renaming requires an update action")
        original = next((current for current in presets if current.casefold() == original_name.casefold()), None)
        if original is None:
            raise ValueError("That favorite no longer exists. Use Save as new.")
        if existing_name and existing_name != original:
            raise ValueError("That favorite name already exists. Choose a new name.")
        del presets[original]
        existing_name = None
    if existing_name and existing_name != clean_name:
        del presets[existing_name]
    normalized = normalize_preset(preset)
    presets[clean_name] = normalized
    _write_presets(store, presets)
    return normalized


def delete_preset(
    name: str,
    *,
    store_path: str | os.PathLike[str] | None = None,
    legacy_path: str | os.PathLike[str] | None = None,
) -> None:
    store = Path(store_path) if store_path is not None else preset_store_path()
    presets = load_presets(store, legacy_path=legacy_path)
    existing_name = next(
        (current for current in presets if current.casefold() == str(name).casefold()),
        None,
    )
    if existing_name is None:
        raise ValueError(f"Favorite not found: {name}")
    del presets[existing_name]
    _write_presets(store, presets)


def compose_favorite_prompt(favorite_text: str, prompt: str) -> str:
    prefix = str(favorite_text or "").strip().rstrip(" ,")
    incoming = str(prompt or "").strip().lstrip(" ,")
    return ", ".join(part for part in (prefix, incoming) if part)
