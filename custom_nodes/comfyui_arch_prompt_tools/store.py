"""Validated, atomic persistence for user-owned Arch PT prompt options."""

from __future__ import annotations

import importlib
import json
import math
import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .catalog import Catalog, CatalogError, FieldRecord


STORE_VERSION = 1
ID_GENERATION_ATTEMPTS = 8
_USER_ID_PATTERN = re.compile(r"^user\.[A-Za-z0-9_-]+$")
_ADDITIVE_GROUP_PREFIX = "user_option:"
_RECORD_KEYS = frozenset(
    {
        "id",
        "label",
        "node",
        "field",
        "group",
        "model_family",
        "phrase",
        "builtin",
        "lora",
        "lora_enabled",
    }
)
_CREATE_KEYS = _RECORD_KEYS - {"id"}
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_DIRECTORY_FSYNC_SUPPORTED = os.name == "posix" and hasattr(os, "O_DIRECTORY")


class OptionStoreError(ValueError):
    """Base error for user-option persistence."""


class OptionValidationError(OptionStoreError):
    """A requested option does not satisfy the user-option contract."""


class OptionStoreDataError(OptionStoreError):
    """The on-disk store cannot be read or safely written."""


class ProtectedOptionError(OptionStoreError):
    """A mutation targeted a protected built-in option."""


class OptionNotFoundError(OptionStoreError):
    """A requested user option does not exist."""


@dataclass(frozen=True)
class UserOption:
    id: str
    label: str
    node: str
    field: str
    group: str
    model_family: str
    phrase: str
    builtin: bool = False
    lora: Mapping[str, Any] | None = None
    lora_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = {
            "id": self.id,
            "label": self.label,
            "node": self.node,
            "field": self.field,
            "group": self.group,
            "model_family": self.model_family,
            "phrase": self.phrase,
            "builtin": False,
            "lora_enabled": self.lora_enabled,
        }
        if self.lora is not None:
            value["lora"] = _thaw_json(self.lora)
        return value


def default_user_options_path() -> Path:
    """Resolve the ComfyUI user path without importing ``folder_paths`` early."""
    try:
        folder_paths = importlib.import_module("folder_paths")
        user_directory = folder_paths.get_user_directory()
    except (ImportError, AttributeError, OSError) as error:
        raise OptionStoreDataError("could not resolve the ComfyUI user directory") from error
    if not isinstance(user_directory, (str, os.PathLike)):
        raise OptionStoreDataError("ComfyUI user directory must be a filesystem path")
    return Path(user_directory) / "arch_prompt_tools" / "options.json"


class OptionStore:
    """A user-option store scoped to one validated built-in catalog."""

    def __init__(
        self,
        catalog: Catalog,
        path: str | os.PathLike[str] | None = None,
        *,
        id_factory: Callable[[], str] | None = None,
    ):
        self.catalog = catalog
        self._explicit_path = None if path is None else Path(path)
        self._resolved_path: Path | None = None
        self._id_factory = id_factory or (lambda: f"user.{uuid.uuid4().hex}")
        self._protected_ids = frozenset(option.id for option in catalog.options)

    @property
    def path(self) -> Path:
        if self._resolved_path is None:
            self._resolved_path = (
                self._explicit_path
                if self._explicit_path is not None
                else default_user_options_path()
            )
        return self._resolved_path

    def list_options(self) -> tuple[UserOption, ...]:
        with _lock_for(self.path):
            return self._read_unlocked()

    def create(self, payload: Mapping[str, Any]) -> UserOption:
        value = _require_mapping(payload, "option")
        unexpected = set(value) - _CREATE_KEYS
        if unexpected:
            raise OptionValidationError(
                f"unexpected option key: {sorted(unexpected)[0]}"
            )
        if value.get("builtin") is True:
            raise OptionValidationError("built-in options are protected")
        field_record = self._field_record(value)
        if field_record.user_selection == "additive" and "group" in value:
            raise OptionValidationError(
                f"group is assigned automatically for additive field "
                f"{value['node']}.{value['field']}; omit group"
            )
        with _lock_for(self.path):
            records = list(self._read_unlocked())
            existing_ids = {item.id for item in records}
            for _attempt in range(ID_GENERATION_ATTEMPTS):
                option_id = self._new_id()
                if (
                    option_id not in self._protected_ids
                    and option_id not in existing_ids
                ):
                    break
            else:
                raise OptionValidationError(
                    "could not generate a unique user option id after "
                    f"{ID_GENERATION_ATTEMPTS} attempts"
                )
            candidate = {**value, "id": option_id}
            if field_record.user_selection == "additive":
                candidate["group"] = _additive_group(option_id)
            record = self._validate_record(candidate)
            records.append(record)
            self._write_unlocked(records)
            return record

    def update(self, option_id: str, changes: Mapping[str, Any]) -> UserOption:
        self._raise_if_protected(option_id)
        patch = _require_mapping(changes, "option update")
        if "id" in patch:
            raise OptionValidationError("user option id cannot be changed")
        unexpected = set(patch) - _CREATE_KEYS
        if unexpected:
            raise OptionValidationError(
                f"unexpected option key: {sorted(unexpected)[0]}"
            )
        if patch.get("builtin") is True:
            raise OptionValidationError("built-in options are protected")
        with _lock_for(self.path):
            records = list(self._read_unlocked())
            index = _record_index(records, option_id)
            current = records[index].to_dict()
            candidate = {**current, **patch, "id": option_id}
            field_record = self._field_record(candidate)
            if field_record.user_selection == "additive":
                expected_group = _additive_group(option_id)
                if "group" in patch and patch["group"] != expected_group:
                    raise OptionValidationError(
                        f"additive user option group must remain stable: "
                        f"{expected_group}"
                    )
                candidate["group"] = expected_group
            updated = self._validate_record(candidate)
            records[index] = updated
            self._write_unlocked(records)
            return updated

    def delete(self, option_id: str) -> UserOption:
        self._raise_if_protected(option_id)
        with _lock_for(self.path):
            records = list(self._read_unlocked())
            index = _record_index(records, option_id)
            removed = records.pop(index)
            self._write_unlocked(records)
            return removed

    def _raise_if_protected(self, option_id: str) -> None:
        if option_id in self._protected_ids:
            raise ProtectedOptionError(f"built-in option is protected: {option_id}")

    def _new_id(self) -> str:
        option_id = self._id_factory()
        if not isinstance(option_id, str) or not _USER_ID_PATTERN.fullmatch(option_id):
            raise OptionValidationError("generated user option id is not a valid opaque id")
        return option_id

    def _field_record(self, value: Mapping[str, Any]) -> FieldRecord:
        node = _nonempty_string(value.get("node"), "node")
        field = _nonempty_string(value.get("field"), "field")
        try:
            return self.catalog.field(node, field)
        except CatalogError as error:
            raise OptionValidationError(str(error)) from error

    def _read_unlocked(self) -> tuple[UserOption, ...]:
        if not self.path.exists():
            return ()
        try:
            with self.path.open("r", encoding="utf-8") as source:
                envelope = json.load(source)
        except json.JSONDecodeError as error:
            raise OptionStoreDataError(
                f"user options JSON is invalid: {self.path}"
            ) from error
        except UnicodeError as error:
            raise OptionStoreDataError(
                f"user options file has invalid UTF-8: {self.path}"
            ) from error
        except OSError as error:
            raise OptionStoreDataError(
                f"could not read user options file: {self.path}"
            ) from error

        try:
            root = _require_mapping(envelope, "user options envelope")
            if set(root) != {"version", "options"}:
                raise OptionValidationError(
                    "user options envelope must contain only version and options"
                )
            version = root["version"]
            if isinstance(version, bool) or not isinstance(version, int):
                raise OptionValidationError("user options version must be an integer")
            if version != STORE_VERSION:
                raise OptionValidationError(
                    f"unsupported user options version: {version}"
                )
            raw_options = root["options"]
            if not isinstance(raw_options, list):
                raise OptionValidationError("user options must be a list")
            records = tuple(self._validate_record(item) for item in raw_options)
            ids = [record.id for record in records]
            if len(set(ids)) != len(ids):
                raise OptionValidationError("user option ids must be unique")
            return records
        except (CatalogError, OptionValidationError) as error:
            raise OptionStoreDataError(
                f"user options file is invalid: {self.path}: {error}"
            ) from error

    def _validate_record(self, raw: Mapping[str, Any]) -> UserOption:
        value = _require_mapping(raw, "user option")
        unexpected = set(value) - _RECORD_KEYS
        if unexpected:
            raise OptionValidationError(
                f"unexpected option key: {sorted(unexpected)[0]}"
            )
        required = {
            "id",
            "label",
            "node",
            "field",
            "group",
            "model_family",
            "phrase",
            "builtin",
        }
        missing = required - set(value)
        if missing:
            raise OptionValidationError(
                f"user option is missing {sorted(missing)[0]}"
            )
        option_id = _nonempty_string(value["id"], "option id")
        if not _USER_ID_PATTERN.fullmatch(option_id):
            raise OptionValidationError("user option id must be an opaque user id")
        if option_id in self._protected_ids:
            raise OptionValidationError("user option id collides with a protected built-in")
        builtin = value["builtin"]
        if not isinstance(builtin, bool):
            raise OptionValidationError("builtin must be boolean")
        if builtin:
            raise OptionValidationError("built-in options are protected")
        node = _nonempty_string(value["node"], "node")
        field = _nonempty_string(value["field"], "field")
        model_family = _nonempty_string(value["model_family"], "model_family")
        try:
            field_record = self.catalog.field(node, field)
        except CatalogError as error:
            raise OptionValidationError(str(error)) from error
        if model_family not in self.catalog.families:
            raise OptionValidationError(f"unknown model family: {model_family}")
        group = _nonempty_string(value["group"], "group")
        if field_record.user_selection == "additive":
            expected_group = _additive_group(option_id)
            if group != expected_group:
                raise OptionValidationError(
                    f"additive user option group must be stable: {expected_group}"
                )
        elif group not in field_record.groups:
            choices = ", ".join(field_record.groups)
            raise OptionValidationError(
                f"unknown group: {node}.{field}.{group}; choose one of: {choices}"
            )
        lora_enabled = value.get("lora_enabled", False)
        if not isinstance(lora_enabled, bool):
            raise OptionValidationError("lora_enabled must be boolean")
        raw_lora = value.get("lora")
        if raw_lora is None:
            if lora_enabled:
                raise OptionValidationError("lora_enabled requires lora metadata")
            lora = None
        else:
            if not isinstance(raw_lora, Mapping):
                raise OptionValidationError("lora metadata must be an object")
            lora = _freeze_lora(raw_lora)
        return UserOption(
            id=option_id,
            label=_nonempty_string(value["label"], "label"),
            node=node,
            field=field,
            group=group,
            model_family=model_family,
            phrase=_nonempty_string(value["phrase"], "phrase"),
            builtin=False,
            lora=lora,
            lora_enabled=lora_enabled,
        )

    def _write_unlocked(self, records: list[UserOption]) -> None:
        envelope = {
            "version": STORE_VERSION,
            "options": [record.to_dict() for record in records],
        }
        temp_path: Path | None = None
        descriptor: int | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            temp_path = Path(temp_name)
            target = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
            descriptor = None
            with target:
                json.dump(
                    envelope,
                    target,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_path, self.path)
            _fsync_directory(self.path.parent)
            temp_path = None
        except (OSError, TypeError, ValueError) as error:
            raise OptionStoreDataError(
                f"could not write user options file: {self.path}"
            ) from error
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _fsync_directory(directory: Path) -> None:
    """Best-effort durability for the directory entry created by ``replace``."""
    if not _DIRECTORY_FSYNC_SUPPORTED:
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        os.fsync(descriptor)
    except (AttributeError, OSError, TypeError):
        pass
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _record_index(records: list[UserOption], option_id: str) -> int:
    for index, record in enumerate(records):
        if record.id == option_id:
            return index
    raise OptionNotFoundError(f"user option not found: {option_id}")


def _additive_group(option_id: str) -> str:
    return f"{_ADDITIVE_GROUP_PREFIX}{option_id}"


def _lock_for(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve(strict=False)))
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OptionValidationError(f"{name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise OptionValidationError(f"{name} keys must be strings")
    return value


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OptionValidationError(f"{name} must be a non-empty string")
    return value.strip()


def _freeze_lora(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(item_key, str) for item_key in value):
            raise OptionValidationError("lora metadata keys must be strings")
        return MappingProxyType(
            {
                item_key: _freeze_lora(item, key=item_key)
                for item_key, item in value.items()
            }
        )
    if isinstance(value, list):
        return tuple(_freeze_lora(item) for item in value)
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        if key in {"strength", "weight"}:
            raise OptionValidationError(f"lora {key} must be a number, not a boolean")
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OptionValidationError("lora numbers must be finite")
        return value
    raise OptionValidationError("lora metadata must contain only JSON values")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
