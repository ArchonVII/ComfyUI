"""Transactional SQLite catalog for the local reference library."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from pathlib import PureWindowsPath
import sqlite3
from typing import Any, Iterator
from uuid import UUID, uuid4


SCHEMA_VERSION = 1
COLLECTION_KINDS = frozenset({"subject", "environment"})
DEFAULT_PROFILE_NAME = "Default"
SELECTION_POLICIES = frozenset({"random", "seeded", "sequential"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_kind(kind: Any) -> str:
    if kind not in COLLECTION_KINDS:
        raise ValueError("collection kind must be 'subject' or 'environment'")
    return str(kind)


def _normalize_name(name: Any, *, label: str = "name") -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{label} must be a non-empty string")
    normalized = name.strip()
    if any(character in normalized for character in "\r\n\t"):
        raise ValueError(f"{label} must be a single line")
    if len(normalized) > 160:
        raise ValueError(f"{label} cannot exceed 160 characters")
    return normalized


def _normalize_id(value: Any, *, label: str = "ID") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{label} must be a canonical UUID") from exc
    canonical = str(parsed)
    if canonical != value.lower():
        raise ValueError(f"{label} must be a canonical UUID")
    return canonical


class ReferenceLibraryStore:
    """Owns the metadata catalog for one local ComfyUI installation."""

    def __init__(self, path: str | Path):
        self.path = str(Path(path))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS collections (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('subject', 'environment')),
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(kind, name_key)
                );

                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL UNIQUE,
                    relative_path TEXT NOT NULL UNIQUE,
                    original_filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    width INTEGER NOT NULL CHECK(width > 0),
                    height INTEGER NOT NULL CHECK(height > 0),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS collection_images (
                    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                    image_id TEXT NOT NULL REFERENCES images(id) ON DELETE RESTRICT,
                    notes TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(collection_id, image_id)
                );

                CREATE TABLE IF NOT EXISTS tags (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE,
                    group_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS collection_image_tags (
                    collection_id TEXT NOT NULL,
                    image_id TEXT NOT NULL,
                    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY(collection_id, image_id, tag_id),
                    FOREIGN KEY(collection_id, image_id)
                        REFERENCES collection_images(collection_id, image_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    model_family TEXT NOT NULL DEFAULT 'default',
                    positive_prompt TEXT NOT NULL DEFAULT '',
                    negative_prompt TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(collection_id, name_key)
                );

                CREATE TABLE IF NOT EXISTS profile_loras (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL CHECK(position >= 0),
                    lora_name TEXT NOT NULL,
                    strength_model REAL NOT NULL,
                    strength_clip REAL NOT NULL,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
                    UNIQUE(profile_id, position)
                );

                CREATE TABLE IF NOT EXISTS selection_state (
                    collection_id TEXT PRIMARY KEY REFERENCES collections(id) ON DELETE CASCADE,
                    policy TEXT NOT NULL DEFAULT 'random' CHECK(policy IN ('random', 'seeded', 'sequential')),
                    seed INTEGER NOT NULL DEFAULT 1,
                    cursor INTEGER NOT NULL DEFAULT 0 CHECK(cursor >= 0),
                    reroll_count INTEGER NOT NULL DEFAULT 0 CHECK(reroll_count >= 0),
                    include_all_json TEXT NOT NULL DEFAULT '[]',
                    include_any_json TEXT NOT NULL DEFAULT '[]',
                    exclude_json TEXT NOT NULL DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS selection_slots (
                    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                    slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 4),
                    image_id TEXT REFERENCES images(id) ON DELETE SET NULL,
                    pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0, 1)),
                    PRIMARY KEY(collection_id, slot)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_collections_kind_name
                    ON collections(kind, name_key);
                CREATE INDEX IF NOT EXISTS idx_membership_image
                    ON collection_images(image_id);
                CREATE INDEX IF NOT EXISTS idx_membership_tags_tag
                    ON collection_image_tags(tag_id, collection_id, image_id);
                CREATE INDEX IF NOT EXISTS idx_profiles_collection
                    ON profiles(collection_id, name_key);
                """
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def schema_version(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def create_collection(self, kind: Any, name: Any, description: Any = "") -> dict[str, Any]:
        normalized_kind = _normalize_kind(kind)
        normalized_name = _normalize_name(name, label="collection name")
        normalized_description = str(description or "")
        now = _utc_now()
        collection_id = str(uuid4())
        profile_id = str(uuid4())
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO collections(id, kind, name, name_key, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        collection_id,
                        normalized_kind,
                        normalized_name,
                        normalized_name.casefold(),
                        normalized_description,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO profiles(
                        id, collection_id, name, name_key, model_family,
                        positive_prompt, negative_prompt, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'default', '', '', ?, ?)
                    """,
                    (profile_id, collection_id, DEFAULT_PROFILE_NAME, DEFAULT_PROFILE_NAME.casefold(), now, now),
                )
                connection.execute(
                    "INSERT INTO selection_state(collection_id) VALUES (?)",
                    (collection_id,),
                )
                connection.executemany(
                    "INSERT INTO selection_slots(collection_id, slot, image_id, pinned) VALUES (?, ?, NULL, 0)",
                    ((collection_id, slot) for slot in range(1, 5)),
                )
                return self._fetch_collection(connection, collection_id)
        except sqlite3.IntegrityError as exc:
            if "collections.kind, collections.name_key" in str(exc):
                raise ValueError(
                    f"a {normalized_kind} collection named '{normalized_name}' already exists"
                ) from exc
            raise

    def get_collection(self, collection_id: Any) -> dict[str, Any]:
        normalized_id = _normalize_id(collection_id, label="collection ID")
        with self._connection() as connection:
            return self._fetch_collection(connection, normalized_id)

    def list_collections(self, kind: Any | None = None) -> list[dict[str, Any]]:
        with self._connection() as connection:
            if kind is None:
                rows = connection.execute(
                    "SELECT * FROM collections ORDER BY kind, name_key, id"
                ).fetchall()
            else:
                normalized_kind = _normalize_kind(kind)
                rows = connection.execute(
                    "SELECT * FROM collections WHERE kind = ? ORDER BY name_key, id",
                    (normalized_kind,),
                ).fetchall()
            return [self._decode_collection(row) for row in rows]

    def update_collection(
        self,
        collection_id: Any,
        *,
        name: Any | None = None,
        description: Any | None = None,
    ) -> dict[str, Any]:
        normalized_id = _normalize_id(collection_id, label="collection ID")
        with self._connection() as connection:
            current = self._fetch_collection(connection, normalized_id)
            next_name = current["name"] if name is None else _normalize_name(name, label="collection name")
            next_description = current["description"] if description is None else str(description)
            try:
                connection.execute(
                    """
                    UPDATE collections
                    SET name = ?, name_key = ?, description = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (next_name, next_name.casefold(), next_description, _utc_now(), normalized_id),
                )
            except sqlite3.IntegrityError as exc:
                if "collections.kind, collections.name_key" in str(exc):
                    raise ValueError(
                        f"a {current['kind']} collection named '{next_name}' already exists"
                    ) from exc
                raise
            return self._fetch_collection(connection, normalized_id)

    def delete_collection(self, collection_id: Any) -> dict[str, Any]:
        normalized_id = _normalize_id(collection_id, label="collection ID")
        with self._connection() as connection:
            collection = self._fetch_collection(connection, normalized_id)
            connection.execute("DELETE FROM collections WHERE id = ?", (normalized_id,))
            connection.execute(
                "DELETE FROM settings WHERE key = ? AND value_json = ?",
                (f"active_{collection['kind']}", json.dumps(normalized_id)),
            )
            connection.execute(
                "DELETE FROM settings WHERE key = ?",
                (f"active_profile_{normalized_id}",),
            )
            return collection

    def set_active(self, kind: Any, collection_id: Any | None) -> dict[str, Any] | None:
        normalized_kind = _normalize_kind(kind)
        key = f"active_{normalized_kind}"
        with self._connection() as connection:
            if collection_id is None:
                connection.execute("DELETE FROM settings WHERE key = ?", (key,))
                return None
            normalized_id = _normalize_id(collection_id, label="collection ID")
            collection = self._fetch_collection(connection, normalized_id)
            if collection["kind"] != normalized_kind:
                raise ValueError("active collection kind does not match the requested kind")
            connection.execute(
                """
                INSERT INTO settings(key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (key, json.dumps(normalized_id)),
            )
            return collection

    def get_active(self, kind: Any) -> dict[str, Any] | None:
        normalized_kind = _normalize_kind(kind)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = ?",
                (f"active_{normalized_kind}",),
            ).fetchone()
            if row is None:
                return None
            try:
                collection_id = json.loads(row["value_json"])
                collection = self._fetch_collection(connection, collection_id)
            except (KeyError, TypeError, ValueError):
                return None
            return collection if collection["kind"] == normalized_kind else None

    def list_profiles(self, collection_id: Any) -> list[dict[str, Any]]:
        normalized_id = _normalize_id(collection_id, label="collection ID")
        with self._connection() as connection:
            self._fetch_collection(connection, normalized_id)
            rows = connection.execute(
                """
                SELECT * FROM profiles
                WHERE collection_id = ?
                ORDER BY CASE WHEN name_key = 'default' THEN 0 ELSE 1 END, name_key, id
                """,
                (normalized_id,),
            ).fetchall()
            return [
                self._decode_profile(row, self._profile_loras(connection, row["id"]))
                for row in rows
            ]

    def create_profile(
        self,
        collection_id: Any,
        *,
        name: Any,
        model_family: Any = "default",
        positive_prompt: Any = "",
        negative_prompt: Any = "",
        loras: Any = (),
    ) -> dict[str, Any]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        normalized_name = _normalize_name(name, label="profile name")
        normalized_family = self._normalize_model_family(model_family)
        normalized_loras = self._normalize_loras(loras)
        profile_id = str(uuid4())
        now = _utc_now()
        try:
            with self._connection() as connection:
                self._fetch_collection(connection, normalized_collection_id)
                connection.execute(
                    """
                    INSERT INTO profiles(
                        id, collection_id, name, name_key, model_family,
                        positive_prompt, negative_prompt, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id,
                        normalized_collection_id,
                        normalized_name,
                        normalized_name.casefold(),
                        normalized_family,
                        str(positive_prompt or ""),
                        str(negative_prompt or ""),
                        now,
                        now,
                    ),
                )
                self._replace_profile_loras(connection, profile_id, normalized_loras)
                return self._fetch_profile(connection, profile_id)
        except sqlite3.IntegrityError as exc:
            if "profiles.collection_id, profiles.name_key" in str(exc):
                raise ValueError(f"profile '{normalized_name}' already exists in this collection") from exc
            raise

    def get_profile(self, profile_id: Any) -> dict[str, Any]:
        normalized_id = _normalize_id(profile_id, label="profile ID")
        with self._connection() as connection:
            return self._fetch_profile(connection, normalized_id)

    def update_profile(
        self,
        profile_id: Any,
        *,
        name: Any | None = None,
        model_family: Any | None = None,
        positive_prompt: Any | None = None,
        negative_prompt: Any | None = None,
        loras: Any | None = None,
    ) -> dict[str, Any]:
        normalized_id = _normalize_id(profile_id, label="profile ID")
        normalized_loras = None if loras is None else self._normalize_loras(loras)
        with self._connection() as connection:
            current = self._fetch_profile(connection, normalized_id)
            next_name = current["name"] if name is None else _normalize_name(name, label="profile name")
            if current["name"].casefold() == DEFAULT_PROFILE_NAME.casefold() and next_name.casefold() != DEFAULT_PROFILE_NAME.casefold():
                raise ValueError("the Default profile cannot be renamed")
            next_family = current["model_family"] if model_family is None else self._normalize_model_family(model_family)
            next_positive = current["positive_prompt"] if positive_prompt is None else str(positive_prompt)
            next_negative = current["negative_prompt"] if negative_prompt is None else str(negative_prompt)
            try:
                connection.execute(
                    """
                    UPDATE profiles
                    SET name = ?, name_key = ?, model_family = ?, positive_prompt = ?,
                        negative_prompt = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        next_name,
                        next_name.casefold(),
                        next_family,
                        next_positive,
                        next_negative,
                        _utc_now(),
                        normalized_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "profiles.collection_id, profiles.name_key" in str(exc):
                    raise ValueError(f"profile '{next_name}' already exists in this collection") from exc
                raise
            if normalized_loras is not None:
                self._replace_profile_loras(connection, normalized_id, normalized_loras)
            return self._fetch_profile(connection, normalized_id)

    def delete_profile(self, profile_id: Any) -> dict[str, Any]:
        normalized_id = _normalize_id(profile_id, label="profile ID")
        with self._connection() as connection:
            profile = self._fetch_profile(connection, normalized_id)
            if profile["name"].casefold() == DEFAULT_PROFILE_NAME.casefold():
                raise ValueError("the Default profile cannot be deleted")
            connection.execute("DELETE FROM profiles WHERE id = ?", (normalized_id,))
            connection.execute(
                "DELETE FROM settings WHERE key = ? AND value_json = ?",
                (f"active_profile_{profile['collection_id']}", json.dumps(normalized_id)),
            )
            return profile

    def set_active_profile(self, collection_id: Any, profile_id: Any) -> dict[str, Any]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        normalized_profile_id = _normalize_id(profile_id, label="profile ID")
        with self._connection() as connection:
            self._fetch_collection(connection, normalized_collection_id)
            profile = self._fetch_profile(connection, normalized_profile_id)
            if profile["collection_id"] != normalized_collection_id:
                raise ValueError("active profile does not belong to the collection")
            connection.execute(
                """
                INSERT INTO settings(key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (f"active_profile_{normalized_collection_id}", json.dumps(normalized_profile_id)),
            )
            return profile

    def get_active_profile(self, collection_id: Any) -> dict[str, Any]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        with self._connection() as connection:
            self._fetch_collection(connection, normalized_collection_id)
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = ?",
                (f"active_profile_{normalized_collection_id}",),
            ).fetchone()
            if row is not None:
                try:
                    profile = self._fetch_profile(connection, json.loads(row["value_json"]))
                    if profile["collection_id"] == normalized_collection_id:
                        return profile
                except (KeyError, TypeError, ValueError):
                    pass
            default = connection.execute(
                "SELECT id FROM profiles WHERE collection_id = ? AND name_key = ?",
                (normalized_collection_id, DEFAULT_PROFILE_NAME.casefold()),
            ).fetchone()
            if default is None:
                raise KeyError("Default profile not found")
            return self._fetch_profile(connection, default["id"])

    def get_selection(self, collection_id: Any) -> dict[str, Any]:
        normalized_id = _normalize_id(collection_id, label="collection ID")
        with self._connection() as connection:
            return self._get_selection(connection, normalized_id)

    def register_image(
        self,
        collection_id: Any,
        *,
        sha256: str,
        relative_path: str,
        original_filename: str,
        media_type: str,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        if not isinstance(sha256, str) or len(sha256) != 64 or any(
            character not in "0123456789abcdef" for character in sha256
        ):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        if not isinstance(relative_path, str) or not relative_path or ".." in relative_path.replace("\\", "/").split("/"):
            raise ValueError("image path must be a safe relative path")
        if isinstance(width, bool) or not isinstance(width, int) or width < 1:
            raise ValueError("image width must be a positive integer")
        if isinstance(height, bool) or not isinstance(height, int) or height < 1:
            raise ValueError("image height must be a positive integer")
        now = _utc_now()
        with self._connection() as connection:
            self._fetch_collection(connection, normalized_collection_id)
            row = connection.execute("SELECT * FROM images WHERE sha256 = ?", (sha256,)).fetchone()
            image_created = row is None
            if image_created:
                image_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO images(
                        id, sha256, relative_path, original_filename, media_type,
                        width, height, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        image_id,
                        sha256,
                        relative_path.replace("\\", "/"),
                        str(original_filename),
                        str(media_type),
                        width,
                        height,
                        now,
                    ),
                )
                row = connection.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM collection_images WHERE collection_id = ?",
                (normalized_collection_id,),
            ).fetchone()[0]
            inserted = connection.execute(
                """
                INSERT INTO collection_images(collection_id, image_id, notes, position, created_at)
                VALUES (?, ?, '', ?, ?)
                ON CONFLICT(collection_id, image_id) DO NOTHING
                """,
                (normalized_collection_id, row["id"], position, now),
            )
            return {
                "image": self._decode_image(row, []),
                "image_created": image_created,
                "membership_created": inserted.rowcount == 1,
            }

    def add_image_membership(self, collection_id: Any, image_id: Any) -> dict[str, Any]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        normalized_image_id = _normalize_id(image_id, label="image ID")
        with self._connection() as connection:
            self._fetch_collection(connection, normalized_collection_id)
            image = self._fetch_image(connection, normalized_image_id)
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM collection_images WHERE collection_id = ?",
                (normalized_collection_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO collection_images(collection_id, image_id, notes, position, created_at)
                VALUES (?, ?, '', ?, ?)
                ON CONFLICT(collection_id, image_id) DO NOTHING
                """,
                (normalized_collection_id, normalized_image_id, position, _utc_now()),
            )
            return self._decode_image(image, self._tags_for_images(connection, normalized_collection_id, [normalized_image_id]).get(normalized_image_id, []))

    def get_image(self, image_id: Any) -> dict[str, Any]:
        normalized_id = _normalize_id(image_id, label="image ID")
        with self._connection() as connection:
            return self._decode_image(self._fetch_image(connection, normalized_id), [])

    def list_orphan_images(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT i.*
                FROM images i
                WHERE NOT EXISTS (
                    SELECT 1 FROM collection_images ci WHERE ci.image_id = i.id
                )
                ORDER BY i.created_at, i.id
                """
            ).fetchall()
            return [self._decode_image(row, []) for row in rows]

    def list_images(
        self,
        collection_id: Any,
        *,
        include_all: Any = (),
        include_any: Any = (),
        exclude: Any = (),
    ) -> list[dict[str, Any]]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        all_ids = self._normalize_id_list(include_all, label="include_all tag IDs")
        any_ids = self._normalize_id_list(include_any, label="include_any tag IDs")
        exclude_ids = self._normalize_id_list(exclude, label="exclude tag IDs")
        clauses = ["ci.collection_id = ?"]
        parameters: list[Any] = [normalized_collection_id]
        if all_ids:
            placeholders = ",".join("?" for _ in all_ids)
            clauses.append(
                f"""(
                    SELECT COUNT(DISTINCT cit.tag_id)
                    FROM collection_image_tags cit
                    WHERE cit.collection_id = ci.collection_id
                      AND cit.image_id = ci.image_id
                      AND cit.tag_id IN ({placeholders})
                ) = ?"""
            )
            parameters.extend(all_ids)
            parameters.append(len(all_ids))
        if any_ids:
            placeholders = ",".join("?" for _ in any_ids)
            clauses.append(
                f"""EXISTS (
                    SELECT 1 FROM collection_image_tags cit
                    WHERE cit.collection_id = ci.collection_id
                      AND cit.image_id = ci.image_id
                      AND cit.tag_id IN ({placeholders})
                )"""
            )
            parameters.extend(any_ids)
        if exclude_ids:
            placeholders = ",".join("?" for _ in exclude_ids)
            clauses.append(
                f"""NOT EXISTS (
                    SELECT 1 FROM collection_image_tags cit
                    WHERE cit.collection_id = ci.collection_id
                      AND cit.image_id = ci.image_id
                      AND cit.tag_id IN ({placeholders})
                )"""
            )
            parameters.extend(exclude_ids)
        with self._connection() as connection:
            self._fetch_collection(connection, normalized_collection_id)
            rows = connection.execute(
                f"""
                SELECT i.*, ci.notes, ci.position
                FROM collection_images ci
                JOIN images i ON i.id = ci.image_id
                WHERE {' AND '.join(clauses)}
                ORDER BY ci.position, i.id
                """,
                parameters,
            ).fetchall()
            tags = self._tags_for_images(
                connection, normalized_collection_id, [row["id"] for row in rows]
            )
            return [self._decode_image(row, tags.get(row["id"], [])) for row in rows]

    def create_tag(self, name: Any, group_name: Any = "") -> dict[str, Any]:
        normalized_name = _normalize_name(name, label="tag name")
        normalized_group = str(group_name or "").strip()
        if len(normalized_group) > 80 or any(character in normalized_group for character in "\r\n\t"):
            raise ValueError("tag group must be a single line up to 80 characters")
        tag_id = str(uuid4())
        now = _utc_now()
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO tags(id, name, name_key, group_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (tag_id, normalized_name, normalized_name.casefold(), normalized_group, now, now),
                )
                return self._fetch_tag(connection, tag_id)
        except sqlite3.IntegrityError as exc:
            if "tags.name_key" in str(exc):
                raise ValueError(f"tag '{normalized_name}' already exists") from exc
            raise

    def list_tags(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tags ORDER BY group_name COLLATE NOCASE, name_key, id"
            ).fetchall()
            return [self._decode_tag(row) for row in rows]

    def update_tag(self, tag_id: Any, *, name: Any | None = None, group_name: Any | None = None) -> dict[str, Any]:
        normalized_id = _normalize_id(tag_id, label="tag ID")
        with self._connection() as connection:
            current = self._fetch_tag(connection, normalized_id)
            next_name = current["name"] if name is None else _normalize_name(name, label="tag name")
            next_group = current["group_name"] if group_name is None else str(group_name).strip()
            if len(next_group) > 80 or any(character in next_group for character in "\r\n\t"):
                raise ValueError("tag group must be a single line up to 80 characters")
            try:
                connection.execute(
                    "UPDATE tags SET name = ?, name_key = ?, group_name = ?, updated_at = ? WHERE id = ?",
                    (next_name, next_name.casefold(), next_group, _utc_now(), normalized_id),
                )
            except sqlite3.IntegrityError as exc:
                if "tags.name_key" in str(exc):
                    raise ValueError(f"tag '{next_name}' already exists") from exc
                raise
            return self._fetch_tag(connection, normalized_id)

    def delete_tag(self, tag_id: Any) -> dict[str, Any]:
        normalized_id = _normalize_id(tag_id, label="tag ID")
        with self._connection() as connection:
            tag = self._fetch_tag(connection, normalized_id)
            connection.execute("DELETE FROM tags WHERE id = ?", (normalized_id,))
            return tag

    def batch_update_tags(
        self,
        collection_id: Any,
        image_ids: Any,
        *,
        add_tag_ids: Any = (),
        remove_tag_ids: Any = (),
    ) -> list[dict[str, Any]]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        normalized_images = self._normalize_id_list(image_ids, label="image IDs")
        additions = self._normalize_id_list(add_tag_ids, label="add tag IDs")
        removals = self._normalize_id_list(remove_tag_ids, label="remove tag IDs")
        if not normalized_images:
            raise ValueError("image IDs must not be empty")
        with self._connection() as connection:
            self._fetch_collection(connection, normalized_collection_id)
            self._require_memberships(connection, normalized_collection_id, normalized_images)
            self._require_tags(connection, additions + removals)
            for image_id in normalized_images:
                connection.executemany(
                    """
                    INSERT INTO collection_image_tags(collection_id, image_id, tag_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(collection_id, image_id, tag_id) DO NOTHING
                    """,
                    ((normalized_collection_id, image_id, tag_id) for tag_id in additions),
                )
                connection.executemany(
                    "DELETE FROM collection_image_tags WHERE collection_id = ? AND image_id = ? AND tag_id = ?",
                    ((normalized_collection_id, image_id, tag_id) for tag_id in removals),
                )
        return self.list_images(normalized_collection_id)

    def set_selection(
        self,
        collection_id: Any,
        *,
        filters: Any | None = None,
        slots: Any | None = None,
        policy: Any | None = None,
        seed: Any | None = None,
    ) -> dict[str, Any]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        with self._connection() as connection:
            current = self._get_selection(connection, normalized_collection_id)
            next_policy = current["policy"] if policy is None else self._normalize_policy(policy)
            next_seed = current["seed"] if seed is None else self._normalize_seed(seed)
            next_filters = current["filters"] if filters is None else self._normalize_filters(filters)
            self._require_tags(
                connection,
                next_filters["include_all"] + next_filters["include_any"] + next_filters["exclude"],
            )
            connection.execute(
                """
                UPDATE selection_state
                SET policy = ?, seed = ?, include_all_json = ?, include_any_json = ?, exclude_json = ?
                WHERE collection_id = ?
                """,
                (
                    next_policy,
                    next_seed,
                    json.dumps(next_filters["include_all"]),
                    json.dumps(next_filters["include_any"]),
                    json.dumps(next_filters["exclude"]),
                    normalized_collection_id,
                ),
            )
            if slots is not None:
                normalized_slots = self._normalize_slots(slots)
                merged_by_slot = {item["slot"]: dict(item) for item in current["slots"]}
                merged_by_slot.update({item["slot"]: item for item in normalized_slots})
                merged_slots = self._normalize_slots(
                    list(merged_by_slot.values()), require_all=True
                )
                image_ids = [item["image_id"] for item in merged_slots if item["image_id"]]
                self._require_memberships(connection, normalized_collection_id, image_ids)
                for item in normalized_slots:
                    connection.execute(
                        "UPDATE selection_slots SET image_id = ?, pinned = ? WHERE collection_id = ? AND slot = ?",
                        (
                            item["image_id"],
                            int(item["pinned"]),
                            normalized_collection_id,
                            item["slot"],
                        ),
                    )
            return self._get_selection(connection, normalized_collection_id)

    def commit_reroll(
        self,
        collection_id: Any,
        *,
        expected_reroll_count: int,
        slots: Any,
        cursor: int,
    ) -> dict[str, Any]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        normalized_slots = self._normalize_slots(slots, require_all=True)
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ValueError("selection cursor must be a non-negative integer")
        with self._connection() as connection:
            current = self._get_selection(connection, normalized_collection_id)
            if current["reroll_count"] != expected_reroll_count:
                raise ValueError("selection changed concurrently; refresh and reroll again")
            image_ids = [item["image_id"] for item in normalized_slots if item["image_id"]]
            self._require_memberships(connection, normalized_collection_id, image_ids)
            updated = connection.execute(
                """
                UPDATE selection_state
                SET cursor = ?, reroll_count = reroll_count + 1
                WHERE collection_id = ? AND reroll_count = ?
                """,
                (cursor, normalized_collection_id, expected_reroll_count),
            )
            if updated.rowcount != 1:
                raise ValueError("selection changed concurrently; refresh and reroll again")
            for item in normalized_slots:
                connection.execute(
                    "UPDATE selection_slots SET image_id = ?, pinned = ? WHERE collection_id = ? AND slot = ?",
                    (item["image_id"], int(item["pinned"]), normalized_collection_id, item["slot"]),
                )
            return self._get_selection(connection, normalized_collection_id)

    def unlink_image(self, collection_id: Any, image_id: Any) -> dict[str, Any]:
        normalized_collection_id = _normalize_id(collection_id, label="collection ID")
        normalized_image_id = _normalize_id(image_id, label="image ID")
        with self._connection() as connection:
            image = self._fetch_image(connection, normalized_image_id)
            deleted = connection.execute(
                "DELETE FROM collection_images WHERE collection_id = ? AND image_id = ?",
                (normalized_collection_id, normalized_image_id),
            )
            if deleted.rowcount != 1:
                raise KeyError("image membership not found")
            connection.execute(
                "UPDATE selection_slots SET image_id = NULL, pinned = 0 WHERE collection_id = ? AND image_id = ?",
                (normalized_collection_id, normalized_image_id),
            )
            return self._decode_image(image, [])

    def membership_count(self, image_id: Any) -> int:
        normalized_id = _normalize_id(image_id, label="image ID")
        with self._connection() as connection:
            self._fetch_image(connection, normalized_id)
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM collection_images WHERE image_id = ?", (normalized_id,)
                ).fetchone()[0]
            )

    def delete_image_record(self, image_id: Any) -> dict[str, Any]:
        normalized_id = _normalize_id(image_id, label="image ID")
        with self._connection() as connection:
            image = self._fetch_image(connection, normalized_id)
            count = connection.execute(
                "SELECT COUNT(*) FROM collection_images WHERE image_id = ?", (normalized_id,)
            ).fetchone()[0]
            if count:
                raise ValueError(f"image still belongs to {count} collection(s)")
            connection.execute("DELETE FROM images WHERE id = ?", (normalized_id,))
            return self._decode_image(image, [])

    def fingerprint(self) -> str:
        try:
            stat = Path(self.path).stat()
        except FileNotFoundError:
            return "missing"
        return f"{stat.st_mtime_ns}:{stat.st_size}"

    def _get_selection(self, connection: sqlite3.Connection, collection_id: str) -> dict[str, Any]:
        self._fetch_collection(connection, collection_id)
        state = connection.execute(
            "SELECT * FROM selection_state WHERE collection_id = ?", (collection_id,)
        ).fetchone()
        slots = connection.execute(
            "SELECT slot, image_id, pinned FROM selection_slots WHERE collection_id = ? ORDER BY slot",
            (collection_id,),
        ).fetchall()
        return {
            "collection_id": collection_id,
            "policy": state["policy"],
            "seed": state["seed"],
            "cursor": state["cursor"],
            "reroll_count": state["reroll_count"],
            "filters": {
                "include_all": json.loads(state["include_all_json"]),
                "include_any": json.loads(state["include_any_json"]),
                "exclude": json.loads(state["exclude_json"]),
            },
            "slots": [
                {
                    "slot": int(row["slot"]),
                    "image_id": row["image_id"],
                    "pinned": bool(row["pinned"]),
                }
                for row in slots
            ],
        }

    @staticmethod
    def _normalize_id_list(values: Any, *, label: str) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, (list, tuple, set, frozenset)):
            raise ValueError(f"{label} must be an array")
        result: list[str] = []
        for value in values:
            normalized = _normalize_id(value, label=label)
            if normalized not in result:
                result.append(normalized)
        return result

    @classmethod
    def _normalize_filters(cls, filters: Any) -> dict[str, list[str]]:
        if not isinstance(filters, dict) or set(filters) - {"include_all", "include_any", "exclude"}:
            raise ValueError("selection filters contain unknown fields")
        return {
            key: cls._normalize_id_list(filters.get(key, []), label=f"{key} tag IDs")
            for key in ("include_all", "include_any", "exclude")
        }

    @staticmethod
    def _normalize_policy(policy: Any) -> str:
        if policy not in SELECTION_POLICIES:
            raise ValueError("selection policy must be random, seeded, or sequential")
        return str(policy)

    @staticmethod
    def _normalize_seed(seed: Any) -> int:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 or seed > 9_007_199_254_740_991:
            raise ValueError("selection seed must be a non-negative JavaScript-safe integer")
        return seed

    @classmethod
    def _normalize_slots(cls, slots: Any, *, require_all: bool = False) -> list[dict[str, Any]]:
        if not isinstance(slots, list):
            raise ValueError("selection slots must be an array")
        normalized: list[dict[str, Any]] = []
        seen_slots: set[int] = set()
        seen_images: set[str] = set()
        for value in slots:
            if not isinstance(value, dict) or set(value) - {"slot", "image_id", "pinned"}:
                raise ValueError("selection slot contains unknown fields")
            slot = value.get("slot")
            if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 4 or slot in seen_slots:
                raise ValueError("selection slot must be a unique integer from 1 through 4")
            image_id = value.get("image_id")
            normalized_image_id = None if image_id is None else _normalize_id(image_id, label="image ID")
            pinned = value.get("pinned", False)
            if not isinstance(pinned, bool):
                raise ValueError("selection slot pinned must be boolean")
            if pinned and normalized_image_id is None:
                raise ValueError("a pinned selection slot requires an image")
            if normalized_image_id is not None and normalized_image_id in seen_images:
                raise ValueError("selection slots must use distinct images")
            seen_slots.add(slot)
            if normalized_image_id is not None:
                seen_images.add(normalized_image_id)
            normalized.append({"slot": slot, "image_id": normalized_image_id, "pinned": pinned})
        if require_all and seen_slots != {1, 2, 3, 4}:
            raise ValueError("reroll must provide all four selection slots")
        return sorted(normalized, key=lambda item: item["slot"])

    @staticmethod
    def _require_memberships(connection: sqlite3.Connection, collection_id: str, image_ids: list[str]) -> None:
        if not image_ids:
            return
        placeholders = ",".join("?" for _ in image_ids)
        found = {
            row[0]
            for row in connection.execute(
                f"SELECT image_id FROM collection_images WHERE collection_id = ? AND image_id IN ({placeholders})",
                [collection_id, *image_ids],
            )
        }
        missing = set(image_ids) - found
        if missing:
            raise KeyError("one or more image memberships were not found")

    @staticmethod
    def _require_tags(connection: sqlite3.Connection, tag_ids: list[str]) -> None:
        if not tag_ids:
            return
        unique = list(dict.fromkeys(tag_ids))
        placeholders = ",".join("?" for _ in unique)
        count = connection.execute(
            f"SELECT COUNT(*) FROM tags WHERE id IN ({placeholders})", unique
        ).fetchone()[0]
        if count != len(unique):
            raise KeyError("one or more tags were not found")

    @staticmethod
    def _fetch_image(connection: sqlite3.Connection, image_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        if row is None:
            raise KeyError(f"image not found: {image_id}")
        return row

    @staticmethod
    def _fetch_tag(connection: sqlite3.Connection, tag_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if row is None:
            raise KeyError(f"tag not found: {tag_id}")
        return ReferenceLibraryStore._decode_tag(row)

    @staticmethod
    def _fetch_profile(connection: sqlite3.Connection, profile_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if row is None:
            raise KeyError(f"profile not found: {profile_id}")
        return ReferenceLibraryStore._decode_profile(
            row, ReferenceLibraryStore._profile_loras(connection, profile_id)
        )

    @staticmethod
    def _profile_loras(connection: sqlite3.Connection, profile_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM profile_loras WHERE profile_id = ? ORDER BY position, id",
            (profile_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "position": int(row["position"]),
                "name": row["lora_name"],
                "strength_model": float(row["strength_model"]),
                "strength_clip": float(row["strength_clip"]),
                "enabled": bool(row["enabled"]),
            }
            for row in rows
        ]

    @staticmethod
    def _replace_profile_loras(
        connection: sqlite3.Connection, profile_id: str, loras: list[dict[str, Any]]
    ) -> None:
        connection.execute("DELETE FROM profile_loras WHERE profile_id = ?", (profile_id,))
        connection.executemany(
            """
            INSERT INTO profile_loras(
                id, profile_id, position, lora_name, strength_model, strength_clip, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    str(uuid4()),
                    profile_id,
                    position,
                    item["name"],
                    item["strength_model"],
                    item["strength_clip"],
                    int(item["enabled"]),
                )
                for position, item in enumerate(loras)
            ),
        )

    @staticmethod
    def _normalize_model_family(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("model family must be a non-empty string")
        normalized = value.strip()
        if len(normalized) > 80 or any(character in normalized for character in "\r\n\t"):
            raise ValueError("model family must be a single line up to 80 characters")
        return normalized

    @staticmethod
    def _normalize_loras(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise ValueError("LoRA stack must be an array")
        result: list[dict[str, Any]] = []
        allowed = {"name", "strength_model", "strength_clip", "enabled"}
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("LoRA entry must be an object")
            unknown = set(item) - allowed
            if unknown:
                raise ValueError(f"LoRA entry contains unknown fields: {', '.join(sorted(unknown))}")
            if set(item) != allowed:
                raise ValueError("LoRA entry requires name, strengths, and enabled")
            name = item["name"]
            if not isinstance(name, str) or not name.strip():
                raise ValueError("LoRA name must be a non-empty relative path")
            normalized_name = name.strip().replace("\\", "/")
            windows = PureWindowsPath(normalized_name)
            if normalized_name.startswith("/") or windows.is_absolute() or windows.drive or ".." in normalized_name.split("/"):
                raise ValueError("LoRA name must be a safe relative catalog path")
            if len(normalized_name) > 500 or any(character in normalized_name for character in "\r\n\0"):
                raise ValueError("LoRA name must be a safe relative catalog path")
            strengths: dict[str, float] = {}
            for key in ("strength_model", "strength_clip"):
                raw = item[key]
                if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(raw):
                    raise ValueError("LoRA strengths must be finite numbers")
                if not -100 <= raw <= 100:
                    raise ValueError("LoRA strengths must be between -100 and 100")
                strengths[key] = float(raw)
            if not isinstance(item["enabled"], bool):
                raise ValueError("LoRA enabled must be boolean")
            result.append(
                {
                    "name": normalized_name,
                    **strengths,
                    "enabled": item["enabled"],
                }
            )
        return result

    @staticmethod
    def _tags_for_images(
        connection: sqlite3.Connection, collection_id: str, image_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        if not image_ids:
            return {}
        placeholders = ",".join("?" for _ in image_ids)
        rows = connection.execute(
            f"""
            SELECT cit.image_id, t.*
            FROM collection_image_tags cit
            JOIN tags t ON t.id = cit.tag_id
            WHERE cit.collection_id = ? AND cit.image_id IN ({placeholders})
            ORDER BY t.group_name COLLATE NOCASE, t.name_key, t.id
            """,
            [collection_id, *image_ids],
        ).fetchall()
        result: dict[str, list[dict[str, Any]]] = {image_id: [] for image_id in image_ids}
        for row in rows:
            result[row["image_id"]].append(ReferenceLibraryStore._decode_tag(row))
        return result

    @staticmethod
    def _fetch_collection(connection: sqlite3.Connection, collection_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM collections WHERE id = ?", (collection_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"collection not found: {collection_id}")
        return ReferenceLibraryStore._decode_collection(row)

    @staticmethod
    def _decode_collection(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "name": row["name"],
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _decode_image(row: sqlite3.Row, tags: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "sha256": row["sha256"],
            "relative_path": row["relative_path"],
            "original_filename": row["original_filename"],
            "media_type": row["media_type"],
            "width": int(row["width"]),
            "height": int(row["height"]),
            "tags": tags,
            "created_at": row["created_at"],
        }

    @staticmethod
    def _decode_tag(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "group_name": row["group_name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _decode_profile(row: sqlite3.Row, loras: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "collection_id": row["collection_id"],
            "name": row["name"],
            "model_family": row["model_family"],
            "positive_prompt": row["positive_prompt"],
            "negative_prompt": row["negative_prompt"],
            "loras": loras,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
