"""JSON payload helpers and optional ComfyUI HTTP route registration."""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any, Callable, Mapping

from .catalog import Catalog, CatalogError, CatalogValidationError, OptionRecord
from .store import (
    OptionNotFoundError,
    OptionStore,
    OptionStoreDataError,
    OptionValidationError,
    ProtectedOptionError,
    UserOption,
)


ROUTE_PREFIX = "/arch-prompt-tools"
_LOGGER = logging.getLogger(__name__)
_REGISTERED_ROUTES: list[Any] = []
_REGISTRATION_LOCK = threading.RLock()


def schema_payload(catalog: Catalog) -> dict[str, Any]:
    """Return the validated schema as fresh JSON-native values."""
    nodes = []
    for node in catalog.schemas_by_node.values():
        sections = []
        for section in node.sections:
            fields = []
            for field in section.fields:
                item: dict[str, Any] = {
                    "key": field.key,
                    "label": field.label,
                    "order": field.order,
                    "control": field.control,
                    "groups": list(field.groups),
                    "user_selection": field.user_selection,
                    "enabled_by_default": field.enabled_by_default,
                }
                if field.catalog_scope is not None:
                    item["catalog_scope"] = field.catalog_scope
                if field.spectrum:
                    item["spectrum"] = [
                        {
                            "minimum": stop.minimum,
                            "maximum": stop.maximum,
                            "phrases": dict(stop.phrases),
                        }
                        for stop in field.spectrum
                    ]
                fields.append(item)
            sections.append(
                {
                    "key": section.key,
                    "label": section.label,
                    "order": section.order,
                    "fields": fields,
                }
            )
        nodes.append({"key": node.key, "label": node.label, "sections": sections})
    return {
        "version": catalog.version,
        "families": list(catalog.families),
        "nodes": nodes,
    }


def options_payload(
    catalog: Catalog,
    store: OptionStore,
    *,
    node: str | None = None,
    field: str | None = None,
    family: str | None = None,
) -> dict[str, Any]:
    """Merge protected and user options into a collision-free projection."""
    _validate_filters(catalog, node=node, field=field, family=family)
    options: list[dict[str, Any]] = []
    for option in catalog.options:
        if _matches(option, node=node, field=field) and (
            family is None or family in option.phrases
        ):
            options.append(_project_builtin(option, family=family))
    for option in store.list_options():
        if _matches(option, node=node, field=field) and (
            family is None or family == option.model_family
        ):
            options.append(_project_user(option))
    ids = [option["id"] for option in options]
    if len(ids) != len(set(ids)):
        raise OptionStoreDataError("built-in and user option ids collide")
    return {
        "version": catalog.version,
        "filters": {
            "node": node,
            "field": field,
            "model_family": family,
        },
        "options": options,
    }


def create_option_payload(
    _catalog: Catalog, store: OptionStore, data: Mapping[str, Any]
) -> dict[str, Any]:
    return {"option": _project_user(store.create(data))}


def update_option_payload(
    _catalog: Catalog,
    store: OptionStore,
    option_id: str,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    return {"option": _project_user(store.update(option_id, data))}


def delete_option_payload(
    _catalog: Catalog, store: OptionStore, option_id: str
) -> dict[str, Any]:
    removed = store.delete(option_id)
    return {"deleted_id": removed.id}


def register_routes(
    prompt_server: Any | None = None,
    *,
    web_module: Any | None = None,
    catalog_provider: Callable[[], Catalog] | None = None,
    store_provider: Callable[[Catalog], OptionStore] | None = None,
) -> bool:
    """Register routes once when ComfyUI's PromptServer is already available."""
    try:
        if prompt_server is None:
            server_module = sys.modules.get("server")
            prompt_server_cls = getattr(server_module, "PromptServer", None)
            prompt_server = getattr(prompt_server_cls, "instance", None)
        if prompt_server is None or getattr(prompt_server, "routes", None) is None:
            return False
        routes = prompt_server.routes
        if web_module is None:
            from aiohttp import web as web_module
    except Exception:
        _LOGGER.exception("Arch PT route registration setup failed")
        return False
    get_catalog = catalog_provider or _default_catalog
    get_store = store_provider or (lambda catalog: OptionStore(catalog))

    async def get_schema(_request):
        try:
            return web_module.json_response(schema_payload(get_catalog()))
        except Exception as error:
            return _error_response(web_module, error)

    async def get_options(request):
        try:
            catalog = get_catalog()
            store = get_store(catalog)
            return web_module.json_response(
                options_payload(
                    catalog,
                    store,
                    node=_query_value(request, "node"),
                    field=_query_value(request, "field"),
                    family=_query_value(request, "model_family"),
                )
            )
        except Exception as error:
            return _error_response(web_module, error)

    async def post_option(request):
        try:
            data = await request.json()
            catalog = get_catalog()
            payload = create_option_payload(catalog, get_store(catalog), data)
            return web_module.json_response(payload, status=201)
        except Exception as error:
            return _error_response(web_module, error)

    async def patch_option(request):
        try:
            data = await request.json()
            catalog = get_catalog()
            payload = update_option_payload(
                catalog,
                get_store(catalog),
                request.match_info["option_id"],
                data,
            )
            return web_module.json_response(payload)
        except Exception as error:
            return _error_response(web_module, error)

    async def delete_option(request):
        try:
            catalog = get_catalog()
            payload = delete_option_payload(
                catalog,
                get_store(catalog),
                request.match_info["option_id"],
            )
            return web_module.json_response(payload)
        except Exception as error:
            return _error_response(web_module, error)

    definitions = (
        ("get", f"{ROUTE_PREFIX}/schema", get_schema),
        ("get", f"{ROUTE_PREFIX}/options", get_options),
        ("post", f"{ROUTE_PREFIX}/options", post_option),
        ("patch", f"{ROUTE_PREFIX}/options/{{option_id}}", patch_option),
        ("delete", f"{ROUTE_PREFIX}/options/{{option_id}}", delete_option),
    )
    with _REGISTRATION_LOCK:
        if any(registered is routes for registered in _REGISTERED_ROUTES):
            return False
        try:
            _install_route_definitions(routes, definitions)
        except Exception:
            _LOGGER.exception("Arch PT route registration failed")
            return False
        _REGISTERED_ROUTES.append(routes)
        return True


def _install_route_definitions(
    routes: Any,
    definitions: tuple[tuple[str, str, Callable[..., Any]], ...],
) -> None:
    items = getattr(routes, "_items", None)
    if isinstance(items, list):
        staged = type(routes)()
        for method, path, handler in definitions:
            getattr(staged, method)(path)(handler)
        staged_items = getattr(staged, "_items")
        original_length = len(items)
        try:
            items.extend(staged_items)
        except Exception:
            del items[original_length:]
            raise
        return

    handlers = getattr(routes, "handlers", None)
    if not isinstance(handlers, dict):
        raise TypeError("unsupported route registry")
    snapshot = dict(handlers)
    try:
        for method, path, handler in definitions:
            getattr(routes, method)(path)(handler)
    except Exception:
        handlers.clear()
        handlers.update(snapshot)
        raise


def _default_catalog() -> Catalog:
    from .nodes import _catalog

    return _catalog()


def _query_value(request: Any, key: str) -> str | None:
    value = request.query.get(key)
    return value if value not in (None, "") else None


def _validate_filters(
    catalog: Catalog,
    *,
    node: str | None,
    field: str | None,
    family: str | None,
) -> None:
    if field is not None and node is None:
        raise CatalogError("field filter requires a node filter")
    if node is not None:
        if node not in catalog.schemas_by_node:
            raise CatalogError(f"unknown node: {node}")
        if field is not None:
            catalog.field(node, field)
    if family is not None and family not in catalog.families:
        raise CatalogError(f"unknown model family: {family}")


def _matches(
    option: OptionRecord | UserOption, *, node: str | None, field: str | None
) -> bool:
    return (node is None or option.node == node) and (
        field is None or option.field == field
    )


def _project_builtin(
    option: OptionRecord, *, family: str | None
) -> dict[str, Any]:
    phrases = (
        dict(option.phrases)
        if family is None
        else {family: option.phrases[family]}
    )
    return {
        "id": option.id,
        "label": option.label,
        "node": option.node,
        "field": option.field,
        "group": option.group,
        "phrases": phrases,
        "builtin": True,
        "lora": _json_copy(option.lora),
        "lora_enabled": option.lora is not None,
    }


def _project_user(option: UserOption) -> dict[str, Any]:
    return {
        "id": option.id,
        "label": option.label,
        "node": option.node,
        "field": option.field,
        "group": option.group,
        "phrases": {option.model_family: option.phrase},
        "builtin": False,
        "lora": _json_copy(option.lora),
        "lora_enabled": option.lora_enabled,
    }


def _json_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _json_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_copy(item) for item in value]
    return value


def _error_response(web_module: Any, error: Exception):
    if isinstance(error, ProtectedOptionError):
        status = 403
    elif isinstance(error, OptionNotFoundError):
        status = 404
    elif isinstance(error, (CatalogValidationError, OptionStoreDataError)):
        status = 500
    elif isinstance(error, (CatalogError, OptionValidationError, KeyError, TypeError, ValueError)):
        status = 400
    else:
        status = 500
    if status == 500:
        _LOGGER.error(
            "Arch PT route request failed",
            exc_info=(type(error), error, error.__traceback__),
        )
        message = "internal server error"
    else:
        message = str(error)
    return web_module.json_response({"error": message}, status=status)
