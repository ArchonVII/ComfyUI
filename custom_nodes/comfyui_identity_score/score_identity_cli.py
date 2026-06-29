from __future__ import annotations

import argparse
import json
from pathlib import Path

from identity_core import build_report, default_model_paths, load_image_bgr


def main() -> int:
    parser = argparse.ArgumentParser(description="Score generated face identity against a reference image and optional catalog.")
    parser.add_argument("--reference", required=True, help="Source/reference image path.")
    parser.add_argument("--generated", required=True, help="Generated image path.")
    parser.add_argument("--catalog-root", default="", help="Optional catalog root. Subject folders are supported.")
    parser.add_argument("--subject", default="", help="Optional subject name/folder.")
    parser.add_argument("--catalog-mode", choices=["off", "subject", "all_subjects"], default="off")
    parser.add_argument("--catalog-aggregation", choices=["mean_top3", "best", "mean_top5", "mean"], default="mean_top3")
    parser.add_argument("--include-subfolders", action="store_true")
    parser.add_argument("--max-catalog-images", type=int, default=64)
    parser.add_argument("--face-score-threshold", type=float, default=0.7)
    parser.add_argument("--same-identity-threshold", type=float, default=0.363)
    parser.add_argument("--face-selection", choices=["largest", "highest_confidence"], default="largest")
    parser.add_argument("--output-json", help="Optional JSON output path.")
    args = parser.parse_args()

    node_dir = Path(__file__).resolve().parent
    input_dir = Path.cwd()
    report = build_report(
        reference_bgr=load_image_bgr(args.reference),
        generated_bgr=load_image_bgr(args.generated),
        models=default_model_paths(node_dir),
        input_dir=input_dir,
        catalog_root_text=args.catalog_root or ".",
        subject_name=args.subject,
        catalog_mode=args.catalog_mode,
        catalog_aggregation=args.catalog_aggregation,
        include_subfolders=args.include_subfolders,
        max_catalog_images=args.max_catalog_images,
        face_score_threshold=args.face_score_threshold,
        same_identity_threshold=args.same_identity_threshold,
        face_selection=args.face_selection,
    )
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output_json:
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
