from __future__ import annotations

import sys
from typing import Any

from aiohttp import web

from .watchdog import get_store


_ROUTES_REGISTERED = False


def events_payload() -> dict[str, Any]:
    return get_store().snapshot()


def clear_events_payload() -> dict[str, Any]:
    get_store().clear()
    return events_payload()


async def get_events(_request):
    return web.json_response(events_payload())


async def clear_events(_request):
    return web.json_response(clear_events_payload())


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
    routes.get("/session-watchdog/events")(get_events)
    routes.post("/session-watchdog/events/clear")(clear_events)
    _ROUTES_REGISTERED = True
