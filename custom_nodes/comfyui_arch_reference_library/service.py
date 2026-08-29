"""Local managed-file service for subject and environment references."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import mimetypes
import os
from pathlib import Path
import random
import secrets
import tempfile
from typing import Any
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .store import ReferenceLibraryStore


DEFAULT_MAX_IMAGE_BYTES = 256 * 1024 * 1024
THUMBNAIL_MAX_SIZE = 320
_FORMAT_EXTENSIONS = {
    "BMP": ".bmp",
    "GIF": ".gif",
    "JPEG": ".jpg",
    "PNG": ".png",
    "TIFF": ".tiff",
    "WEBP": ".webp",
}


class ReferenceLibraryService:
    """Coordinates the ignored local catalog, managed images, and thumbnails."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.images_root = self.root / "images"
        self.thumbnails_root = self.root / "thumbnails"
        self.root.mkdir(parents=True, exist_ok=True)
        self.images_root.mkdir(parents=True, exist_ok=True)
        self.thumbnails_root.mkdir(parents=True, exist_ok=True)
        self.store = ReferenceLibraryStore(self.root / "catalog.sqlite3")

    def import_image(
        self,
        collection_id: str,
        filename: str,
        media_type: str,
        content: bytes,
        *,
        max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    ) -> dict[str, Any]:
        self.store.get_collection(collection_id)
        if not isinstance(content, bytes):
            raise ValueError("image content must be bytes")
        if len(content) > max_bytes:
            raise ValueError(f"image exceeds the {max_bytes}-byte maximum")
        if not content:
            raise ValueError("image content must not be empty")
        safe_filename = self._safe_filename(filename)
        image_format, width, height = self._inspect_still_image(content)
        extension = _FORMAT_EXTENSIONS[image_format]
        digest = sha256(content).hexdigest()
        relative_path = Path("images") / digest[:2] / f"{digest}{extension}"
        destination = self._confined(self.root, relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        created_file = False
        if not destination.exists():
            self._atomic_write(destination, content)
            created_file = True
        try:
            registered = self.store.register_image(
                collection_id,
                sha256=digest,
                relative_path=relative_path.as_posix(),
                original_filename=safe_filename,
                media_type=self._media_type(image_format, media_type),
                width=width,
                height=height,
            )
        except Exception:
            if created_file:
                destination.unlink(missing_ok=True)
            raise
        try:
            self.ensure_thumbnail(registered["image"]["id"])
        except Exception:
            # The managed original and catalog are authoritative; thumbnails are
            # deliberately regenerable and must not make an otherwise safe import fail.
            pass
        return registered

    def managed_path(self, image: dict[str, Any] | str) -> Path:
        record = self.store.get_image(image) if isinstance(image, str) else image
        return self._confined(self.root, Path(record["relative_path"]))

    def thumbnail_path(self, image_id: str) -> Path:
        image = self.store.get_image(image_id)
        path = self.thumbnails_root / image["id"][:2] / f"{image['id']}.jpg"
        return self._confined(self.thumbnails_root, path.relative_to(self.thumbnails_root))

    def ensure_thumbnail(self, image_id: str) -> Path:
        image = self.store.get_image(image_id)
        destination = self.thumbnail_path(image_id)
        if destination.is_file():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self.managed_path(image)
        try:
            with Image.open(source) as opened:
                frame = ImageOps.exif_transpose(opened).convert("RGBA")
                frame.thumbnail((THUMBNAIL_MAX_SIZE, THUMBNAIL_MAX_SIZE), Image.Resampling.LANCZOS)
                background = Image.new("RGB", frame.size, "white")
                background.paste(frame, mask=frame.getchannel("A"))
                buffer = BytesIO()
                background.save(buffer, format="JPEG", quality=88, optimize=True)
        except (OSError, UnidentifiedImageError) as exc:
            raise ValueError("managed reference is not a readable still image") from exc
        self._atomic_write(destination, buffer.getvalue())
        return destination

    def reroll(self, collection_id: str) -> dict[str, Any]:
        selection = self.store.get_selection(collection_id)
        filters = selection["filters"]
        pool = self.store.list_images(
            collection_id,
            include_all=filters["include_all"],
            include_any=filters["include_any"],
            exclude=filters["exclude"],
        )
        pinned = {
            slot["image_id"]
            for slot in selection["slots"]
            if slot["pinned"] and slot["image_id"] is not None
        }
        automatic = [slot for slot in selection["slots"] if not slot["pinned"]]
        candidates = [image["id"] for image in pool if image["id"] not in pinned]
        if len(pinned) + len(candidates) < 4 or len(candidates) < len(automatic):
            raise ValueError("the filtered pool must contain four distinct reference images")

        policy = selection["policy"]
        next_cursor = selection["cursor"]
        if policy == "seeded":
            generator = random.Random(selection["seed"] + selection["reroll_count"])
            chosen = generator.sample(candidates, len(automatic))
        elif policy == "sequential":
            start = selection["cursor"] % len(candidates)
            chosen = [candidates[(start + offset) % len(candidates)] for offset in range(len(automatic))]
            next_cursor = selection["cursor"] + len(automatic)
        else:
            chosen = secrets.SystemRandom().sample(candidates, len(automatic))

        chosen_iterator = iter(chosen)
        slots = [
            dict(slot) if slot["pinned"] else {"slot": slot["slot"], "image_id": next(chosen_iterator), "pinned": False}
            for slot in selection["slots"]
        ]
        return self.store.commit_reroll(
            collection_id,
            expected_reroll_count=selection["reroll_count"],
            slots=slots,
            cursor=next_cursor,
        )

    def unlink_image(self, collection_id: str, image_id: str) -> dict[str, Any]:
        return self.store.unlink_image(collection_id, image_id)

    def delete_managed_image(self, image_id: str) -> dict[str, Any]:
        image = self.store.get_image(image_id)
        count = self.store.membership_count(image_id)
        if count:
            raise ValueError(f"image still belongs to {count} collection(s)")
        source = self.managed_path(image)
        thumbnail = self.thumbnail_path(image_id)
        staged_source = source.with_name(f".{source.name}.deleting-{uuid4().hex}")
        staged_thumbnail = thumbnail.with_name(f".{thumbnail.name}.deleting-{uuid4().hex}")
        source_moved = False
        thumbnail_moved = False
        try:
            if source.exists():
                os.replace(source, staged_source)
                source_moved = True
            if thumbnail.exists():
                os.replace(thumbnail, staged_thumbnail)
                thumbnail_moved = True
            deleted = self.store.delete_image_record(image_id)
        except Exception:
            if source_moved and staged_source.exists():
                os.replace(staged_source, source)
            if thumbnail_moved and staged_thumbnail.exists():
                os.replace(staged_thumbnail, thumbnail)
            raise
        staged_source.unlink(missing_ok=True)
        staged_thumbnail.unlink(missing_ok=True)
        return deleted

    @staticmethod
    def _safe_filename(filename: Any) -> str:
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("image filename must be non-empty")
        name = Path(filename.replace("\\", "/")).name.strip()
        if name in {"", ".", ".."} or any(character in name for character in "\r\n\0"):
            raise ValueError("image filename is invalid")
        return name[:255]

    @staticmethod
    def _inspect_still_image(content: bytes) -> tuple[str, int, int]:
        try:
            with Image.open(BytesIO(content)) as opened:
                image_format = str(opened.format or "").upper()
                if image_format not in _FORMAT_EXTENSIONS:
                    raise ValueError("unsupported still image format")
                if bool(getattr(opened, "is_animated", False)):
                    raise ValueError("animated images are not supported; import a still frame")
                width, height = opened.size
                opened.verify()
        except ValueError:
            raise
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise ValueError("content is not a valid still image") from exc
        if width < 1 or height < 1:
            raise ValueError("content is not a valid still image")
        return image_format, int(width), int(height)

    @staticmethod
    def _media_type(image_format: str, supplied: Any) -> str:
        expected = Image.MIME.get(image_format) or mimetypes.types_map.get(_FORMAT_EXTENSIONS[image_format])
        return str(expected or supplied or "application/octet-stream")

    @staticmethod
    def _atomic_write(destination: Path, content: bytes) -> None:
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False
            ) as handle:
                temporary_name = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

    @staticmethod
    def _confined(root: Path, relative: Path) -> Path:
        resolved_root = root.resolve()
        candidate = (resolved_root / relative).resolve()
        if candidate != resolved_root and resolved_root not in candidate.parents:
            raise ValueError("managed image path escapes the reference library")
        return candidate
