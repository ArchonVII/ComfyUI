from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_identity_score import DualIdentityScore
from comfyui_identity_score.nodes import NODE_DISPLAY_NAME_MAPPINGS, OpenCVIdentityScore
from comfyui_identity_score import nodes


def test_identity_score_is_arch_prefixed_for_searchability():
    assert NODE_DISPLAY_NAME_MAPPINGS["OpenCVIdentityScore"] == "arch-OpenCV Identity Score"
    assert OpenCVIdentityScore.CATEGORY == "arch-image/identity"


def test_dual_identity_score_exposes_experiment_contract_and_visible_node_metadata():
    dual = nodes.DualIdentityScore
    inputs = dual.INPUT_TYPES()

    assert {"base_image", "reference_image", "generated_image", "experiment_mode"} <= set(inputs["required"])
    assert {"experiment_id", "run_id", "extra_metadata"} <= set(inputs["optional"])
    assert dual.RETURN_TYPES == (
        "FLOAT",
        "BOOLEAN",
        "FLOAT",
        "BOOLEAN",
        "FLOAT",
        "BOOLEAN",
        "BOOLEAN",
        "STRING",
        "EXTRA_METADATA",
    )
    assert dual.OUTPUT_NODE is True
    assert dual.CATEGORY == "arch-image/identity"
    assert NODE_DISPLAY_NAME_MAPPINGS["DualIdentityScore"] == "arch-Dual Identity Score"
    assert DualIdentityScore is dual


def test_dual_identity_score_returns_ui_payload_and_result_values(monkeypatch):
    report = {
        "reference_to_output": {"cosine_similarity": 0.91, "same_identity": True},
        "base_to_output": {"cosine_similarity": 0.42, "same_identity": True},
        "active_score": {"source": "reference", "cosine_similarity": 0.91, "same_identity": True},
        "rankable": True,
        "face_detection": {"base": True, "reference": True, "generated": True},
        "issues": [],
    }
    monkeypatch.setattr(nodes, "build_dual_report", lambda **_kwargs: report)
    monkeypatch.setattr(nodes, "image_tensor_to_bgr", lambda image: image)

    result = nodes.DualIdentityScore().score_identity(
        base_image="base",
        reference_image="reference",
        generated_image="generated",
        experiment_mode="face_swap",
        face_score_threshold=0.7,
        same_identity_threshold=0.363,
        face_selection="largest",
        write_manifest=False,
        manifest_dir="default/identity_score_runs",
        run_label="dual-score",
        metadata_key="identity_score_report",
        experiment_id="experiment-1",
        run_id="run-2",
        extra_metadata={"prior": "metadata"},
    )

    assert result["result"][:7] == (0.91, True, 0.42, True, 0.91, True, True)
    assert result["result"][8]["prior"] == "metadata"
    assert result["ui"]["status"] == ["rankable"]
    assert result["ui"]["result_id"] == ["run-2"]
    assert "reference 0.910000" in result["ui"]["text"][0]
