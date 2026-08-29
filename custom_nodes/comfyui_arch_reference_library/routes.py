"""Local HTTP API used by the ComfyUI Reference Library sidebar."""

from __future__ import annotations

import sys
from typing import Any, Awaitable, Callable
from uuid import UUID

from aiohttp import web

from .nodes import get_service
from .service import DEFAULT_MAX_IMAGE_BYTES


ROOT = "/arch-reference-library"
_ROUTES_REGISTERED = False


def local_lora_names() -> list[str]:
    import folder_paths

    return sorted(folder_paths.get_filename_list("loras"), key=str.casefold)


def require_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


def require_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("ID must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError("ID must be a canonical UUID") from exc
    if str(parsed) != value.lower():
        raise ValueError("ID must be a canonical UUID")
    return str(parsed)


def _strict(
    value: Any,
    *,
    allowed: set[str],
    required: set[str] = frozenset(),
    label: str = "payload",
) -> dict[str, Any]:
    payload = require_object(value)
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(
            f"{label} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    missing = required - set(payload)
    if missing:
        raise ValueError(
            f"{label} is missing required fields: {', '.join(sorted(missing))}"
        )
    return payload


def validate_collection_create(value: Any) -> dict[str, Any]:
    return _strict(
        value,
        allowed={"kind", "name", "description"},
        required={"kind", "name"},
        label="collection payload",
    )


def validate_collection_update(value: Any) -> dict[str, Any]:
    payload = _strict(
        value, allowed={"name", "description"}, label="collection payload"
    )
    if not payload:
        raise ValueError("collection payload must change at least one field")
    return payload


def validate_active(value: Any) -> dict[str, Any]:
    payload = _strict(
        value,
        allowed={"collection_id", "profile_id"},
        required={"collection_id"},
        label="active selection payload",
    )
    payload["collection_id"] = require_id(payload["collection_id"])
    if payload.get("profile_id") is not None:
        payload["profile_id"] = require_id(payload["profile_id"])
    return payload


def validate_tag_create(value: Any) -> dict[str, Any]:
    return _strict(
        value,
        allowed={"name", "group_name"},
        required={"name"},
        label="tag payload",
    )


def validate_tag_update(value: Any) -> dict[str, Any]:
    payload = _strict(value, allowed={"name", "group_name"}, label="tag payload")
    if not payload:
        raise ValueError("tag payload must change at least one field")
    return payload


def validate_membership_tags(value: Any) -> dict[str, Any]:
    payload = _strict(
        value,
        allowed={"collection_id", "image_ids", "add_tag_ids", "remove_tag_ids"},
        required={"collection_id", "image_ids", "add_tag_ids", "remove_tag_ids"},
        label="membership tag payload",
    )
    payload["collection_id"] = require_id(payload["collection_id"])
    for key in ("image_ids", "add_tag_ids", "remove_tag_ids"):
        if not isinstance(payload[key], list):
            raise ValueError(f"{key} must be an array")
        payload[key] = [require_id(item) for item in payload[key]]
    return payload


def validate_profile_create(value: Any) -> dict[str, Any]:
    payload = _strict(
        value,
        allowed={
            "collection_id",
            "name",
            "model_family",
            "positive_prompt",
            "negative_prompt",
            "loras",
        },
        required={"collection_id", "name"},
        label="profile payload",
    )
    payload["collection_id"] = require_id(payload["collection_id"])
    return payload


def validate_profile_update(value: Any) -> dict[str, Any]:
    payload = _strict(
        value,
        allowed={"name", "model_family", "positive_prompt", "negative_prompt", "loras"},
        label="profile payload",
    )
    if not payload:
        raise ValueError("profile payload must change at least one field")
    return payload


def validate_selection(value: Any) -> dict[str, Any]:
    payload = _strict(
        value,
        allowed={"filters", "slots", "policy", "seed"},
        label="selection payload",
    )
    if not payload:
        raise ValueError("selection payload must change at least one field")
    return payload


def validate_permanent_delete(value: Any) -> dict[str, Any]:
    payload = _strict(
        value,
        allowed={"confirmation"},
        required={"confirmation"},
        label="permanent delete payload",
    )
    if payload["confirmation"] != "DELETE":
        raise ValueError("permanent deletion confirmation must be exactly DELETE")
    return payload


def _page_value(value: Any, *, label: str, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if normalized <= 0 or (maximum is not None and normalized > maximum):
        suffix = f" no greater than {maximum}" if maximum is not None else ""
        raise ValueError(f"{label} must be a positive integer{suffix}")
    return normalized


def bootstrap_payload(
    *,
    kind: str | None = None,
    collection_id: str | None = None,
    page: Any = 1,
    page_size: Any = 100,
    orphan_page: Any = 1,
    orphan_page_size: Any = 50,
) -> dict[str, Any]:
    service = get_service()
    store = service.store
    if kind is not None and kind not in {"subject", "environment"}:
        raise ValueError("kind must be subject or environment")
    normalized_page = _page_value(page, label="page")
    normalized_page_size = _page_value(page_size, label="page_size", maximum=200)
    normalized_orphan_page = _page_value(orphan_page, label="orphan_page")
    normalized_orphan_page_size = _page_value(
        orphan_page_size, label="orphan_page_size", maximum=200
    )
    active = {
        "subject": store.get_active("subject"),
        "environment": store.get_active("environment"),
    }
    selected = (
        store.get_collection(require_id(collection_id))
        if collection_id
        else active.get(kind or "subject")
    )
    detail = None
    if selected is not None:
        selection = store.get_selection(selected["id"])
        filters = selection["filters"]
        total = store.count_images(
            selected["id"],
            include_all=filters["include_all"],
            include_any=filters["include_any"],
            exclude=filters["exclude"],
        )
        total_pages = max(1, (total + normalized_page_size - 1) // normalized_page_size)
        normalized_page = min(normalized_page, total_pages)
        detail = {
            "collection": selected,
            "profiles": store.list_profiles(selected["id"]),
            "active_profile": store.get_active_profile(selected["id"]),
            "selection": selection,
            "images": store.list_images(
                selected["id"],
                include_all=filters["include_all"],
                include_any=filters["include_any"],
                exclude=filters["exclude"],
                limit=normalized_page_size,
                offset=(normalized_page - 1) * normalized_page_size,
            ),
            "pagination": {
                "page": normalized_page,
                "page_size": normalized_page_size,
                "total": total,
                "total_pages": total_pages,
            },
        }
    orphan_total = store.count_orphan_images()
    orphan_total_pages = max(
        1,
        (orphan_total + normalized_orphan_page_size - 1) // normalized_orphan_page_size,
    )
    normalized_orphan_page = min(normalized_orphan_page, orphan_total_pages)
    return {
        "version": 1,
        "data_path": str(service.root),
        "collections": store.list_collections(),
        "tags": store.list_tags(),
        "active": active,
        "loras": local_lora_names(),
        "orphans": store.list_orphan_images(
            limit=normalized_orphan_page_size,
            offset=(normalized_orphan_page - 1) * normalized_orphan_page_size,
        ),
        "orphan_pagination": {
            "page": normalized_orphan_page,
            "page_size": normalized_orphan_page_size,
            "total": orphan_total,
            "total_pages": orphan_total_pages,
        },
        "detail": detail,
    }


async def _body(request: web.Request) -> dict[str, Any]:
    try:
        return require_object(await request.json())
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc


def _validated(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> Callable[[web.Request], Awaitable[web.StreamResponse]]:
    async def wrapped(request: web.Request) -> web.StreamResponse:
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except KeyError as exc:
            raise web.HTTPNotFound(text=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc

    return wrapped


async def get_bootstrap(request: web.Request) -> web.Response:
    return web.json_response(
        bootstrap_payload(
            kind=request.query.get("kind"),
            collection_id=request.query.get("collection_id"),
            page=request.query.get("page", "1"),
            page_size=request.query.get("page_size", "100"),
            orphan_page=request.query.get("orphan_page", "1"),
            orphan_page_size=request.query.get("orphan_page_size", "50"),
        )
    )


async def post_collection(request: web.Request) -> web.Response:
    payload = validate_collection_create(await _body(request))
    collection = get_service().store.create_collection(
        payload["kind"], payload["name"], payload.get("description", "")
    )
    return web.json_response({"collection": collection})


async def patch_collection(request: web.Request) -> web.Response:
    collection_id = require_id(request.match_info["collection_id"])
    payload = validate_collection_update(await _body(request))
    return web.json_response(
        {"collection": get_service().store.update_collection(collection_id, **payload)}
    )


async def delete_collection(request: web.Request) -> web.Response:
    collection_id = require_id(request.match_info["collection_id"])
    return web.json_response(
        {"collection": get_service().store.delete_collection(collection_id)}
    )


async def put_active(request: web.Request) -> web.Response:
    kind = request.match_info["kind"]
    payload = validate_active(await _body(request))
    collection = get_service().store.set_active(kind, payload["collection_id"])
    profile = None
    if payload.get("profile_id"):
        profile = get_service().store.set_active_profile(
            payload["collection_id"], payload["profile_id"]
        )
    return web.json_response({"collection": collection, "profile": profile})


async def post_import(request: web.Request) -> web.Response:
    collection_id = require_id(request.match_info["collection_id"])
    reader = await request.multipart()
    imported: list[dict[str, Any]] = []
    async for part in reader:
        if part.name != "files" or not part.filename:
            raise ValueError("multipart import accepts only named files fields")
        content = bytearray()
        while True:
            chunk = await part.read_chunk(size=1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > DEFAULT_MAX_IMAGE_BYTES:
                raise ValueError(
                    f"image exceeds the {DEFAULT_MAX_IMAGE_BYTES}-byte maximum"
                )
        imported.append(
            get_service().import_image(
                collection_id,
                part.filename,
                part.headers.get("Content-Type", "application/octet-stream"),
                bytes(content),
            )
        )
    if not imported:
        raise ValueError("import requires at least one image file")
    return web.json_response({"imports": imported})


async def delete_membership(request: web.Request) -> web.Response:
    collection_id = require_id(request.match_info["collection_id"])
    image_id = require_id(request.match_info["image_id"])
    return web.json_response(
        {"image": get_service().unlink_image(collection_id, image_id)}
    )


async def post_tag(request: web.Request) -> web.Response:
    payload = validate_tag_create(await _body(request))
    return web.json_response({"tag": get_service().store.create_tag(**payload)})


async def patch_tag(request: web.Request) -> web.Response:
    tag_id = require_id(request.match_info["tag_id"])
    payload = validate_tag_update(await _body(request))
    return web.json_response({"tag": get_service().store.update_tag(tag_id, **payload)})


async def delete_tag(request: web.Request) -> web.Response:
    tag_id = require_id(request.match_info["tag_id"])
    return web.json_response({"tag": get_service().store.delete_tag(tag_id)})


async def patch_membership_tags(request: web.Request) -> web.Response:
    payload = validate_membership_tags(await _body(request))
    updated = get_service().store.batch_update_tags(
        payload["collection_id"],
        payload["image_ids"],
        add_tag_ids=payload["add_tag_ids"],
        remove_tag_ids=payload["remove_tag_ids"],
    )
    return web.json_response({"updated": updated})


async def post_profile(request: web.Request) -> web.Response:
    payload = validate_profile_create(await _body(request))
    collection_id = payload.pop("collection_id")
    return web.json_response(
        {"profile": get_service().store.create_profile(collection_id, **payload)}
    )


async def patch_profile(request: web.Request) -> web.Response:
    profile_id = require_id(request.match_info["profile_id"])
    payload = validate_profile_update(await _body(request))
    return web.json_response(
        {"profile": get_service().store.update_profile(profile_id, **payload)}
    )


async def delete_profile(request: web.Request) -> web.Response:
    profile_id = require_id(request.match_info["profile_id"])
    return web.json_response(
        {"profile": get_service().store.delete_profile(profile_id)}
    )


async def put_selection(request: web.Request) -> web.Response:
    collection_id = require_id(request.match_info["collection_id"])
    payload = validate_selection(await _body(request))
    return web.json_response(
        {"selection": get_service().store.set_selection(collection_id, **payload)}
    )


async def post_reroll(request: web.Request) -> web.Response:
    collection_id = require_id(request.match_info["collection_id"])
    payload = await _body(request)
    if payload:
        raise ValueError("reroll request body must be empty")
    return web.json_response({"selection": get_service().reroll(collection_id)})


async def get_thumbnail(request: web.Request) -> web.FileResponse:
    image_id = require_id(request.match_info["image_id"])
    path = get_service().ensure_thumbnail(image_id)
    return web.FileResponse(
        path,
        headers={
            "Content-Type": "image/jpeg",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


async def get_preview(request: web.Request) -> web.FileResponse:
    image_id = require_id(request.match_info["image_id"])
    image = get_service().store.get_image(image_id)
    return web.FileResponse(
        get_service().managed_path(image),
        headers={
            "Content-Type": image["media_type"],
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


async def delete_managed_image(request: web.Request) -> web.Response:
    image_id = require_id(request.match_info["image_id"])
    validate_permanent_delete(await _body(request))
    return web.json_response({"image": get_service().delete_managed_image(image_id)})


def add_routes(router: web.UrlDispatcher, prefix: str = "") -> None:
    router.add_get(f"{prefix}/bootstrap", _validated(get_bootstrap))
    router.add_post(f"{prefix}/collections", _validated(post_collection))
    router.add_patch(
        f"{prefix}/collections/{{collection_id}}", _validated(patch_collection)
    )
    router.add_delete(
        f"{prefix}/collections/{{collection_id}}", _validated(delete_collection)
    )
    router.add_put(f"{prefix}/active/{{kind}}", _validated(put_active))
    router.add_post(f"{prefix}/import/{{collection_id}}", _validated(post_import))
    router.add_delete(
        f"{prefix}/collections/{{collection_id}}/images/{{image_id}}",
        _validated(delete_membership),
    )
    router.add_post(f"{prefix}/tags", _validated(post_tag))
    router.add_patch(f"{prefix}/tags/{{tag_id}}", _validated(patch_tag))
    router.add_delete(f"{prefix}/tags/{{tag_id}}", _validated(delete_tag))
    router.add_patch(f"{prefix}/membership-tags", _validated(patch_membership_tags))
    router.add_post(f"{prefix}/profiles", _validated(post_profile))
    router.add_patch(f"{prefix}/profiles/{{profile_id}}", _validated(patch_profile))
    router.add_delete(f"{prefix}/profiles/{{profile_id}}", _validated(delete_profile))
    router.add_put(f"{prefix}/selections/{{collection_id}}", _validated(put_selection))
    router.add_post(
        f"{prefix}/selections/{{collection_id}}/reroll", _validated(post_reroll)
    )
    router.add_get(f"{prefix}/images/{{image_id}}/thumbnail", _validated(get_thumbnail))
    router.add_get(f"{prefix}/images/{{image_id}}/preview", _validated(get_preview))
    router.add_delete(f"{prefix}/images/{{image_id}}", _validated(delete_managed_image))


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
    routes.get(f"{ROOT}/bootstrap")(_validated(get_bootstrap))
    routes.post(f"{ROOT}/collections")(_validated(post_collection))
    routes.patch(f"{ROOT}/collections/{{collection_id}}")(_validated(patch_collection))
    routes.delete(f"{ROOT}/collections/{{collection_id}}")(
        _validated(delete_collection)
    )
    routes.put(f"{ROOT}/active/{{kind}}")(_validated(put_active))
    routes.post(f"{ROOT}/import/{{collection_id}}")(_validated(post_import))
    routes.delete(f"{ROOT}/collections/{{collection_id}}/images/{{image_id}}")(
        _validated(delete_membership)
    )
    routes.post(f"{ROOT}/tags")(_validated(post_tag))
    routes.patch(f"{ROOT}/tags/{{tag_id}}")(_validated(patch_tag))
    routes.delete(f"{ROOT}/tags/{{tag_id}}")(_validated(delete_tag))
    routes.patch(f"{ROOT}/membership-tags")(_validated(patch_membership_tags))
    routes.post(f"{ROOT}/profiles")(_validated(post_profile))
    routes.patch(f"{ROOT}/profiles/{{profile_id}}")(_validated(patch_profile))
    routes.delete(f"{ROOT}/profiles/{{profile_id}}")(_validated(delete_profile))
    routes.put(f"{ROOT}/selections/{{collection_id}}")(_validated(put_selection))
    routes.post(f"{ROOT}/selections/{{collection_id}}/reroll")(_validated(post_reroll))
    routes.get(f"{ROOT}/images/{{image_id}}/thumbnail")(_validated(get_thumbnail))
    routes.get(f"{ROOT}/images/{{image_id}}/preview")(_validated(get_preview))
    routes.delete(f"{ROOT}/images/{{image_id}}")(_validated(delete_managed_image))
    _ROUTES_REGISTERED = True
