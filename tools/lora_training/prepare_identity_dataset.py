"""Prepare an immutable, captioned identity dataset from an explicit selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

try:
    from .character_dataset import IMAGE_EXTENSIONS, validate_character_dataset, validate_trigger_token
except ImportError:  # Direct script execution.
    from character_dataset import (  # type: ignore[no-redef]
        IMAGE_EXTENSIONS,
        validate_character_dataset,
        validate_trigger_token,
    )


class DatasetPreparationError(ValueError):
    """Raised when a private identity dataset cannot be prepared safely."""


@dataclass(frozen=True)
class PreparationResult:
    destination: Path
    manifest: Path
    image_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_selection(path: Path) -> list[dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetPreparationError(f"Could not read selection JSON '{path}': {exc}") from exc
    images = payload.get("images") if isinstance(payload, dict) else None
    if not isinstance(images, list) or not images:
        raise DatasetPreparationError("Selection JSON must contain a non-empty 'images' list.")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(images, 1):
        if not isinstance(item, dict):
            raise DatasetPreparationError(f"Selection item {index} must be an object.")
        name = item.get("file")
        caption = item.get("caption")
        reason = item.get("reason", "selected")
        if not isinstance(name, str) or not name or any(mark in name for mark in ("/", "\\")):
            raise DatasetPreparationError(
                f"Selection item {index} must use one flat filename with no path components."
            )
        candidate = Path(name)
        if candidate.is_absolute() or candidate.name != name or name in {".", ".."}:
            raise DatasetPreparationError(
                f"Selection item {index} must use one flat filename with no path components."
            )
        folded = name.casefold()
        if folded in seen:
            raise DatasetPreparationError(f"Selection filename is duplicated: {name}")
        seen.add(folded)
        if not isinstance(caption, str) or not caption.strip():
            raise DatasetPreparationError(f"Selection item {index} needs a non-empty caption.")
        if not isinstance(reason, str) or not reason.strip():
            raise DatasetPreparationError(f"Selection item {index} needs a non-empty reason.")
        normalized.append({"file": name, "caption": caption.strip(), "reason": reason.strip()})
    return normalized


def prepare_identity_dataset(
    source_dir: Path | str,
    destination_dir: Path | str,
    selection_file: Path | str,
    trigger_token: str,
) -> PreparationResult:
    token = validate_trigger_token(trigger_token)
    source = Path(source_dir).expanduser().resolve()
    destination = Path(destination_dir).expanduser().resolve()
    selection_path = Path(selection_file).expanduser().resolve()
    if not source.is_dir():
        raise DatasetPreparationError(f"Source directory does not exist: {source}")
    if os.path.lexists(destination):
        raise DatasetPreparationError(f"Destination already exists and will not be replaced: {destination}")
    items = _load_selection(selection_path)
    token_pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])", re.I)

    validated: list[tuple[Path, dict[str, str]]] = []
    for item in items:
        image = source / item["file"]
        if not image.is_file():
            raise DatasetPreparationError(f"Selected image does not exist: {image}")
        if image.suffix.casefold() not in IMAGE_EXTENSIONS:
            raise DatasetPreparationError(f"Selected file is not a supported image: {image.name}")
        if not token_pattern.search(item["caption"]):
            raise DatasetPreparationError(
                f"Caption for '{image.name}' must include trigger token '{token}'."
            )
        validated.append((image, item))

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    temporary.mkdir()
    manifest_images: list[dict[str, object]] = []
    try:
        for index, (image, item) in enumerate(validated, 1):
            target_name = f"identity-{index:03d}{image.suffix.casefold()}"
            target = temporary / target_name
            shutil.copy2(image, target)
            (temporary / f"identity-{index:03d}.txt").write_text(
                item["caption"] + "\n", encoding="utf-8", newline="\n"
            )
            manifest_images.append(
                {
                    "source": image.name,
                    "target": target_name,
                    "reason": item["reason"],
                    "bytes": target.stat().st_size,
                    "sha256": _sha256(target),
                }
            )

        report = validate_character_dataset(temporary, token)
        if not report.ok:
            raise DatasetPreparationError("Prepared dataset is invalid: " + "; ".join(report.errors))
        manifest = {
            "source_root": str(source),
            "trigger_token": token,
            "image_count": len(manifest_images),
            "images": manifest_images,
            "warnings": list(report.warnings),
        }
        (temporary / "selection-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.rename(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    return PreparationResult(
        destination=destination,
        manifest=destination / "selection-manifest.json",
        image_count=len(manifest_images),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a private local identity dataset.")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--destination-dir", type=Path, required=True)
    parser.add_argument("--selection-file", type=Path, required=True)
    parser.add_argument("--trigger-token", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = prepare_identity_dataset(
            args.source_dir, args.destination_dir, args.selection_file, args.trigger_token
        )
    except (DatasetPreparationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Prepared {result.image_count} local identity images at: {result.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
