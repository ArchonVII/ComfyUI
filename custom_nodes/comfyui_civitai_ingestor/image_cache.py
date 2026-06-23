from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .civitai_api import USER_AGENT
from .store import utc_now


ImageFetcher = Callable[[str, str | None], tuple[bytes, str | None]]


def default_cache_root() -> Path:
    import folder_paths

    return Path(folder_paths.get_system_user_directory("civitai_ingestor")) / "images"


def fetch_image_bytes(url: str, token: str | None = None) -> tuple[bytes, str | None]:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read(), response.headers.get("Content-Type")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Image download failed: {exc.reason}") from exc


def extension_for(url: str, content_type: str | None) -> str:
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    by_type = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    if normalized_type in by_type:
        return by_type[normalized_type]

    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".img"


def cache_collection_images(
    conn,
    collection_id: int,
    *,
    cache_root: str | Path | None = None,
    token: str | None = None,
    fetcher: ImageFetcher = fetch_image_bytes,
    force: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    root = Path(cache_root) if cache_root is not None else default_cache_root()
    rows = conn.execute(
        """
        SELECT image_id, url, local_image_path, local_image_status
        FROM images
        WHERE collection_id=?
        ORDER BY image_id
        """,
        (collection_id,),
    ).fetchall()

    counts = {"cached": 0, "failed": 0, "skipped": 0}
    for row in rows:
        image_id = int(row["image_id"])
        existing = Path(row["local_image_path"]) if row["local_image_path"] else None
        if not force and row["local_image_status"] == "cached" and existing and existing.exists():
            counts["skipped"] += 1
            continue
        if not row["url"]:
            _mark_failed(conn, image_id, "Image row has no URL.")
            counts["failed"] += 1
            continue

        try:
            content, content_type = fetcher(row["url"], token)
            extension = extension_for(row["url"], content_type)
            target_dir = root / f"collection-{int(collection_id)}"
            target_path = target_dir / f"image-{image_id}{extension}"
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = target_path.with_suffix(target_path.suffix + ".part")
            tmp_path.write_bytes(content)
            tmp_path.replace(target_path)
            conn.execute(
                """
                UPDATE images SET
                    local_image_path=?,
                    local_image_status='cached',
                    local_image_error=NULL,
                    local_image_cached_at=?
                WHERE image_id=?
                """,
                (str(target_path), utc_now(), image_id),
            )
            counts["cached"] += 1
            if progress:
                progress(f"Cached image {image_id}.")
        except Exception as exc:
            _mark_failed(conn, image_id, str(exc))
            counts["failed"] += 1
            if progress:
                progress(f"Image {image_id} failed: {exc}")
        conn.commit()
    return counts


def _mark_failed(conn, image_id: int, error: str) -> None:
    conn.execute(
        """
        UPDATE images SET
            local_image_status='failed',
            local_image_error=?,
            local_image_cached_at=?
        WHERE image_id=?
        """,
        (error[:500], utc_now(), image_id),
    )

