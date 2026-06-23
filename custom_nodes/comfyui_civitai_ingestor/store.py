from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from .civitai_api import image_resource_refs
from .local_models import find_local_match, target_folder_for_file


SCHEMA_VERSION = 2


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str | None, fallback=None):
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def default_db_path() -> Path:
    import folder_paths

    root = Path(folder_paths.get_system_user_directory("civitai_ingestor"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "civitai_ingestor.sqlite3"


def connect(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path is not None else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS collections (
            collection_id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL,
            api_base TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS images (
            image_id INTEGER PRIMARY KEY,
            collection_id INTEGER NOT NULL,
            post_id INTEGER,
            url TEXT,
            image_hash TEXT,
            width INTEGER,
            height INTEGER,
            nsfw_level TEXT,
            media_type TEXT,
            username TEXT,
            base_model TEXT,
            created_at TEXT,
            has_meta INTEGER NOT NULL DEFAULT 0,
            prompt TEXT,
            negative_prompt TEXT,
            seed TEXT,
            steps TEXT,
            sampler TEXT,
            cfg_scale TEXT,
            meta_json TEXT,
            raw_json TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            FOREIGN KEY(collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS resource_versions (
            model_version_id INTEGER PRIMARY KEY,
            model_id INTEGER,
            version_name TEXT,
            model_name TEXT,
            model_type TEXT,
            base_model TEXT,
            air TEXT,
            trained_words_json TEXT,
            raw_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS resource_files (
            file_id INTEGER PRIMARY KEY,
            model_version_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            file_type TEXT,
            target_folder TEXT NOT NULL,
            size_kb REAL,
            sha256 TEXT,
            auto_v2 TEXT,
            download_url TEXT,
            primary_file INTEGER NOT NULL DEFAULT 0,
            hashes_json TEXT,
            raw_json TEXT NOT NULL,
            local_status TEXT NOT NULL DEFAULT 'unknown',
            match_type TEXT,
            local_path TEXT,
            local_folder TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(model_version_id) REFERENCES resource_versions(model_version_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS image_resources (
            image_id INTEGER NOT NULL,
            model_version_id INTEGER NOT NULL,
            resource_type TEXT,
            weight REAL,
            name TEXT,
            source TEXT NOT NULL,
            PRIMARY KEY(image_id, model_version_id, source),
            FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE,
            FOREIGN KEY(model_version_id) REFERENCES resource_versions(model_version_id) ON DELETE CASCADE
        );
        """
    )
    ensure_columns(
        conn,
        "images",
        {
            "local_image_path": "TEXT",
            "local_image_status": "TEXT NOT NULL DEFAULT 'remote'",
            "local_image_error": "TEXT",
            "local_image_cached_at": "TEXT",
        },
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})")
    }
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def upsert_collection(
    conn: sqlite3.Connection,
    *,
    collection_id: int,
    source_url: str,
    api_base: str,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO collections(collection_id, source_url, api_base, imported_at, updated_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(collection_id) DO UPDATE SET
            source_url=excluded.source_url,
            api_base=excluded.api_base,
            updated_at=excluded.updated_at
        """,
        (collection_id, source_url, api_base, now, now),
    )


def upsert_image(conn: sqlite3.Connection, collection_id: int, image: dict[str, Any]) -> None:
    meta = image.get("meta") if isinstance(image.get("meta"), dict) else None
    now = utc_now()
    conn.execute(
        """
        INSERT INTO images(
            image_id, collection_id, post_id, url, image_hash, width, height,
            nsfw_level, media_type, username, base_model, created_at, has_meta,
            prompt, negative_prompt, seed, steps, sampler, cfg_scale,
            meta_json, raw_json, imported_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(image_id) DO UPDATE SET
            collection_id=excluded.collection_id,
            post_id=excluded.post_id,
            url=excluded.url,
            image_hash=excluded.image_hash,
            width=excluded.width,
            height=excluded.height,
            nsfw_level=excluded.nsfw_level,
            media_type=excluded.media_type,
            username=excluded.username,
            base_model=excluded.base_model,
            created_at=excluded.created_at,
            has_meta=excluded.has_meta,
            prompt=excluded.prompt,
            negative_prompt=excluded.negative_prompt,
            seed=excluded.seed,
            steps=excluded.steps,
            sampler=excluded.sampler,
            cfg_scale=excluded.cfg_scale,
            meta_json=excluded.meta_json,
            raw_json=excluded.raw_json,
            imported_at=excluded.imported_at
        """,
        (
            image.get("id"),
            collection_id,
            image.get("postId"),
            image.get("url"),
            image.get("hash"),
            image.get("width"),
            image.get("height"),
            str(image.get("nsfwLevel") or ""),
            image.get("type"),
            image.get("username"),
            image.get("baseModel"),
            image.get("createdAt"),
            1 if meta else 0,
            meta.get("prompt") if meta else None,
            meta.get("negativePrompt") if meta else None,
            str(meta.get("seed")) if meta and meta.get("seed") is not None else None,
            str(meta.get("steps")) if meta and meta.get("steps") is not None else None,
            meta.get("sampler") if meta else None,
            str(meta.get("cfgScale")) if meta and meta.get("cfgScale") is not None else None,
            dumps(meta) if meta else None,
            dumps(image),
            now,
        ),
    )


def upsert_image_resource_links(conn: sqlite3.Connection, image: dict[str, Any]) -> list[int]:
    image_id = image.get("id")
    version_ids: list[int] = []
    for ref in image_resource_refs(image):
        version_id = int(ref["model_version_id"])
        version_ids.append(version_id)
        conn.execute(
            """
            INSERT OR IGNORE INTO resource_versions(
                model_version_id, raw_json, fetched_at
            )
            VALUES(?, '{}', ?)
            """,
            (version_id, utc_now()),
        )
        conn.execute(
            """
            INSERT INTO image_resources(image_id, model_version_id, resource_type, weight, name, source)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(image_id, model_version_id, source) DO UPDATE SET
                resource_type=excluded.resource_type,
                weight=excluded.weight,
                name=excluded.name
            """,
            (
                image_id,
                version_id,
                ref.get("resource_type"),
                ref.get("weight"),
                ref.get("name"),
                ref.get("source") or "unknown",
            ),
        )
    return version_ids


def upsert_model_version(conn: sqlite3.Connection, version: dict[str, Any]) -> None:
    model = version.get("model") if isinstance(version.get("model"), dict) else {}
    now = utc_now()
    conn.execute(
        """
        INSERT INTO resource_versions(
            model_version_id, model_id, version_name, model_name, model_type,
            base_model, air, trained_words_json, raw_json, fetched_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(model_version_id) DO UPDATE SET
            model_id=excluded.model_id,
            version_name=excluded.version_name,
            model_name=excluded.model_name,
            model_type=excluded.model_type,
            base_model=excluded.base_model,
            air=excluded.air,
            trained_words_json=excluded.trained_words_json,
            raw_json=excluded.raw_json,
            fetched_at=excluded.fetched_at
        """,
        (
            version.get("id"),
            version.get("modelId"),
            version.get("name"),
            model.get("name"),
            model.get("type"),
            version.get("baseModel"),
            version.get("air"),
            dumps(version.get("trainedWords") or []),
            dumps(version),
            now,
        ),
    )

    for file_item in version.get("files") or []:
        if not isinstance(file_item, dict) or file_item.get("type") == "Training Data":
            continue
        hashes = file_item.get("hashes") if isinstance(file_item.get("hashes"), dict) else {}
        conn.execute(
            """
            INSERT INTO resource_files(
                file_id, model_version_id, file_name, file_type, target_folder,
                size_kb, sha256, auto_v2, download_url, primary_file,
                hashes_json, raw_json, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id) DO UPDATE SET
                model_version_id=excluded.model_version_id,
                file_name=excluded.file_name,
                file_type=excluded.file_type,
                target_folder=excluded.target_folder,
                size_kb=excluded.size_kb,
                sha256=excluded.sha256,
                auto_v2=excluded.auto_v2,
                download_url=excluded.download_url,
                primary_file=excluded.primary_file,
                hashes_json=excluded.hashes_json,
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """,
            (
                file_item.get("id"),
                version.get("id"),
                file_item.get("name"),
                file_item.get("type"),
                target_folder_for_file(version, file_item),
                file_item.get("sizeKB"),
                hashes.get("SHA256"),
                hashes.get("AutoV2"),
                file_item.get("downloadUrl") or version.get("downloadUrl"),
                1 if file_item.get("primary") else 0,
                dumps(hashes),
                dumps(file_item),
                now,
            ),
        )


def refresh_local_status(
    conn: sqlite3.Connection,
    *,
    collection_id: int | None = None,
    folder_paths_module=None,
) -> dict[str, int]:
    where = ""
    params: tuple[Any, ...] = ()
    if collection_id is not None:
        where = """
        WHERE rf.model_version_id IN (
            SELECT DISTINCT model_version_id
            FROM image_resources ir
            JOIN images i ON i.image_id = ir.image_id
            WHERE i.collection_id = ?
        )
        """
        params = (collection_id,)

    rows = conn.execute(
        f"""
        SELECT rf.file_id, rf.file_name, rf.target_folder
        FROM resource_files rf
        {where}
        """,
        params,
    ).fetchall()

    counts = {"present": 0, "present_elsewhere": 0, "missing": 0}
    for row in rows:
        match = find_local_match(
            row["file_name"],
            row["target_folder"],
            folder_paths_module=folder_paths_module,
        )
        counts[match["status"]] = counts.get(match["status"], 0) + 1
        conn.execute(
            """
            UPDATE resource_files SET
                local_status=?,
                match_type=?,
                local_path=?,
                local_folder=?,
                updated_at=?
            WHERE file_id=?
            """,
            (
                match["status"],
                match.get("match_type"),
                match.get("local_path"),
                match.get("local_folder"),
                utc_now(),
                row["file_id"],
            ),
        )
    return counts


def collection_payload(
    conn: sqlite3.Connection,
    collection_id: int,
    *,
    include_raw: bool = False,
) -> dict[str, Any]:
    collection = conn.execute(
        "SELECT * FROM collections WHERE collection_id=?", (collection_id,)
    ).fetchone()
    images = [
        row_to_image(row, include_raw=include_raw)
        for row in conn.execute(
            """
            SELECT * FROM images
            WHERE collection_id=?
            ORDER BY imported_at DESC, image_id DESC
            """,
            (collection_id,),
        )
    ]
    files = [
        row_to_resource_file(row, include_raw=include_raw)
        for row in conn.execute(
            """
            SELECT
                rf.*,
                rv.version_name,
                rv.model_name,
                rv.model_type,
                rv.base_model,
                rv.air,
                rv.trained_words_json,
                rv.raw_json AS version_raw_json
            FROM resource_files rf
            JOIN resource_versions rv ON rv.model_version_id = rf.model_version_id
            WHERE rf.model_version_id IN (
                SELECT DISTINCT ir.model_version_id
                FROM image_resources ir
                JOIN images i ON i.image_id = ir.image_id
                WHERE i.collection_id=?
            )
            ORDER BY rf.local_status DESC, rv.model_type, rv.model_name, rf.file_name
            """,
            (collection_id,),
        )
    ]
    links = [
        dict(row)
        for row in conn.execute(
            """
            SELECT ir.*
            FROM image_resources ir
            JOIN images i ON i.image_id = ir.image_id
            WHERE i.collection_id=?
            """,
            (collection_id,),
        )
    ]
    summary = {
        "images": len(images),
        "images_with_meta": sum(1 for image in images if image.get("has_meta")),
        "resource_files": len(files),
        "missing_files": sum(1 for item in files if item.get("local_status") == "missing"),
        "present_files": sum(1 for item in files if item.get("local_status", "").startswith("present")),
    }
    return {
        "collection": dict(collection) if collection else None,
        "summary": summary,
        "images": images,
        "resources": files,
        "image_resources": links,
    }


def row_to_image(row: sqlite3.Row, *, include_raw: bool = False) -> dict[str, Any]:
    data = dict(row)
    data["has_meta"] = bool(data["has_meta"])
    data["meta"] = loads(data.pop("meta_json"), None)
    raw_json = data.pop("raw_json")
    if include_raw:
        data["raw"] = loads(raw_json, {})
    return data


def row_to_resource_file(row: sqlite3.Row, *, include_raw: bool = False) -> dict[str, Any]:
    data = dict(row)
    data["primary_file"] = bool(data["primary_file"])
    data["hashes"] = loads(data.pop("hashes_json"), {})
    raw_json = data.pop("raw_json")
    data["trained_words"] = loads(data.pop("trained_words_json", None), [])
    version_raw_json = data.pop("version_raw_json", None)
    if include_raw:
        data["raw"] = loads(raw_json, {})
        data["version_raw"] = loads(version_raw_json, {})
    return data


def get_image_context(conn: sqlite3.Connection, image_id: int) -> dict[str, Any]:
    image_row = conn.execute("SELECT * FROM images WHERE image_id=?", (image_id,)).fetchone()
    if image_row is None:
        raise ValueError(f"Image {image_id} was not found.")
    image = row_to_image(image_row)
    links = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM image_resources WHERE image_id=? ORDER BY source, model_version_id",
            (image_id,),
        )
    ]
    version_ids = sorted({int(link["model_version_id"]) for link in links})
    resources: list[dict[str, Any]] = []
    if version_ids:
        placeholders = ",".join("?" for _ in version_ids)
        resources = [
            row_to_resource_file(row)
            for row in conn.execute(
                f"""
                SELECT
                    rf.*,
                    rv.version_name,
                    rv.model_name,
                    rv.model_type,
                    rv.base_model,
                    rv.air,
                    rv.trained_words_json,
                    rv.raw_json AS version_raw_json
                FROM resource_files rf
                JOIN resource_versions rv ON rv.model_version_id = rf.model_version_id
                WHERE rf.model_version_id IN ({placeholders})
                ORDER BY rf.primary_file DESC, rf.file_name
                """,
                tuple(version_ids),
            )
        ]
    return {"image": image, "resources": resources, "image_resources": links}


def get_resource_files(conn: sqlite3.Connection, file_ids: list[int]) -> list[dict[str, Any]]:
    if not file_ids:
        return []
    placeholders = ",".join("?" for _ in file_ids)
    return [
        row_to_resource_file(row)
        for row in conn.execute(
            f"""
            SELECT
                rf.*,
                rv.version_name,
                rv.model_name,
                rv.model_type,
                rv.base_model,
                rv.air,
                rv.trained_words_json,
                rv.raw_json AS version_raw_json
            FROM resource_files rf
            JOIN resource_versions rv ON rv.model_version_id = rf.model_version_id
            WHERE rf.file_id IN ({placeholders})
            """,
            tuple(file_ids),
        )
    ]
