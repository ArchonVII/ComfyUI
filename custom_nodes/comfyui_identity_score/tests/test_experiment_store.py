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
            "UPDATE runs SET updated_at = '2000-01-01T00:00:00.000000Z' WHERE id IN (?, ?)",
            (stale_running["id"], stale_queued["id"]),
        )

    resumed = store.resume_stale_runs(stale_after_seconds=60)

    assert {item["id"] for item in resumed} == {stale_running["id"], stale_queued["id"]}
    assert {item["state"] for item in resumed} == {"planned"}
    assert store.get_run(fresh_queued["id"])["state"] == "queued"
    assert store.resume_stale_runs(stale_after_seconds=60) == []


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


def test_store_refuses_embedding_like_data_in_plans_but_keeps_numeric_parameter_arrays(store, planned_run):
    experiment = store.create_experiment(name="Plan privacy", mode="face_swap")
    numeric_parameters = replace(planned_run, refine={"guidance_values": [2.5, 3.0]})
    safe_run = store.create_run(experiment["id"], numeric_parameters)

    assert safe_run["plan"]["refine"] == {"guidance_values": [2.5, 3.0]}
    unsafe_plan = replace(
        plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[8], stages=["baseline"])[0],
        refine={"face_embedding": [0.1, 0.2]},
    )
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


def test_store_archives_experiments_non_destructively(store, planned_run):
    experiment = store.create_experiment(name="Archive", mode="face_swap")
    run = store.create_run(experiment["id"], planned_run)

    archived = store.archive_experiment(experiment["id"])

    assert archived["state"] == "archived"
    assert store.get_experiment(experiment["id"])["state"] == "archived"
    assert store.get_run(run["id"])["id"] == run["id"]
