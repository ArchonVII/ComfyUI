"""Lazy local HTTP routes for the identity experiment service."""

from __future__ import annotations

import sys
from pathlib import PureWindowsPath
from typing import Any, Mapping
from uuid import UUID

from aiohttp import web

from .experiment_planner import VALID_MODES, VALID_STAGES
from .experiment_service import ExperimentService
from .experiment_store import RUN_STATES


_ROUTES_REGISTERED = False
_SERVICE: ExperimentService | None = None


def get_service() -> ExperimentService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ExperimentService()
    return _SERVICE


def require_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


def require_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("ID must be a UUID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("ID must be a UUID") from exc
    if str(parsed) != value.lower():
        raise ValueError("ID must be a canonical UUID")
    return value


def require_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("output path must be relative")
    normalized = value.replace("\\", "/")
    windows = PureWindowsPath(normalized)
    if normalized.startswith("/") or windows.is_absolute() or windows.drive or ".." in normalized.split("/"):
        raise ValueError("output path must be relative")
    return normalized


def validate_create_payload(value: Any) -> dict[str, Any]:
    payload = require_object(value)
    allowed = {"name", "mode", "checkpoints", "seeds", "loras", "stages", "refine_settings", "settings", "workflow"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
    if not isinstance(payload.get("name"), str) or not payload["name"].strip():
        raise ValueError("name must be a non-empty string")
    if payload.get("mode") not in VALID_MODES:
        raise ValueError("invalid mode")
    for field in ("checkpoints", "seeds"):
        if not isinstance(payload.get(field), list) or not payload[field]:
            raise ValueError(f"{field} must be a non-empty array")
    if "loras" in payload and not isinstance(payload["loras"], list):
        raise ValueError("loras must be an array")
    if "stages" in payload:
        if not isinstance(payload["stages"], list) or any(stage not in VALID_STAGES for stage in payload["stages"]):
            raise ValueError("invalid stage")
    return payload


def validate_review_payload(value: Any) -> dict[str, Any]:
    payload = require_object(value)
    allowed = {"rating", "favorite", "notes"}
    if not payload or set(payload) - allowed:
        raise ValueError("review payload contains an invalid state or field")
    if "rating" in payload and payload["rating"] is not None and (isinstance(payload["rating"], bool) or not isinstance(payload["rating"], int) or not 1 <= payload["rating"] <= 5):
        raise ValueError("rating must be 1 through 5 or null")
    if "favorite" in payload and not isinstance(payload["favorite"], bool):
        raise ValueError("favorite must be boolean")
    if "notes" in payload and not isinstance(payload["notes"], str):
        raise ValueError("notes must be string")
    return payload


async def _body(request) -> dict[str, Any]:
    try:
        return require_object(await request.json())
    except (ValueError, TypeError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc


def _response(call):
    try:
        return web.json_response(call())
    except KeyError as exc:
        raise web.HTTPNotFound(text=str(exc)) from exc
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc


def _validated(handler):
    async def wrapped(request):
        try:
            return await handler(request)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc

    return wrapped


async def get_catalog(_request):
    return _response(lambda: get_service().catalogs())


async def get_experiments(request):
    include_archived = request.query.get("archived") in {"1", "true"}
    return _response(lambda: {"experiments": get_service().list_experiments(include_archived=include_archived)})


async def post_experiment(request):
    payload = validate_create_payload(await _body(request))
    return _response(lambda: get_service().create_experiment(payload))


async def get_experiment(request):
    experiment_id = require_id(request.match_info["experiment_id"])
    return _response(lambda: get_service().detail(experiment_id))


async def post_plan(request):
    experiment_id = require_id(request.match_info["experiment_id"])
    payload = await _body(request)
    return _response(lambda: {"runs": get_service().plan_stage(experiment_id, payload)})


async def post_promote(request):
    experiment_id = require_id(request.match_info["experiment_id"])
    payload = await _body(request)
    return _response(lambda: {"runs": get_service().promote(experiment_id, payload)})


async def get_results(request):
    experiment_id = require_id(request.match_info["experiment_id"])
    return _response(lambda: {"results": get_service().list_results(experiment_id)})


async def patch_review(request):
    run_id = require_id(request.match_info["run_id"])
    payload = validate_review_payload(await _body(request))
    return _response(lambda: get_service().update_review(run_id, payload))


async def post_resume(request):
    experiment_id = require_id(request.match_info["experiment_id"])
    payload = await _body(request)
    timeout = payload.get("stale_after_seconds", 300)
    return _response(lambda: {"runs": get_service().resume_stale(experiment_id, stale_after_seconds=timeout)})


async def post_archive(request):
    experiment_id = require_id(request.match_info["experiment_id"])
    return _response(lambda: get_service().archive(experiment_id))


async def get_output(request):
    output_path = require_relative_path(request.match_info["output_path"])
    try:
        return web.FileResponse(get_service().output_file(output_path))
    except ValueError as exc:
        raise web.HTTPNotFound(text=str(exc)) from exc


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
    routes.get("/identity-lab/catalog")(_validated(get_catalog))
    routes.get("/identity-lab/experiments")(_validated(get_experiments))
    routes.post("/identity-lab/experiments")(_validated(post_experiment))
    routes.get("/identity-lab/experiments/{experiment_id}")(_validated(get_experiment))
    routes.post("/identity-lab/experiments/{experiment_id}/plan")(_validated(post_plan))
    routes.post("/identity-lab/experiments/{experiment_id}/promote")(_validated(post_promote))
    routes.get("/identity-lab/experiments/{experiment_id}/results")(_validated(get_results))
    routes.patch("/identity-lab/runs/{run_id}/review")(_validated(patch_review))
    routes.post("/identity-lab/experiments/{experiment_id}/resume")(_validated(post_resume))
    routes.post("/identity-lab/experiments/{experiment_id}/archive")(_validated(post_archive))
    routes.get("/identity-lab/output/{output_path:.*}")(_validated(get_output))
    _ROUTES_REGISTERED = True
