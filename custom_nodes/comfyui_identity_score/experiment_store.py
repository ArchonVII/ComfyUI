"""Small transactional SQLite store for local identity experiment metadata."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from math import isfinite
from pathlib import Path, PureWindowsPath
import sqlite3
from typing import Any, Iterator, Mapping
from uuid import uuid4

from .experiment_planner import PlannedRun, VALID_MODES, canonical_combination_hash


RUN_STATES = frozenset({"planned", "queued", "running", "completed", "failed", "archived"})
_TRANSITIONS = {
    "planned": frozenset({"queued", "archived"}),
    "queued": frozenset({"running", "archived"}),
    "running": frozenset({"queued", "failed", "archived"}),
    "completed": frozenset({"archived"}),
    "failed": frozenset({"queued", "archived"}),
    "archived": frozenset(),
}
_UNSET = object()
MAX_EXPERIMENT_RUNS = 100


class ExperimentStore:
    """Owns a SQLite database for one local user and one generation worker."""

    def __init__(self, path: str | Path):
        self.path = str(Path(path))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create_experiment(self, *, name: str, mode: str, settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("experiment name must be a non-empty string")
        if mode not in VALID_MODES:
            raise ValueError(f"invalid experiment mode: {mode!r}")
        settings_json = _encode_json(dict(settings or {}), label="settings", reject_embeddings=True)
        now = _utc_now()
        experiment_id = str(uuid4())
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO experiments (id, name, mode, state, settings_json, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?, ?)
                """,
                (experiment_id, name.strip(), mode.strip(), settings_json, now, now),
            )
            return self._fetch_experiment(connection, experiment_id)

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            return self._fetch_experiment(connection, experiment_id)

    def archive_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            self._fetch_experiment(connection, experiment_id)
            connection.execute("UPDATE experiments SET state = 'archived', updated_at = ? WHERE id = ?", (_utc_now(), experiment_id))
            return self._fetch_experiment(connection, experiment_id)

    def create_run(self, experiment_id: str, planned_run: PlannedRun) -> dict[str, Any]:
        if not isinstance(planned_run, PlannedRun):
            raise ValueError("planned_run must be a PlannedRun")
        plan = planned_run.as_dict()
        expected_hash = canonical_combination_hash(plan)
        if planned_run.combination_hash != expected_hash:
            raise ValueError("planned_run does not have its canonical combination hash")
        plan_json = _encode_json(plan, label="plan", reject_embeddings=True)
        now = _utc_now()
        with self._connection() as connection:
            experiment = self._fetch_experiment(connection, experiment_id)
            if experiment["state"] != "active":
                raise ValueError("cannot add runs to an archived experiment")
            if planned_run.mode != experiment["mode"]:
                raise ValueError("planned run mode must match the experiment mode")
            run_id = str(uuid4())
            inserted = connection.execute(
                """
                INSERT INTO runs (
                    id, experiment_id, combination_hash, state, plan_json, identity_report_json,
                    output_path, rating, favorite, notes, created_at, updated_at, started_at, completed_at
                )
                SELECT ?, id, ?, 'planned', ?, NULL, NULL, NULL, 0, '', ?, ?, NULL, NULL
                FROM experiments
                WHERE id = ? AND state = 'active' AND mode = ?
                ON CONFLICT(experiment_id, combination_hash) DO NOTHING
                RETURNING *
                """,
                (run_id, planned_run.combination_hash, plan_json, now, now, experiment_id, planned_run.mode),
            ).fetchone()
            if inserted is not None:
                return _decode_run(inserted)
            existing = connection.execute(
                "SELECT * FROM runs WHERE experiment_id = ? AND combination_hash = ?", (experiment_id, planned_run.combination_hash)
            ).fetchone()
            if existing is None:
                experiment = self._fetch_experiment(connection, experiment_id)
                if experiment["state"] != "active":
                    raise ValueError("cannot add runs to an archived experiment")
                if planned_run.mode != experiment["mode"]:
                    raise ValueError("planned run mode must match the experiment mode")
                raise ValueError("run insertion did not produce a deterministic existing row")
            return _verified_existing_run(existing, plan)

    insert_run = create_run

    def create_runs(self, experiment_id: str, planned_runs: list[PlannedRun]) -> list[dict[str, Any]]:
        """Atomically add a deduplicated batch without exceeding the experiment cap."""
        unique = {run.combination_hash: run for run in planned_runs}
        with self._connection() as connection:
            experiment = self._fetch_experiment(connection, experiment_id)
            if experiment["state"] != "active":
                raise ValueError("cannot add runs to an archived experiment")
            existing = {row["combination_hash"] for row in connection.execute("SELECT combination_hash FROM runs WHERE experiment_id = ?", (experiment_id,))}
            additions = [run for key, run in unique.items() if key not in existing]
            if len(existing) + len(additions) > MAX_EXPERIMENT_RUNS:
                raise ValueError("experiment cannot exceed 100 runs")
            result: list[dict[str, Any]] = []
            for run in planned_runs:
                if not isinstance(run, PlannedRun) or run.combination_hash != canonical_combination_hash(run.as_dict()):
                    raise ValueError("planned_run does not have its canonical combination hash")
                row = connection.execute("SELECT * FROM runs WHERE experiment_id = ? AND combination_hash = ?", (experiment_id, run.combination_hash)).fetchone()
                if row is None:
                    now = _utc_now()
                    connection.execute("INSERT INTO runs (id, experiment_id, combination_hash, state, plan_json, identity_report_json, output_path, rating, favorite, notes, created_at, updated_at, started_at, queued_at, completed_at) VALUES (?, ?, ?, 'planned', ?, NULL, NULL, NULL, 0, '', ?, ?, NULL, NULL, NULL)", (str(uuid4()), experiment_id, run.combination_hash, _encode_json(run.as_dict(), label="plan", reject_embeddings=True), now, now))
                    row = connection.execute("SELECT * FROM runs WHERE experiment_id = ? AND combination_hash = ?", (experiment_id, run.combination_hash)).fetchone()
                result.append(_decode_run(row))
            return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            return self._fetch_run(connection, run_id)

    def list_runs(self, experiment_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            self._fetch_experiment(connection, experiment_id)
            rows = connection.execute("SELECT * FROM runs WHERE experiment_id = ? ORDER BY created_at, id", (experiment_id,)).fetchall()
            return [_decode_run(row) for row in rows]

    def transition_run(self, run_id: str, target_state: str) -> dict[str, Any]:
        if target_state not in RUN_STATES:
            raise ValueError(f"unknown state: {target_state!r}")
        with self._connection() as connection:
            run = self._fetch_run(connection, run_id)
            if target_state not in _TRANSITIONS[run["state"]]:
                raise ValueError(f"invalid state transition: {run['state']} -> {target_state}")
            now = _utc_now()
            started_at = now if target_state == "running" else run["started_at"]
            updated = connection.execute(
                "UPDATE runs SET state = ?, updated_at = ?, started_at = ? WHERE id = ? AND state = ? AND updated_at = ?",
                (target_state, now, started_at, run_id, run["state"], run["updated_at"]),
            )
            if updated.rowcount != 1:
                raise ValueError("run state changed concurrently")
            return self._fetch_run(connection, run_id)

    def mark_run_queued(self, *, experiment_id: str, run_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            run = self._fetch_run(connection, run_id)
            if run["experiment_id"] != experiment_id or run["state"] not in {"planned", "failed"}:
                raise ValueError("run is not queueable")
            now = _utc_now()
            connection.execute("UPDATE runs SET state = 'queued', queued_at = ?, updated_at = ? WHERE id = ?", (now, now, run_id))
            return self._fetch_run(connection, run_id)

    def resume_stale_runs(
        self,
        *,
        stale_after_seconds: float,
        experiment_id: str | None = None,
        active_run_ids: set[str] | frozenset[str] = frozenset(),
    ) -> list[dict[str, Any]]:
        if (
            isinstance(stale_after_seconds, bool)
            or not isinstance(stale_after_seconds, (int, float))
            or not isfinite(stale_after_seconds)
            or stale_after_seconds < 0
        ):
            raise ValueError("stale_after_seconds must be a finite non-negative number")
        if experiment_id is not None and (not isinstance(experiment_id, str) or not experiment_id):
            raise ValueError("experiment_id must be a non-empty string")
        if not isinstance(active_run_ids, (set, frozenset)) or not all(isinstance(run_id, str) and run_id for run_id in active_run_ids):
            raise ValueError("active_run_ids must be a set of non-empty strings")
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        cutoff_text = cutoff.isoformat(timespec="microseconds").replace("+00:00", "Z")
        now = _utc_now()
        with self._connection() as connection:
            if experiment_id is not None:
                self._fetch_experiment(connection, experiment_id)
            clauses = ["state IN ('queued', 'running')", "updated_at <= ?"]
            values: list[Any] = [cutoff_text]
            if experiment_id is not None:
                clauses.append("experiment_id = ?")
                values.append(experiment_id)
            if active_run_ids:
                placeholders = ", ".join("?" for _ in active_run_ids)
                clauses.append(f"id NOT IN ({placeholders})")
                values.extend(sorted(active_run_ids))
            rows = connection.execute(
                "SELECT id, state, updated_at FROM runs WHERE " + " AND ".join(clauses) + " ORDER BY updated_at, id",
                values,
            ).fetchall()
            resumed: list[dict[str, Any]] = []
            for row in rows:
                updated = connection.execute(
                    """
                UPDATE runs SET state = 'planned', output_path = NULL, updated_at = ?, started_at = NULL
                    WHERE id = ? AND state = ? AND updated_at = ?
                    """,
                    (now, row["id"], row["state"], row["updated_at"]),
                )
                if updated.rowcount == 1:
                    resumed.append(self._fetch_run(connection, row["id"]))
            return resumed

    def complete_recorded_run(
        self,
        *,
        experiment_id: str,
        run_id: str,
        output_path: str,
        identity_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically complete exactly one active recorded run without state hops."""
        normalized_path = _relative_output_path(output_path)
        report_json = _encode_json(dict(identity_report), label="identity report", reject_embeddings=True)
        with self._connection() as connection:
            self._fetch_experiment(connection, experiment_id)
            run = self._fetch_run(connection, run_id)
            if run["experiment_id"] != experiment_id:
                raise ValueError("run does not belong to experiment")
            if run["state"] not in {"planned", "queued", "running"}:
                raise ValueError(f"run is not recordable from state: {run['state']}")
            now = _utc_now()
            queued_at = run.get("queued_at")
            report = dict(identity_report)
            if queued_at:
                report["runtime_seconds"] = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(queued_at.replace("Z", "+00:00"))).total_seconds())
                report["runtime_source"] = "queued_to_completion"
            else:
                report["runtime_source"] = "completion_fallback"
            report_json = _encode_json(report, label="identity report", reject_embeddings=True)
            updated = connection.execute(
                """
                UPDATE runs
                SET state = 'completed', output_path = ?, identity_report_json = ?, updated_at = ?, completed_at = ?
                WHERE id = ? AND experiment_id = ? AND state = ? AND updated_at = ?
                    AND (output_path IS NULL OR output_path = ?) AND identity_report_json IS NULL
                """,
                (normalized_path, report_json, now, now, run_id, experiment_id, run["state"], run["updated_at"], normalized_path),
            )
            if updated.rowcount != 1:
                raise ValueError("run state changed concurrently")
            return self._fetch_run(connection, run_id)

    def claim_recorded_run(self, *, experiment_id: str, run_id: str, output_path: str) -> dict[str, Any]:
        """Reserve one output path before a recorder creates its local file."""
        normalized_path = _relative_output_path(output_path)
        with self._connection() as connection:
            self._fetch_experiment(connection, experiment_id)
            run = self._fetch_run(connection, run_id)
            if run["experiment_id"] != experiment_id:
                raise ValueError("run does not belong to experiment")
            if run["state"] not in {"planned", "queued", "running"} or run["output_path"] is not None or run["identity_report"] is not None:
                raise ValueError("run is not recordable")
            now = _utc_now()
            updated = connection.execute(
                """
                UPDATE runs SET state = 'running', output_path = ?, updated_at = ?, started_at = COALESCE(started_at, ?)
                WHERE id = ? AND experiment_id = ? AND state = ? AND updated_at = ?
                    AND output_path IS NULL AND identity_report_json IS NULL
                """,
                (normalized_path, now, now, run_id, experiment_id, run["state"], run["updated_at"]),
            )
            if updated.rowcount != 1:
                raise ValueError("run is not recordable")
            return self._fetch_run(connection, run_id)

    def fail_recorded_run(self, *, experiment_id: str, run_id: str, error: str) -> dict[str, Any]:
        if not isinstance(error, str) or not error.strip():
            raise ValueError("error must be a non-empty string")
        report_json = _encode_json({"error": error.strip()[:500], "rankable": False}, label="failure report", reject_embeddings=True)
        with self._connection() as connection:
            self._fetch_experiment(connection, experiment_id)
            run = self._fetch_run(connection, run_id)
            if run["experiment_id"] != experiment_id:
                raise ValueError("run does not belong to experiment")
            if run["state"] not in {"planned", "queued", "running"}:
                raise ValueError(f"run is not fail-able from state: {run['state']}")
            now = _utc_now()
            updated = connection.execute(
                """
                UPDATE runs SET state = 'failed', output_path = NULL, identity_report_json = ?, updated_at = ?
                WHERE id = ? AND experiment_id = ? AND state = ? AND updated_at = ?
                """,
                (report_json, now, run_id, experiment_id, run["state"], run["updated_at"]),
            )
            if updated.rowcount != 1:
                raise ValueError("run state changed concurrently")
            return self._fetch_run(connection, run_id)

    def complete_run(self, run_id: str, *, output_path: str, identity_report: Mapping[str, Any]) -> dict[str, Any]:
        normalized_path = _relative_output_path(output_path)
        report_json = _encode_json(dict(identity_report), label="identity report", reject_embeddings=True)
        with self._connection() as connection:
            run = self._fetch_run(connection, run_id)
            if run["state"] == "completed":
                raise ValueError("completed run data is immutable")
            if run["state"] != "running":
                raise ValueError(f"invalid state transition: {run['state']} -> completed")
            now = _utc_now()
            updated = connection.execute(
                """
                UPDATE runs
                SET state = 'completed', output_path = ?, identity_report_json = ?, updated_at = ?, completed_at = ?
                WHERE id = ? AND state = 'running' AND updated_at = ?
                    AND output_path IS NULL AND identity_report_json IS NULL
                """,
                (normalized_path, report_json, now, now, run_id, run["updated_at"]),
            )
            if updated.rowcount != 1:
                current = self._fetch_run(connection, run_id)
                if current["state"] == "completed":
                    raise ValueError("completed run data is immutable")
                raise ValueError("run state changed concurrently")
            return self._fetch_run(connection, run_id)

    def update_review(
        self,
        run_id: str,
        *,
        rating: int | None | object = _UNSET,
        favorite: bool | object = _UNSET,
        notes: str | object = _UNSET,
    ) -> dict[str, Any]:
        with self._connection() as connection:
            run = self._fetch_run(connection, run_id)
            if run["state"] != "completed":
                raise ValueError("reviews are only allowed for completed runs")
            assignments: list[str] = []
            values: list[Any] = []
            if rating is not _UNSET:
                assignments.append("rating = ?")
                values.append(_validate_rating(rating))
            if favorite is not _UNSET:
                assignments.append("favorite = ?")
                values.append(int(_validate_favorite(favorite)))
            if notes is not _UNSET:
                assignments.append("notes = ?")
                values.append(_validate_notes(notes))
            if not assignments:
                return run
            assignments.append("updated_at = ?")
            values.extend([_utc_now(), run_id])
            updated = connection.execute(
                f"UPDATE runs SET {', '.join(assignments)} WHERE id = ? AND state = 'completed'",
                values,
            )
            if updated.rowcount != 1:
                raise ValueError("run state changed concurrently")
            return self._fetch_run(connection, run_id)

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK (mode IN ('face_swap', 'identity_i2i')),
                    state TEXT NOT NULL CHECK (state IN ('active', 'archived')),
                    settings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    combination_hash TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('planned', 'queued', 'running', 'completed', 'failed', 'archived')),
                    plan_json TEXT NOT NULL,
                    identity_report_json TEXT,
                    output_path TEXT,
                    rating INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
                    favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    queued_at TEXT,
                    completed_at TEXT,
                    UNIQUE (experiment_id, combination_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_runs_experiment_created ON runs(experiment_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_runs_state_updated ON runs(state, updated_at);
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
            if "queued_at" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN queued_at TEXT")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _fetch_experiment(connection: sqlite3.Connection, experiment_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(f"experiment not found: {experiment_id}")
        return _decode_experiment(row)

    @staticmethod
    def _fetch_run(connection: sqlite3.Connection, run_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"run not found: {run_id}")
        return _decode_run(row)


def _decode_experiment(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["settings"] = json.loads(result.pop("settings_json"))
    return result


def _decode_run(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["plan"] = json.loads(result.pop("plan_json"))
    report_json = result.pop("identity_report_json")
    result["identity_report"] = json.loads(report_json) if report_json is not None else None
    result["favorite"] = bool(result["favorite"])
    return result


def _verified_existing_run(row: sqlite3.Row, incoming_plan: Mapping[str, Any]) -> dict[str, Any]:
    existing = _decode_run(row)
    existing_hash = canonical_combination_hash(existing["plan"])
    if existing_hash != existing["combination_hash"]:
        raise ValueError("existing run integrity error: hash does not match its payload")
    if _canonical_plan_json(existing["plan"]) != _canonical_plan_json(incoming_plan):
        raise ValueError("existing run integrity error: hash maps to a different payload")
    return existing


def _canonical_plan_json(plan: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "combination_hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _relative_output_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("output_path must be a non-empty relative path")
    normalized = value.replace("\\", "/")
    windows_path = PureWindowsPath(normalized)
    if normalized.startswith("/") or Path(normalized).is_absolute() or windows_path.is_absolute() or windows_path.drive or ".." in Path(normalized).parts:
        raise ValueError("output_path must be a relative path")
    return normalized


def _encode_json(value: Any, *, label: str, reject_embeddings: bool = False) -> str:
    if reject_embeddings:
        _reject_sensitive_completion_data(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain JSON-compatible values") from exc


def _reject_sensitive_completion_data(value: Any) -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("identity report must not contain image bytes")
    if isinstance(value, str) and value.lstrip().lower().startswith("data:image/"):
        raise ValueError("identity report must not contain image payloads")
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = "".join(character for character in str(key).lower() if character.isalnum())
            if "embedding" in normalized_key:
                raise ValueError("identity report must not contain embeddings")
            if any(marker in normalized_key for marker in ("base64", "b64", "bytes", "blob", "datauri")):
                raise ValueError("identity report must not contain image payloads")
            _reject_sensitive_completion_data(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_sensitive_completion_data(item)


def _validate_rating(value: int | None | object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError("rating must be an integer from 1 to 5 or None")
    return value


def _validate_favorite(value: bool | object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("favorite must be a boolean")
    return value


def _validate_notes(value: str | object) -> str:
    if not isinstance(value, str):
        raise ValueError("notes must be a string")
    return value
