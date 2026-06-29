from __future__ import annotations

import sys
from typing import Any

from aiohttp import web

from .catalog import build_catalog_payload, scan_local_profiles


_ROUTES_REGISTERED = False
_PROFILE_CACHE: list[Any] | None = None


def cached_profiles(force: bool = False):
    global _PROFILE_CACHE
    if force or _PROFILE_CACHE is None:
        _PROFILE_CACHE = scan_local_profiles()
    return _PROFILE_CACHE


def catalog_response_payload(selected_model: str | None = None, force: bool = False) -> dict[str, Any]:
    return build_catalog_payload(
        cached_profiles(force=force),
        selected_model=selected_model,
    )


async def get_catalog(request):
    selected_model = request.query.get("selected_model")
    force = request.query.get("refresh") in {"1", "true", "yes"}
    return web.json_response(catalog_response_payload(selected_model=selected_model, force=force))


async def refresh_catalog(request):
    selected_model = request.query.get("selected_model")
    return web.json_response(catalog_response_payload(selected_model=selected_model, force=True))


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
    routes.get("/smart-model-loader/catalog")(get_catalog)
    routes.post("/smart-model-loader/catalog/refresh")(refresh_catalog)
    _ROUTES_REGISTERED = True
