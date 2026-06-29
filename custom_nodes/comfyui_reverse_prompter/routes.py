from __future__ import annotations

import asyncio
import sys
from typing import Any

from aiohttp import web

from .reverse_prompt import DEFAULT_ENDPOINT, DEFAULT_MODEL, generate_prompt_from_data_url


_ROUTES_REGISTERED = False


def generate_payload(data: dict[str, Any]) -> dict[str, Any]:
    image_data_url = data.get("image_data_url") or data.get("image")
    if not image_data_url:
        raise ValueError("image_data_url is required.")

    return generate_prompt_from_data_url(
        image_data_url=image_data_url,
        api_key=data.get("api_key", ""),
        model=data.get("model", DEFAULT_MODEL),
        endpoint=data.get("endpoint", DEFAULT_ENDPOINT),
        detail=data.get("detail", "high"),
        mode=data.get("mode", "detailed"),
        extra_context=data.get("extra_context", ""),
        timeout=int(data.get("timeout_seconds", 90) or 90),
        fallback_on_error=bool(data.get("fallback_on_error", True)),
        use_env_api_key=bool(data.get("use_env_api_key", False)),
    )


async def post_generate(request):
    try:
        data = await request.json()
        payload = await asyncio.to_thread(generate_payload, data)
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)
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

    prompt_server.routes.post("/reverse-prompter/generate")(post_generate)
    _ROUTES_REGISTERED = True
