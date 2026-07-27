from pathlib import Path
import shutil
import sys

import numpy as np
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_identity_score.experiment_service import (
    IDENTITY_LAB_BASE_IMAGE,
    IDENTITY_LAB_LORA_1,
    IDENTITY_LAB_LORA_2,
    IDENTITY_LAB_LORA_3,
    IDENTITY_LAB_MODEL,
    IDENTITY_LAB_PIXEL_BUDGET,
    IDENTITY_LAB_REFERENCE_IMAGE,
    IDENTITY_LAB_SAMPLER,
    IDENTITY_LAB_SCORE,
    ExperimentService,
    validate_api_workflow,
)


class FakeFolderPaths:
    names = {
        "diffusion_models": ["Flux/9B/flux-9b.safetensors", "sdxl.safetensors", "../escape.safetensors"],
        "checkpoints": ["flux-dev-9b.safetensors"],
        "loras": ["Flux/9B/face-9b.safetensors", "Flux/other.safetensors", "../bad.safetensors"],
    }

    def __init__(self, root):
        self.root = root

    def get_filename_list(self, category):
        return list(self.names.get(category, []))

    def get_user_directory(self):
        return str(self.root / "user")

    def get_output_directory(self):
        return str(self.root / "output")


def template():
    return {
        "1": {"class_type": "LoadImage", "inputs": {}, "_meta": {"title": IDENTITY_LAB_BASE_IMAGE}},
        "2": {"class_type": "LoadImage", "inputs": {}, "_meta": {"title": IDENTITY_LAB_REFERENCE_IMAGE}},
        "3": {"class_type": "UNETLoader", "inputs": {}, "_meta": {"title": IDENTITY_LAB_MODEL}},
        "4": {"class_type": "LoraLoader", "inputs": {}, "_meta": {"title": IDENTITY_LAB_LORA_1}},
        "5": {"class_type": "LoraLoader", "inputs": {}, "_meta": {"title": IDENTITY_LAB_LORA_2}},
        "6": {"class_type": "LoraLoader", "inputs": {}, "_meta": {"title": IDENTITY_LAB_LORA_3}},
        "7": {"class_type": "KSampler", "inputs": {}, "_meta": {"title": IDENTITY_LAB_SAMPLER}},
        "8": {"class_type": "DualIdentityScore", "inputs": {}, "_meta": {"title": IDENTITY_LAB_SCORE}},
        "9": {"class_type": "ImageScaleToTotalPixels", "inputs": {}, "_meta": {"title": IDENTITY_LAB_PIXEL_BUDGET}},
    }


def test_catalogs_are_deterministic_flux_9b_only_and_path_safe(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))

    catalog = service.catalogs()
    assert catalog["diffusion_models"] == ["Flux/9B/flux-9b.safetensors", "flux-dev-9b.safetensors"]
    assert catalog["loras"] == ["Flux/9B/face-9b.safetensors"]
    assert isinstance(catalog["samplers"], list)
    assert isinstance(catalog["schedulers"], list)


def test_workflow_template_requires_one_typed_node_for_every_stable_role():
    roles = validate_api_workflow(template())
    assert roles[IDENTITY_LAB_SCORE] == "8"

    missing = template()
    del missing["8"]
    with pytest.raises(ValueError, match="missing"):
        validate_api_workflow(missing)
    duplicate = template()
    duplicate["10"] = {"class_type": "DualIdentityScore", "inputs": {}, "_meta": {"title": IDENTITY_LAB_SCORE}}
    with pytest.raises(ValueError, match="duplicate"):
        validate_api_workflow(duplicate)
    wrong = template()
    wrong["3"]["class_type"] = "KSampler"
    with pytest.raises(ValueError, match="expected"):
        validate_api_workflow(wrong)
    advanced_sampler = template()
    advanced_sampler["7"]["class_type"] = "KSamplerAdvanced"
    with pytest.raises(ValueError, match="IDENTITY_LAB_SAMPLER"):
        validate_api_workflow(advanced_sampler)

    missing_pixel_budget = template()
    del missing_pixel_budget["9"]
    with pytest.raises(ValueError, match="IDENTITY_LAB_PIXEL_BUDGET"):
        validate_api_workflow(missing_pixel_budget)


def test_created_experiment_keeps_validated_workflow_in_durable_settings_not_run_refine(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    workflow = template()
    created = service.create_experiment({"name": "workflow", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"], "workflow": workflow})

    restarted = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path), db_path=service.store.path)
    detail = restarted.detail(created["experiment"]["id"])
    assert detail["experiment"]["settings"]["workflow_template"] == workflow
    assert detail["runs"][0]["plan"]["refine"] == {}


def test_estimates_use_completed_medians_or_labeled_fallback_and_current_free_output_space(tmp_path, monkeypatch):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    experiment = service.create_experiment({
        "name": "median", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    run = experiment["runs"][0]
    service.store.transition_run(run["id"], "queued")
    service.store.transition_run(run["id"], "running")
    service.store.complete_run(run["id"], output_path="identity_lab/results/a.png", identity_report={"runtime_seconds": 12.0})
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: (1000, 250, 750))

    known = service.estimate(experiment["experiment"]["id"], run_count=2)
    assert known["seconds_per_run"] == 12.0
    assert known["time_source"] == "completed_run_median"
    assert known["free_bytes"] == 750
    fallback = service.estimate(None, run_count=2, fallback_seconds=9)
    assert fallback["seconds_per_run"] == 9
    assert fallback["time_source"] == "fallback"


def test_estimate_requires_a_real_experiment_when_an_id_is_supplied(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))

    with pytest.raises(KeyError, match="not found"):
        service.estimate("missing", run_count=1)


def test_service_lifecycle_reviews_resume_archive_results_and_safe_output_file(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "local", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    experiment_id = created["experiment"]["id"]
    run = created["runs"][0]
    service.store.transition_run(run["id"], "queued")
    assert service.resume_stale(experiment_id, stale_after_seconds=0)[0]["state"] == "planned"
    service.store.transition_run(run["id"], "queued")
    service.store.transition_run(run["id"], "running")
    output = Path(service.output_directory) / "identity_lab/results/a.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"png")
    service.store.complete_run(run["id"], output_path="identity_lab/results/a.png", identity_report={"rankable": False})

    assert service.list_results(experiment_id)[0]["id"] == run["id"]
    assert service.update_review(run["id"], {"rating": 5, "favorite": True})["rating"] == 5
    assert service.output_file("identity_lab/results/a.png") == output
    with pytest.raises(ValueError, match="relative"):
        service.output_file("../secret.png")
    assert service.archive(experiment_id)["state"] == "archived"


def test_resume_reconciliation_fails_terminal_history_and_only_replans_absent_rows(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({"name": "reconcile", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7, 8], "stages": ["baseline"]})
    experiment_id = created["experiment"]["id"]
    terminal, absent = created["runs"]
    service.store.transition_run(terminal["id"], "queued")
    service.store.transition_run(absent["id"], "queued")

    resumed = service.resume_stale(experiment_id, stale_after_seconds=0, terminal_history={terminal["id"]: "history error"})

    assert {run["id"] for run in resumed} == {absent["id"]}
    failed = service.store.get_run(terminal["id"])
    assert failed["state"] == "failed" and failed["identity_report"]["error"] == "history error"


def test_record_run_writes_local_png_metadata_and_completes_a_non_rankable_run(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "record", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
    report = {"rankable": False, "face_detection": {"base": True, "reference": False, "generated": True}}

    completed = service.record_run(
        experiment_id=experiment_id, run_id=run_id, generated_image=np.zeros((4, 4, 3), dtype=np.uint8),
        report=report, prompt={"positive": "portrait"}, extra_pnginfo={"workflow": {"nodes": []}}, runtime_seconds=3.5,
    )

    output = service.output_file(completed["output_path"])
    assert output.is_file()
    assert completed["state"] == "completed"
    assert completed["identity_report"]["rankable"] is False
    assert completed["identity_report"]["scorer_seconds"] == 3.5
    assert completed["identity_report"]["runtime_source"] == "completion_fallback"


def test_estimate_uses_recent_completed_output_median_and_blocks_insufficient_storage_before_create(tmp_path, monkeypatch):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "sizes", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    run = created["runs"][0]
    output = Path(service.output_directory) / "identity_lab/results/sized.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"x" * 321)
    service.store.transition_run(run["id"], "queued")
    service.store.transition_run(run["id"], "running")
    service.store.complete_run(run["id"], output_path="identity_lab/results/sized.png", identity_report={"runtime_seconds": 4})
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: (1000, 950, 50))

    estimate = service.estimate(created["experiment"]["id"], run_count=1)
    assert estimate["bytes_per_run"] == 321
    assert estimate["disk_source"] == "completed_output_median"
    assert estimate["can_launch"] is False
    with pytest.raises(ValueError, match="insufficient"):
        service.create_experiment({
            "name": "blocked", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [8], "stages": ["baseline"],
        })
    assert all(item["name"] != "blocked" for item in service.list_experiments(include_archived=True))


def test_record_run_cleans_files_and_marks_exact_run_failed_when_saving_or_completion_fails(tmp_path, monkeypatch):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "failures", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7, 8], "stages": ["baseline"],
    })
    experiment_id = created["experiment"]["id"]
    save_run, db_run = created["runs"]
    monkeypatch.setattr(service, "_save_png", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        service.record_run(experiment_id=experiment_id, run_id=save_run["id"], generated_image=np.zeros((2, 2, 3)), report={})
    assert service.store.get_run(save_run["id"])["state"] == "failed"

    monkeypatch.undo()
    monkeypatch.setattr(service.store, "complete_recorded_run", lambda **_kwargs: (_ for _ in ()).throw(ValueError("database failure")))
    with pytest.raises(ValueError, match="database failure"):
        service.record_run(experiment_id=experiment_id, run_id=db_run["id"], generated_image=np.zeros((2, 2, 3)), report={})
    assert service.store.get_run(db_run["id"])["state"] == "failed"
    assert not (Path(service.output_directory) / f"identity_lab/results/{db_run['id']}.png").exists()


def test_record_run_retry_never_overwrites_or_deletes_a_completed_result(tmp_path, monkeypatch):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "retry", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
    service.record_run(experiment_id=experiment_id, run_id=run_id, generated_image=np.zeros((2, 2, 3)), report={})
    output = Path(service.output_directory) / f"identity_lab/results/{run_id}.png"
    original = output.read_bytes()
    monkeypatch.setattr(service, "_save_png", lambda *_args, **_kwargs: pytest.fail("completed run must be rejected before save"))

    with pytest.raises(ValueError, match="recordable"):
        service.record_run(experiment_id=experiment_id, run_id=run_id, generated_image=np.ones((2, 2, 3)), report={})

    assert output.read_bytes() == original


def test_record_run_conflict_never_deletes_a_preexisting_result_file(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "conflict", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
    output = Path(service.output_directory) / f"identity_lab/results/{run_id}.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"someone-else-result")

    with pytest.raises(FileExistsError):
        service.record_run(experiment_id=experiment_id, run_id=run_id, generated_image=np.zeros((2, 2, 3)), report={})

    assert output.read_bytes() == b"someone-else-result"
    assert service.store.get_run(run_id)["state"] == "failed"


def test_interrupted_claim_resumes_and_successfully_retries_recording(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "interrupted", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
    service.store.claim_recorded_run(experiment_id=experiment_id, run_id=run_id, output_path=f"identity_lab/results/{run_id}.png")
    with service.store._connection() as connection:
        connection.execute("UPDATE runs SET updated_at = '2000-01-01T00:00:00.000000Z' WHERE id = ?", (run_id,))

    service.resume_stale(experiment_id, stale_after_seconds=0)
    completed = service.record_run(experiment_id=experiment_id, run_id=run_id, generated_image=np.zeros((2, 2, 3)), report={})

    assert completed["state"] == "completed"
    assert (Path(service.output_directory) / completed["output_path"]).is_file()


def test_record_run_marks_claim_failed_when_result_directory_setup_raises(tmp_path, monkeypatch):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "mkdir failure", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
    results_directory = Path(service.output_directory) / "identity_lab/results"
    original_mkdir = Path.mkdir

    def fail_results_mkdir(path, *args, **kwargs):
        if path == results_directory:
            raise OSError("cannot create results directory")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_results_mkdir)
    with pytest.raises(OSError, match="cannot create"):
        service.record_run(experiment_id=experiment_id, run_id=run_id, generated_image=np.zeros((2, 2, 3)), report={})

    assert service.store.get_run(run_id)["state"] == "failed"


def test_stale_claimed_file_is_removed_before_resume_and_retry_completes(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "after install", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
    relative = f"identity_lab/results/{run_id}.png"
    service.store.claim_recorded_run(experiment_id=experiment_id, run_id=run_id, output_path=relative)
    stale_file = Path(service.output_directory) / relative
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_bytes(b"interrupted-final")
    with service.store._connection() as connection:
        connection.execute("UPDATE runs SET updated_at = '2000-01-01T00:00:00.000000Z' WHERE id = ?", (run_id,))

    resumed = service.resume_stale(experiment_id, stale_after_seconds=0)
    completed = service.record_run(experiment_id=experiment_id, run_id=run_id, generated_image=np.zeros((2, 2, 3)), report={})

    assert resumed[0]["output_path"] is None
    assert completed["state"] == "completed"
    assert stale_file.is_file()
    assert stale_file.read_bytes() != b"interrupted-final"


def test_stale_cleanup_rejects_out_of_root_claims_and_fails_closed(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "unsafe stale", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
    service.store.claim_recorded_run(experiment_id=experiment_id, run_id=run_id, output_path="other/result.png")
    outside = Path(service.output_directory) / "other/result.png"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"keep")
    with service.store._connection() as connection:
        connection.execute("UPDATE runs SET updated_at = '2000-01-01T00:00:00.000000Z' WHERE id = ?", (run_id,))

    with pytest.raises(ValueError, match="stale claimed output"):
        service.resume_stale(experiment_id, stale_after_seconds=0)

    assert outside.read_bytes() == b"keep"
    assert service.store.get_run(run_id)["state"] == "failed"


def test_archived_experiment_delete_preview_requires_exact_confirmation_and_only_removes_its_png(tmp_path):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({
        "name": "discard", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [7], "stages": ["baseline"],
    })
    experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
    completed = service.record_run(experiment_id=experiment_id, run_id=run_id, generated_image=np.zeros((2, 2, 3)), report={})
    output = Path(service.output_directory) / completed["output_path"]
    unrelated = Path(service.output_directory) / "identity_lab/results/keep.png"
    unrelated.write_bytes(b"keep")
    service.archive(experiment_id)

    preview = service.delete_preview(experiment_id)
    assert preview["runs"] == [run_id]
    assert preview["files"] == [completed["output_path"]]
    assert preview["token"]
    with pytest.raises(ValueError, match="confirmation"):
        service.delete_archived(experiment_id, token=preview["token"], confirmation="DELETE anything else")
    assert output.is_file()

    with service.store._connection() as connection:
        connection.execute("UPDATE runs SET notes = 'changed' WHERE id = ?", (run_id,))
    with pytest.raises(ValueError, match="snapshot"):
        service.delete_archived(experiment_id, token=preview["token"], confirmation=preview["confirmation"])

    preview = service.delete_preview(experiment_id)
    deleted = service.delete_archived(experiment_id, token=preview["token"], confirmation=preview["confirmation"])

    assert deleted["runs"] == [run_id]
    assert not output.exists()
    assert unrelated.read_bytes() == b"keep"
    with pytest.raises(KeyError, match="not found"):
        service.detail(experiment_id)


def test_delete_quarantine_restores_outputs_when_database_delete_fails(tmp_path, monkeypatch):
    service = ExperimentService(folder_paths_module=FakeFolderPaths(tmp_path))
    created = service.create_experiment({"name": "restore", "mode": "face_swap", "checkpoints": ["flux-dev-9b.safetensors"], "seeds": [9], "stages": ["baseline"]})
    experiment_id, run_id = created["experiment"]["id"], created["runs"][0]["id"]
    completed = service.record_run(experiment_id=experiment_id, run_id=run_id, generated_image=np.zeros((2, 2, 3)), report={})
    output = Path(service.output_directory) / completed["output_path"]
    service.archive(experiment_id)
    preview = service.delete_preview(experiment_id)
    monkeypatch.setattr(service.store, "delete_archived_experiment", lambda _id: (_ for _ in ()).throw(RuntimeError("database unavailable")))

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.delete_archived(experiment_id, token=preview["token"], confirmation=preview["confirmation"])

    assert output.is_file()
    assert service.detail(experiment_id)["experiment"]["state"] == "archived"
