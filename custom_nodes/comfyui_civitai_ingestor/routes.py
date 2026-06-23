from __future__ import annotations

import asyncio
import sys
from typing import Any

from aiohttp import web

from .downloader import download_manager
from .image_cache import cache_collection_images
from .ingest import ingest_collection
from .store import collection_payload, connect, get_image_context, refresh_local_status
from .workflow_draft import build_workflow_draft, save_draft_file


_ROUTES_REGISTERED = False
_INGEST_PROGRESS: dict[int, list[str]] = {}


def _token(data: dict[str, Any]) -> str | None:
    value = str(data.get("token") or "").strip()
    return value or None


async def post_ingest(request):
    try:
        data = await request.json()
        source = data.get("url") or data.get("collection")
        max_items = data.get("max_items", 50)
        max_items = None if max_items in ("", None, 0, "0") else int(max_items)
        browsing_level = data.get("browsing_level")
        browsing_level = int(browsing_level) if browsing_level not in ("", None) else None
        progress_messages: list[str] = []

        def progress(message: str) -> None:
            progress_messages.append(message)

        payload = await asyncio.to_thread(
            ingest_collection,
            source,
            token=_token(data),
            max_items=max_items,
            browsing_level=browsing_level,
            progress=progress,
        )
        collection_id = int(payload["ingest"]["collection_id"])
        _INGEST_PROGRESS[collection_id] = progress_messages[-50:]
        payload["progress"] = progress_messages
        return web.json_response(payload)
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)


async def get_collection(request):
    try:
        collection_id = int(request.match_info["collection_id"])
        conn = connect()
        try:
            payload = collection_payload(conn, collection_id)
        finally:
            conn.close()
        payload["progress"] = _INGEST_PROGRESS.get(collection_id, [])
        return web.json_response(payload)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def post_refresh_local(request):
    try:
        data = await request.json()
        collection_id = int(data["collection_id"])
        conn = connect()
        try:
            counts = refresh_local_status(conn, collection_id=collection_id)
            conn.commit()
            payload = collection_payload(conn, collection_id)
        finally:
            conn.close()
        payload["local_status"] = counts
        return web.json_response(payload)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def post_cache_images(request):
    try:
        data = await request.json()
        collection_id = int(data["collection_id"])
        force = bool(data.get("force", False))
        progress_messages: list[str] = []

        def progress(message: str) -> None:
            progress_messages.append(message)

        def cache_task():
            conn = connect()
            try:
                counts = cache_collection_images(
                    conn,
                    collection_id,
                    token=_token(data),
                    force=force,
                    progress=progress,
                )
                payload = collection_payload(conn, collection_id)
                return counts, payload
            finally:
                conn.close()

        counts, payload = await asyncio.to_thread(cache_task)
        _INGEST_PROGRESS[collection_id] = (_INGEST_PROGRESS.get(collection_id, []) + progress_messages)[-50:]
        payload["image_cache"] = counts
        payload["progress"] = _INGEST_PROGRESS.get(collection_id, [])
        return web.json_response(payload)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def get_cached_image(request):
    try:
        image_id = int(request.match_info["image_id"])
        conn = connect()
        try:
            row = conn.execute(
                "SELECT local_image_path, local_image_status FROM images WHERE image_id=?",
                (image_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None or row["local_image_status"] != "cached" or not row["local_image_path"]:
            return web.json_response({"error": "Cached image not found."}, status=404)
        return web.FileResponse(row["local_image_path"])
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def post_workflow_draft(request):
    try:
        data = await request.json()
        image_id = int(data["image_id"])
        should_save = bool(data.get("save", True))
        readonly = bool(data.get("readonly", True))
        conn = connect()
        try:
            context = get_image_context(conn, image_id)
        finally:
            conn.close()
        draft = build_workflow_draft(
            context["image"],
            context["resources"],
            context["image_resources"],
        )
        if should_save:
            path = save_draft_file(
                draft,
                collection_id=context["image"].get("collection_id"),
                readonly=readonly,
            )
            draft["saved_path"] = str(path)
        return web.json_response(draft)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def post_downloads(request):
    try:
        data = await request.json()
        file_ids = [int(value) for value in data.get("file_ids") or []]
        if not file_ids:
            return web.json_response({"error": "file_ids is required."}, status=400)
        job = download_manager.start(file_ids, token=_token(data))
        return web.json_response(job)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def get_download(request):
    job_id = request.match_info["job_id"]
    job = download_manager.get(job_id)
    if not job:
        return web.json_response({"error": "Download job not found."}, status=404)
    return web.json_response(job)


def register_routes() -> None:
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return

    server_module = sys.modules.get("server")
    prompt_server_cls = getattr(server_module, "PromptServer", None)
    prompt_server = getattr(prompt_server_cls, "instance", None)
    if prompt_server is None:
        return

    routes = prompt_server.routes
    routes.post("/civitai-ingestor/ingest")(post_ingest)
    routes.get("/civitai-ingestor/collections/{collection_id}")(get_collection)
    routes.post("/civitai-ingestor/local/refresh")(post_refresh_local)
    routes.post("/civitai-ingestor/images/cache")(post_cache_images)
    routes.get("/civitai-ingestor/images/{image_id}/cached")(get_cached_image)
    routes.post("/civitai-ingestor/workflows/draft")(post_workflow_draft)
    routes.post("/civitai-ingestor/downloads")(post_downloads)
    routes.get("/civitai-ingestor/downloads/{job_id}")(get_download)
    _ROUTES_REGISTERED = True
