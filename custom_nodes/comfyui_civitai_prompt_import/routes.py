from __future__ import annotations

import asyncio
import sys
from typing import Any

from aiohttp import web

from .metadata import analyze_civitai_image_url
from .nodes import resolve_model_roots


_ROUTES_REGISTERED = False


async def analyze(request):
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        payload = {}

    url = str(payload.get("url") or "").strip()
    model_roots = payload.get("model_roots") or payload.get("modelRoots") or ""
    scan_comfy_models = bool(payload.get("scan_comfy_models", payload.get("scanComfyModels", True)))

    try:
        roots = resolve_model_roots(model_roots, scan_comfy_models=scan_comfy_models)
        report = await asyncio.to_thread(analyze_civitai_image_url, url, roots)
        return web.json_response(report.to_dict())
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=400)


def register_routes() -> None:
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return

    server_module = sys.modules.get("server")
    prompt_server_cls = getattr(server_module, "PromptServer", None)
    prompt_server = getattr(prompt_server_cls, "instance", None)
    if prompt_server is None:
        return

    prompt_server.routes.post("/civitai-prompt-import/analyze")(analyze)
    _ROUTES_REGISTERED = True
