from dataclasses import replace
from pathlib import Path
import sqlite3
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_identity_score.experiment_planner import plan_runs
from comfyui_identity_score.experiment_store import ExperimentStore


@pytest.fixture
def store(tmp_path):
    return ExperimentStore(tmp_path / "experiments.sqlite3")


@pytest.fixture
def planned_run():
    return plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[7], stages=["baseline"])[0]


def test_store_initializes_sqlite_schema_with_foreign_keys_and_wal(store):
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'experiments'").fetchone()
        assert connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'runs'").fetchone()

    experiment = store.create_experiment(name="Baseline", mode="face_swap", settings={"prompt": "portrait"})
    assert experiment["name"] == "Baseline"
    assert experiment["mode"] == "face_swap"
    assert experiment["state"] == "active"
    assert experiment["settings"] == {"prompt": "portrait"}
    assert isinstance(experiment, dict)


def test_store_creates_one_run_per_experiment_combination_hash(store, planned_run):
    first_experiment = store.create_experiment(name="First", mode="face_swap")
    second_experiment = store.create_experiment(name="Second", mode="face_swap")

    first = store.create_run(first_experiment["id"], planned_run)
    duplicate = store.create_run(first_experiment["id"], planned_run)
    second = store.create_run(second_experiment["id"], planned_run)

    assert first["id"] == duplicate["id"]
    assert second["id"] != first["id"]
    assert store.list_runs(first_experiment["id"]) == [first]
    assert first["combination_hash"] == planned_run.combination_hash
    assert first["plan"] == planned_run.as_dict()
    assert first["state"] == "planned"


def test_store_insert_is_atomic_against_experiment_archival(store, planned_run, monkeypatch):
    experiment = store.create_experiment(name="Archive race", mode="face_swap")
    original_fetch = store._fetch_experiment
    archived = False

    def fetch_then_archive(connection, experiment_id):
        nonlocal archived
        row = original_fetch(connection, experiment_id)
        if not archived:
            archived = True
            with sqlite3.connect(store.path) as other:
                other.execute("UPDATE experiments SET state = 'archived' WHERE id = ?", (experiment_id,))
        return row

    monkeypatch.setattr(store, "_fetch_experiment", fetch_then_archive)
    with pytest.raises(ValueError, match="archived"):
        store.create_run(experiment["id"], planned_run)
    monkeypatch.setattr(store, "_fetch_experiment", original_fetch)
    assert store.list_runs(experiment["id"]) == []


def test_store_requires_valid_matching_modes_and_durable_mode_constraints(store, planned_run):
    with pytest.raises(ValueError, match="mode"):
        store.create_experiment(name="Invalid", mode="txt2img")

    experiment = store.create_experiment(name="Mode", mode="face_swap")
    mismatched = plan_runs(mode="identity_i2i", checkpoints=["flux"], seeds=[8], stages=["baseline"])[0]
    with pytest.raises(ValueError, match="mode"):
        store.create_run(experiment["id"], mismatched)

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO experiments (id, name, mode, state, settings_json, created_at, updated_at)
                VALUES ('invalid-mode', 'Invalid', 'txt2img', 'active', '{}', '2000-01-01T00:00:00Z', '2000-01-01T00:00:00Z')
                """
            )


def test_store_verifies_canonical_hashes_and_rejects_conflicting_existing_payloads(store, planned_run):
    experiment = store.create_experiment(name="Integrity", mode="face_swap")
    with pytest.raises(ValueError, match="canonical combination hash"):
        store.create_run(experiment["id"], replace(planned_run, combination_hash="not-a-hash"))

    first = store.create_run(experiment["id"], planned_run)
    second_plan = plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[8], stages=["baseline"])[0]
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE runs SET combination_hash = ? WHERE id = ?", (second_plan.combination_hash, first["id"]))

    with pytest.raises(ValueError, match="integrity"):
        store.create_run(experiment["id"], second_plan)


def test_store_enforces_valid_run_state_transitions(store, planned_run):
    experiment = store.create_experiment(name="States", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)

    assert store.transition_run(run["id"], "queued")["state"] == "queued"
    assert store.transition_run(run["id"], "running")["state"] == "running"
    assert store.transition_run(run["id"], "failed")["state"] == "failed"
    assert store.transition_run(run["id"], "queued")["state"] == "queued"
    assert store.transition_run(run["id"], "archived")["state"] == "archived"
    with pytest.raises(ValueError, match="invalid state transition"):
        store.transition_run(run["id"], "running")
    with pytest.raises(ValueError, match="unknown state"):
        store.transition_run(run["id"], "discarded")


def test_store_resumes_stale_queued_and_running_runs_to_planned_without_touching_fresh_runs(store, planned_run):
    experiment = store.create_experiment(name="Resume", mode="face_swap")
    stale_running = store.create_run(experiment["id"], planned_run)
    stale_queued = store.create_run(
        experiment["id"], plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[8], stages=["baseline"])[0]
    )
    fresh_queued = store.create_run(
        experiment["id"], plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[9], stages=["baseline"])[0]
    )
    store.transition_run(stale_running["id"], "queued")
    store.transition_run(stale_running["id"], "running")
    store.transition_run(stale_queued["id"], "queued")
    store.transition_run(fresh_queued["id"], "queued")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            """
            UPDATE runs
            SET updated_at = '2000-01-01T00:00:00.000000Z',
                started_at = '2000-01-01T00:00:00.000000Z'
            WHERE id IN (?, ?)
            """,
            (stale_running["id"], stale_queued["id"]),
        )

    resumed = store.resume_stale_runs(stale_after_seconds=60)

    assert {item["id"] for item in resumed} == {stale_running["id"], stale_queued["id"]}
    assert {item["state"] for item in resumed} == {"planned"}
    assert {item["started_at"] for item in resumed} == {None}
    assert store.get_run(fresh_queued["id"])["state"] == "queued"
    assert store.resume_stale_runs(stale_after_seconds=60) == []


def test_store_resumes_only_the_requested_experiment_and_never_confirmed_active_runs(store, planned_run):
    first = store.create_experiment(name="First scope", mode="face_swap")
    second = store.create_experiment(name="Second scope", mode="face_swap")
    first_run = store.create_run(first["id"], planned_run)
    active_run = store.create_run(first["id"], plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[8], stages=["baseline"])[0])
    other_run = store.create_run(second["id"], planned_run)
    for run in (first_run, active_run, other_run):
        store.transition_run(run["id"], "queued")
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE runs SET updated_at = '2000-01-01T00:00:00.000000Z' WHERE state = 'queued'")

    resumed = store.resume_stale_runs(
        experiment_id=first["id"], stale_after_seconds=0, active_run_ids={active_run["id"]}
    )

    assert [run["id"] for run in resumed] == [first_run["id"]]
    assert store.get_run(active_run["id"])["state"] == "queued"
    assert store.get_run(other_run["id"])["state"] == "queued"


def test_store_completes_and_fails_an_exact_queued_run_without_intermediate_transitions(store, planned_run):
    experiment = store.create_experiment(name="Exact", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)
    store.transition_run(run["id"], "queued")

    completed = store.complete_recorded_run(
        experiment_id=experiment["id"], run_id=run["id"], output_path="identity_lab/results/result.png", identity_report={"rankable": False}
    )

    assert completed["state"] == "completed"
    failed = store.create_run(experiment["id"], plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[8], stages=["baseline"])[0])
    store.transition_run(failed["id"], "queued")
    assert store.fail_recorded_run(experiment_id=experiment["id"], run_id=failed["id"], error="image write failed")["state"] == "failed"


def test_failed_retry_clears_attempt_fields_before_claim_and_completion(store, planned_run):
    experiment = store.create_experiment(name="Retry reset", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)
    store.claim_recorded_run(experiment_id=experiment["id"], run_id=run["id"], output_path="identity_lab/results/first.png")
    store.fail_recorded_run(experiment_id=experiment["id"], run_id=run["id"], error="write failed")

    queued = store.mark_run_queued(experiment_id=experiment["id"], run_id=run["id"])
    assert queued["identity_report"] is None
    assert queued["output_path"] is None
    assert queued["started_at"] is None
    assert queued["completed_at"] is None
    assert queued["plan"] == planned_run.as_dict()
    claimed = store.claim_recorded_run(experiment_id=experiment["id"], run_id=run["id"], output_path="identity_lab/results/retry.png")
    assert store.complete_recorded_run(experiment_id=experiment["id"], run_id=run["id"], output_path=claimed["output_path"], identity_report={})["state"] == "completed"


def test_store_claims_one_exact_result_path_before_file_writes_and_rejects_competing_claims(store, planned_run):
    experiment = store.create_experiment(name="Claim", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)

    claimed = store.claim_recorded_run(experiment_id=experiment["id"], run_id=run["id"], output_path="identity_lab/results/result.png")

    assert claimed["output_path"] == "identity_lab/results/result.png"
    with pytest.raises(ValueError, match="recordable"):
        store.claim_recorded_run(experiment_id=experiment["id"], run_id=run["id"], output_path="identity_lab/results/result.png")


def test_stale_running_claim_is_released_for_a_retry(store, planned_run):
    experiment = store.create_experiment(name="Interrupted claim", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)
    claimed = store.claim_recorded_run(experiment_id=experiment["id"], run_id=run["id"], output_path="identity_lab/results/result.png")

    assert claimed["state"] == "running"
    assert claimed["started_at"] is not None
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE runs SET updated_at = '2000-01-01T00:00:00.000000Z' WHERE id = ?", (run["id"],))
    resumed = store.resume_stale_runs(experiment_id=experiment["id"], stale_after_seconds=0)

    assert resumed[0]["state"] == "planned"
    assert resumed[0]["started_at"] is None
    assert resumed[0]["output_path"] is None
    assert store.claim_recorded_run(experiment_id=experiment["id"], run_id=run["id"], output_path="identity_lab/results/retry.png")["state"] == "running"


def test_store_completion_data_is_immutable_and_output_paths_are_relative(store, planned_run):
    experiment = store.create_experiment(name="Completion", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)
    store.transition_run(run["id"], "queued")
    store.transition_run(run["id"], "running")

    completed = store.complete_run(
        run["id"],
        output_path="identity-lab/results/run-1.png",
        identity_report={"active_score": {"cosine_similarity": 0.91, "same_identity": True}},
    )

    assert completed["state"] == "completed"
    assert completed["output_path"] == "identity-lab/results/run-1.png"
    assert completed["identity_report"]["active_score"]["cosine_similarity"] == 0.91
    with pytest.raises(ValueError, match="completed"):
        store.complete_run(run["id"], output_path="identity-lab/results/other.png", identity_report={})
    with pytest.raises(ValueError, match="invalid state transition"):
        store.transition_run(run["id"], "running")


def test_store_compare_and_set_prevents_concurrent_transition_and_completion_overwrites(store, planned_run, monkeypatch):
    experiment = store.create_experiment(name="Atomic", mode="face_swap")
    transitioning = store.create_run(experiment["id"], planned_run)
    original_fetch = store._fetch_run
    changed = False

    def fetch_after_external_archive(connection, run_id):
        nonlocal changed
        row = original_fetch(connection, run_id)
        if run_id == transitioning["id"] and not changed:
            changed = True
            with sqlite3.connect(store.path) as other:
                other.execute("UPDATE runs SET state = 'archived', updated_at = '2000-01-01T00:00:00.000000Z' WHERE id = ?", (run_id,))
        return row

    monkeypatch.setattr(store, "_fetch_run", fetch_after_external_archive)
    with pytest.raises(ValueError, match="changed"):
        store.transition_run(transitioning["id"], "queued")
    monkeypatch.setattr(store, "_fetch_run", original_fetch)
    assert store.get_run(transitioning["id"])["state"] == "archived"

    completing = store.create_run(
        experiment["id"], plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[8], stages=["baseline"])[0]
    )
    store.transition_run(completing["id"], "queued")
    store.transition_run(completing["id"], "running")
    changed = False

    def fetch_after_external_failure(connection, run_id):
        nonlocal changed
        row = original_fetch(connection, run_id)
        if run_id == completing["id"] and not changed:
            changed = True
            with sqlite3.connect(store.path) as other:
                other.execute("UPDATE runs SET state = 'failed', updated_at = '2000-01-01T00:00:00.000000Z' WHERE id = ?", (run_id,))
        return row

    monkeypatch.setattr(store, "_fetch_run", fetch_after_external_failure)
    with pytest.raises(ValueError, match="changed"):
        store.complete_run(completing["id"], output_path="result.png", identity_report={})
    monkeypatch.setattr(store, "_fetch_run", original_fetch)
    assert store.get_run(completing["id"])["state"] == "failed"


@pytest.mark.parametrize("path", ["C:/output/run.png", "/output/run.png", "../run.png", ""])
def test_store_rejects_non_relative_output_paths(store, planned_run, path):
    experiment = store.create_experiment(name="Paths", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)
    store.transition_run(run["id"], "queued")
    store.transition_run(run["id"], "running")

    with pytest.raises(ValueError, match="relative"):
        store.complete_run(run["id"], output_path=path, identity_report={})


def test_store_refuses_embeddings_or_image_bytes_in_completion_data(store, planned_run):
    experiment = store.create_experiment(name="Private", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)
    store.transition_run(run["id"], "queued")
    store.transition_run(run["id"], "running")

    with pytest.raises(ValueError, match="embedding"):
        store.complete_run(run["id"], output_path="result.png", identity_report={"face_embedding": [0.1, 0.2]})

    with pytest.raises(ValueError, match="embedding"):
        store.create_experiment(name="No embeddings", mode="face_swap", settings={"reference_embedding": [0.1, 0.2]})


@pytest.mark.parametrize(
    "image_payload",
    [
        {"image_bytes": [0, 127, 255]},
        {"image_base64": "iVBORw0KGgo="},
        {"png_base64": "iVBORw0KGgo="},
        {"thumbnail_b64": "iVBORw0KGgo="},
        {"image_data-uri": "payload"},
        {"preview": "data:image/png;base64,iVBORw0KGgo="},
        {"preview": " \tDATA:IMAGE/png;base64,iVBORw0KGgo="},
    ],
)
def test_store_rejects_image_payload_encodings_but_allows_paths(store, planned_run, image_payload):
    experiment = store.create_experiment(name="Image privacy", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)
    store.transition_run(run["id"], "queued")
    store.transition_run(run["id"], "running")

    with pytest.raises(ValueError, match="image"):
        store.complete_run(run["id"], output_path="result.png", identity_report=image_payload)

    path_run = store.create_run(
        experiment["id"], plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[8], stages=["baseline"])[0]
    )
    store.transition_run(path_run["id"], "queued")
    store.transition_run(path_run["id"], "running")
    assert store.complete_run(
        path_run["id"], output_path="result-2.png", identity_report={"preview_path": "outputs/preview.png"}
    )["state"] == "completed"


def test_store_refuses_embedding_like_data_in_plans_but_keeps_numeric_parameter_arrays(store, planned_run):
    experiment = store.create_experiment(name="Plan privacy", mode="face_swap")
    numeric_parameters = plan_runs(
        mode="face_swap",
        checkpoints=["flux"],
        seeds=[7],
        stages=["focused_refine"],
        refine_settings={"guidance_values": [2.5, 3.0]},
    )[0]
    safe_run = store.create_run(experiment["id"], numeric_parameters)

    assert safe_run["plan"]["refine"] == {"guidance_values": [2.5, 3.0]}
    unsafe_plan = plan_runs(
        mode="face_swap",
        checkpoints=["flux"],
        seeds=[8],
        stages=["focused_refine"],
        refine_settings={"face_embedding": [0.1, 0.2]},
    )[0]
    with pytest.raises(ValueError, match="embedding"):
        store.create_run(experiment["id"], unsafe_plan)


def test_store_allows_human_review_fields_to_change_after_completion(store, planned_run):
    experiment = store.create_experiment(name="Review", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)
    store.transition_run(run["id"], "queued")
    store.transition_run(run["id"], "running")
    store.complete_run(run["id"], output_path="result.png", identity_report={})

    reviewed = store.update_review(run["id"], rating=5, favorite=True, notes="best likeness")
    changed = store.update_review(run["id"], rating=4, favorite=False, notes="still strong")

    assert reviewed["rating"] == 5
    assert reviewed["favorite"] is True
    assert changed["rating"] == 4
    assert changed["favorite"] is False
    assert changed["notes"] == "still strong"
    assert changed["output_path"] == "result.png"


def test_store_reviews_only_completed_runs_and_preserve_separate_fields(store, planned_run, monkeypatch):
    experiment = store.create_experiment(name="Review contract", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)
    with pytest.raises(ValueError, match="completed"):
        store.update_review(run["id"], rating=5)

    store.transition_run(run["id"], "queued")
    store.transition_run(run["id"], "running")
    store.complete_run(run["id"], output_path="result.png", identity_report={})
    assert store.update_review(run["id"], rating=5)["rating"] == 5
    assert store.update_review(run["id"], favorite=True)["favorite"] is True
    assert store.update_review(run["id"], notes="keep this one")["notes"] == "keep this one"

    original_fetch = store._fetch_run
    changed = False

    def fetch_after_separate_review(connection, run_id):
        nonlocal changed
        row = original_fetch(connection, run_id)
        if run_id == run["id"] and not changed:
            changed = True
            with sqlite3.connect(store.path) as other:
                other.execute("UPDATE runs SET favorite = 0, notes = 'concurrent note' WHERE id = ?", (run_id,))
        return row

    monkeypatch.setattr(store, "_fetch_run", fetch_after_separate_review)
    reviewed = store.update_review(run["id"], rating=4)
    monkeypatch.setattr(store, "_fetch_run", original_fetch)

    assert reviewed["rating"] == 4
    assert reviewed["favorite"] is False
    assert reviewed["notes"] == "concurrent note"


def test_store_archives_experiments_non_destructively(store, planned_run):
    experiment = store.create_experiment(name="Archive", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)

    archived = store.archive_experiment(experiment["id"])

    assert archived["state"] == "archived"
    assert store.get_experiment(experiment["id"])["state"] == "archived"
    assert store.get_run(run["id"])["id"] == run["id"]


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf")])
def test_store_rejects_non_finite_stale_timeouts(store, timeout):
    with pytest.raises(ValueError, match="finite"):
        store.resume_stale_runs(stale_after_seconds=timeout)


def test_store_connections_close_at_the_end_of_each_context(store):
    with store._connection() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
