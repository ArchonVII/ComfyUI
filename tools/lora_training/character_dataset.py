"""Local-only validation for captioned character LoRA image datasets."""

from __future__ import annotations

import hashlib
import re
import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO


IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
RECOMMENDED_IMAGE_COUNT = (10, 30)
_TRIGGER_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,63}$")
_NUMBERED_CONTROL = re.compile(r"^(?P<stem>.+)_(?P<index>[0-9]+)$")


class DatasetValidationError(ValueError):
    """Raised when a dataset cannot safely be used for training."""


class InsufficientDiskSpaceError(RuntimeError):
    """Raised when a configured storage root lacks the required free space."""


@dataclass(frozen=True)
class DatasetReport:
    root: Path
    trigger_token: str
    images: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root.as_posix(),
            "trigger_token": self.trigger_token,
            "image_count": len(self.images),
            "images": list(self.images),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ControlReport:
    root: Path
    pairs: dict[str, list[str]] = field(default_factory=dict)
    controls: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_trigger_token(token: str) -> str:
    if not isinstance(token, str) or not _TRIGGER_TOKEN.fullmatch(token):
        raise ValueError(
            "Unsafe trigger token: use 3-64 characters, start with an ASCII letter, "
            "and use only letters, digits, '_' or '-'."
        )
    return token


def _webp_dimensions(stream: BinaryIO, file_size: int) -> tuple[int, int] | None:
    stream.seek(0)
    riff_header = stream.read(12)
    if (
        len(riff_header) != 12
        or riff_header[:4] != b"RIFF"
        or riff_header[8:12] != b"WEBP"
    ):
        return None

    riff_size = int.from_bytes(riff_header[4:8], "little")
    declared_end = 8 + riff_size
    if riff_size < 4 or declared_end != file_size:
        return None

    cursor = 12
    while cursor < declared_end:
        if declared_end - cursor < 8:
            return None
        stream.seek(cursor)
        chunk_header = stream.read(8)
        if len(chunk_header) != 8:
            return None
        chunk_type = chunk_header[:4]
        chunk_size = int.from_bytes(chunk_header[4:8], "little")
        payload_start = cursor + 8
        payload_end = payload_start + chunk_size
        padded_end = payload_end + (chunk_size & 1)
        if payload_end > declared_end or padded_end > declared_end:
            return None

        if chunk_type == b"VP8X":
            if chunk_size != 10:
                return None
            payload = stream.read(10)
            if len(payload) != 10:
                return None
            width = 1 + int.from_bytes(payload[4:7], "little")
            height = 1 + int.from_bytes(payload[7:10], "little")
            return width, height

        if chunk_type == b"VP8L":
            if chunk_size < 5:
                return None
            payload = stream.read(5)
            if len(payload) != 5 or payload[0] != 0x2F:
                return None
            bits = int.from_bytes(payload[1:5], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1

        if chunk_type == b"VP8 ":
            if chunk_size < 10:
                return None
            frame_header = stream.read(10)
            frame_tag = int.from_bytes(frame_header[:3], "little")
            if (
                len(frame_header) != 10
                or frame_tag & 1
                or frame_tag >> 5 > chunk_size - 10
                or frame_header[3:6] != b"\x9d\x01\x2a"
            ):
                return None
            width = int.from_bytes(frame_header[6:8], "little") & 0x3FFF
            height = int.from_bytes(frame_header[8:10], "little") & 0x3FFF
            if width == 0 or height == 0:
                return None
            return width, height

        cursor = padded_end

    return None


def _image_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(32)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
            return struct.unpack(">II", header[16:24])

        if header.startswith(b"\xff\xd8"):
            stream.seek(2)
            while True:
                marker_start = stream.read(1)
                if not marker_start:
                    break
                if marker_start != b"\xff":
                    continue
                marker = stream.read(1)
                while marker == b"\xff":
                    marker = stream.read(1)
                if marker in {b"\xd8", b"\xd9"}:
                    continue
                length_bytes = stream.read(2)
                if len(length_bytes) != 2:
                    break
                segment_length = struct.unpack(">H", length_bytes)[0]
                if marker and marker[0] in {
                    0xC0,
                    0xC1,
                    0xC2,
                    0xC3,
                    0xC5,
                    0xC6,
                    0xC7,
                    0xC9,
                    0xCA,
                    0xCB,
                    0xCD,
                    0xCE,
                    0xCF,
                }:
                    dimensions = stream.read(5)
                    if len(dimensions) == 5:
                        height, width = struct.unpack(">HH", dimensions[1:5])
                        return width, height
                    break
                stream.seek(max(segment_length - 2, 0), 1)

        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            stream.seek(0, 2)
            dimensions = _webp_dimensions(stream, stream.tell())
            if dimensions is not None:
                return dimensions

    raise ValueError(
        f"Could not read dimensions from '{path.name}'. Re-encode it as a valid PNG, JPEG, or WebP image."
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_metadata(path: Path, relative_to: Path) -> dict[str, Any]:
    width, height = _image_dimensions(path)
    return {
        "image": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "sha256": _sha256(path),
    }


def _directory_files(root: Path, purpose: str) -> tuple[list[Path], list[str]]:
    if not root.is_dir():
        return [], [f"{purpose} directory does not exist or is not a directory: {root}"]
    files: list[Path] = []
    errors: list[str] = []
    for entry in sorted(root.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
        if entry.is_dir():
            errors.append(
                f"unsupported subdirectory '{entry.name}' in {purpose} directory; keep this dataset flat."
            )
        elif entry.is_file():
            files.append(entry)
    return files, errors


def validate_character_dataset(dataset_dir: Path | str, trigger_token: str) -> DatasetReport:
    token = validate_trigger_token(trigger_token)
    root = Path(dataset_dir).expanduser().resolve()
    files, errors = _directory_files(root, "dataset")
    warnings: list[str] = []
    images = [path for path in files if path.suffix.casefold() in IMAGE_EXTENSIONS]
    captions = [path for path in files if path.suffix.casefold() == ".txt"]

    supported = set(images) | set(captions)
    for path in files:
        if path not in supported:
            errors.append(
                f"unsupported file '{path.name}'. Keep only PNG/JPEG/WebP images and .txt sidecar captions."
            )

    stems: dict[str, list[Path]] = {}
    for image in images:
        stems.setdefault(image.stem.casefold(), []).append(image)
    for folded_stem, matches in sorted(stems.items()):
        if len(matches) > 1:
            names = ", ".join(path.name for path in matches)
            errors.append(
                f"duplicate image stem '{folded_stem}' (case-insensitive): {names}. "
                "Each target needs one unique stem."
            )

    image_stems = set(stems)
    caption_stems: dict[str, list[Path]] = {}
    for caption in captions:
        caption_stems.setdefault(caption.stem.casefold(), []).append(caption)
    for folded_stem, matches in sorted(caption_stems.items()):
        if len(matches) > 1:
            errors.append(
                f"duplicate caption stem '{folded_stem}' (case-insensitive): "
                + ", ".join(path.name for path in matches)
            )
        if folded_stem not in image_stems:
            errors.append(
                f"Orphan sidecar caption '{matches[0].name}' has no matching image. "
                "Remove it or add the target image."
            )

    metadata: list[dict[str, Any]] = []
    for folded_stem, matches in sorted(stems.items()):
        image = matches[0]
        expected_caption = root / f"{image.stem}.txt"
        caption_matches = caption_stems.get(folded_stem, [])
        if not caption_matches:
            errors.append(
                f"Missing sidecar caption '{expected_caption.name}' for '{image.name}'. "
                "Add a UTF-8 .txt file with the same stem."
            )
            continue
        caption = caption_matches[0]
        try:
            caption_text = caption.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            errors.append(f"Sidecar caption '{caption.name}' is not valid UTF-8.")
            continue
        if not caption_text:
            errors.append(f"Sidecar caption '{caption.name}' is empty; add a local training caption.")
        elif token.casefold() not in caption_text.casefold():
            warnings.append(
                f"Sidecar caption '{caption.name}' does not contain trigger token '{token}'."
            )
        try:
            item = _image_metadata(image, root)
            item["caption"] = caption.relative_to(root).as_posix()
            item["caption_sha256"] = _sha256(caption)
            metadata.append(item)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))

    image_count = len(images)
    minimum, maximum = RECOMMENDED_IMAGE_COUNT
    if image_count < minimum or image_count > maximum:
        warnings.append(
            f"Dataset has {image_count} images; 10-30 curated images are recommended for an initial character LoRA."
        )

    return DatasetReport(
        root=root,
        trigger_token=token,
        images=tuple(sorted(metadata, key=lambda item: (item["image"].casefold(), item["image"]))),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _target_images(dataset_dir: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in dataset_dir.iterdir()
            if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS
        ),
        key=lambda path: (-len(path.stem), path.name.casefold(), path.name),
    )


def validate_qwen_control_directory(
    dataset_dir: Path | str, control_dir: Path | str
) -> ControlReport:
    dataset_root = Path(dataset_dir).expanduser().resolve()
    root = Path(control_dir).expanduser().resolve()
    files, errors = _directory_files(root, "Qwen control")
    control_images = [path for path in files if path.suffix.casefold() in IMAGE_EXTENSIONS]
    for path in files:
        if path not in control_images:
            errors.append(
                f"Unsupported control file '{path.name}'. Keep only PNG/JPEG/WebP control images."
            )

    targets = _target_images(dataset_root) if dataset_root.is_dir() else []
    remaining = set(control_images)
    pairs: dict[str, list[str]] = {}
    control_metadata: dict[str, list[dict[str, Any]]] = {}

    for target in targets:
        direct: list[Path] = []
        numbered: list[tuple[int, Path]] = []
        exact_prefix = target.stem
        for control in sorted(remaining, key=lambda path: (path.name.casefold(), path.name)):
            if control.stem == exact_prefix:
                direct.append(control)
                continue
            match = _NUMBERED_CONTROL.fullmatch(control.stem)
            if match and match.group("stem") == exact_prefix:
                numbered.append((int(match.group("index")), control))

        matched = direct + [path for _, path in numbered]
        remaining.difference_update(matched)
        if not matched:
            errors.append(
                f"Target '{target.name}' has no control image. Add '{target.stem}.png' "
                f"or numbered '{target.stem}_0.png', '{target.stem}_1.png', ... in {root}."
            )
            continue
        if len(direct) > 1:
            errors.append(
                f"Target '{target.stem}' has duplicate direct control stems: "
                + ", ".join(path.name for path in direct)
            )
        if direct and numbered:
            errors.append(
                f"Target '{target.stem}' mixes direct and numbered control conventions. "
                "Use one direct file or only numeric suffixes."
            )

        indices: dict[int, list[Path]] = {}
        for index, path in numbered:
            indices.setdefault(index, []).append(path)
        for index, paths in sorted(indices.items()):
            if len(paths) > 1:
                errors.append(
                    f"Target '{target.stem}' has duplicate control index {index}: "
                    + ", ".join(path.name for path in paths)
                )

        ordered = (
            sorted(direct, key=lambda path: (path.name.casefold(), path.name))
            if direct
            else [path for _, path in sorted(numbered, key=lambda item: (item[0], item[1].name))]
        )
        pairs[target.stem] = [path.name for path in ordered]
        items: list[dict[str, Any]] = []
        for path in ordered:
            try:
                items.append(_image_metadata(path, root))
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
        control_metadata[target.stem] = items

    for path in sorted(remaining, key=lambda item: (item.name.casefold(), item.name)):
        errors.append(
            f"Control image '{path.name}' does not match any target stem in {dataset_root}. "
            "Remove it or rename it to TARGET.png / TARGET_N.png."
        )

    return ControlReport(
        root=root,
        pairs=dict(sorted(pairs.items(), key=lambda item: (item[0].casefold(), item[0]))),
        controls=dict(
            sorted(control_metadata.items(), key=lambda item: (item[0].casefold(), item[0]))
        ),
        errors=tuple(errors),
    )


def build_dataset_manifest(
    dataset_dir: Path | str,
    trigger_token: str,
    control_dir: Path | str | None = None,
) -> dict[str, Any]:
    report = validate_character_dataset(dataset_dir, trigger_token)
    errors = list(report.errors)
    controls: ControlReport | None = None
    if control_dir is not None:
        controls = validate_qwen_control_directory(report.root, control_dir)
        errors.extend(controls.errors)
    if errors:
        raise DatasetValidationError("Dataset validation failed:\n- " + "\n- ".join(errors))

    images: list[dict[str, Any]] = []
    for source in report.images:
        item = dict(source)
        if controls is not None:
            item["controls"] = controls.controls.get(Path(item["image"]).stem, [])
        images.append(item)
    result = {
        "schema_version": 1,
        "trigger_token": report.trigger_token,
        "image_count": len(images),
        "images": images,
        "warnings": list(report.warnings) + (list(controls.warnings) if controls else []),
    }
    if controls is not None:
        result["control_image_count"] = sum(len(item["controls"]) for item in images)
    return result


def check_free_space(
    path: Path | str,
    minimum_gib: float,
    available_bytes: int | None = None,
) -> float:
    target = Path(path).expanduser().resolve()
    existing = target
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    available = (
        available_bytes if available_bytes is not None else shutil.disk_usage(existing).free
    )
    available_gib = available / 1024**3
    if available_gib < minimum_gib:
        raise InsufficientDiskSpaceError(
            f"At least {minimum_gib:.1f} GiB free is required under '{target}', "
            f"but only {available_gib:.1f} GiB is available. Free disk space or choose another local root."
        )
    return available_gib
