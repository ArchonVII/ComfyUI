"""Tests for arch-pt-Random: seeded blank-filling that never overrides a choice."""

import json

from custom_nodes.comfyui_arch_prompt_tools.nodes import (
    ArchPtCombine,
    ArchPtIdentity,
    ArchPtRandom,
    _FOCUSED_NODE_KEYS,
)


def roll(seed=0, preset="scene", family="flux", **bundles):
    outputs = ArchPtRandom().roll(family, preset, seed, **bundles)
    return dict(zip((*_FOCUSED_NODE_KEYS, "rolled_summary"), outputs))


def combine(rolled):
    node = ArchPtCombine()
    return node.combine(", ", True, **{k: rolled[k] for k in _FOCUSED_NODE_KEYS})[0]


def identity_with_hair(text="hand-picked test hair"):
    state = json.dumps(
        {
            "version": 1,
            "node": "identity",
            "model_family": "flux",
            "fields": {"hair_color": {"fragments": [], "specifics": text}},
        }
    )
    return ArchPtIdentity().build("flux", state)[1]


def test_scene_roll_produces_combinable_bundles_and_a_nonempty_prompt():
    rolled = roll(seed=1)
    prompt = combine(rolled)

    assert prompt
    # every category the scene preset touches contributed text
    for node_key in ("identity", "pose", "clothing", "environment", "camera", "lighting"):
        assert rolled[node_key]["prompt"], node_key


def test_same_seed_repeats_and_different_seed_varies():
    first = combine(roll(seed=7))
    again = combine(roll(seed=7))
    other = combine(roll(seed=8))

    assert first == again
    assert first != other


def test_hand_picked_field_is_never_overridden():
    hand = identity_with_hair()
    rolled = roll(seed=3, identity=hand)

    identity_fields = {f["key"]: f for f in rolled["identity"]["fields"]}
    assert identity_fields["hair_color"]["specifics"] == "hand-picked test hair"
    assert identity_fields["hair_color"]["fragments"] == []
    assert "identity.hair_color" not in rolled["rolled_summary"]
    # other scene fields still rolled
    assert "identity.expression" in rolled["rolled_summary"]


def test_everything_preset_rolls_more_fields_than_scene():
    scene = roll(seed=5)["rolled_summary"].count("\n")
    everything = roll(seed=5, preset="everything")["rolled_summary"].count("\n")

    assert everything > scene


def test_qwen_family_rolls_use_qwen_phrases():
    rolled = roll(seed=2, family="qwen")

    for node_key in _FOCUSED_NODE_KEYS:
        assert rolled[node_key]["model_family"] == "qwen"
        for field in rolled[node_key]["fields"]:
            for fragment in field["fragments"]:
                assert fragment["model_family"] == "qwen"


def test_summary_reports_when_everything_was_already_set():
    hand = identity_with_hair()
    rolled = roll(seed=4, preset="portrait", identity=hand)
    # portrait rolls only identity/lighting/camera fields; re-roll with all of
    # those already present must report nothing new for the identity fields
    again = roll(seed=4, preset="portrait", identity=rolled["identity"],
                 lighting=rolled["lighting"], camera=rolled["camera"])

    assert "identity." not in again["rolled_summary"]
