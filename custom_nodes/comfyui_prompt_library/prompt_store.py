from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

try:
    import folder_paths
except Exception:
    folder_paths = None


EMPTY_PROMPT_NAME = "<empty: save a prompt first>"
SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_library_path() -> Path:
    if folder_paths is not None:
        user_dir = folder_paths.get_user_directory()
    else:
        user_dir = Path(__file__).resolve().parents[2] / "user"
    return Path(user_dir) / "prompt_library" / "prompts.json"


class PromptStore:
    def __init__(self, path: str | os.PathLike[str] | None = None, clock: Callable[[], str] | None = None):
        self.path = Path(path) if path is not None else default_library_path()
        self.clock = clock or _utc_now

    def dropdown_names(self) -> list[str]:
        names = self.list_names()
        return names or [EMPTY_PROMPT_NAME]

    def list_names(self) -> list[str]:
        return sorted(self._read()["prompts"].keys(), key=str.casefold)

    def list_records(self) -> list[dict[str, str]]:
        prompts = self._read()["prompts"]
        return [self._record(name, prompts[name]) for name in self.list_names()]

    def get(self, name: str) -> dict[str, str]:
        normalized_name = self._normalize_name(name)
        prompts = self._read()["prompts"]
        if normalized_name not in prompts:
            raise KeyError(f"Prompt '{normalized_name}' was not found in the prompt library.")
        return self._record(normalized_name, prompts[normalized_name])

    def save(
        self,
        name: str,
        positive: str,
        negative: str = "",
        notes: str = "",
        overwrite: bool = True,
    ) -> dict[str, str]:
        normalized_name = self._normalize_name(name)
        data = self._read()
        if normalized_name in data["prompts"] and not overwrite:
            raise ValueError(f"Prompt '{normalized_name}' already exists.")

        record = {
            "positive": str(positive),
            "negative": str(negative),
            "notes": str(notes),
            "updated_at": self.clock(),
        }
        data["prompts"][normalized_name] = record
        self._write(data)
        return self._record(normalized_name, record)

    def fingerprint(self) -> str:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return "missing"
        return f"{stat.st_mtime_ns}:{stat.st_size}"

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": SCHEMA_VERSION, "prompts": {}}

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Prompt library JSON is invalid: {self.path}") from exc

        prompts = data.get("prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError(f"Prompt library JSON has invalid 'prompts': {self.path}")
        return {"version": SCHEMA_VERSION, "prompts": prompts}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_path, self.path)

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("Prompt name cannot be empty.")
        if any(char in normalized for char in "\r\n\t"):
            raise ValueError("Prompt name must be a single line.")
        if len(normalized) > 160:
            raise ValueError("Prompt name cannot be longer than 160 characters.")
        if normalized == EMPTY_PROMPT_NAME:
            raise ValueError("Save a prompt before selecting from the prompt library.")
        return normalized

    @staticmethod
    def _record(name: str, record: dict) -> dict[str, str]:
        return {
            "name": name,
            "positive": str(record.get("positive", "")),
            "negative": str(record.get("negative", "")),
            "notes": str(record.get("notes", "")),
            "updated_at": str(record.get("updated_at", "")),
        }
