from pathlib import Path
import sys
from uuid import uuid4

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_identity_score import routes


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
    routes._ROUTES_REGISTERED = False
