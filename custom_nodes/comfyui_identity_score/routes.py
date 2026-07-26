"""Lazy local HTTP routes for the identity experiment service."""

from __future__ import annotations

import sys
from math import isfinite
from pathlib import PureWindowsPath
from typing import Any, Mapping
from uuid import UUID

from aiohttp import web

from .experiment_planner import VALID_MODES, VALID_STAGES
from .experiment_service import ExperimentService
from .experiment_store import RUN_STATES


_ROUTES_REGISTERED = False
_SERVICE: ExperimentService | None = None


class QueueInspectionError(RuntimeError):
    pass


def get_service() -> ExperimentService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ExperimentService()
    return _SERVICE


def _run_ids_in_prompt(prompt: Any) -> set[str]:
    if not isinstance(prompt, Mapping):
        return set()
    run_ids: set[str] = set()
    for node in prompt.values():
        if not isinstance(node, Mapping) or node.get("class_type") != "DualIdentityScore":
            continue
        inputs = node.get("inputs")
        run_id = inputs.get("run_id") if isinstance(inputs, Mapping) else None
        if isinstance(run_id, str) and run_id.strip():
            run_ids.add(run_id)
    return run_ids


def _queued_run_ids(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found = _run_ids_in_prompt(value)
        found.update(_run_ids_in_prompt(value.get("prompt")))
        for nested in value.values():
            found.update(_queued_run_ids(nested))
        return found
    if isinstance(value, (tuple, list)):
        found: set[str] = set()
        for nested in value:
            found.update(_queued_run_ids(nested))
        return found
    return set()


def active_identity_lab_run_ids(prompt_server: Any | None = None) -> set[str]:
    """Best-effort local queue/history inspection; easy to replace in route tests."""
    if prompt_server is None:
        server_module = sys.modules.get("server")
        prompt_server = getattr(getattr(server_module, "PromptServer", None), "instance", None)
    if prompt_server is None:
        raise QueueInspectionError("unable to inspect ComfyUI queue/history")
    queue = getattr(prompt_server, "prompt_queue", None)
    get_current_queue = getattr(queue, "get_current_queue", None)
    get_history = getattr(queue, "get_history", None)
    if not callable(get_current_queue) or not callable(get_history):
        raise QueueInspectionError("unable to inspect ComfyUI queue/history")
    try:
        current = get_current_queue()
        history = get_history()
    except Exception as exc:
        raise QueueInspectionError("unable to inspect ComfyUI queue/history") from exc
    if not isinstance(history, Mapping):
        raise QueueInspectionError("unable to inspect ComfyUI queue/history")
    return _queued_run_ids(current)


# Test seam for route-level resume handling; production keeps it local to PromptServer.
active_run_ids_provider = active_identity_lab_run_ids


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
    _validate_plan_fields(payload, require_stages=False)
    for field in ("refine_settings", "settings"):
        if field in payload and not isinstance(payload[field], dict):
            raise ValueError(f"{field} must be an object")
    if "workflow" in payload and not isinstance(payload["workflow"], dict):
        raise ValueError("workflow must be an object")
    return payload


def _validate_plan_fields(payload: Mapping[str, Any], *, require_stages: bool) -> None:
    for field in ("checkpoints", "seeds"):
        if not isinstance(payload.get(field), list) or not payload[field]:
            raise ValueError(f"{field} must be a non-empty array")
    if any(not isinstance(name, str) or not name.strip() for name in payload["checkpoints"]):
        raise ValueError("checkpoints must contain non-empty strings")
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in payload["seeds"]):
        raise ValueError("seeds must contain integers")
    loras = payload.get("loras", [])
    if not isinstance(loras, list):
        raise ValueError("loras must be an array")
    for lora in loras:
        if not isinstance(lora, list) or len(lora) != 2 or not isinstance(lora[0], str) or not lora[0].strip() or isinstance(lora[1], bool) or not isinstance(lora[1], (int, float)) or not isfinite(lora[1]):
            raise ValueError("LoRA entries must be [name, strength]")
    if require_stages and "stages" not in payload:
        raise ValueError("stages must be an array")
    if "stages" in payload and (not isinstance(payload["stages"], list) or not payload["stages"] or any(stage not in VALID_STAGES for stage in payload["stages"])):
        raise ValueError("invalid stage")


def validate_plan_payload(value: Any) -> dict[str, Any]:
    payload = require_object(value)
    allowed = {"mode", "checkpoints", "seeds", "loras", "stages", "refine_settings"}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(sorted(unknown))}")
    if "mode" in payload and payload["mode"] not in VALID_MODES:
        raise ValueError("invalid mode")
    _validate_plan_fields(payload, require_stages=True)
    if "refine_settings" in payload and not isinstance(payload["refine_settings"], dict):
        raise ValueError("refine_settings must be an object")
    return payload


def validate_resume_payload(value: Any) -> dict[str, Any]:
    payload = require_object(value)
    if set(payload) - {"stale_after_seconds"}:
        raise ValueError("unknown resume fields")
    timeout = payload.get("stale_after_seconds", 300)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not isfinite(timeout) or timeout < 0:
        raise ValueError("stale_after_seconds must be a finite non-negative number")
    return payload


def validate_archive_payload(value: Any) -> dict[str, Any]:
    payload = require_object(value)
    if payload:
        raise ValueError("unknown archive fields")
    return payload


def validate_estimate_payload(value: Any) -> dict[str, Any]:
    payload = require_object(value)
    allowed = {"run_count", "fallback_seconds", "fallback_bytes"}
    if set(payload) - allowed:
        raise ValueError("unknown estimate fields")
    if isinstance(payload.get("run_count"), bool) or not isinstance(payload.get("run_count"), int) or payload["run_count"] < 0:
        raise ValueError("run_count must be a non-negative integer")
    if "fallback_seconds" in payload and (isinstance(payload["fallback_seconds"], bool) or not isinstance(payload["fallback_seconds"], (int, float)) or not isfinite(payload["fallback_seconds"]) or payload["fallback_seconds"] < 0):
        raise ValueError("fallback_seconds must be a finite non-negative number")
    if "fallback_bytes" in payload and (isinstance(payload["fallback_bytes"], bool) or not isinstance(payload["fallback_bytes"], int) or payload["fallback_bytes"] < 0):
        raise ValueError("fallback_bytes must be a non-negative integer")
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
    except QueueInspectionError as exc:
        raise web.HTTPServiceUnavailable(text=str(exc)) from exc
    except KeyError as exc:
        if "not found" in str(exc).lower():
            raise web.HTTPNotFound(text=str(exc)) from exc
        raise web.HTTPBadRequest(text=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc


def _validated(handler):
    async def wrapped(request):
        try:
            return await handler(request)
        except QueueInspectionError as exc:
            raise web.HTTPServiceUnavailable(text=str(exc)) from exc
        except KeyError as exc:
            if "not found" in str(exc).lower():
                raise web.HTTPNotFound(text=str(exc)) from exc
            raise web.HTTPBadRequest(text=str(exc)) from exc
        except (TypeError, ValueError) as exc:
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
    payload = validate_plan_payload(await _body(request))
    return _response(lambda: {"runs": get_service().plan_stage(experiment_id, payload)})


async def post_promote(request):
    experiment_id = require_id(request.match_info["experiment_id"])
    payload = validate_plan_payload(await _body(request))
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
    payload = validate_resume_payload(await _body(request))
    timeout = payload.get("stale_after_seconds", 300)
    return _response(lambda: {"runs": get_service().resume_stale(experiment_id, stale_after_seconds=timeout, active_run_ids=active_run_ids_provider())})


async def post_archive(request):
    experiment_id = require_id(request.match_info["experiment_id"])
    validate_archive_payload(await _body(request))
    return _response(lambda: get_service().archive(experiment_id))


async def post_estimate(request):
    experiment_id = require_id(request.match_info["experiment_id"])
    payload = validate_estimate_payload(await _body(request))
    return _response(lambda: get_service().estimate(experiment_id, **payload))


async def post_mark_queued(request):
    run_id = require_id(request.match_info["run_id"])
    payload = require_object(await _body(request))
    if set(payload) != {"experiment_id"}:
        raise ValueError("queue payload requires only experiment_id")
    return _response(lambda: get_service().mark_queued(require_id(payload["experiment_id"]), run_id))


async def get_output(request):
    run_id = require_id(request.match_info["run_id"])
    try:
        return web.FileResponse(get_service().completed_output_file(run_id), headers={"Content-Type": "image/png", "X-Content-Type-Options": "nosniff"})
    except (KeyError, ValueError) as exc:
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
    routes.post("/identity-lab/experiments/{experiment_id}/estimate")(_validated(post_estimate))
    routes.post("/identity-lab/runs/{run_id}/queued")(_validated(post_mark_queued))
    routes.get("/identity-lab/experiments/{experiment_id}/results")(_validated(get_results))
    routes.patch("/identity-lab/runs/{run_id}/review")(_validated(patch_review))
    routes.post("/identity-lab/experiments/{experiment_id}/resume")(_validated(post_resume))
    routes.post("/identity-lab/experiments/{experiment_id}/archive")(_validated(post_archive))
    routes.get("/identity-lab/runs/{run_id}/output")(_validated(get_output))
    _ROUTES_REGISTERED = True
