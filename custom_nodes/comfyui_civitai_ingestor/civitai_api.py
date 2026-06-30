from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_API_BASE = "https://civitai.com"
RED_API_BASE = "https://civitai.red"
USER_AGENT = "ComfyUI-Civitai-Ingestor/0.1"
GLOBAL_FEED_CHECK_LIMIT = 10
COLLECTION_FILTER_IGNORED_ERROR = (
    "Civitai images endpoint ignored collectionId; refusing to import unfiltered global images. "
    "Civitai's public image API does not currently document collectionId filtering; paste one "
    "or more Civitai image/post URLs into the ingestor to import a curated set."
)


@dataclass(frozen=True)
class ImageQuery:
    param: str
    value: int
    source_url: str


@dataclass(frozen=True)
class CollectionTarget:
    collection_id: int
    api_base: str
    source_url: str
    kind: str = "collection"
    queries: tuple[ImageQuery, ...] = ()


def api_base_for_host(host: str) -> str:
    normalized = (host or "").lower()
    return RED_API_BASE if "civitai.red" in normalized or "civitaired.com" in normalized else DEFAULT_API_BASE


def parse_collection_target(value: str) -> CollectionTarget:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Collection URL or ID is required.")

    if raw.isdigit():
        return CollectionTarget(int(raw), DEFAULT_API_BASE, raw)

    parsed = urllib.parse.urlparse(raw)
    match = re.search(r"/collections/(\d+)", parsed.path or "")
    if not match:
        raise ValueError("Expected a Civitai collection URL like https://civitai.red/collections/8081491.")

    api_base = api_base_for_host(parsed.netloc or "")
    return CollectionTarget(int(match.group(1)), api_base, raw)


def parse_ingest_target(value: str) -> CollectionTarget:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Collection, image, or post URL is required.")

    parts = [part for part in re.split(r"[\s,]+", raw) if part]
    if len(parts) == 1:
        part = parts[0]
        if part.isdigit() or re.search(r"/collections/\d+", urllib.parse.urlparse(part).path or ""):
            return parse_collection_target(part)

    collection_targets: list[CollectionTarget] = []
    queries: list[ImageQuery] = []
    for part in parts:
        parsed = urllib.parse.urlparse(part)
        path = parsed.path or ""

        collection_match = re.search(r"/collections/(\d+)", path)
        if collection_match:
            collection_targets.append(parse_collection_target(part))
            continue

        image_match = re.search(r"/images/(\d+)", path)
        if image_match:
            queries.append(ImageQuery("imageId", int(image_match.group(1)), part))
            continue

        post_match = re.search(r"/posts/(\d+)", path)
        if post_match:
            queries.append(ImageQuery("postId", int(post_match.group(1)), part))
            continue

        raise ValueError(
            "Use one Civitai collection URL/ID, or paste one or more Civitai image/post URLs."
        )

    if collection_targets:
        if len(collection_targets) == 1 and not queries:
            return collection_targets[0]
        raise ValueError("Use one collection URL, or one or more image/post URLs; do not mix them.")

    if not queries:
        raise ValueError("No supported Civitai image or post URLs were found.")

    source_key = "\n".join(f"{query.param}:{query.value}" for query in queries)
    synthetic_id = -((zlib.crc32(source_key.encode("utf-8")) & 0x7FFFFFFF) or 1)
    return CollectionTarget(
        synthetic_id,
        DEFAULT_API_BASE,
        raw,
        kind="urls",
        queries=tuple(queries),
    )


def request_json(
    url: str,
    token: str | None = None,
    timeout: int = 45,
) -> dict[str, Any] | list[Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Civitai request failed with HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Civitai request failed: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Civitai returned non-JSON content from {url}") from exc


def build_url(api_base: str, path: str, params: dict[str, Any] | None = None) -> str:
    query = urllib.parse.urlencode(
        {key: value for key, value in (params or {}).items() if value is not None},
        doseq=True,
    )
    suffix = f"?{query}" if query else ""
    return f"{api_base.rstrip('/')}{path}{suffix}"


def image_page_signature(items: list[Any], limit: int) -> list[tuple[Any, Any, Any]]:
    signature: list[tuple[Any, Any, Any]] = []
    for item in items[:limit]:
        if isinstance(item, dict):
            signature.append((item.get("id"), item.get("postId"), item.get("url")))
    return signature


def normalize_image_item(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta")
    if (
        isinstance(meta, dict)
        and isinstance(meta.get("meta"), dict)
        and not any(key in meta for key in ("prompt", "negativePrompt", "civitaiResources"))
    ):
        normalized = dict(item)
        normalized["meta"] = meta["meta"]
        return normalized
    return item


def ensure_collection_filter_is_honored(
    target: CollectionTarget,
    batch: list[Any],
    *,
    token: str | None = None,
    browsing_level: int | None = None,
) -> None:
    check_limit = min(GLOBAL_FEED_CHECK_LIMIT, len(batch))
    if check_limit <= 0:
        return

    url = build_url(
        target.api_base,
        "/api/v1/images",
        {
            "limit": check_limit,
            "withMeta": "false",
            "browsingLevel": browsing_level,
        },
    )
    payload = request_json(url, token=token)
    if not isinstance(payload, dict):
        return

    global_batch = payload.get("items") or []
    if not isinstance(global_batch, list):
        return

    collection_signature = image_page_signature(batch, check_limit)
    global_signature = image_page_signature(global_batch, check_limit)
    if collection_signature and collection_signature == global_signature:
        raise RuntimeError(COLLECTION_FILTER_IGNORED_ERROR)


def fetch_url_images(
    target: CollectionTarget,
    *,
    token: str | None = None,
    limit: int = 100,
    max_items: int | None = None,
    browsing_level: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 200))
    images: list[dict[str, Any]] = []
    seen: set[int] = set()

    for query in target.queries:
        cursor: str | None = None
        while True:
            params = {
                query.param: query.value,
                "limit": limit,
                "withMeta": "true",
                "cursor": cursor,
                "browsingLevel": browsing_level,
            }
            url = build_url(target.api_base, "/api/v1/images", params)
            payload = request_json(url, token=token)
            if not isinstance(payload, dict):
                raise RuntimeError("Civitai images response was not an object.")

            batch = payload.get("items") or []
            if not isinstance(batch, list):
                raise RuntimeError("Civitai images response did not include an items list.")

            for item in batch:
                if not isinstance(item, dict):
                    continue
                image = normalize_image_item(item)
                image_id = image.get("id")
                if isinstance(image_id, int) and image_id in seen:
                    continue
                if isinstance(image_id, int):
                    seen.add(image_id)
                images.append(image)
                if max_items and len(images) >= max_items:
                    if progress:
                        progress(f"Fetched {len(images)} image rows.")
                    return images

            if progress:
                progress(f"Fetched {len(images)} image rows.")

            metadata = payload.get("metadata") or {}
            cursor = metadata.get("nextCursor")
            if not cursor or query.param == "imageId":
                break

    return images


def fetch_collection_images(
    target: CollectionTarget,
    *,
    token: str | None = None,
    limit: int = 100,
    max_items: int | None = None,
    browsing_level: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    if target.kind == "urls":
        return fetch_url_images(
            target,
            token=token,
            limit=limit,
            max_items=max_items,
            browsing_level=browsing_level,
            progress=progress,
        )

    limit = max(1, min(int(limit or 100), 200))
    images: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        params = {
            "collectionId": target.collection_id,
            "limit": limit,
            "withMeta": "true",
            "cursor": cursor,
            "browsingLevel": browsing_level,
        }
        url = build_url(target.api_base, "/api/v1/images", params)
        payload = request_json(url, token=token)
        if not isinstance(payload, dict):
            raise RuntimeError("Civitai images response was not an object.")

        batch = payload.get("items") or []
        if not isinstance(batch, list):
            raise RuntimeError("Civitai images response did not include an items list.")

        if cursor is None:
            ensure_collection_filter_is_honored(
                target,
                batch,
                token=token,
                browsing_level=browsing_level,
            )

        for item in batch:
            if isinstance(item, dict):
                images.append(normalize_image_item(item))
                if max_items and len(images) >= max_items:
                    if progress:
                        progress(f"Fetched {len(images)} image rows.")
                    return images

        if progress:
            progress(f"Fetched {len(images)} image rows.")

        metadata = payload.get("metadata") or {}
        cursor = metadata.get("nextCursor")
        if not cursor:
            return images


def fetch_model_version(
    api_base: str,
    model_version_id: int,
    *,
    token: str | None = None,
) -> dict[str, Any]:
    url = build_url(api_base, f"/api/v1/model-versions/{int(model_version_id)}")
    payload = request_json(url, token=token)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Model version {model_version_id} response was not an object.")
    return payload


def image_resource_refs(image: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[int] = set()
    meta = image.get("meta") if isinstance(image.get("meta"), dict) else {}

    for resource in meta.get("civitaiResources") or []:
        if not isinstance(resource, dict):
            continue
        version_id = resource.get("modelVersionId")
        if not isinstance(version_id, int):
            continue
        seen.add(version_id)
        refs.append(
            {
                "model_version_id": version_id,
                "resource_type": resource.get("type"),
                "weight": resource.get("weight"),
                "name": resource.get("modelVersionName") or resource.get("name"),
                "source": "meta.civitaiResources",
            }
        )

    for version_id in image.get("modelVersionIds") or []:
        if isinstance(version_id, int) and version_id not in seen:
            seen.add(version_id)
            refs.append(
                {
                    "model_version_id": version_id,
                    "resource_type": None,
                    "weight": None,
                    "name": None,
                    "source": "image.modelVersionIds",
                }
            )
    return refs
