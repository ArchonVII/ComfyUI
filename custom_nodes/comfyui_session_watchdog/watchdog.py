from __future__ import annotations

import copy
import logging
import re
import sys
import threading
import time
from collections import Counter, OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable


EVENT_NAME = "session-watchdog-event"

_LORA_KEY_NOT_LOADED_RE = re.compile(r"^lora key not loaded:\s*(?P<key>\S+)")
_ADAPTER_ERROR_RE = re.compile(
    r"^ERROR\s+(?P<adapter>[A-Za-z0-9_]+)\s+(?P<target>\S+)\s+(?P<error>.+)$"
)
_WEIGHT_NOT_MERGED_RE = re.compile(
    r"^WARNING SHAPE MISMATCH\s+(?P<target>\S+)\s+WEIGHT NOT MERGED\s+"
    r"(?P<expected>.+?)\s+!=\s+(?P<actual>.+)$"
)

_LORA_ADAPTERS = {
    "lora",
    "lokr",
    "loha",
    "glora",
    "ia3",
    "oft",
    "boft",
    "diff",
    "set",
}

_MAX_TRACKED_LORA_SOURCES = 512
_RECENT_LORA_FAILURE_TTL_SECONDS = 120
_LORA_SOURCE_BY_STATE_ID: OrderedDict[int, str] = OrderedDict()
_LORA_SOURCE_LOCK = threading.RLock()
_LORA_CONTEXT = threading.local()
_RECENT_LORA_FAILURE: dict[str, Any] = {"lora_name": None, "timestamp": 0.0}
_LORA_CONTEXT_HOOKS_INSTALLED = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _display_lora_name(source: Any) -> str | None:
    if source is None:
        return None
    value = str(source).strip()
    if not value:
        return None
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def track_lora_source(lora_state_dict: Any, source: Any) -> None:
    if not isinstance(lora_state_dict, dict):
        return

    lora_name = _display_lora_name(source)
    if lora_name is None:
        return

    with _LORA_SOURCE_LOCK:
        _LORA_SOURCE_BY_STATE_ID[id(lora_state_dict)] = lora_name
        _LORA_SOURCE_BY_STATE_ID.move_to_end(id(lora_state_dict))
        while len(_LORA_SOURCE_BY_STATE_ID) > _MAX_TRACKED_LORA_SOURCES:
            _LORA_SOURCE_BY_STATE_ID.popitem(last=False)


def _tracked_lora_name(lora_state_dict: Any) -> str | None:
    if not isinstance(lora_state_dict, dict):
        return _display_lora_name(lora_state_dict)

    with _LORA_SOURCE_LOCK:
        return _LORA_SOURCE_BY_STATE_ID.get(id(lora_state_dict))


def _lora_context_stack() -> list[str | None]:
    stack = getattr(_LORA_CONTEXT, "names", None)
    if stack is None:
        stack = []
        _LORA_CONTEXT.names = stack
    return stack


def current_lora_name() -> str | None:
    stack = getattr(_LORA_CONTEXT, "names", [])
    return stack[-1] if stack else None


@contextmanager
def lora_context(lora_state_dict_or_name: Any):
    stack = _lora_context_stack()
    stack.append(_tracked_lora_name(lora_state_dict_or_name))
    try:
        yield
    finally:
        stack.pop()


def _remember_lora_failure(lora_name: str | None) -> None:
    if lora_name is None:
        return

    with _LORA_SOURCE_LOCK:
        _RECENT_LORA_FAILURE["lora_name"] = lora_name
        _RECENT_LORA_FAILURE["timestamp"] = time.monotonic()


def _recent_lora_failure_name() -> str | None:
    with _LORA_SOURCE_LOCK:
        lora_name = _RECENT_LORA_FAILURE.get("lora_name")
        timestamp = float(_RECENT_LORA_FAILURE.get("timestamp") or 0.0)

    if lora_name and time.monotonic() - timestamp <= _RECENT_LORA_FAILURE_TTL_SECONDS:
        return str(lora_name)
    return None


def _resolve_lora_name(lora_name: Any = None) -> str | None:
    return _display_lora_name(lora_name) or current_lora_name() or _recent_lora_failure_name()


def _lora_load_failed_event(lora_name: str | None, reason: str, level: str) -> dict[str, Any]:
    _remember_lora_failure(lora_name)
    model_label = lora_name or "A LoRA model"
    summary = (
        f"{model_label} did not load because {reason}. "
        "Disable that LoRA for this workflow, or use one trained for the active base model."
    )
    return {
        "kind": "lora_load_failed",
        "severity": "warning",
        "level": level or "WARNING",
        "title": "LoRA did not load",
        "summary": summary,
        "message": summary,
        "fingerprint": f"lora_load_failed:{lora_name or 'unknown'}",
        "details": {
            "lora_name": lora_name,
            "reason": reason,
        },
    }


def classify_message(message: str, level: str = "", lora_name: str | None = None) -> dict[str, Any] | None:
    clean_message = str(message).strip()
    clean_level = str(level).upper()
    resolved_lora_name = _resolve_lora_name(lora_name)

    key_match = _LORA_KEY_NOT_LOADED_RE.match(clean_message)
    if key_match:
        return _lora_load_failed_event(
            resolved_lora_name,
            "it does not match the active base model",
            clean_level or "WARNING",
        )

    adapter_match = _ADAPTER_ERROR_RE.match(clean_message)
    if adapter_match and adapter_match.group("adapter").lower() in _LORA_ADAPTERS:
        error = adapter_match.group("error")
        is_shape_error = "shape" in error.lower() or "invalid for input of size" in error.lower()
        return _lora_load_failed_event(
            resolved_lora_name,
            "its weights do not match the active base model" if is_shape_error else "ComfyUI could not apply it",
            clean_level or "ERROR",
        )

    mismatch = _WEIGHT_NOT_MERGED_RE.match(clean_message)
    if mismatch:
        return _lora_load_failed_event(
            resolved_lora_name,
            "its weights do not match the active base model",
            clean_level or "WARNING",
        )

    return None


def install_lora_context_hooks() -> None:
    global _LORA_CONTEXT_HOOKS_INSTALLED
    if _LORA_CONTEXT_HOOKS_INSTALLED:
        return

    try:
        import comfy.sd
        import comfy.utils
    except Exception:
        return

    if not getattr(comfy.utils.load_torch_file, "_session_watchdog_wrapped", False):
        original_load_torch_file = comfy.utils.load_torch_file

        def load_torch_file_with_lora_tracking(ckpt, *args, **kwargs):
            result = original_load_torch_file(ckpt, *args, **kwargs)
            try:
                if isinstance(result, tuple) and result and isinstance(result[0], dict):
                    track_lora_source(result[0], ckpt)
                elif isinstance(result, dict):
                    track_lora_source(result, ckpt)
            except Exception:
                pass
            return result

        load_torch_file_with_lora_tracking._session_watchdog_wrapped = True
        load_torch_file_with_lora_tracking._session_watchdog_original = original_load_torch_file
        comfy.utils.load_torch_file = load_torch_file_with_lora_tracking

    if not getattr(comfy.sd.load_lora_for_models, "_session_watchdog_wrapped", False):
        original_load_lora_for_models = comfy.sd.load_lora_for_models

        def load_lora_for_models_with_context(model, clip, lora, strength_model, strength_clip, *args, **kwargs):
            with lora_context(lora):
                return original_load_lora_for_models(
                    model,
                    clip,
                    lora,
                    strength_model,
                    strength_clip,
                    *args,
                    **kwargs,
                )

        load_lora_for_models_with_context._session_watchdog_wrapped = True
        load_lora_for_models_with_context._session_watchdog_original = original_load_lora_for_models
        comfy.sd.load_lora_for_models = load_lora_for_models_with_context

    _LORA_CONTEXT_HOOKS_INSTALLED = True


class WatchdogEventStore:
    def __init__(self, max_events: int = 200, clock: Callable[[], str] = _utc_now):
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self.max_events = max_events
        self._clock = clock
        self._events: list[dict[str, Any]] = []
        self._index: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        self._lock = threading.RLock()

    def _fingerprint(self, event: dict[str, Any]) -> str:
        return str(event.get("fingerprint") or f"{event.get('kind')}:{event.get('message')}")

    def add_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            fingerprint = self._fingerprint(event)
            now = self._clock()
            existing = self._index.get(fingerprint)
            if existing is not None:
                existing["count"] += 1
                existing["last_seen"] = now
                return copy.deepcopy(existing)

            stored = copy.deepcopy(event)
            stored["id"] = str(self._next_id)
            stored["fingerprint"] = fingerprint
            stored["count"] = 1
            stored["first_seen"] = now
            stored["last_seen"] = now
            self._next_id += 1

            self._events.append(stored)
            self._index[fingerprint] = stored
            while len(self._events) > self.max_events:
                removed = self._events.pop(0)
                self._index.pop(removed["fingerprint"], None)

            return copy.deepcopy(stored)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._index.clear()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            events = [copy.deepcopy(event) for event in reversed(self._events)]
            counts = Counter(event["severity"] for event in self._events)
            return {
                "events": events,
                "counts": dict(counts),
                "max_events": self.max_events,
            }


_STORE = WatchdogEventStore()


def get_store() -> WatchdogEventStore:
    return _STORE


def send_event_to_prompt_server(event: dict[str, Any]) -> None:
    server_module = sys.modules.get("server")
    prompt_server_cls = getattr(server_module, "PromptServer", None)
    prompt_server = getattr(prompt_server_cls, "instance", None)
    if prompt_server is not None:
        prompt_server.send_sync(EVENT_NAME, event)


class SessionWatchdogLoggingHandler(logging.Handler):
    def __init__(
        self,
        store: WatchdogEventStore | None = None,
        sender: Callable[[dict[str, Any]], None] | None = None,
    ):
        super().__init__(level=logging.WARNING)
        self.store = store or get_store()
        self.sender = sender or send_event_to_prompt_server
        self._local = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._local, "handling", False):
            return
        if record.name.startswith("comfyui_session_watchdog"):
            return

        self._local.handling = True
        try:
            event = classify_message(record.getMessage(), record.levelname)
            if event is None:
                return

            stored = self.store.add_event(event)
            if stored.get("count") == 1:
                self.sender(stored)
        except Exception:
            # Logging handlers should never interrupt generation.
            return
        finally:
            self._local.handling = False


def install_logging_handler(store: WatchdogEventStore | None = None) -> SessionWatchdogLoggingHandler:
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, SessionWatchdogLoggingHandler):
            return handler

    handler = SessionWatchdogLoggingHandler(store=store)
    root_logger.addHandler(handler)
    return handler
