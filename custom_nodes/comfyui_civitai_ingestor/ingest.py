from __future__ import annotations

from typing import Any, Callable

from .civitai_api import fetch_collection_images, fetch_model_version, parse_collection_target
from .store import (
    collection_payload,
    connect,
    refresh_local_status,
    upsert_collection,
    upsert_image,
    upsert_image_resource_links,
    upsert_model_version,
)


def ingest_collection(
    source: str,
    *,
    token: str | None = None,
    max_items: int | None = 50,
    browsing_level: int | None = None,
    db_path: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    target = parse_collection_target(source)
    if progress:
        progress(f"Fetching collection {target.collection_id}.")

    images = fetch_collection_images(
        target,
        token=token,
        max_items=max_items,
        browsing_level=browsing_level,
        progress=progress,
    )

    conn = connect(db_path)
    try:
        upsert_collection(
            conn,
            collection_id=target.collection_id,
            source_url=target.source_url,
            api_base=target.api_base,
        )
        wanted_version_ids: set[int] = set()
        for image in images:
            upsert_image(conn, target.collection_id, image)
            wanted_version_ids.update(upsert_image_resource_links(conn, image))
        conn.commit()

        for index, version_id in enumerate(sorted(wanted_version_ids), start=1):
            if progress:
                progress(f"Fetching model version {index}/{len(wanted_version_ids)}: {version_id}.")
            try:
                upsert_model_version(
                    conn,
                    fetch_model_version(target.api_base, version_id, token=token),
                )
                conn.commit()
            except Exception as exc:
                if progress:
                    progress(f"Model version {version_id} failed: {exc}")

        status_counts = refresh_local_status(conn, collection_id=target.collection_id)
        conn.commit()
        payload = collection_payload(conn, target.collection_id)
        payload["ingest"] = {
            "collection_id": target.collection_id,
            "api_base": target.api_base,
            "fetched_images": len(images),
            "fetched_model_versions": len(wanted_version_ids),
            "local_status": status_counts,
        }
        return payload
    finally:
        conn.close()

