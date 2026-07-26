"""Deterministic expansion of small, local identity experiment plans."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from itertools import combinations
from math import comb
from types import MappingProxyType
from typing import Any, Iterable, Mapping


MAX_EXPERIMENT_RUNS = 100
VALID_MODES = frozenset({"face_swap", "identity_i2i"})
VALID_STAGES = frozenset({"baseline", "lora_single", "lora_pair", "lora_triple", "focused_refine"})
DEFAULT_STAGES = ("baseline", "lora_single", "lora_pair")


@dataclass(frozen=True)
class LoRASetting:
    """One active LoRA and its normalized strength."""

    name: str
    strength: float

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "strength": self.strength}


@dataclass(frozen=True)
class PlannedRun:
    """An immutable generation configuration with a reproducible identity hash."""

    mode: str
    stage: str
    checkpoint: str
    seed: int
    loras: tuple[LoRASetting, ...]
    refine: Mapping[str, Any]
    combination_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkpoint": self.checkpoint,
            "combination_hash": self.combination_hash,
            "loras": [lora.as_dict() for lora in self.loras],
            "mode": self.mode,
            "refine": _thaw_json(self.refine),
            "seed": self.seed,
            "stage": self.stage,
        }


def plan_runs(
    *,
    mode: str,
    checkpoints: Iterable[str],
    seeds: Iterable[int],
    loras: Iterable[tuple[str, float]] = (),
    stages: Iterable[str] = DEFAULT_STAGES,
    refine_settings: Mapping[str, Any] | None = None,
) -> tuple[PlannedRun, ...]:
    """Return a stable, bounded staged expansion for one local experiment.

    Checkpoints and seeds expand in caller order. LoRA triples are deliberately
    opt-in by including ``"lora_triple"`` in ``stages``.
    """

    normalized_mode = _normalize_mode(mode)
    normalized_checkpoints = _unique_checkpoints(checkpoints)
    normalized_seeds = _unique_seeds(seeds)
    normalized_loras = _unique_loras(loras)
    normalized_stages = _unique_stages(stages)
    normalized_refine = _freeze_json(dict(refine_settings or {}))
    _ensure_run_limit(
        checkpoints=normalized_checkpoints,
        seeds=normalized_seeds,
        loras=normalized_loras,
        stages=normalized_stages,
    )

    runs: list[PlannedRun] = []
    seen_hashes: set[str] = set()
    for stage in normalized_stages:
        for active_loras in _stage_lora_sets(stage, normalized_loras):
            for checkpoint in normalized_checkpoints:
                for seed in normalized_seeds:
                    payload = {
                        "checkpoint": checkpoint,
                        "loras": [lora.as_dict() for lora in active_loras],
                        "mode": normalized_mode,
                        "refine": _thaw_json(normalized_refine) if stage == "focused_refine" else {},
                        "seed": seed,
                        "stage": stage,
                    }
                    combination_hash = _canonical_hash(payload)
                    if combination_hash in seen_hashes:
                        continue
                    seen_hashes.add(combination_hash)
                    runs.append(
                        PlannedRun(
                            mode=normalized_mode,
                            stage=stage,
                            checkpoint=checkpoint,
                            seed=seed,
                            loras=active_loras,
                            refine=normalized_refine if stage == "focused_refine" else MappingProxyType({}),
                            combination_hash=combination_hash,
                        )
                    )
                    if len(runs) > MAX_EXPERIMENT_RUNS:
                        raise ValueError(f"experiment plan exceeds the {MAX_EXPERIMENT_RUNS}-run limit")
    return tuple(runs)


def _normalize_mode(mode: str) -> str:
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    return mode


def _unique_checkpoints(checkpoints: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, str) or not checkpoint.strip():
            raise ValueError("checkpoint must be a non-empty string")
        normalized = checkpoint.strip()
        if normalized not in result:
            result.append(normalized)
    if not result:
        raise ValueError("at least one checkpoint is required")
    return tuple(result)


def _unique_seeds(seeds: Iterable[int]) -> tuple[int, ...]:
    result: list[int] = []
    for seed in seeds:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        if seed not in result:
            result.append(seed)
    if not result:
        raise ValueError("at least one seed is required")
    return tuple(result)


def _unique_loras(loras: Iterable[tuple[str, float]]) -> tuple[LoRASetting, ...]:
    result: list[LoRASetting] = []
    for item in loras:
        try:
            name, strength = item
        except (TypeError, ValueError) as exc:
            raise ValueError("each LoRA must be a (name, strength) pair") from exc
        if not isinstance(name, str) or not name.strip():
            raise ValueError("LoRA name must be a non-empty string")
        if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not 0 < strength <= 1:
            raise ValueError("LoRA strength must be greater than 0 and at most 1")
        setting = LoRASetting(name=name.strip(), strength=float(strength))
        if setting not in result:
            result.append(setting)
    return tuple(sorted(result, key=lambda setting: (setting.name, setting.strength)))


def _unique_stages(stages: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for stage in stages:
        if stage not in VALID_STAGES:
            raise ValueError(f"invalid stage: {stage!r}")
        if stage not in result:
            result.append(stage)
    if not result:
        raise ValueError("at least one stage is required")
    return tuple(result)


def _stage_lora_sets(stage: str, loras: tuple[LoRASetting, ...]) -> tuple[tuple[LoRASetting, ...], ...]:
    if stage == "baseline":
        return ((),)
    if stage == "lora_single":
        return tuple((lora,) for lora in loras)
    if stage == "lora_pair":
        return tuple(combinations(loras, 2))
    if stage == "lora_triple":
        return tuple(combinations(loras, 3))
    if len(loras) > 3:
        raise ValueError("focused_refine may not activate more than three LoRAs")
    return (loras,)


def _ensure_run_limit(
    *,
    checkpoints: tuple[str, ...],
    seeds: tuple[int, ...],
    loras: tuple[LoRASetting, ...],
    stages: tuple[str, ...],
) -> None:
    stage_counts = {
        "baseline": 1,
        "lora_single": len(loras),
        "lora_pair": comb(len(loras), 2),
        "lora_triple": comb(len(loras), 3),
        "focused_refine": 1,
    }
    planned_count = len(checkpoints) * len(seeds) * sum(stage_counts[stage] for stage in stages)
    if planned_count > MAX_EXPERIMENT_RUNS:
        raise ValueError(f"experiment plan exceeds the {MAX_EXPERIMENT_RUNS}-run limit")


def canonical_combination_hash(plan: Mapping[str, Any]) -> str:
    """Return the hash for a persisted planned-run mapping, excluding its hash field."""

    required_fields = ("checkpoint", "loras", "mode", "refine", "seed", "stage")
    try:
        payload = {field: plan[field] for field in required_fields}
    except (KeyError, TypeError) as exc:
        raise ValueError("plan is missing canonical combination fields") from exc
    return _canonical_hash(payload)


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in sorted(value.items())})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("refine settings must contain JSON-compatible values")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
