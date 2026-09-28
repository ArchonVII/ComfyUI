"""Stable local character, image, and scan-root persistence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 10
# Kept aligned with comfyui_identity_score's calibrated SFace default.
# OpenCV SFace's published LFW cosine threshold:
# https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html
DEFAULT_MATCH_THRESHOLD = 0.363
SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _name(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 160 or any(c in normalized for c in "\r\n\0"):
        raise ValueError("Character name must be 1-160 characters on one line")
    return normalized


def _resolved_path(value: Any) -> Path:
    return Path(value).expanduser().resolve()


class CharacterCatalog:
    """Owns local catalog truth; never modifies registered source files."""

    def __init__(self, root: Path):
        self.root = _resolved_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "catalog.sqlite3"
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._closed = False
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self._initialize()
        self._recover_quarantine_operations()
        self._recover_restore_operations()

    def close(self) -> None:
        if not self._closed:
            self.connection.close()
            self._closed = True

    def _initialize(self) -> None:
        current = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, SCHEMA_VERSION):
            raise ValueError(f"Unsupported character catalog schema version: {current}")
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS characters (
                    id TEXT PRIMARY KEY,
                    preset_id TEXT UNIQUE,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE,
                    positive TEXT NOT NULL DEFAULT '',
                    negative TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_blobs (
                    id TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    content_blob_id TEXT NOT NULL REFERENCES content_blobs(id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_assets_blob
                    ON assets(content_blob_id);
                CREATE TABLE IF NOT EXISTS asset_locations (
                    id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL REFERENCES assets(id),
                    path TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('source', 'managed', 'quarantine')),
                    original_name TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    unavailable_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_locations_available_path
                    ON asset_locations(path) WHERE unavailable_at IS NULL;
                CREATE INDEX IF NOT EXISTS idx_asset_locations_asset
                    ON asset_locations(asset_id, unavailable_at);
                CREATE TABLE IF NOT EXISTS character_assets (
                    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    assignment_type TEXT NOT NULL CHECK(assignment_type IN ('manual', 'imported', 'discovered', 'lineage')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(character_id, asset_id)
                );
                CREATE TABLE IF NOT EXISTS scan_roots (
                    id TEXT PRIMARY KEY,
                    character_id TEXT REFERENCES characters(id) ON DELETE CASCADE,
                    scope_key TEXT NOT NULL,
                    path TEXT NOT NULL,
                    recursive INTEGER NOT NULL CHECK(recursive IN (0, 1)),
                    watch_enabled INTEGER NOT NULL DEFAULT 0 CHECK(watch_enabled IN (0, 1)),
                    created_at TEXT NOT NULL,
                    UNIQUE(scope_key, path)
                );
                CREATE TABLE IF NOT EXISTS assignment_jobs (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    root_path TEXT NOT NULL,
                    recursive INTEGER NOT NULL CHECK(recursive IN (0, 1)),
                    state TEXT NOT NULL CHECK(state IN ('pending', 'running', 'completed', 'failed')),
                    found_count INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    assigned_count INTEGER NOT NULL DEFAULT 0,
                    already_assigned_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_assignment_jobs_character
                    ON assignment_jobs(character_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS face_embeddings (
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    analyzer_key TEXT NOT NULL,
                    face_index INTEGER NOT NULL CHECK(face_index >= 0),
                    vector BLOB NOT NULL,
                    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
                    box_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    image_width INTEGER NOT NULL,
                    image_height INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(asset_id, analyzer_key, face_index)
                );
                CREATE TABLE IF NOT EXISTS discovery_jobs (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    root_path TEXT NOT NULL,
                    recursive INTEGER NOT NULL CHECK(recursive IN (0, 1)),
                    state TEXT NOT NULL CHECK(state IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
                    found_count INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    matched_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_jobs_character
                    ON discovery_jobs(character_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS discovery_errors (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES discovery_jobs(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_errors_job
                    ON discovery_errors(job_id, created_at, id);
                CREATE TABLE IF NOT EXISTS discovery_review (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES discovery_jobs(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    face_index INTEGER NOT NULL,
                    score REAL NOT NULL,
                    decision TEXT NOT NULL DEFAULT 'pending' CHECK(decision IN ('pending', 'accepted', 'rejected', 'deferred')),
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    UNIQUE(job_id, asset_id, face_index)
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_review_queue
                    ON discovery_review(job_id, decision, score DESC);
                CREATE TABLE IF NOT EXISTS quarantine_operations (
                    id TEXT PRIMARY KEY,
                    location_id TEXT NOT NULL REFERENCES asset_locations(id),
                    asset_id TEXT NOT NULL REFERENCES assets(id),
                    original_path TEXT NOT NULL,
                    original_kind TEXT NOT NULL CHECK(original_kind IN ('source', 'managed')),
                    quarantine_path TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL CHECK(state IN ('planned', 'filesystem_done', 'database_done', 'restored')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_quarantine_state
                    ON quarantine_operations(state, created_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_quarantine_active_location
                    ON quarantine_operations(location_id)
                    WHERE state != 'restored';
                CREATE TABLE IF NOT EXISTS asset_dimensions (
                    asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
                    width INTEGER NOT NULL CHECK(width > 0),
                    height INTEGER NOT NULL CHECK(height > 0),
                    measured_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS image_families (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(character_id, name_key)
                );
                CREATE INDEX IF NOT EXISTS idx_image_families_character
                    ON image_families(character_id, name_key);
                CREATE TABLE IF NOT EXISTS family_assets (
                    family_id TEXT NOT NULL REFERENCES image_families(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(family_id, asset_id)
                );
                CREATE TABLE IF NOT EXISTS family_sources (
                    family_id TEXT PRIMARY KEY REFERENCES image_families(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    designated_at TEXT NOT NULL,
                    FOREIGN KEY(family_id, asset_id)
                        REFERENCES family_assets(family_id, asset_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS generation_lineage (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    source_asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    output_asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, character_id, source_asset_id, output_asset_id)
                );
                CREATE INDEX IF NOT EXISTS idx_generation_lineage_source
                    ON generation_lineage(source_asset_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_generation_lineage_output
                    ON generation_lineage(output_asset_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS discovery_job_control (
                    job_id TEXT PRIMARY KEY REFERENCES discovery_jobs(id) ON DELETE CASCADE,
                    action TEXT NOT NULL CHECK(action IN ('cancel')),
                    requested_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quarantine_restore_journal (
                    operation_id TEXT PRIMARY KEY REFERENCES quarantine_operations(id) ON DELETE CASCADE,
                    target_path TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('planned', 'filesystem_done')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discovery_job_analyzers (
                    job_id TEXT PRIMARY KEY REFERENCES discovery_jobs(id) ON DELETE CASCADE,
                    analyzer_key TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS face_rejections (
                    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    analyzer_key TEXT NOT NULL,
                    face_index INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(character_id, asset_id, analyzer_key, face_index)
                );
                CREATE TABLE IF NOT EXISTS face_assignments (
                    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    analyzer_key TEXT NOT NULL,
                    face_index INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(character_id, asset_id, analyzer_key, face_index)
                );
                """
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO settings(key, value_json) VALUES ('watch_enabled', 'false')"
            )
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def schema_version(self) -> int:
        return int(self.connection.execute("PRAGMA user_version").fetchone()[0])

    def settings(self) -> dict[str, Any]:
        rows = self.connection.execute("SELECT key, value_json FROM settings").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def create_character(
        self,
        name: Any,
        *,
        preset_id: str | None = None,
        positive: Any = "",
        negative: Any = "",
    ) -> dict[str, Any]:
        normalized = _name(name)
        character_id = str(uuid.uuid4())
        now = _now()
        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO characters(
                        id, preset_id, name, name_key, positive, negative,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        character_id,
                        preset_id,
                        normalized,
                        normalized.casefold(),
                        str(positive or ""),
                        str(negative or ""),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Character already exists: {normalized}") from error
        return self._character(character_id)

    def _character(self, character_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown character: {character_id}")
        return dict(row)

    def character_for_preset(self, preset_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM characters WHERE preset_id = ?", (preset_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def list_characters(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM characters ORDER BY name_key, id"
            ).fetchall()
        ]

    def register_file(self, source: Any, *, kind: str = "source") -> dict[str, Any]:
        if kind not in {"source", "managed"}:
            raise ValueError("Registered files must be source or managed locations")
        path = _resolved_path(source)
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f"File changed while hashing: {path}")
        sha256 = digest.hexdigest()
        now = _now()
        path_text = str(path)
        asset_created = False
        location_created = False

        with self.connection:
            current = self.connection.execute(
                """
                SELECT al.id, al.asset_id, cb.sha256
                FROM asset_locations al
                JOIN assets a ON a.id = al.asset_id
                JOIN content_blobs cb ON cb.id = a.content_blob_id
                WHERE al.path = ? AND al.unavailable_at IS NULL
                """,
                (path_text,),
            ).fetchone()
            if current is not None and current["sha256"] == sha256:
                self.connection.execute(
                    "UPDATE asset_locations SET last_seen_at = ? WHERE id = ?",
                    (now, current["id"]),
                )
                return {
                    "asset_id": current["asset_id"],
                    "sha256": sha256,
                    "asset_created": False,
                    "location_created": False,
                }
            if current is not None:
                self.connection.execute(
                    "UPDATE asset_locations SET unavailable_at = ?, last_seen_at = ? WHERE id = ?",
                    (now, now, current["id"]),
                )

            blob = self.connection.execute(
                "SELECT id FROM content_blobs WHERE sha256 = ?", (sha256,)
            ).fetchone()
            if blob is None:
                blob_id = str(uuid.uuid4())
                asset_id = str(uuid.uuid4())
                self.connection.execute(
                    "INSERT INTO content_blobs(id, sha256, size_bytes, created_at) VALUES (?, ?, ?, ?)",
                    (blob_id, sha256, after.st_size, now),
                )
                self.connection.execute(
                    "INSERT INTO assets(id, content_blob_id, created_at) VALUES (?, ?, ?)",
                    (asset_id, blob_id, now),
                )
                asset_created = True
            else:
                asset = self.connection.execute(
                    "SELECT id FROM assets WHERE content_blob_id = ? ORDER BY created_at, id LIMIT 1",
                    (blob["id"],),
                ).fetchone()
                asset_id = asset["id"]

            self.connection.execute(
                """
                INSERT INTO asset_locations(
                    id, asset_id, path, kind, original_name,
                    first_seen_at, last_seen_at, unavailable_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    str(uuid.uuid4()),
                    asset_id,
                    path_text,
                    kind,
                    path.name,
                    now,
                    now,
                ),
            )
            location_created = True
        return {
            "asset_id": asset_id,
            "sha256": sha256,
            "asset_created": asset_created,
            "location_created": location_created,
        }

    def list_asset_locations(self, asset_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, asset_id, path, kind, original_name,
                   first_seen_at, last_seen_at, unavailable_at
            FROM asset_locations
            WHERE asset_id = ?
            ORDER BY first_seen_at, id
            """,
            (asset_id,),
        ).fetchall()
        return [
            {**dict(row), "available": row["unavailable_at"] is None} for row in rows
        ]

    def list_asset_locations_for_path(self, path: Any) -> list[dict[str, Any]]:
        resolved = str(_resolved_path(path))
        rows = self.connection.execute(
            "SELECT * FROM asset_locations WHERE path = ? ORDER BY first_seen_at, id",
            (resolved,),
        ).fetchall()
        return [dict(row) for row in rows]

    def asset_id_for_path(self, path: Any) -> str | None:
        row = self.connection.execute(
            """
            SELECT asset_id FROM asset_locations
            WHERE path = ? AND unavailable_at IS NULL
            """,
            (str(_resolved_path(path)),),
        ).fetchone()
        return row["asset_id"] if row is not None else None

    def assign_asset(
        self, character_id: str, asset_id: str, *, assignment_type: str
    ) -> bool:
        if assignment_type not in {"manual", "imported", "discovered", "lineage"}:
            raise ValueError("Unknown assignment type")
        with self.connection:
            result = self.connection.execute(
                """
                INSERT OR IGNORE INTO character_assets(
                    character_id, asset_id, assignment_type, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (character_id, asset_id, assignment_type, _now()),
            )
        return result.rowcount == 1

    def list_character_assets(
        self, character_id: str, *, query: str = "", sort: str = "oldest",
        limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        self._character(character_id)
        if limit is not None and not 1 <= limit <= 500:
            raise ValueError("Character image page limit must be 1-500")
        if offset < 0:
            raise ValueError("Character image page offset must be nonnegative")
        query = str(query).strip().casefold()
        if len(query) > 200:
            raise ValueError("Character image search is too long")
        order_by = {
            "oldest": "ca.created_at, a.id",
            "newest": "ca.created_at DESC, a.id DESC",
            "name": "LOWER(al.original_name), a.id",
            "largest": "cb.size_bytes DESC, a.id",
        }.get(sort)
        if order_by is None:
            raise ValueError("Unknown character image sort")
        pattern = f"%{query}%"
        pagination = "" if limit is None else " LIMIT ? OFFSET ?"
        parameters: tuple[Any, ...] = (character_id, query, pattern, pattern)
        if limit is not None:
            parameters += (limit, offset)
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT a.id, ca.assignment_type, cb.sha256, cb.size_bytes,
                       al.path, al.original_name, al.kind AS location_kind
                FROM character_assets ca
                JOIN assets a ON a.id = ca.asset_id
                JOIN content_blobs cb ON cb.id = a.content_blob_id
                JOIN asset_locations al ON al.id = (
                    SELECT candidate.id
                    FROM asset_locations candidate
                    WHERE candidate.asset_id = a.id
                      AND candidate.unavailable_at IS NULL
                    ORDER BY CASE candidate.kind
                               WHEN 'managed' THEN 0
                               WHEN 'source' THEN 1
                               ELSE 2
                             END,
                             candidate.first_seen_at,
                             candidate.id
                    LIMIT 1
                )
                WHERE ca.character_id = ?
                  AND (? = '' OR LOWER(al.original_name) LIKE ? OR LOWER(al.path) LIKE ?)
                ORDER BY """ + order_by + """
                """ + pagination,
                parameters,
            ).fetchall()
        ]

    def character_asset_count(self, character_id: str, *, query: str = "") -> int:
        self._character(character_id)
        query = str(query).strip().casefold()
        if len(query) > 200:
            raise ValueError("Character image search is too long")
        pattern = f"%{query}%"
        return int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM character_assets assignment
                WHERE assignment.character_id = ?
                  AND (
                    ? = '' OR EXISTS (
                      SELECT 1 FROM asset_locations location
                      WHERE location.asset_id = assignment.asset_id
                        AND location.unavailable_at IS NULL
                        AND (
                          LOWER(location.original_name) LIKE ?
                          OR LOWER(location.path) LIKE ?
                        )
                    )
                  )
                """,
                (character_id, query, pattern, pattern),
            ).fetchone()[0]
        )

    def character_has_asset(self, character_id: str, asset_id: str) -> bool:
        self._character(character_id)
        return self.connection.execute(
            """
            SELECT 1 FROM character_assets
            WHERE character_id = ? AND asset_id = ?
            """,
            (character_id, asset_id),
        ).fetchone() is not None

    def assign_folder(
        self, character_id: str, folder: Any, *, recursive: bool
    ) -> dict[str, Any]:
        self._character(character_id)
        root = _resolved_path(folder)
        if not root.is_dir():
            raise ValueError(f"Image folder is not a directory: {root}")
        candidates = root.rglob("*") if recursive else root.iterdir()
        files = sorted(
            (
                path
                for path in candidates
                if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
            ),
            key=lambda path: str(path).casefold(),
        )
        result: dict[str, Any] = {
            "found": len(files),
            "assigned": 0,
            "already_assigned": 0,
            "failed": [],
        }
        for path in files:
            try:
                registered = self.register_file(path)
                added = self.assign_asset(
                    character_id,
                    registered["asset_id"],
                    assignment_type="manual",
                )
                result["assigned" if added else "already_assigned"] += 1
            except (OSError, ValueError) as error:
                result["failed"].append({"path": str(path), "error": str(error)})
        return result

    def create_assignment_job(
        self, character_id: str, folder: Any, *, recursive: bool
    ) -> dict[str, Any]:
        self._character(character_id)
        root = _resolved_path(folder)
        if not root.is_dir():
            raise ValueError(f"Image folder is not a directory: {root}")
        if type(recursive) is not bool:
            raise ValueError("Assignment recursion setting must be true or false")
        job_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO assignment_jobs(
                    id, character_id, root_path, recursive, state, created_at
                ) VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (job_id, character_id, str(root), int(recursive), _now()),
            )
        return self.get_assignment_job(job_id)

    def get_assignment_job(self, job_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM assignment_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown assignment job: {job_id}")
        return dict(row)

    def list_assignment_jobs(self, character_id: str) -> list[dict[str, Any]]:
        self._character(character_id)
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT * FROM assignment_jobs
                WHERE character_id = ? ORDER BY created_at DESC, id DESC
                """,
                (character_id,),
            ).fetchall()
        ]

    def recover_interrupted_assignment_jobs(self) -> int:
        with self.connection:
            changed = self.connection.execute(
                """
                UPDATE assignment_jobs
                SET state = 'failed', error = 'Preset Studio stopped before assignment completed',
                    completed_at = ?
                WHERE state IN ('pending', 'running')
                """,
                (_now(),),
            )
        return changed.rowcount

    def run_assignment_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_assignment_job(job_id)
        if job["state"] == "completed":
            return job
        if job["state"] != "pending":
            raise ValueError(f"Assignment job is already {job['state']}")
        root = Path(job["root_path"])
        try:
            candidates = root.rglob("*") if job["recursive"] else root.iterdir()
            files = sorted(
                (
                    path for path in candidates
                    if path.is_file()
                    and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
                ),
                key=lambda path: str(path).casefold(),
            )
            with self.connection:
                claimed = self.connection.execute(
                    """
                    UPDATE assignment_jobs
                    SET state = 'running', found_count = ?, started_at = ?
                    WHERE id = ? AND state = 'pending'
                    """,
                    (len(files), _now(), job_id),
                )
            if not claimed.rowcount:
                raise ValueError("Assignment job was claimed by another worker")
            failures = []
            for path in files:
                assigned = False
                already = False
                try:
                    registered = self.register_file(path)
                    assigned = self.assign_asset(
                        job["character_id"], registered["asset_id"],
                        assignment_type="manual",
                    )
                    already = not assigned
                except (OSError, ValueError) as error:
                    failures.append(f"{path}: {error}")
                with self.connection:
                    self.connection.execute(
                        """
                        UPDATE assignment_jobs
                        SET processed_count = processed_count + 1,
                            assigned_count = assigned_count + ?,
                            already_assigned_count = already_assigned_count + ?,
                            error_count = error_count + ?
                        WHERE id = ?
                        """,
                        (int(assigned), int(already), int(not assigned and not already), job_id),
                    )
            with self.connection:
                self.connection.execute(
                    """
                    UPDATE assignment_jobs
                    SET state = 'completed', error = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    ("\n".join(failures[:20]) or None, _now(), job_id),
                )
        except Exception as error:
            with self.connection:
                self.connection.execute(
                    """
                    UPDATE assignment_jobs
                    SET state = 'failed', error = ?, completed_at = ? WHERE id = ?
                    """,
                    (str(error)[:4000], _now(), job_id),
                )
            raise
        return self.get_assignment_job(job_id)

    def import_presets(
        self,
        presets: Sequence[Mapping[str, Any]],
        references: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, int]:
        counts = {"characters": 0, "assets": 0, "assignments": 0}
        for preset in presets:
            if preset.get("kind") != "character":
                continue
            row = self.connection.execute(
                "SELECT id FROM characters WHERE preset_id = ?", (preset.get("id"),)
            ).fetchone()
            if row is None:
                character = self.create_character(
                    preset.get("name"),
                    preset_id=str(preset.get("id")),
                    positive=preset.get("positive", ""),
                    negative=preset.get("negative", ""),
                )
                counts["characters"] += 1
            else:
                character = self._character(row["id"])
            for reference_id in preset.get("references", []):
                reference = references.get(reference_id)
                if not reference or "path" not in reference:
                    continue
                registered = self.register_file(reference["path"], kind="managed")
                counts["assets"] += int(registered["asset_created"])
                counts["assignments"] += int(
                    self.assign_asset(
                        character["id"],
                        registered["asset_id"],
                        assignment_type="imported",
                    )
                )
        return counts

    def sync_preset(
        self,
        preset: Mapping[str, Any],
        references: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        """Upsert one linked character preset without removing accepted catalog truth."""
        if preset.get("kind") != "character":
            return None
        preset_id = str(preset.get("id") or "")
        if not preset_id:
            raise ValueError("Character preset needs an ID")
        row = self.connection.execute(
            "SELECT id FROM characters WHERE preset_id = ?", (preset_id,)
        ).fetchone()
        if row is None:
            character = self.create_character(
                preset.get("name"),
                preset_id=preset_id,
                positive=preset.get("positive", ""),
                negative=preset.get("negative", ""),
            )
        else:
            character_id = row["id"]
            normalized = _name(preset.get("name"))
            try:
                with self.connection:
                    self.connection.execute(
                        """
                        UPDATE characters
                        SET name = ?, name_key = ?, positive = ?, negative = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            normalized,
                            normalized.casefold(),
                            str(preset.get("positive", "") or ""),
                            str(preset.get("negative", "") or ""),
                            _now(),
                            character_id,
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"Character already exists: {normalized}") from error
            character = self._character(character_id)
        for reference_id in preset.get("references", []):
            reference = references.get(reference_id)
            if not reference or "path" not in reference:
                continue
            path = _resolved_path(reference["path"])
            if not path.is_file():
                continue
            registered = self.register_file(path, kind="managed")
            self.assign_asset(
                character["id"],
                registered["asset_id"],
                assignment_type="imported",
            )
        return character

    def add_scan_root(
        self,
        path: Any,
        *,
        character_id: str | None = None,
        recursive: bool = True,
    ) -> dict[str, Any]:
        resolved = _resolved_path(path)
        if not resolved.is_dir():
            raise ValueError(f"Scan root is not a directory: {resolved}")
        if character_id is not None:
            self._character(character_id)
        root_id = str(uuid.uuid4())
        scope_key = character_id or "global"
        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO scan_roots(
                        id, character_id, scope_key, path, recursive,
                        watch_enabled, created_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        root_id,
                        character_id,
                        scope_key,
                        str(resolved),
                        int(bool(recursive)),
                        _now(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Scan root already exists: {resolved}") from error
        return next(row for row in self.list_scan_roots() if row["id"] == root_id)

    def list_scan_roots(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM scan_roots ORDER BY scope_key, path"
        ).fetchall()
        return [
            {
                **dict(row),
                "recursive": bool(row["recursive"]),
                "watch_enabled": bool(row["watch_enabled"]),
            }
            for row in rows
        ]

    def create_discovery_job(
        self, character_id: str, folder: Any, *, recursive: bool
    ) -> dict[str, Any]:
        self._character(character_id)
        root = _resolved_path(folder)
        if not root.is_dir():
            raise ValueError(f"Scan folder is not a directory: {root}")
        job_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO discovery_jobs(
                    id, character_id, root_path, recursive, state, created_at
                ) VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (job_id, character_id, str(root), int(bool(recursive)), _now()),
            )
        return self.get_discovery_job(job_id)

    def get_discovery_job(self, job_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM discovery_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown discovery job: {job_id}")
        return {**dict(row), "recursive": bool(row["recursive"])}

    def request_discovery_cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get_discovery_job(job_id)
        if job["state"] not in {"pending", "running"}:
            return job
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO discovery_job_control(job_id, action, requested_at)
                VALUES (?, 'cancel', ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    action = excluded.action,
                    requested_at = excluded.requested_at
                """,
                (job_id, _now()),
            )
            if job["state"] == "pending":
                self.connection.execute(
                    "UPDATE discovery_jobs SET state = 'cancelled', completed_at = ? WHERE id = ?",
                    (_now(), job_id),
                )
        return self.get_discovery_job(job_id)

    def _discovery_cancel_requested(self, job_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM discovery_job_control WHERE job_id = ? AND action = 'cancel'",
            (job_id,),
        ).fetchone() is not None

    def list_discovery_jobs(self, character_id: str) -> list[dict[str, Any]]:
        self._character(character_id)
        return [
            {**dict(row), "recursive": bool(row["recursive"])}
            for row in self.connection.execute(
                "SELECT * FROM discovery_jobs WHERE character_id = ? ORDER BY created_at DESC",
                (character_id,),
            ).fetchall()
        ]

    @staticmethod
    def _pack_vector(vector: Sequence[float]) -> tuple[bytes, int]:
        values = [float(value) for value in vector]
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError("Face analyzer returned an invalid vector")
        return struct.pack(f"<{len(values)}f", *values), len(values)

    @staticmethod
    def _unpack_vector(payload: bytes, dimensions: int) -> tuple[float, ...]:
        return struct.unpack(f"<{dimensions}f", payload)

    def _asset_path(self, asset_id: str) -> Path:
        row = self.connection.execute(
            """
            SELECT path FROM asset_locations
            WHERE asset_id = ? AND unavailable_at IS NULL
            ORDER BY CASE kind WHEN 'managed' THEN 0 WHEN 'source' THEN 1 ELSE 2 END,
                     first_seen_at, id
            LIMIT 1
            """,
            (asset_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Asset has no available file: {asset_id}")
        return Path(row["path"])

    def asset_path(self, asset_id: str) -> Path:
        """Return a currently registered path for local preview serving."""
        return self._asset_path(asset_id)

    def thumbnail_path(self, asset_id: str, size: int = 256) -> Path:
        if size not in {128, 192, 256, 320, 512}:
            raise ValueError("Unsupported thumbnail size")
        target = self.root / "thumbnails" / str(size) / f"{asset_id}.webp"
        if target.is_file():
            return target
        from PIL import Image, ImageOps

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with Image.open(self._asset_path(asset_id)) as source:
                thumbnail = ImageOps.exif_transpose(source).convert("RGB")
                thumbnail.thumbnail((size, size), Image.Resampling.LANCZOS)
                thumbnail.save(temporary, format="WEBP", quality=82, method=4)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def review_face_thumbnail_path(self, review_id: str, size: int = 192) -> Path:
        if size not in {128, 192, 256, 320, 512}:
            raise ValueError("Unsupported face thumbnail size")
        row = self.connection.execute(
            """
            SELECT review.asset_id, embedding.box_json
            FROM discovery_review review
            JOIN discovery_job_analyzers analyzer ON analyzer.job_id = review.job_id
            JOIN face_embeddings embedding
              ON embedding.asset_id = review.asset_id
             AND embedding.analyzer_key = analyzer.analyzer_key
             AND embedding.face_index = review.face_index
            WHERE review.id = ?
            """,
            (review_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown review face: {review_id}")
        target = self.root / "thumbnails" / "review-faces" / str(size) / f"{review_id}.webp"
        if target.is_file():
            return target
        from PIL import Image, ImageOps

        x, y, width, height = [float(value) for value in json.loads(row["box_json"])]
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with Image.open(self._asset_path(row["asset_id"])) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                side = max(width, height) * 2.2
                center_x, center_y = x + width / 2, y + height / 2
                left = max(0, int(round(center_x - side / 2)))
                top = max(0, int(round(center_y - side / 2)))
                right = min(image.width, int(round(center_x + side / 2)))
                bottom = min(image.height, int(round(center_y + side / 2)))
                if right <= left or bottom <= top:
                    raise ValueError("Stored face box is outside the image")
                crop = image.crop((left, top, right, bottom))
                crop.thumbnail((size, size), Image.Resampling.LANCZOS)
                crop.save(temporary, format="WEBP", quality=86, method=4)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def _face_vectors(self, asset_id: str, analyzer: Any) -> list[dict[str, Any]]:
        analyzer_key = str(getattr(analyzer, "key", "")).strip()
        if not analyzer_key:
            raise ValueError("Face analyzer must declare a versioned key")
        rows = self.connection.execute(
            """
            SELECT * FROM face_embeddings
            WHERE asset_id = ? AND analyzer_key = ?
            ORDER BY face_index
            """,
            (asset_id, analyzer_key),
        ).fetchall()
        if not rows:
            faces = analyzer.analyze(self._asset_path(asset_id))
            with self.connection:
                for index, face in enumerate(faces):
                    payload, dimensions = self._pack_vector(face["vector"])
                    width, height = face["image_size"]
                    self.connection.execute(
                        """
                        INSERT INTO face_embeddings(
                            asset_id, analyzer_key, face_index, vector, dimensions,
                            box_json, confidence, image_width, image_height, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            asset_id,
                            analyzer_key,
                            index,
                            payload,
                            dimensions,
                            json.dumps(list(face["box"])),
                            float(face["confidence"]),
                            int(width),
                            int(height),
                            _now(),
                        ),
                    )
            rows = self.connection.execute(
                """
                SELECT * FROM face_embeddings
                WHERE asset_id = ? AND analyzer_key = ? ORDER BY face_index
                """,
                (asset_id, analyzer_key),
            ).fetchall()
        return [
            {
                **dict(row),
                "vector": self._unpack_vector(row["vector"], row["dimensions"]),
                "box": json.loads(row["box_json"]),
            }
            for row in rows
        ]

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

    def run_discovery_job(
        self, job_id: str, analyzer: Any, *, threshold: float = DEFAULT_MATCH_THRESHOLD
    ) -> dict[str, Any]:
        job = self.get_discovery_job(job_id)
        if job["state"] not in {"pending", "failed"}:
            raise ValueError(f"Discovery job is already {job['state']}")
        analyzer_key = str(getattr(analyzer, "key", "")).strip()
        if not analyzer_key:
            raise ValueError("Face analyzer must declare a versioned key")
        now = _now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE discovery_jobs
                SET state = 'running', started_at = ?, completed_at = NULL,
                    error = NULL, found_count = 0, processed_count = 0,
                    matched_count = 0, error_count = 0
                WHERE id = ?
                """,
                (now, job_id),
            )
            self.connection.execute(
                "DELETE FROM discovery_review WHERE job_id = ?", (job_id,)
            )
            self.connection.execute(
                "DELETE FROM discovery_errors WHERE job_id = ?", (job_id,)
            )
            self.connection.execute(
                """
                INSERT INTO discovery_job_analyzers(job_id, analyzer_key)
                VALUES (?, ?)
                ON CONFLICT(job_id) DO UPDATE SET analyzer_key = excluded.analyzer_key
                """,
                (job_id, analyzer_key),
            )
        try:
            reference_ids = [
                row["id"]
                for row in self.connection.execute(
                    "SELECT asset_id AS id FROM character_assets WHERE character_id = ?",
                    (job["character_id"],),
                ).fetchall()
            ]
            if not reference_ids:
                raise ValueError("Assign at least one character image before finding new pictures")
            reference_vectors = [
                face["vector"]
                for asset_id in reference_ids
                for face in self._face_vectors(asset_id, analyzer)
            ]
            if not reference_vectors:
                raise ValueError("No face was found in the character's assigned images")
            root = Path(job["root_path"])
            candidates = root.rglob("*") if job["recursive"] else root.iterdir()
            files = sorted(
                (
                    path
                    for path in candidates
                    if path.is_file()
                    and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
                ),
                key=lambda path: str(path).casefold(),
            )
            with self.connection:
                self.connection.execute(
                    "UPDATE discovery_jobs SET found_count = ? WHERE id = ?",
                    (len(files), job_id),
                )
            matched = 0
            errors = 0
            for processed, path in enumerate(files, 1):
                if self._discovery_cancel_requested(job_id):
                    with self.connection:
                        self.connection.execute(
                            "UPDATE discovery_jobs SET state = 'cancelled', completed_at = ? WHERE id = ?",
                            (_now(), job_id),
                        )
                    return self.get_discovery_job(job_id)
                try:
                    registered = self.register_file(path)
                    if registered["asset_id"] not in reference_ids:
                        for face in self._face_vectors(registered["asset_id"], analyzer):
                            score = max(
                                self._cosine(face["vector"], reference)
                                for reference in reference_vectors
                            )
                            if score >= threshold:
                                rejected = self.connection.execute(
                                    """
                                    SELECT 1 FROM face_rejections
                                    WHERE character_id = ? AND asset_id = ?
                                      AND analyzer_key = ? AND face_index = ?
                                    """,
                                    (
                                        job["character_id"],
                                        registered["asset_id"],
                                        analyzer_key,
                                        face["face_index"],
                                    ),
                                ).fetchone()
                                if rejected is not None:
                                    continue
                                with self.connection:
                                    inserted = self.connection.execute(
                                        """
                                        INSERT OR IGNORE INTO discovery_review(
                                            id, job_id, asset_id, face_index, score, created_at
                                        ) VALUES (?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            str(uuid.uuid4()),
                                            job_id,
                                            registered["asset_id"],
                                            face["face_index"],
                                            score,
                                            _now(),
                                        ),
                                    )
                                matched += int(inserted.rowcount == 1)
                except (OSError, ValueError, sqlite3.Error) as error:
                    errors += 1
                    with self.connection:
                        self.connection.execute(
                            """
                            INSERT INTO discovery_errors(id, job_id, path, error, created_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (str(uuid.uuid4()), job_id, str(path), str(error)[:2000], _now()),
                        )
                with self.connection:
                    self.connection.execute(
                        """
                        UPDATE discovery_jobs
                        SET processed_count = ?, matched_count = ?, error_count = ?
                        WHERE id = ?
                        """,
                        (processed, matched, errors, job_id),
                    )
            with self.connection:
                self.connection.execute(
                    "UPDATE discovery_jobs SET state = 'completed', completed_at = ? WHERE id = ?",
                    (_now(), job_id),
                )
        except Exception as error:
            with self.connection:
                self.connection.execute(
                    "UPDATE discovery_jobs SET state = 'failed', error = ?, completed_at = ? WHERE id = ?",
                    (str(error)[:1000], _now(), job_id),
                )
            raise
        return self.get_discovery_job(job_id)

    def list_discovery_errors(self, job_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        self.get_discovery_job(job_id)
        if not 1 <= limit <= 500:
            raise ValueError("Discovery error limit must be 1-500")
        return [dict(row) for row in self.connection.execute(
            """
            SELECT * FROM discovery_errors WHERE job_id = ?
            ORDER BY created_at, id LIMIT ?
            """,
            (job_id, limit),
        ).fetchall()]

    def review_item_count(self, job_id: str, decision: str | None = None) -> int:
        self.get_discovery_job(job_id)
        if decision is not None and decision not in {
            "pending", "accepted", "rejected", "deferred"
        }:
            raise ValueError("Unknown review decision")
        where = "job_id = ?" if decision is None else "job_id = ? AND decision = ?"
        parameters = (job_id,) if decision is None else (job_id, decision)
        return int(
            self.connection.execute(
                f"SELECT COUNT(*) FROM discovery_review WHERE {where}", parameters
            ).fetchone()[0]
        )

    def apply_all_pending_recommended(self, job_id: str) -> dict[str, int]:
        review_ids = [
            row["id"]
            for row in self.connection.execute(
                """
                SELECT id FROM discovery_review
                WHERE job_id = ? AND decision = 'pending'
                ORDER BY score DESC, id
                """,
                (job_id,),
            ).fetchall()
        ]
        return self.apply_recommended(job_id, review_ids)

    def list_review_items(
        self, job_id: str, *, limit: int = 500, offset: int = 0
    ) -> list[dict[str, Any]]:
        self.get_discovery_job(job_id)
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("Review page must use limit 1-1000 and a nonnegative offset")
        items = []
        for row in self.connection.execute(
                """
                SELECT review.id, review.job_id, review.asset_id,
                       review.face_index, review.score, review.decision,
                       location.path, location.original_name,
                       embedding.box_json, embedding.confidence AS face_confidence,
                       embedding.image_width, embedding.image_height
                FROM discovery_review review
                JOIN discovery_job_analyzers analyzer ON analyzer.job_id = review.job_id
                JOIN face_embeddings embedding
                  ON embedding.asset_id = review.asset_id
                 AND embedding.analyzer_key = analyzer.analyzer_key
                 AND embedding.face_index = review.face_index
                JOIN asset_locations location ON location.id = (
                    SELECT candidate.id FROM asset_locations candidate
                    WHERE candidate.asset_id = review.asset_id
                      AND candidate.unavailable_at IS NULL
                    ORDER BY candidate.first_seen_at, candidate.id LIMIT 1
                )
                WHERE review.job_id = ?
                ORDER BY CASE review.decision
                           WHEN 'pending' THEN 0
                           WHEN 'deferred' THEN 1
                           WHEN 'accepted' THEN 2
                           ELSE 3
                         END,
                         review.score DESC, review.id
                LIMIT ? OFFSET ?
                """,
                (job_id, limit, offset),
            ).fetchall():
            item = dict(row)
            item["face_box"] = json.loads(item.pop("box_json"))
            items.append(item)
        return items

    def apply_recommended(
        self, job_id: str, review_ids: Sequence[str]
    ) -> dict[str, int]:
        job = self.get_discovery_job(job_id)
        analyzer = self.connection.execute(
            "SELECT analyzer_key FROM discovery_job_analyzers WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if analyzer is None:
            raise ValueError("Discovery job has no analyzer record")
        result = {"assigned": 0, "already_applied": 0}
        for review_id in dict.fromkeys(str(value) for value in review_ids):
            row = self.connection.execute(
                "SELECT * FROM discovery_review WHERE id = ? AND job_id = ?",
                (review_id, job_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown review item: {review_id}")
            if row["decision"] == "accepted":
                result["already_applied"] += 1
                continue
            with self.connection:
                self.assign_asset(
                    job["character_id"], row["asset_id"], assignment_type="discovered"
                )
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO face_assignments(
                        character_id, asset_id, analyzer_key, face_index, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        job["character_id"], row["asset_id"],
                        analyzer["analyzer_key"], row["face_index"], _now(),
                    ),
                )
                self.connection.execute(
                    """
                    DELETE FROM face_rejections
                    WHERE character_id = ? AND asset_id = ?
                      AND analyzer_key = ? AND face_index = ?
                    """,
                    (
                        job["character_id"], row["asset_id"],
                        analyzer["analyzer_key"], row["face_index"],
                    ),
                )
                self.connection.execute(
                    "UPDATE discovery_review SET decision = 'accepted', decided_at = ? WHERE id = ?",
                    (_now(), review_id),
                )
            result["assigned"] += 1
        return result

    def decide_review_items(
        self, job_id: str, review_ids: Sequence[str], decision: str
    ) -> dict[str, int]:
        if decision not in {"rejected", "deferred"}:
            raise ValueError("Review decision must be rejected or deferred")
        job = self.get_discovery_job(job_id)
        analyzer = self.connection.execute(
            "SELECT analyzer_key FROM discovery_job_analyzers WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if analyzer is None:
            raise ValueError("Discovery job has no analyzer record")
        result = {"updated": 0, "already_decided": 0}
        for review_id in dict.fromkeys(str(value) for value in review_ids):
            row = self.connection.execute(
                "SELECT * FROM discovery_review WHERE id = ? AND job_id = ?",
                (review_id, job_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown review item: {review_id}")
            if row["decision"] == decision:
                result["already_decided"] += 1
                continue
            if row["decision"] == "accepted":
                raise ValueError("Accepted matches must be removed from the character instead")
            with self.connection:
                self.connection.execute(
                    "UPDATE discovery_review SET decision = ?, decided_at = ? WHERE id = ?",
                    (decision, _now(), review_id),
                )
                if decision == "rejected":
                    self.connection.execute(
                        """
                        INSERT OR IGNORE INTO face_rejections(
                            character_id, asset_id, analyzer_key, face_index, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            job["character_id"], row["asset_id"],
                            analyzer["analyzer_key"], row["face_index"], _now(),
                        ),
                    )
            result["updated"] += 1
        return result

    def list_exact_duplicate_groups(self, character_id: str) -> list[dict[str, Any]]:
        self._character(character_id)
        assets = self.connection.execute(
            """
            SELECT a.id AS asset_id, cb.sha256, cb.size_bytes
            FROM character_assets ca
            JOIN assets a ON a.id = ca.asset_id
            JOIN content_blobs cb ON cb.id = a.content_blob_id
            WHERE ca.character_id = ?
              AND (
                SELECT COUNT(*) FROM asset_locations al
                WHERE al.asset_id = a.id AND al.unavailable_at IS NULL
                  AND al.kind IN ('source', 'managed')
              ) > 1
            ORDER BY cb.sha256, a.id
            """,
            (character_id,),
        ).fetchall()
        groups = []
        for asset in assets:
            locations = [
                dict(row)
                for row in self.connection.execute(
                    """
                    SELECT id, asset_id, path, kind, original_name,
                           first_seen_at, last_seen_at
                    FROM asset_locations
                    WHERE asset_id = ? AND unavailable_at IS NULL
                      AND kind IN ('source', 'managed')
                    ORDER BY CASE kind WHEN 'managed' THEN 0 ELSE 1 END,
                             first_seen_at, id
                    """,
                    (asset["asset_id"],),
                ).fetchall()
            ]
            groups.append(
                {
                    **dict(asset),
                    "copy_count": len(locations),
                    "recommended_keeper": locations[0],
                    "locations": locations,
                }
            )
        return groups

    def _quarantine_operation(self, operation_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM quarantine_operations WHERE id = ?", (operation_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown quarantine operation: {operation_id}")
        return dict(row)

    def quarantine_duplicate(self, location_id: str) -> dict[str, Any]:
        operation_id = str(uuid.uuid4())
        now = _now()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            location = self.connection.execute(
                """
                SELECT * FROM asset_locations
                WHERE id = ? AND unavailable_at IS NULL
                  AND kind IN ('source', 'managed')
                """,
                (location_id,),
            ).fetchone()
            if location is None:
                raise ValueError(f"Duplicate location is unavailable: {location_id}")
            available = int(
                self.connection.execute(
                    """
                    SELECT COUNT(*) FROM asset_locations
                    WHERE asset_id = ? AND unavailable_at IS NULL
                      AND kind IN ('source', 'managed')
                    """,
                    (location["asset_id"],),
                ).fetchone()[0]
            )
            reserved = int(
                self.connection.execute(
                    """
                    SELECT COUNT(*) FROM quarantine_operations
                    WHERE asset_id = ? AND state IN ('planned', 'filesystem_done')
                    """,
                    (location["asset_id"],),
                ).fetchone()[0]
            )
            if available - reserved <= 1:
                raise ValueError("Cannot quarantine the last available copy")
            original = Path(location["path"])
            if not original.is_file():
                raise ValueError(f"Duplicate file is unavailable: {original}")
            target = (
                self.root
                / "quarantine"
                / location["asset_id"]
                / f"{operation_id}-{original.name}"
            )
            self.connection.execute(
                """
                INSERT INTO quarantine_operations(
                    id, location_id, asset_id, original_path, original_kind,
                    quarantine_path, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'planned', ?, ?)
                """,
                (
                    operation_id,
                    location_id,
                    location["asset_id"],
                    str(original),
                    location["kind"],
                    str(target),
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(original), str(target))
        with self.connection:
            self.connection.execute(
                "UPDATE quarantine_operations SET state = 'filesystem_done', updated_at = ? WHERE id = ?",
                (_now(), operation_id),
            )
        completed = _now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE asset_locations
                SET path = ?, kind = 'quarantine', unavailable_at = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (str(target), completed, completed, location_id),
            )
            self.connection.execute(
                "UPDATE quarantine_operations SET state = 'database_done', updated_at = ? WHERE id = ?",
                (completed, operation_id),
            )
        return self._quarantine_operation(operation_id)

    @staticmethod
    def _restore_target(original: Path) -> Path:
        if not original.exists():
            return original
        counter = 1
        while True:
            candidate = original.with_name(
                f"{original.stem}-restored-{counter}{original.suffix}"
            )
            if not candidate.exists():
                return candidate
            counter += 1

    def restore_quarantine(self, operation_id: str) -> dict[str, Any]:
        operation = self._quarantine_operation(operation_id)
        if operation["state"] == "restored":
            return operation
        if operation["state"] != "database_done":
            raise ValueError("Quarantine operation is not ready to restore")
        journal = self.connection.execute(
            "SELECT * FROM quarantine_restore_journal WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if journal is None:
            target = self._restore_target(Path(operation["original_path"]))
            now = _now()
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO quarantine_restore_journal(
                        operation_id, target_path, state, created_at, updated_at
                    ) VALUES (?, ?, 'planned', ?, ?)
                    """,
                    (operation_id, str(target), now, now),
                )
        else:
            target = Path(journal["target_path"])
        quarantined = Path(operation["quarantine_path"])
        if not quarantined.is_file():
            if target.is_file():
                self._finalize_restore(operation, target)
                return self._quarantine_operation(operation_id)
            raise ValueError(f"Quarantined file is unavailable: {quarantined}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(quarantined), str(target))
        with self.connection:
            self.connection.execute(
                """
                UPDATE quarantine_restore_journal
                SET state = 'filesystem_done', updated_at = ?
                WHERE operation_id = ?
                """,
                (_now(), operation_id),
            )
        self._finalize_restore(operation, target)
        return self._quarantine_operation(operation_id)

    def _finalize_restore(self, operation: Mapping[str, Any], target: Path) -> None:
        now = _now()
        with self.connection:
            self.connection.execute(
                """
                UPDATE asset_locations
                SET path = ?, kind = ?, unavailable_at = NULL, last_seen_at = ?
                WHERE id = ?
                """,
                (
                    str(target),
                    operation["original_kind"],
                    now,
                    operation["location_id"],
                ),
            )
            self.connection.execute(
                "UPDATE quarantine_operations SET state = 'restored', updated_at = ? WHERE id = ?",
                (now, operation["id"]),
            )
            self.connection.execute(
                "DELETE FROM quarantine_restore_journal WHERE operation_id = ?",
                (operation["id"],),
            )

    def list_quarantine_operations(
        self, character_id: str | None = None
    ) -> list[dict[str, Any]]:
        if character_id is not None:
            self._character(character_id)
            rows = self.connection.execute(
                """
                SELECT operation.* FROM quarantine_operations operation
                WHERE EXISTS (
                    SELECT 1 FROM character_assets assignment
                    WHERE assignment.character_id = ?
                      AND assignment.asset_id = operation.asset_id
                )
                ORDER BY operation.created_at DESC, operation.id DESC
                """,
                (character_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM quarantine_operations ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [
            dict(row)
            for row in rows
        ]

    def _recover_quarantine_operations(self) -> None:
        rows = self.connection.execute(
            """
            SELECT * FROM quarantine_operations
            WHERE state IN ('planned', 'filesystem_done')
            ORDER BY created_at, id
            """
        ).fetchall()
        for row in rows:
            original = Path(row["original_path"])
            quarantined = Path(row["quarantine_path"])
            if not quarantined.is_file() or original.exists():
                continue
            now = _now()
            with self.connection:
                self.connection.execute(
                    """
                    UPDATE asset_locations
                    SET path = ?, kind = 'quarantine', unavailable_at = ?, last_seen_at = ?
                    WHERE id = ?
                    """,
                    (str(quarantined), now, now, row["location_id"]),
                )
                self.connection.execute(
                    """
                    UPDATE quarantine_operations
                    SET state = 'database_done', updated_at = ? WHERE id = ?
                    """,
                    (now, row["id"]),
                )

    def _recover_restore_operations(self) -> None:
        rows = self.connection.execute(
            """
            SELECT journal.target_path, journal.created_at,
                   operation.*
            FROM quarantine_restore_journal journal
            JOIN quarantine_operations operation
              ON operation.id = journal.operation_id
            ORDER BY journal.created_at, journal.operation_id
            """
        ).fetchall()
        for row in rows:
            target = Path(row["target_path"])
            quarantined = Path(row["quarantine_path"])
            if target.is_file() and not quarantined.exists():
                self._finalize_restore(dict(row), target)

    def create_family(self, character_id: str, name: Any) -> dict[str, Any]:
        self._character(character_id)
        normalized = _name(name)
        family_id = str(uuid.uuid4())
        now = _now()
        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO image_families(
                        id, character_id, name, name_key, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        family_id,
                        character_id,
                        normalized,
                        normalized.casefold(),
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Image family already exists: {normalized}") from error
        return self._family(family_id)

    def _family(self, family_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM image_families WHERE id = ?", (family_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown image family: {family_id}")
        return dict(row)

    def add_family_assets(
        self, family_id: str, asset_ids: Sequence[str]
    ) -> dict[str, int]:
        family = self._family(family_id)
        result = {"added": 0, "already_member": 0}
        for asset_id in dict.fromkeys(str(value) for value in asset_ids):
            assigned = self.connection.execute(
                """
                SELECT 1 FROM character_assets
                WHERE character_id = ? AND asset_id = ?
                """,
                (family["character_id"], asset_id),
            ).fetchone()
            if assigned is None:
                raise ValueError("Family images must already belong to the character")
            with self.connection:
                inserted = self.connection.execute(
                    """
                    INSERT OR IGNORE INTO family_assets(family_id, asset_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (family_id, asset_id, _now()),
                )
            result["added" if inserted.rowcount else "already_member"] += 1
        return result

    def update_family(
        self, family_id: str, name: Any, asset_ids: Sequence[str]
    ) -> dict[str, Any]:
        family = self._family(family_id)
        normalized = _name(name)
        members = list(dict.fromkeys(str(value) for value in asset_ids))
        if not members:
            raise ValueError("Image family must contain at least one image")
        placeholders = ",".join("?" for _ in members)
        assigned = {
            row["asset_id"]
            for row in self.connection.execute(
                f"""
                SELECT asset_id FROM character_assets
                WHERE character_id = ? AND asset_id IN ({placeholders})
                """,
                (family["character_id"], *members),
            ).fetchall()
        }
        missing = [asset_id for asset_id in members if asset_id not in assigned]
        if missing:
            raise ValueError("Family images must already belong to the character")
        now = _now()
        try:
            with self.connection:
                self.connection.execute(
                    """
                    UPDATE image_families
                    SET name = ?, name_key = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (normalized, normalized.casefold(), now, family_id),
                )
                self.connection.execute(
                    f"""
                    DELETE FROM family_assets
                    WHERE family_id = ? AND asset_id NOT IN ({placeholders})
                    """,
                    (family_id, *members),
                )
                self.connection.executemany(
                    """
                    INSERT OR IGNORE INTO family_assets(family_id, asset_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    [(family_id, asset_id, now) for asset_id in members],
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Image family already exists: {normalized}") from error
        return self._family(family_id)

    def set_family_source(self, family_id: str, asset_id: str) -> dict[str, Any]:
        self._family(family_id)
        membership = self.connection.execute(
            "SELECT 1 FROM family_assets WHERE family_id = ? AND asset_id = ?",
            (family_id, asset_id),
        ).fetchone()
        if membership is None:
            raise ValueError("Designated source must be a member of the image family")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO family_sources(family_id, asset_id, designated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(family_id) DO UPDATE SET
                    asset_id = excluded.asset_id,
                    designated_at = excluded.designated_at
                """,
                (family_id, asset_id, _now()),
            )
            self.connection.execute(
                "UPDATE image_families SET updated_at = ? WHERE id = ?",
                (_now(), family_id),
            )
        return self._family(family_id)

    def _dimensions(self, asset_id: str) -> tuple[int, int]:
        row = self.connection.execute(
            "SELECT width, height FROM asset_dimensions WHERE asset_id = ?",
            (asset_id,),
        ).fetchone()
        if row is not None:
            return int(row["width"]), int(row["height"])
        from PIL import Image, ImageOps

        with Image.open(self._asset_path(asset_id)) as image:
            width, height = ImageOps.exif_transpose(image).size
        with self.connection:
            self.connection.execute(
                """
                INSERT OR REPLACE INTO asset_dimensions(asset_id, width, height, measured_at)
                VALUES (?, ?, ?, ?)
                """,
                (asset_id, width, height, _now()),
            )
        return width, height

    def list_families(self, character_id: str) -> list[dict[str, Any]]:
        self._character(character_id)
        families = []
        for family_row in self.connection.execute(
            """
            SELECT family.*, source.asset_id AS designated_source_id
            FROM image_families family
            LEFT JOIN family_sources source ON source.family_id = family.id
            WHERE family.character_id = ?
            ORDER BY family.name_key, family.id
            """,
            (character_id,),
        ).fetchall():
            family = dict(family_row)
            members = []
            for member in self.connection.execute(
                """
                SELECT fa.asset_id, cb.size_bytes, location.path,
                       location.original_name
                FROM family_assets fa
                JOIN assets asset ON asset.id = fa.asset_id
                JOIN content_blobs cb ON cb.id = asset.content_blob_id
                JOIN asset_locations location ON location.id = (
                    SELECT candidate.id FROM asset_locations candidate
                    WHERE candidate.asset_id = asset.id
                      AND candidate.unavailable_at IS NULL
                    ORDER BY CASE candidate.kind WHEN 'managed' THEN 0 ELSE 1 END,
                             candidate.first_seen_at, candidate.id LIMIT 1
                )
                WHERE fa.family_id = ?
                ORDER BY fa.created_at, fa.asset_id
                """,
                (family["id"],),
            ).fetchall():
                item = dict(member)
                try:
                    width, height = self._dimensions(item["asset_id"])
                    pixels = width * height
                except (OSError, ValueError):
                    width, height, pixels = None, None, 0
                item.update(width=width, height=height, pixels=pixels)
                item["generated_count"] = int(
                    self.connection.execute(
                        "SELECT COUNT(*) FROM generation_lineage WHERE source_asset_id = ?",
                        (item["asset_id"],),
                    ).fetchone()[0]
                )
                members.append(item)
            recommended = max(
                members,
                key=lambda item: (item["pixels"], item["size_bytes"], item["asset_id"]),
                default=None,
            )
            family["members"] = members
            family["recommended_source_id"] = (
                recommended["asset_id"] if recommended else None
            )
            families.append(family)
        return families

    def record_generation(
        self,
        run_id: str,
        character_id: str,
        source_asset_id: str,
        output_path: Any,
    ) -> dict[str, Any]:
        if not str(run_id).strip():
            raise ValueError("Generation run ID required")
        self._character(character_id)
        assigned = self.connection.execute(
            """
            SELECT 1 FROM character_assets
            WHERE character_id = ? AND asset_id = ?
            """,
            (character_id, source_asset_id),
        ).fetchone()
        if assigned is None:
            raise ValueError("Generation source must belong to the character")
        path = _resolved_path(output_path)
        if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            raise ValueError("Generation lineage supports still images only")
        registered = self.register_file(path)
        self.assign_asset(
            character_id, registered["asset_id"], assignment_type="lineage"
        )
        lineage_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO generation_lineage(
                    id, run_id, character_id, source_asset_id,
                    output_asset_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    lineage_id,
                    str(run_id),
                    character_id,
                    source_asset_id,
                    registered["asset_id"],
                    _now(),
                ),
            )
        row = self.connection.execute(
            """
            SELECT lineage.*, location.path AS output_path
            FROM generation_lineage lineage
            JOIN asset_locations location ON location.id = (
                SELECT candidate.id FROM asset_locations candidate
                WHERE candidate.asset_id = lineage.output_asset_id
                  AND candidate.unavailable_at IS NULL
                ORDER BY candidate.first_seen_at, candidate.id LIMIT 1
            )
            WHERE lineage.run_id = ? AND lineage.character_id = ?
              AND lineage.source_asset_id = ? AND lineage.output_asset_id = ?
            """,
            (
                str(run_id),
                character_id,
                source_asset_id,
                registered["asset_id"],
            ),
        ).fetchone()
        return dict(row)

    def list_generated_from(self, source_asset_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT lineage.*, location.path AS output_path,
                       location.original_name
                FROM generation_lineage lineage
                JOIN asset_locations location ON location.id = (
                    SELECT candidate.id FROM asset_locations candidate
                    WHERE candidate.asset_id = lineage.output_asset_id
                      AND candidate.unavailable_at IS NULL
                    ORDER BY candidate.first_seen_at, candidate.id LIMIT 1
                )
                WHERE lineage.source_asset_id = ?
                ORDER BY lineage.created_at DESC, lineage.id DESC
                """,
                (source_asset_id,),
            ).fetchall()
        ]
