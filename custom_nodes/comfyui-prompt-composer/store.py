"""Persistence + HTTP routes for Prompt Composer.

State lives in a single JSON file (``data/presets.json``) next to this module:

    {
      "presets":   { "clothing": {name: {slot: text}}, "body": {...}, "environment": {...} },
      "libraries": { "<library name>": { "<snippet title>": "<snippet text>" } }
    }

* "presets"   back the slot nodes (Clothing/Body/Environment) -- a preset is a
               saved full set of slot values you can re-apply with one click.
* "libraries" back the generic Snippets node -- a named collection of
               title -> text snippets you toggle on/off and chain together.

All write routes return the updated collection so the frontend can refresh
without a second request.  Everything is wrapped so a failure to import the
ComfyUI ``server`` module (e.g. running these files outside ComfyUI for a unit
test) never crashes the import -- routes simply aren't registered.
"""

import json
import os
import threading

from .fields import schema_payload

_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIR = os.path.join(_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "presets.json")

# Single process-wide lock: ComfyUI route handlers run on one asyncio loop, but
# node execution can read concurrently from a worker thread.  Cheap insurance
# against a torn read mid-write.
_LOCK = threading.RLock()

_EMPTY = {
    "presets": {"clothing": {}, "body": {}, "environment": {}},
    "libraries": {},
}


def _ensure_shape(data):
    """Guarantee every expected key exists so callers never KeyError."""
    if not isinstance(data, dict):
        data = {}
    presets = data.get("presets")
    if not isinstance(presets, dict):
        presets = {}
    for cat in ("clothing", "body", "environment"):
        if not isinstance(presets.get(cat), dict):
            presets[cat] = {}
    data["presets"] = presets
    if not isinstance(data.get("libraries"), dict):
        data["libraries"] = {}
    return data


def load_data():
    with _LOCK:
        if not os.path.exists(DATA_FILE):
            return _ensure_shape({})
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as fh:
                return _ensure_shape(json.load(fh))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[PromptComposer] could not read {DATA_FILE}: {exc}")
            return _ensure_shape({})


def save_data(data):
    with _LOCK:
        os.makedirs(DATA_DIR, exist_ok=True)
        data = _ensure_shape(data)
        # Write to a temp file then replace, so a crash mid-write can't leave a
        # half-written, unparseable presets file.
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
        return data


# --- read helpers used by the nodes at execution time --------------------
def get_library(name):
    """Return {title: text} for a snippet library, or {} if missing."""
    return load_data()["libraries"].get(name, {})


# --- route registration ---------------------------------------------------
def _register_routes():
    try:
        import server  # ComfyUI's PromptServer module
        from aiohttp import web
    except Exception as exc:  # not running inside ComfyUI -> skip routes
        print(f"[PromptComposer] routes not registered ({exc}); nodes still work.")
        return

    routes = server.PromptServer.instance.routes
    PREFIX = "/prompt_composer"

    @routes.get(f"{PREFIX}/schema")
    async def _schema(_request):
        return web.json_response(schema_payload())

    # -- slot-node presets -------------------------------------------------
    @routes.get(PREFIX + "/presets")
    async def _get_presets(request):
        category = request.query.get("category", "")
        presets = load_data()["presets"]
        if category:
            return web.json_response(presets.get(category, {}))
        return web.json_response(presets)

    @routes.post(PREFIX + "/presets/save")
    async def _save_preset(request):
        try:
            body = await request.json()
            category = body.get("category")
            name = (body.get("name") or "").strip()
            values = body.get("data")
            if category not in ("clothing", "body", "environment"):
                return web.json_response({"error": "bad category"}, status=400)
            if not name or not isinstance(values, dict):
                return web.json_response({"error": "missing name/data"}, status=400)
            data = load_data()
            data["presets"][category][name] = values
            save_data(data)
            return web.json_response({"ok": True, "presets": data["presets"][category]})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @routes.post(PREFIX + "/presets/delete")
    async def _delete_preset(request):
        try:
            body = await request.json()
            category = body.get("category")
            name = body.get("name")
            data = load_data()
            cat = data["presets"].get(category, {})
            if name in cat:
                del cat[name]
                save_data(data)
            return web.json_response({"ok": True, "presets": cat})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    # -- snippet libraries -------------------------------------------------
    @routes.get(PREFIX + "/libraries")
    async def _get_libraries(_request):
        return web.json_response(load_data()["libraries"])

    @routes.post(PREFIX + "/libraries/save")
    async def _save_library(request):
        # Saves a whole library at once (frontend sends the full title->text map
        # on every edit -- libraries are small, so this keeps the API trivial).
        try:
            body = await request.json()
            name = (body.get("name") or "").strip()
            snippets = body.get("snippets")
            if not name or not isinstance(snippets, dict):
                return web.json_response({"error": "missing name/snippets"}, status=400)
            data = load_data()
            data["libraries"][name] = snippets
            save_data(data)
            return web.json_response({"ok": True, "libraries": data["libraries"]})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @routes.post(PREFIX + "/libraries/delete")
    async def _delete_library(request):
        try:
            body = await request.json()
            name = body.get("name")
            data = load_data()
            if name in data["libraries"]:
                del data["libraries"][name]
                save_data(data)
            return web.json_response({"ok": True, "libraries": data["libraries"]})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    print("[PromptComposer] HTTP routes registered under /prompt_composer")


_register_routes()
