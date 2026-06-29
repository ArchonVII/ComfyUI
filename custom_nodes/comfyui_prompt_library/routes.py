from __future__ import annotations

import sys
from typing import Any

from aiohttp import web

from .prompt_store import PromptStore


_ROUTES_REGISTERED = False


def get_store() -> PromptStore:
    return PromptStore()


def prompt_payload() -> dict[str, Any]:
    store = get_store()
    return {
        "path": str(store.path),
        "names": store.list_names(),
        "dropdown_names": store.dropdown_names(),
        "prompts": store.list_records(),
    }


def save_prompt_payload(data: dict[str, Any]) -> dict[str, Any]:
    store = get_store()
    record = store.save(
        data.get("name", data.get("prompt_name", "")),
        positive=data.get("positive", ""),
        negative=data.get("negative", ""),
        notes=data.get("notes", ""),
        overwrite=bool(data.get("overwrite", True)),
    )
    payload = prompt_payload()
    payload["prompt"] = record
    return payload


async def get_prompts(_request):
    return web.json_response(prompt_payload())


async def post_prompt(request):
    try:
        data = await request.json()
        payload = save_prompt_payload(data)
    except (KeyError, TypeError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(payload)


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
    routes.get("/prompt-library/prompts")(get_prompts)
    routes.post("/prompt-library/prompts")(post_prompt)
    _ROUTES_REGISTERED = True
