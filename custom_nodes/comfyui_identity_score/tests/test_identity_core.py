from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from identity_core import (
    OpenCVFaceModels,
    aggregate_scores,
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
