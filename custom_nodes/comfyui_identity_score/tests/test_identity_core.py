from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from identity_core import (
    FaceEmbedding,
    OpenCVFaceModels,
    aggregate_scores,
    build_dual_report,
    build_report,
    default_model_paths,
    resolve_path,
)


def test_resolve_path_uses_relative_base(tmp_path):
    assert resolve_path("people", tmp_path) == (tmp_path / "people").resolve()


def test_aggregate_scores_modes():
    values = [0.1, 0.5, 0.3, 0.9]
    assert aggregate_scores(values, "best") == 0.9
    assert round(aggregate_scores(values, "mean_top3"), 6) == round((0.9 + 0.5 + 0.3) / 3, 6)
    assert round(aggregate_scores(values, "mean"), 6) == 0.45


def test_blank_images_return_no_face_report():
    node_dir = Path(__file__).resolve().parents[1]
    models: OpenCVFaceModels = default_model_paths(node_dir)
    blank = np.zeros((128, 128, 3), dtype=np.uint8)
    report = build_report(
        reference_bgr=blank,
        generated_bgr=blank,
        models=models,
        input_dir=Path.cwd(),
        catalog_root_text=".",
        subject_name="",
        catalog_mode="off",
        catalog_aggregation="mean_top3",
        include_subfolders=False,
        max_catalog_images=0,
        face_score_threshold=0.7,
        same_identity_threshold=0.363,
        face_selection="largest",
    )
    assert report["source_identity"]["cosine_similarity"] == 0.0
    assert report["source_identity"]["same_identity"] is False
    assert "generated face not detected" in report["source_identity"]["issues"]


def _face(feature):
    return FaceEmbedding(
        feature=np.asarray(feature, dtype=np.float32),
        face=[0.0, 0.0, 10.0, 10.0, 0.99],
        confidence=0.99,
        box=(0, 0, 10, 10),
        image_size=(20, 20),
    )


def test_dual_report_detects_generated_face_once_for_both_comparisons(monkeypatch, tmp_path):
    detected = iter([_face([0.0, 1.0]), _face([1.0, 0.0]), _face([1.0, 0.0])])
    calls = []

    def detect_once(bgr, *_args):
        calls.append(bgr)
        return next(detected)

    monkeypatch.setattr("identity_core.detect_best_face", detect_once)
    report = build_dual_report(
        base_bgr=np.full((2, 2, 3), 1, dtype=np.uint8),
        reference_bgr=np.full((2, 2, 3), 2, dtype=np.uint8),
        generated_bgr=np.full((2, 2, 3), 3, dtype=np.uint8),
        models=default_model_paths(tmp_path),
        experiment_mode="face_swap",
        face_score_threshold=0.7,
        same_identity_threshold=0.363,
        face_selection="largest",
    )

    assert len(calls) == 3
    assert [int(bgr[0, 0, 0]) for bgr in calls] == [1, 2, 3]
    assert report["reference_to_output"]["cosine_similarity"] == 1.0
    assert report["base_to_output"]["cosine_similarity"] == 0.0


def test_dual_report_selects_the_mode_appropriate_active_score(monkeypatch, tmp_path):
    def detect_by_pixel(bgr, *_args):
        return {
            1: _face([0.0, 1.0]),
            2: _face([1.0, 0.0]),
            3: _face([1.0, 0.0]),
        }[int(bgr[0, 0, 0])]

    monkeypatch.setattr("identity_core.detect_best_face", detect_by_pixel)
    kwargs = {
        "base_bgr": np.full((2, 2, 3), 1, dtype=np.uint8),
        "reference_bgr": np.full((2, 2, 3), 2, dtype=np.uint8),
        "generated_bgr": np.full((2, 2, 3), 3, dtype=np.uint8),
        "models": default_model_paths(tmp_path),
        "face_score_threshold": 0.7,
        "same_identity_threshold": 0.363,
        "face_selection": "largest",
    }

    swap = build_dual_report(experiment_mode="face_swap", **kwargs)
    i2i = build_dual_report(experiment_mode="identity_i2i", **kwargs)

    assert swap["active_score"] == {"source": "reference", "cosine_similarity": 1.0, "same_identity": True}
    assert i2i["active_score"] == {"source": "base", "cosine_similarity": 0.0, "same_identity": False}


def test_dual_report_marks_missing_active_face_as_non_rankable(monkeypatch, tmp_path):
    detected = iter([None, _face([1.0, 0.0]), _face([1.0, 0.0])])
    monkeypatch.setattr("identity_core.detect_best_face", lambda *_args: next(detected))

    report = build_dual_report(
        base_bgr=np.zeros((2, 2, 3), dtype=np.uint8),
        reference_bgr=np.ones((2, 2, 3), dtype=np.uint8),
        generated_bgr=np.full((2, 2, 3), 2, dtype=np.uint8),
        models=default_model_paths(tmp_path),
        experiment_mode="identity_i2i",
        face_score_threshold=0.7,
        same_identity_threshold=0.363,
        face_selection="largest",
    )

    assert report["face_detection"] == {"base": False, "reference": True, "generated": True}
    assert report["base_to_output"]["cosine_similarity"] is None
    assert report["base_to_output"]["issues"] == ["base face not detected"]
    assert report["base_to_output"]["base_face"] is None
    assert "reference_face" not in report["base_to_output"]
    assert report["rankable"] is False
    assert report["active_score"]["cosine_similarity"] is None
    assert "base face not detected" in report["issues"]


def test_dual_report_marks_missing_inactive_face_as_non_rankable(monkeypatch, tmp_path):
    detected = iter([None, _face([1.0, 0.0]), _face([1.0, 0.0])])
    monkeypatch.setattr("identity_core.detect_best_face", lambda *_args: next(detected))

    report = build_dual_report(
        base_bgr=np.zeros((2, 2, 3), dtype=np.uint8),
        reference_bgr=np.ones((2, 2, 3), dtype=np.uint8),
        generated_bgr=np.full((2, 2, 3), 2, dtype=np.uint8),
        models=default_model_paths(tmp_path),
        experiment_mode="face_swap",
        face_score_threshold=0.7,
        same_identity_threshold=0.363,
        face_selection="largest",
    )

    assert report["active_score"]["cosine_similarity"] == 1.0
    assert report["rankable"] is False
    assert "base face not detected" in report["issues"]
