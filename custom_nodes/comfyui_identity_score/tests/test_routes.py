from pathlib import Path
import asyncio
import json
import sys
from uuid import uuid4

import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_identity_score import routes
from comfyui_identity_score.experiment_service import (
    IDENTITY_LAB_BASE_IMAGE, IDENTITY_LAB_LORA_1, IDENTITY_LAB_LORA_2, IDENTITY_LAB_LORA_3,
    IDENTITY_LAB_MODEL, IDENTITY_LAB_REFERENCE_IMAGE, IDENTITY_LAB_SAMPLER, IDENTITY_LAB_SCORE, ExperimentService,
)


class RouteFolderPaths:
    def __init__(self, root):
        self.root = root

    def get_filename_list(self, category):
        return {"diffusion_models": ["flux-9b.safetensors"], "checkpoints": [], "loras": []}.get(category, [])

    def get_user_directory(self):
        return str(self.root / "user")

    def get_output_directory(self):
        return str(self.root / "output")


def api_workflow():
    pairs = [(IDENTITY_LAB_BASE_IMAGE, "LoadImage"), (IDENTITY_LAB_REFERENCE_IMAGE, "LoadImage"), (IDENTITY_LAB_MODEL, "UNETLoader"), (IDENTITY_LAB_LORA_1, "LoraLoader"), (IDENTITY_LAB_LORA_2, "LoraLoader"), (IDENTITY_LAB_LORA_3, "LoraLoader"), (IDENTITY_LAB_SAMPLER, "KSampler"), (IDENTITY_LAB_SCORE, "DualIdentityScore")]
    return {str(index): {"class_type": kind, "inputs": {}, "_meta": {"title": title}} for index, (title, kind) in enumerate(pairs, 1)}


def test_aiohttp_handlers_create_detail_queue_retry_and_completed_png(tmp_path, monkeypatch):
    service = ExperimentService(folder_paths_module=RouteFolderPaths(tmp_path))
    monkeypatch.setattr(routes, "get_service", lambda: service)

    async def exercise():
        app = web.Application()
        app.router.add_post("/experiments", routes._validated(routes.post_experiment))
        app.router.add_get("/experiments/{experiment_id}", routes._validated(routes.get_experiment))
        app.router.add_post("/runs/{run_id}/queued", routes._validated(routes.post_mark_queued))
        app.router.add_get("/runs/{run_id}/output", routes._validated(routes.get_output))
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            payload = {"name": "roundtrip", "mode": "face_swap", "checkpoints": ["flux-9b.safetensors"], "seeds": [7], "stages": ["baseline"], "workflow": api_workflow()}
            create = await client.post("/experiments", json=payload)
            assert create.status == 200
            created = await create.json()
            experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
            detail = await client.get(f"/experiments/{experiment_id}")
            assert detail.status == 200
            assert (await detail.json())["experiment"]["settings"]["workflow_template"] == payload["workflow"]
            service.store.claim_recorded_run(experiment_id=experiment_id, run_id=run_id, output_path="identity_lab/results/temp.png")
            service.store.fail_recorded_run(experiment_id=experiment_id, run_id=run_id, error="retry")
            queued = await client.post(f"/runs/{run_id}/queued", json={"experiment_id": experiment_id})
            assert queued.status == 200 and (await queued.json())["state"] == "queued"
            service.record_run(experiment_id=experiment_id, run_id=run_id, generated_image=np.zeros((2, 2, 3)), report={})
            output = await client.get(f"/runs/{run_id}/output")
            assert output.status == 200
            assert output.headers["Content-Type"].startswith("image/png")
            assert output.headers["X-Content-Type-Options"] == "nosniff"
            assert (await output.read()).startswith(b"\x89PNG")
        finally:
            await client.close()

    asyncio.run(exercise())


def test_payload_validators_reject_non_objects_bad_ids_modes_states_and_traversal():
    with pytest.raises(ValueError, match="JSON object"):
        routes.require_object([])
    with pytest.raises(ValueError, match="ID"):
        routes.require_id("not-an-id")
    with pytest.raises(ValueError, match="mode"):
        routes.validate_create_payload({"name": "x", "mode": "bad"})
    with pytest.raises(ValueError, match="state"):
        routes.validate_review_payload({"state": "completed"})
    with pytest.raises(ValueError, match="relative"):
        routes.require_relative_path("../output.png")


def test_payload_validators_accept_strict_create_and_review_contracts():
    payload = routes.validate_create_payload({
        "name": "A", "mode": "face_swap", "checkpoints": ["flux-9b.safetensors"], "seeds": [1], "stages": ["baseline"],
    })
    assert payload["name"] == "A"
    assert routes.require_id(str(uuid4()))
    assert routes.validate_review_payload({"rating": 5, "favorite": False, "notes": "keep"})["rating"] == 5


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "A", "mode": "face_swap", "checkpoints": ["flux-9b.safetensors"], "seeds": [1], "loras": [["face.safetensors"]]},
        {"name": "A", "mode": "face_swap", "checkpoints": ["flux-9b.safetensors"], "seeds": [1], "loras": [["face.safetensors", "high"]]},
        {"name": "A", "mode": "face_swap", "checkpoints": ["flux-9b.safetensors"], "seeds": [1], "unexpected": True},
    ],
)
def test_create_validation_rejects_unknown_fields_and_malformed_lora_items(payload):
    with pytest.raises(ValueError):
        routes.validate_create_payload(payload)


def test_plan_resume_archive_and_estimate_validators_reject_unknown_or_wrong_nested_values():
    with pytest.raises(ValueError, match="LoRA"):
        routes.validate_plan_payload({"checkpoints": ["flux-9b"], "seeds": [1], "stages": ["baseline"], "loras": ["wrong"]})
    with pytest.raises(ValueError, match="unknown"):
        routes.validate_resume_payload({"stale_after_seconds": 10, "extra": True})
    with pytest.raises(ValueError, match="unknown"):
        routes.validate_archive_payload({"confirm": True})
    with pytest.raises(ValueError, match="run_count"):
        routes.validate_estimate_payload({"run_count": "one"})


def test_active_run_helper_extracts_only_dual_identity_runs_from_live_queue_and_active_history():
    dual_prompt = {"4": {"class_type": "DualIdentityScore", "inputs": {"run_id": "queued-run"}}}
    completed_prompt = {"4": {"class_type": "DualIdentityScore", "inputs": {"run_id": "complete-run"}}}
    class PromptQueue:
        def get_current_queue(self):
            return ([(1, "prompt-id", dual_prompt, {}, [])], [])

        def get_history(self):
            return {
                "active": {"status": {"status_str": "running"}, "prompt": {"5": {"class_type": "DualIdentityScore", "inputs": {"run_id": "history-run"}}}},
                "done": {"status": {"status_str": "success"}, "prompt": completed_prompt},
            }

    prompt_server = type("PromptServer", (), {"prompt_queue": PromptQueue()})()

    assert routes.active_identity_lab_run_ids(prompt_server) == {"queued-run"}


def test_active_run_helper_uses_prompt_queue_history_api_and_treats_history_as_active():
    history_prompt = (1, "history-prompt", {"4": {"class_type": "DualIdentityScore", "inputs": {"experiment_id": "experiment", "run_id": "history-run"}}}, {}, [])

    class PromptQueue:
        def get_current_queue(self):
            return ([], [])

        def get_history(self):
            return {"history-prompt": {"prompt": history_prompt, "status": {"status_str": "success"}}}

    prompt_server = type("PromptServer", (), {"prompt_queue": PromptQueue()})()

    assert routes.active_identity_lab_run_ids(prompt_server) == set()


def test_active_run_helper_fails_closed_when_prompt_queue_inspection_errors():
    class PromptQueue:
        def get_current_queue(self):
            raise RuntimeError("queue locked")

        def get_history(self):
            return {}

    prompt_server = type("PromptServer", (), {"prompt_queue": PromptQueue()})()

    with pytest.raises(routes.QueueInspectionError, match="unable to inspect"):
        routes.active_identity_lab_run_ids(prompt_server)


def test_wrapped_routes_translate_malformed_json_and_type_errors_to_bad_request():
    class BadJsonRequest:
        match_info = {"experiment_id": str(uuid4())}

        async def json(self):
            raise json.JSONDecodeError("bad json", "{", 1)

    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(routes._validated(routes.post_estimate)(BadJsonRequest()))

    async def type_error(_request):
        raise TypeError("bad nested value")

    with pytest.raises(web.HTTPBadRequest):
        asyncio.run(routes._validated(type_error)(object()))


def test_register_routes_is_safe_without_comfyui_server(monkeypatch):
    monkeypatch.setattr(routes.sys, "modules", {})
    routes._ROUTES_REGISTERED = False
    routes.register_routes()
    assert routes._ROUTES_REGISTERED is False


def test_register_routes_includes_explicit_human_controlled_promotion_endpoint(monkeypatch):
    registered = []

    class RouteTable:
        def __getattr__(self, method):
            def register(path):
                registered.append((method, path))
                return lambda handler: handler

            return register

    class PromptServer:
        instance = type("Instance", (), {"routes": RouteTable()})()

    routes._ROUTES_REGISTERED = False
    monkeypatch.setitem(routes.sys.modules, "server", type("Server", (), {"PromptServer": PromptServer})())
    routes.register_routes()

    assert ("post", "/identity-lab/experiments/{experiment_id}/promote") in registered
    assert ("post", "/identity-lab/experiments/{experiment_id}/estimate") in registered
    routes._ROUTES_REGISTERED = False
