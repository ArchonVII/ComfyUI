import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_nodes.comfyui_arch_prompt_tools.catalog import (
    CatalogError,
    CatalogValidationError,
    load_catalog,
)
from custom_nodes.comfyui_arch_prompt_tools.routes import (
    ROUTE_PREFIX,
    create_option_payload,
    delete_option_payload,
    options_payload,
    register_routes,
    schema_payload,
    update_option_payload,
)
from custom_nodes.comfyui_arch_prompt_tools.store import OptionStore


@pytest.fixture(scope="module")
def catalog():
    data = Path(__file__).parents[1] / "data"
    return load_catalog(data / "schemas.json", data / "builtin_options.json")


@pytest.fixture
def store(tmp_path, catalog):
    ids = iter(("user.route-one", "user.route-two"))
    return OptionStore(catalog, tmp_path / "options.json", id_factory=lambda: next(ids))


def valid_option(**changes):
    value = {
        "label": "Route option",
        "node": "identity",
        "field": "subject_type",
        "group": "subject_type",
        "model_family": "flux",
        "phrase": "a route-created person",
        "builtin": False,
    }
    value.update(changes)
    return value


def test_schema_payload_is_complete_json_native_and_copy_safe(catalog):
    first = schema_payload(catalog)
    encoded = json.dumps(first, ensure_ascii=False)
    first["nodes"][0]["sections"][0]["fields"][0]["label"] = "Mutated"
    second = schema_payload(catalog)

    assert json.loads(encoded)["version"] == catalog.version
    assert first["families"] == ["flux", "qwen"]
    assert {node["key"] for node in second["nodes"]} == set(catalog.schemas_by_node)
    assert second["nodes"][0]["sections"][0]["fields"][0]["label"] != "Mutated"


def test_options_payload_merges_protected_builtins_and_users_with_family_projection(store, catalog):
    created = store.create(valid_option())

    payload = options_payload(
        catalog,
        store,
        node="identity",
        field="subject_type",
        family="flux",
    )

    assert payload["version"] == catalog.version
    assert payload["filters"] == {
        "node": "identity",
        "field": "subject_type",
        "model_family": "flux",
    }
    assert len({option["id"] for option in payload["options"]}) == len(payload["options"])
    projected = next(option for option in payload["options"] if option["id"] == created.id)
    assert projected == {
        "id": created.id,
        "label": "Route option",
        "node": "identity",
        "field": "subject_type",
        "group": "subject_type",
        "phrases": {"flux": "a route-created person"},
        "builtin": False,
        "lora": None,
        "lora_enabled": False,
    }
    assert all(option["node"] == "identity" for option in payload["options"])
    assert all(option["field"] == "subject_type" for option in payload["options"])
    assert all(set(option["phrases"]) == {"flux"} for option in payload["options"])
    assert any(option["builtin"] is True for option in payload["options"])


def test_options_payload_without_filters_returns_each_stable_id_once(store, catalog):
    created = store.create(valid_option(model_family="qwen"))

    payload = options_payload(catalog, store)

    assert created.id in {option["id"] for option in payload["options"]}
    assert len({option["id"] for option in payload["options"]}) == len(payload["options"])
    assert {"flux", "qwen"} <= set(
        next(option for option in payload["options"] if option["builtin"])["phrases"]
    )


@pytest.mark.parametrize(
    ("filters", "match"),
    [
        ({"node": "unknown"}, "unknown node"),
        ({"node": "identity", "field": "unknown"}, "unknown field"),
        ({"family": "sdxl"}, "unknown model family"),
        ({"field": "subject_type"}, "field filter requires"),
    ],
)
def test_options_payload_validates_filters(store, catalog, filters, match):
    with pytest.raises(CatalogError, match=match):
        options_payload(catalog, store, **filters)


def test_explicit_payload_helpers_create_update_and_delete(store, catalog):
    created = create_option_payload(catalog, store, valid_option())
    updated = update_option_payload(catalog, store, created["option"]["id"], {"label": "Updated"})
    deleted = delete_option_payload(catalog, store, created["option"]["id"])

    assert created["option"]["builtin"] is False
    assert updated["option"]["id"] == created["option"]["id"]
    assert updated["option"]["label"] == "Updated"
    assert deleted == {"deleted_id": created["option"]["id"]}


class FakeRoutes:
    def __init__(self):
        self.handlers = {}

    def _decorator(self, method, path):
        def add(handler):
            if (method, path) in self.handlers:
                raise RuntimeError("duplicate route")
            self.handlers[(method, path)] = handler
            return handler

        return add

    def get(self, path):
        return self._decorator("GET", path)

    def post(self, path):
        return self._decorator("POST", path)

    def patch(self, path):
        return self._decorator("PATCH", path)

    def delete(self, path):
        return self._decorator("DELETE", path)


class FakeWeb:
    @staticmethod
    def json_response(payload, status=200):
        return {"status": status, "payload": payload}


class FakeRequest:
    def __init__(self, *, body=None, query=None, option_id=None, json_error=None):
        self._body = body
        self.query = query or {}
        self.match_info = {} if option_id is None else {"option_id": option_id}
        self._json_error = json_error

    async def json(self):
        if self._json_error:
            raise self._json_error
        return self._body


def test_route_registration_is_safe_when_prompt_server_is_unavailable(monkeypatch):
    monkeypatch.delitem(sys.modules, "server", raising=False)

    assert register_routes() is False


def test_route_registration_is_idempotent_per_registry_and_has_the_explicit_api(store, catalog):
    routes = FakeRoutes()
    prompt_server = SimpleNamespace(routes=routes)

    assert register_routes(
        prompt_server,
        web_module=FakeWeb,
        catalog_provider=lambda: catalog,
        store_provider=lambda _catalog: store,
    ) is True
    assert register_routes(
        prompt_server,
        web_module=FakeWeb,
        catalog_provider=lambda: catalog,
        store_provider=lambda _catalog: store,
    ) is False
    assert set(routes.handlers) == {
        ("GET", f"{ROUTE_PREFIX}/schema"),
        ("GET", f"{ROUTE_PREFIX}/options"),
        ("POST", f"{ROUTE_PREFIX}/options"),
        ("PATCH", f"{ROUTE_PREFIX}/options/{{option_id}}"),
        ("DELETE", f"{ROUTE_PREFIX}/options/{{option_id}}"),
    }


def test_registered_handlers_return_useful_success_and_4xx_responses(store, catalog):
    routes = FakeRoutes()
    register_routes(
        SimpleNamespace(routes=routes),
        web_module=FakeWeb,
        catalog_provider=lambda: catalog,
        store_provider=lambda _catalog: store,
    )
    post = routes.handlers[("POST", f"{ROUTE_PREFIX}/options")]
    patch = routes.handlers[("PATCH", f"{ROUTE_PREFIX}/options/{{option_id}}")]
    delete = routes.handlers[("DELETE", f"{ROUTE_PREFIX}/options/{{option_id}}")]
    get_options = routes.handlers[("GET", f"{ROUTE_PREFIX}/options")]

    created = asyncio.run(post(FakeRequest(body=valid_option())))
    option_id = created["payload"]["option"]["id"]
    filtered = asyncio.run(
        get_options(
            FakeRequest(query={"node": "identity", "field": "subject_type", "model_family": "flux"})
        )
    )
    bad_json = asyncio.run(post(FakeRequest(json_error=ValueError("bad JSON"))))
    protected = asyncio.run(
        patch(FakeRequest(body={"label": "No"}, option_id=catalog.options[0].id))
    )
    missing = asyncio.run(delete(FakeRequest(option_id="user.missing")))

    assert created["status"] == 201
    assert any(item["id"] == option_id for item in filtered["payload"]["options"])
    assert bad_json == {"status": 400, "payload": {"error": "bad JSON"}}
    assert protected["status"] == 403
    assert missing["status"] == 404


def test_registered_handlers_report_corrupt_store_as_server_error(tmp_path, catalog):
    path = tmp_path / "options.json"
    path.write_text("{bad", encoding="utf-8")
    corrupt = OptionStore(catalog, path)
    routes = FakeRoutes()
    register_routes(
        SimpleNamespace(routes=routes),
        web_module=FakeWeb,
        catalog_provider=lambda: catalog,
        store_provider=lambda _catalog: corrupt,
    )

    response = asyncio.run(
        routes.handlers[("GET", f"{ROUTE_PREFIX}/options")](FakeRequest())
    )

    assert response["status"] == 500
    assert "invalid" in response["payload"]["error"].lower()


def test_registered_handlers_report_invalid_builtin_catalog_as_server_error():
    routes = FakeRoutes()

    def invalid_catalog():
        raise CatalogValidationError("built-in catalog is invalid")

    register_routes(
        SimpleNamespace(routes=routes),
        web_module=FakeWeb,
        catalog_provider=invalid_catalog,
    )

    response = asyncio.run(
        routes.handlers[("GET", f"{ROUTE_PREFIX}/schema")](FakeRequest())
    )

    assert response["status"] == 500
    assert response["payload"] == {"error": "built-in catalog is invalid"}
