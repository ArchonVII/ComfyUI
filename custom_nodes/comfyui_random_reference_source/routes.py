from __future__ import annotations

import asyncio
import concurrent.futures
import sys
from pathlib import Path
from typing import Any

from aiohttp import web

import folder_paths

from .nodes import (
    VALID_IMAGE_EXTENSIONS,
    _expand_path_text,
    build_reference_preview_payload,
    load_favorites,
)

_ROUTES_REGISTERED = False

# Native file dialogs (tkinter) must be created and destroyed on a single,
# consistent thread; reusing one worker avoids cross-thread Tcl interpreter
# state corruption and naturally serializes dialogs so only one is open at a
# time. max_workers=1 enforces both. Source: tkinter thread-safety guidance
# (https://docs.python.org/3/library/tkinter.html#threading-model).
_DIALOG_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="arch-ref-dialog"
)

# File-picker "type" filter for the multi-select image dialog, derived from the
# image extensions the node itself accepts (nodes.VALID_IMAGE_EXTENSIONS) so the
# dialog and the loader can never disagree about what counts as an image.
_IMAGE_FILETYPES = [
    ("Images", " ".join(f"*{ext}" for ext in VALID_IMAGE_EXTENSIONS)),
    ("All files", "*.*"),
]


def _initial_dir(initial_dir: str) -> str:
    """Best-effort starting directory for a dialog.

    Falls back to ComfyUI's input directory when the supplied hint is empty or
    is not an existing directory, so the dialog always opens somewhere sane.
    """
    expanded = _expand_path_text(initial_dir or "")
    if expanded:
        candidate = Path(expanded)
        if candidate.is_dir():
            return str(candidate)
        # A file hint (or the folder a file lives in) is still useful.
        if candidate.parent.is_dir():
            return str(candidate.parent)
    return folder_paths.get_input_directory()


def _make_root():
    """Create a hidden, foregrounded Tk root, or raise if tkinter is unusable.

    Raising here (rather than returning None) lets the route handler convert the
    failure into an explicit error response instead of silently doing nothing.
    """
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    # Force the dialog above the browser window; without -topmost the native
    # dialog frequently opens behind the active window on Windows.
    root.attributes("-topmost", True)
    root.update()
    return root


def _ask_directory(initial_dir: str) -> str:
    from tkinter import filedialog

    root = _make_root()
    try:
        return filedialog.askdirectory(
            initialdir=_initial_dir(initial_dir),
            title="Select reference source folder",
            parent=root,
        )
    finally:
        root.destroy()


def _ask_image_files(initial_dir: str) -> list[str]:
    from tkinter import filedialog

    root = _make_root()
    try:
        selection = filedialog.askopenfilenames(
            initialdir=_initial_dir(initial_dir),
            title="Select reference images",
            filetypes=_IMAGE_FILETYPES,
            parent=root,
        )
    finally:
        root.destroy()
    # askopenfilenames returns a tuple of paths, or "" on cancel.
    return [str(path) for path in (selection or ()) if str(path).strip()]


async def _run_dialog(func, initial_dir: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_DIALOG_EXECUTOR, func, initial_dir)


async def post_browse_folder(request: web.Request) -> web.Response:
    data = await _read_json(request)
    try:
        path = await _run_dialog(_ask_directory, data.get("initial_dir", ""))
    except Exception as exc:  # noqa: BLE001 - surface any dialog failure to the UI
        return _dialog_error(exc)
    return web.json_response({"path": path or ""})


async def post_pick_images(request: web.Request) -> web.Response:
    data = await _read_json(request)
    try:
        paths = await _run_dialog(_ask_image_files, data.get("initial_dir", ""))
    except Exception as exc:  # noqa: BLE001 - surface any dialog failure to the UI
        return _dialog_error(exc)
    return web.json_response({"paths": paths})


async def post_preview(request: web.Request) -> web.Response:
    data = await _read_json(request)
    try:
        payload = build_reference_preview_payload(
            source_mode=data.get("source_mode", "auto"),
            folder=data.get("folder", "."),
            favorite=data.get("favorite", "None"),
            selected_images=data.get("selected_images", ""),
            selection_policy=data.get("selection_policy", "random_each_queue"),
            seed=int(data.get("seed") or 0),
            include_subfolders=bool(data.get("include_subfolders", False)),
            favorites=load_favorites(),
        )
    except Exception as exc:  # noqa: BLE001 - report preview issues to the node UI
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(payload)


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 - tolerate empty/invalid bodies
        return {}
    return data if isinstance(data, dict) else {}


def _dialog_error(exc: Exception) -> web.Response:
    return web.json_response(
        {
            "error": (
                "Could not open a native file dialog on the ComfyUI server "
                f"({type(exc).__name__}: {exc}). This requires a desktop "
                "session on the machine running ComfyUI. Type the path manually."
            )
        },
        status=500,
    )


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
    routes.post("/arch-random-reference/browse-folder")(post_browse_folder)
    routes.post("/arch-random-reference/pick-images")(post_pick_images)
    routes.post("/arch-random-reference/preview")(post_preview)
    _ROUTES_REGISTERED = True
