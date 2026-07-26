"""Local-only service facade for identity experiment planning and recording."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import time
from typing import Any, Mapping
from uuid import uuid4

import folder_paths

from .experiment_planner import DEFAULT_STAGES, VALID_MODES, plan_runs
from .experiment_store import ExperimentStore


IDENTITY_LAB_BASE_IMAGE = "IDENTITY_LAB_BASE_IMAGE"
IDENTITY_LAB_REFERENCE_IMAGE = "IDENTITY_LAB_REFERENCE_IMAGE"
IDENTITY_LAB_MODEL = "IDENTITY_LAB_MODEL"
IDENTITY_LAB_LORA_1 = "IDENTITY_LAB_LORA_1"
IDENTITY_LAB_LORA_2 = "IDENTITY_LAB_LORA_2"
IDENTITY_LAB_LORA_3 = "IDENTITY_LAB_LORA_3"
IDENTITY_LAB_SAMPLER = "IDENTITY_LAB_SAMPLER"
IDENTITY_LAB_SCORE = "IDENTITY_LAB_SCORE"

_ROLE_TYPES = {
    IDENTITY_LAB_BASE_IMAGE: frozenset({"LoadImage"}),
    IDENTITY_LAB_REFERENCE_IMAGE: frozenset({"LoadImage"}),
    IDENTITY_LAB_MODEL: frozenset({"UNETLoader", "CheckpointLoaderSimple"}),
    IDENTITY_LAB_LORA_1: frozenset({"LoraLoader"}),
    IDENTITY_LAB_LORA_2: frozenset({"LoraLoader"}),
    IDENTITY_LAB_LORA_3: frozenset({"LoraLoader"}),
    IDENTITY_LAB_SAMPLER: frozenset({"KSampler", "KSamplerAdvanced"}),
    IDENTITY_LAB_SCORE: frozenset({"DualIdentityScore"}),
}


def _safe_relative_name(value: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    name = value.replace("\\", "/")
    windows = PureWindowsPath(name)
    if name.startswith("/") or Path(name).is_absolute() or windows.is_absolute() or windows.drive or ".." in Path(name).parts:
        return None
    return name


def _catalog_entries(folder_paths_module: Any, groups: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for group in groups:
        for raw_name in folder_paths_module.get_filename_list(group):
            name = _safe_relative_name(raw_name)
            lowered = (name or "").casefold()
            if name and "flux" in lowered and "9b" in lowered and name not in values:
                values.append(name)
    return values


def validate_api_workflow(workflow: Mapping[str, Any]) -> dict[str, str]:
    """Map stable title roles to API prompt node ids, rejecting ambiguous graphs."""
    if not isinstance(workflow, Mapping):
        raise ValueError("workflow must be an API prompt object")
    found: dict[str, str] = {}
    for node_id, node in workflow.items():
        if not isinstance(node, Mapping):
            raise ValueError("workflow nodes must be objects")
        title = node.get("_meta", {}).get("title") if isinstance(node.get("_meta"), Mapping) else None
        if title not in _ROLE_TYPES:
            continue
        if title in found:
            raise ValueError(f"duplicate workflow role: {title}")
        node_type = node.get("class_type")
        if node_type not in _ROLE_TYPES[title]:
            raise ValueError(f"workflow role {title} expected {_ROLE_TYPES[title]}, got {node_type!r}")
        found[title] = str(node_id)
    missing = [role for role in _ROLE_TYPES if role not in found]
    if missing:
        raise ValueError(f"missing workflow roles: {', '.join(missing)}")
    return found


class ExperimentService:
    """Narrow local API over the deterministic planner and SQLite store."""

    def __init__(self, *, folder_paths_module: Any = folder_paths, store: ExperimentStore | None = None, db_path: str | Path | None = None, output_directory: str | Path | None = None):
        self.folder_paths = folder_paths_module
        self._store = store
        self._db_path = Path(db_path) if db_path is not None else None
        self.output_directory = Path(output_directory) if output_directory is not None else Path(folder_paths_module.get_output_directory())

    @property
    def store(self) -> ExperimentStore:
        if self._store is None:
            path = self._db_path or (Path(self.folder_paths.get_user_directory()) / "default" / "identity_lab" / "identity_lab.sqlite3")
            self._store = ExperimentStore(path)
        return self._store

    def catalogs(self) -> dict[str, list[str]]:
        return {
            "diffusion_models": _catalog_entries(self.folder_paths, ("diffusion_models", "checkpoints")),
            "loras": _catalog_entries(self.folder_paths, ("loras",)),
        }

    def _validate_catalog_selection(self, checkpoints: list[str], loras: list[tuple[str, float]]) -> None:
        catalog = self.catalogs()
        if any(checkpoint not in catalog["diffusion_models"] for checkpoint in checkpoints):
            raise ValueError("checkpoint is not in the local Flux 9B catalog")
        if any(name not in catalog["loras"] for name, _strength in loras):
            raise ValueError("LoRA is not in the local Flux 9B catalog")

    def create_experiment(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("experiment payload must be an object")
        name, mode = payload.get("name"), payload.get("mode")
        checkpoints = list(payload.get("checkpoints", ()))
        seeds = list(payload.get("seeds", ()))
        loras = [tuple(item) for item in payload.get("loras", ())]
        stages = list(payload.get("stages", DEFAULT_STAGES))
        if "workflow" in payload:
            validate_api_workflow(payload["workflow"])
        self._validate_catalog_selection(checkpoints, loras)
        runs = plan_runs(mode=mode, checkpoints=checkpoints, seeds=seeds, loras=loras, stages=stages, refine_settings=payload.get("refine_settings"))
        self._require_capacity(self.estimate(None, run_count=len(runs)))
        settings = dict(payload.get("settings", {}))
        experiment = self.store.create_experiment(name=name, mode=mode, settings=settings)
        stored_runs = [self.store.create_run(experiment["id"], run) for run in runs]
        return {"experiment": experiment, "runs": stored_runs}

    def list_experiments(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self.store._connection() as connection:
            query = "SELECT * FROM experiments" + ("" if include_archived else " WHERE state = 'active'") + " ORDER BY created_at DESC, id DESC"
            return [self.store._fetch_experiment(connection, row["id"]) for row in connection.execute(query)]

    def detail(self, experiment_id: str) -> dict[str, Any]:
        return {"experiment": self.store.get_experiment(experiment_id), "runs": self.store.list_runs(experiment_id)}

    def plan_stage(self, experiment_id: str, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        experiment = self.store.get_experiment(experiment_id)
        if payload.get("mode", experiment["mode"]) != experiment["mode"]:
            raise ValueError("planned stage mode must match experiment")
        checkpoints = list(payload.get("checkpoints", ()))
        loras = [tuple(item) for item in payload.get("loras", ())]
        self._validate_catalog_selection(checkpoints, loras)
        planned = plan_runs(mode=experiment["mode"], checkpoints=checkpoints, seeds=list(payload.get("seeds", ())), loras=loras, stages=list(payload.get("stages", ())), refine_settings=payload.get("refine_settings"))
        self._require_capacity(self.estimate(experiment_id, run_count=len(planned)))
        return [self.store.create_run(experiment_id, run) for run in planned]

    promote = plan_stage

    def estimate(self, experiment_id: str | None, *, run_count: int, fallback_seconds: float = 60.0, fallback_bytes: int = 8_000_000) -> dict[str, Any]:
        if isinstance(run_count, bool) or not isinstance(run_count, int) or run_count < 0:
            raise ValueError("run_count must be a non-negative integer")
        if isinstance(fallback_seconds, bool) or not isinstance(fallback_seconds, (int, float)) or fallback_seconds < 0:
            raise ValueError("fallback_seconds must be a non-negative number")
        if isinstance(fallback_bytes, bool) or not isinstance(fallback_bytes, int) or fallback_bytes < 0:
            raise ValueError("fallback_bytes must be a non-negative integer")
        completed: list[float] = []
        output_sizes: list[int] = []
        if experiment_id is None:
            runs = []
        else:
            runs = self.store.list_runs(experiment_id)
        for run in runs:
            if run["state"] != "completed":
                continue
            runtime = (run.get("identity_report") or {}).get("runtime_seconds")
            if isinstance(runtime, (int, float)) and not isinstance(runtime, bool) and runtime >= 0:
                completed.append(float(runtime))
            output_path = run.get("output_path")
            if isinstance(output_path, str):
                candidate = self.output_directory / output_path
                try:
                    if candidate.is_file():
                        output_sizes.append(candidate.stat().st_size)
                except OSError:
                    pass
        if completed:
            completed.sort()
            seconds = completed[len(completed) // 2] if len(completed) % 2 else (completed[len(completed) // 2 - 1] + completed[len(completed) // 2]) / 2
            source = "completed_run_median"
        else:
            seconds, source = float(fallback_seconds), "fallback"
        if output_sizes:
            output_sizes.sort()
            bytes_per_run = output_sizes[len(output_sizes) // 2] if len(output_sizes) % 2 else (output_sizes[len(output_sizes) // 2 - 1] + output_sizes[len(output_sizes) // 2]) // 2
            disk_source = "completed_output_median"
        else:
            bytes_per_run, disk_source = fallback_bytes, "fallback"
        self.output_directory.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(self.output_directory)
        free_bytes = usage.free if hasattr(usage, "free") else usage[2]
        estimated_bytes = bytes_per_run * run_count
        can_launch = estimated_bytes <= free_bytes
        return {"run_count": run_count, "seconds_per_run": seconds, "estimated_seconds": seconds * run_count, "time_source": source, "bytes_per_run": bytes_per_run, "estimated_bytes": estimated_bytes, "disk_source": disk_source, "free_bytes": free_bytes, "can_launch": can_launch, "status": "ok" if can_launch else "insufficient_space"}

    @staticmethod
    def _require_capacity(estimate: Mapping[str, Any]) -> None:
        if not estimate["can_launch"]:
            raise ValueError("insufficient output disk space for planned runs")

    def list_results(self, experiment_id: str) -> list[dict[str, Any]]:
        return [run for run in self.store.list_runs(experiment_id) if run["state"] == "completed"]

    def update_review(self, run_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        fields = {key: payload[key] for key in ("rating", "favorite", "notes") if key in payload}
        return self.store.update_review(run_id, **fields)

    def resume_stale(self, experiment_id: str, *, stale_after_seconds: float, active_run_ids: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
        return self.store.resume_stale_runs(experiment_id=experiment_id, stale_after_seconds=stale_after_seconds, active_run_ids=active_run_ids)

    def archive(self, experiment_id: str) -> dict[str, Any]:
        return self.store.archive_experiment(experiment_id)

    def output_file(self, output_path: str) -> Path:
        relative = _safe_relative_name(output_path)
        if relative is None:
            raise ValueError("output path must be relative")
        root = self.output_directory.resolve()
        target = (root / relative).resolve()
        if root not in target.parents or not target.is_file():
            raise ValueError("output file is not available")
        return target

    def record_run(self, *, experiment_id: str, run_id: str, generated_image: Any, report: dict[str, Any], prompt: Any = None, extra_pnginfo: Any = None, runtime_seconds: float | None = None) -> dict[str, Any]:
        relative = f"identity_lab/results/{run_id}.png"
        output = self.output_directory / relative
        self.store.claim_recorded_run(experiment_id=experiment_id, run_id=run_id, output_path=relative)
        temporary = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
        output.parent.mkdir(parents=True, exist_ok=True)
        created_output = False
        try:
            self._save_png(generated_image, temporary, prompt=prompt, extra_pnginfo=extra_pnginfo)
            descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            created_output = True
            temporary.replace(output)
        except BaseException as exc:
            temporary.unlink(missing_ok=True)
            if created_output:
                output.unlink(missing_ok=True)
            try:
                self.store.fail_recorded_run(experiment_id=experiment_id, run_id=run_id, error=f"image save failed: {type(exc).__name__}: {exc}")
            except (KeyError, ValueError):
                pass
            raise
        report["experiment_id"] = experiment_id
        report["run_id"] = run_id
        report["result_path"] = relative
        report["runtime_seconds"] = float(runtime_seconds if runtime_seconds is not None else report.get("runtime_seconds", 0.0))
        try:
            return self.store.complete_recorded_run(experiment_id=experiment_id, run_id=run_id, output_path=relative, identity_report=report)
        except BaseException as exc:
            if created_output:
                output.unlink(missing_ok=True)
            try:
                self.store.fail_recorded_run(experiment_id=experiment_id, run_id=run_id, error=f"record completion failed: {type(exc).__name__}: {exc}")
            except (KeyError, ValueError):
                pass
            raise

    @staticmethod
    def _save_png(image: Any, path: Path, *, prompt: Any, extra_pnginfo: Any) -> None:
        import numpy as np
        from PIL import Image, PngImagePlugin

        value = image[0] if getattr(image, "ndim", 0) == 4 else image
        if hasattr(value, "detach"):
            value = value.detach().cpu().numpy()
        array = np.asarray(value)
        if array.dtype.kind == "f":
            array = np.clip(array * 255.0, 0, 255).astype("uint8")
        pnginfo = PngImagePlugin.PngInfo()
        if prompt is not None:
            pnginfo.add_text("prompt", json.dumps(prompt, ensure_ascii=False))
        if extra_pnginfo is not None:
            pnginfo.add_text("extra_pnginfo", json.dumps(extra_pnginfo, ensure_ascii=False))
        Image.fromarray(array).save(path, format="PNG", pnginfo=pnginfo)
