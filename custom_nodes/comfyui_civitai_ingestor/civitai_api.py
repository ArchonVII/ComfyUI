from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_API_BASE = "https://civitai.com"
RED_API_BASE = "https://civitai.red"
USER_AGENT = "ComfyUI-Civitai-Ingestor/0.1"


@dataclass(frozen=True)
class CollectionTarget:
    collection_id: int
    api_base: str
    source_url: str


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

    host = (parsed.netloc or "").lower()
    api_base = RED_API_BASE if "civitai.red" in host or "civitaired.com" in host else DEFAULT_API_BASE
    return CollectionTarget(int(match.group(1)), api_base, raw)


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


def fetch_collection_images(
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

        for item in batch:
            if isinstance(item, dict):
                images.append(item)
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

