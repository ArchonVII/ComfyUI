from dataclasses import FrozenInstanceError
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_identity_score import experiment_planner
from comfyui_identity_score.experiment_planner import MAX_EXPERIMENT_RUNS, plan_runs


def test_plan_runs_uses_canonical_hashes_and_immutable_normalized_records():
    runs = plan_runs(
        mode="face_swap",
        checkpoints=["flux-a.safetensors"],
        seeds=[7],
        stages=["baseline"],
    )

    assert len(runs) == 1
    assert runs[0].combination_hash == "88f1736a3c468c0709bc01ad0b49e772721730a2adc5f2b981dad7d95ccbbe86"
    assert runs[0].as_dict() == {
        "checkpoint": "flux-a.safetensors",
        "combination_hash": "88f1736a3c468c0709bc01ad0b49e772721730a2adc5f2b981dad7d95ccbbe86",
        "loras": [],
        "mode": "face_swap",
        "refine": {},
        "seed": 7,
        "stage": "baseline",
    }
    with pytest.raises(FrozenInstanceError):
        runs[0].seed = 8


def test_plan_runs_expands_checkpoints_and_seeds_in_stable_order():
    runs = plan_runs(
        mode="identity_i2i",
        checkpoints=["flux-b", "flux-a"],
        seeds=[22, 11],
        stages=["baseline"],
    )

    assert [(run.checkpoint, run.seed) for run in runs] == [
        ("flux-b", 22),
        ("flux-b", 11),
        ("flux-a", 22),
        ("flux-a", 11),
    ]
    assert plan_runs(
        mode="identity_i2i",
        checkpoints=["flux-b", "flux-a"],
        seeds=[22, 11],
        stages=["baseline"],
    ) == runs


def test_plan_runs_expands_lora_stages_and_only_enables_triples_explicitly():
    loras = [("a.safetensors", 0.7), ("b.safetensors", 0.8), ("c.safetensors", 0.9)]

    default_runs = plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[1], loras=loras)
    assert [run.stage for run in default_runs] == [
        "baseline",
        "lora_single",
        "lora_single",
        "lora_single",
        "lora_pair",
        "lora_pair",
        "lora_pair",
    ]
    assert max(len(run.loras) for run in default_runs) == 2

    triple_runs = plan_runs(
        mode="face_swap",
        checkpoints=["flux"],
        seeds=[1],
        loras=loras,
        stages=["lora_triple"],
    )
    assert len(triple_runs) == 1
    assert triple_runs[0].stage == "lora_triple"
    assert [lora.name for lora in triple_runs[0].loras] == ["a.safetensors", "b.safetensors", "c.safetensors"]


def test_plan_runs_carries_focused_refine_settings_without_mutable_input_references():
    refine = {"steps": 28, "denoise": 0.35}
    runs = plan_runs(
        mode="face_swap",
        checkpoints=["flux"],
        seeds=[5],
        loras=[("identity.safetensors", 0.75)],
        stages=["focused_refine"],
        refine_settings=refine,
    )
    refine["steps"] = 99

    assert runs[0].stage == "focused_refine"
    assert runs[0].refine == {"denoise": 0.35, "steps": 28}
    with pytest.raises(TypeError):
        runs[0].refine["steps"] = 99


def test_plan_runs_removes_duplicate_inputs_and_never_activates_more_than_three_loras():
    runs = plan_runs(
        mode="face_swap",
        checkpoints=["flux", "flux"],
        seeds=[1, 1],
        loras=[("a", 0.5), ("a", 0.5), ("b", 0.6), ("c", 0.7), ("d", 0.8)],
        stages=["lora_triple"],
    )

    assert len(runs) == 4
    assert all(len(run.loras) == 3 for run in runs)
    assert len({run.combination_hash for run in runs}) == 4


def test_plan_runs_canonicalizes_lora_stack_order_before_pair_and_triple_hashing():
    forward = plan_runs(
        mode="face_swap",
        checkpoints=["flux"],
        seeds=[1],
        loras=[("a", 0.5), ("b", 0.6), ("c", 0.7)],
        stages=["lora_pair", "lora_triple"],
    )
    reverse = plan_runs(
        mode="face_swap",
        checkpoints=["flux"],
        seeds=[1],
        loras=[("c", 0.7), ("a", 0.5), ("b", 0.6)],
        stages=["lora_pair", "lora_triple"],
    )

    assert forward == reverse


def test_plan_runs_rejects_large_lora_combinations_before_materializing_them(monkeypatch):
    monkeypatch.setattr(experiment_planner, "combinations", lambda *_args: pytest.fail("combinations materialized"))

    with pytest.raises(ValueError, match="100"):
        plan_runs(
            mode="face_swap",
            checkpoints=["flux"],
            seeds=[1],
            loras=[(f"lora-{index}", 0.5) for index in range(100)],
            stages=["lora_pair"],
        )


@pytest.mark.parametrize("mode", ["txt2img", "", None])
def test_plan_runs_rejects_invalid_modes(mode):
    with pytest.raises(ValueError, match="mode"):
        plan_runs(mode=mode, checkpoints=["flux"], seeds=[1])


@pytest.mark.parametrize("stage", ["triple", "", None])
def test_plan_runs_rejects_invalid_stages(stage):
    with pytest.raises(ValueError, match="stage"):
        plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[1], stages=[stage])


@pytest.mark.parametrize("loras", [[("a", 0)], [("a", 1.01)], [("a", "high")]])
def test_plan_runs_rejects_invalid_lora_strengths(loras):
    with pytest.raises(ValueError, match="strength"):
        plan_runs(mode="face_swap", checkpoints=["flux"], seeds=[1], loras=loras)


@pytest.mark.parametrize("seeds", [[], ["not-a-seed"]])
def test_plan_runs_rejects_empty_or_invalid_seeds(seeds):
    with pytest.raises(ValueError, match="seed"):
        plan_runs(mode="face_swap", checkpoints=["flux"], seeds=seeds)


def test_plan_runs_enforces_hard_one_hundred_run_limit():
    assert MAX_EXPERIMENT_RUNS == 100
    with pytest.raises(ValueError, match="100"):
        plan_runs(mode="face_swap", checkpoints=["flux"], seeds=range(MAX_EXPERIMENT_RUNS + 1), stages=["baseline"])
