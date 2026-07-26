from __future__ import annotations

import json
from pathlib import Path

import folder_paths

from .identity_core import (
    DEFAULT_SAME_IDENTITY_THRESHOLD,
    build_dual_report,
    build_report,
    default_model_paths,
    image_tensor_to_bgr,
    resolve_path,
    write_manifest as write_identity_manifest,
)


class OpenCVIdentityScore:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reference_image": ("IMAGE", {"tooltip": "Source identity or trusted reference image."}),
                "generated_image": ("IMAGE", {"tooltip": "Generated final image to score."}),
                "catalog_root": (
                    "STRING",
                    {
                        "default": "people",
                        "multiline": False,
                        "tooltip": "Optional subject catalog. Relative paths resolve under ComfyUI/input.",
                    },
                ),
                "subject_name": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": "Optional subject folder/name under catalog_root.",
                    },
                ),
                "catalog_mode": (["off", "subject", "all_subjects"],),
                "catalog_aggregation": (["mean_top3", "best", "mean_top5", "mean"],),
                "max_catalog_images": ("INT", {"default": 64, "min": 0, "max": 10000, "step": 1}),
                "include_subfolders": ("BOOLEAN", {"default": True}),
                "face_score_threshold": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.01}),
                "same_identity_threshold": (
                    "FLOAT",
                    {"default": DEFAULT_SAME_IDENTITY_THRESHOLD, "min": -1.0, "max": 1.0, "step": 0.001},
                ),
                "face_selection": (["largest", "highest_confidence"],),
                "write_manifest": ("BOOLEAN", {"default": True}),
                "manifest_dir": (
                    "STRING",
                    {
                        "default": "default/identity_score_runs",
                        "multiline": False,
                        "tooltip": "Relative paths resolve under ComfyUI/user.",
                    },
                ),
                "run_label": ("STRING", {"default": "flux9b-face-swap", "multiline": False}),
                "metadata_key": ("STRING", {"default": "identity_score_report", "multiline": False}),
            },
            "optional": {
                "extra_metadata": ("EXTRA_METADATA", {"forceInput": True}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("FLOAT", "BOOLEAN", "STRING", "STRING", "STRING", "EXTRA_METADATA")
    RETURN_NAMES = (
        "source_cosine_similarity",
        "source_same_identity",
        "best_catalog_subject",
        "best_catalog_reference",
        "report_json",
        "extra_metadata",
    )
    FUNCTION = "score_identity"
    CATEGORY = "arch-image/identity"
    OUTPUT_NODE = True
    DESCRIPTION = "Score generated-image identity preservation with OpenCV YuNet face detection and SFace embeddings."

    def score_identity(
        self,
        reference_image,
        generated_image,
        catalog_root,
        subject_name,
        catalog_mode,
        catalog_aggregation,
        max_catalog_images,
        include_subfolders,
        face_score_threshold,
        same_identity_threshold,
        face_selection,
        write_manifest,
        manifest_dir,
        run_label,
        metadata_key,
        extra_metadata=None,
        prompt=None,
        extra_pnginfo=None,
    ):
        node_dir = Path(__file__).resolve().parent
        models = default_model_paths(node_dir)
        report = build_report(
            reference_bgr=image_tensor_to_bgr(reference_image),
            generated_bgr=image_tensor_to_bgr(generated_image),
            models=models,
            input_dir=Path(folder_paths.get_input_directory()),
            catalog_root_text=catalog_root,
            subject_name=subject_name,
            catalog_mode=catalog_mode,
            catalog_aggregation=catalog_aggregation,
            include_subfolders=include_subfolders,
            max_catalog_images=max_catalog_images,
            face_score_threshold=face_score_threshold,
            same_identity_threshold=same_identity_threshold,
            face_selection=face_selection,
        )

        if write_manifest:
            manifest_root = resolve_path(manifest_dir, Path(folder_paths.get_user_directory()))
            manifest_path = write_identity_manifest(report, manifest_root, run_label, prompt, extra_pnginfo)
            report["manifest_path"] = str(manifest_path)

        report_json = json.dumps(report, indent=2, ensure_ascii=False)
        metadata = dict(extra_metadata or {})
        metadata[metadata_key or "identity_score_report"] = report_json

        source = report["source_identity"]
        catalog = report["catalog"]
        return (
            float(source["cosine_similarity"]),
            bool(source["same_identity"]),
            str(catalog.get("best_subject", "")),
            str(catalog.get("best_reference", "")),
            report_json,
            metadata,
        )


class DualIdentityScore:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "base_image": ("IMAGE", {"tooltip": "Base/input image that supplies composition."}),
                "reference_image": ("IMAGE", {"tooltip": "Identity/reference image."}),
                "generated_image": ("IMAGE", {"tooltip": "Generated final image to score."}),
                "experiment_mode": (["face_swap", "identity_i2i"],),
                "face_score_threshold": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.01}),
                "same_identity_threshold": (
                    "FLOAT",
                    {"default": DEFAULT_SAME_IDENTITY_THRESHOLD, "min": -1.0, "max": 1.0, "step": 0.001},
                ),
                "face_selection": (["largest", "highest_confidence"],),
                "write_manifest": ("BOOLEAN", {"default": True}),
                "manifest_dir": (
                    "STRING",
                    {
                        "default": "default/identity_score_runs",
                        "multiline": False,
                        "tooltip": "Relative paths resolve under ComfyUI/user.",
                    },
                ),
                "run_label": ("STRING", {"default": "dual-identity-score", "multiline": False}),
                "metadata_key": ("STRING", {"default": "identity_score_report", "multiline": False}),
            },
            "optional": {
                "experiment_id": ("STRING", {"default": "", "forceInput": True}),
                "run_id": ("STRING", {"default": "", "forceInput": True}),
                "extra_metadata": ("EXTRA_METADATA", {"forceInput": True}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = (
        "FLOAT",
        "BOOLEAN",
        "BOOLEAN",
        "FLOAT",
        "BOOLEAN",
        "BOOLEAN",
        "BOOLEAN",
        "FLOAT",
        "BOOLEAN",
        "BOOLEAN",
        "STRING",
        "EXTRA_METADATA",
    )
    RETURN_NAMES = (
        "reference_cosine_similarity",
        "reference_detected",
        "reference_same_identity",
        "base_cosine_similarity",
        "base_detected",
        "base_same_identity",
        "generated_detected",
        "active_cosine_similarity",
        "active_same_identity",
        "rankable",
        "report_json",
        "extra_metadata",
    )
    FUNCTION = "score_identity"
    CATEGORY = "arch-image/identity"
    OUTPUT_NODE = True
    DESCRIPTION = "Compare generated identity against both the reference and base images for local experiment ranking."

    def score_identity(
        self,
        base_image,
        reference_image,
        generated_image,
        experiment_mode,
        face_score_threshold,
        same_identity_threshold,
        face_selection,
        write_manifest,
        manifest_dir,
        run_label,
        metadata_key,
        experiment_id="",
        run_id="",
        extra_metadata=None,
        prompt=None,
        extra_pnginfo=None,
    ):
        node_dir = Path(__file__).resolve().parent
        report = build_dual_report(
            base_bgr=image_tensor_to_bgr(base_image),
            reference_bgr=image_tensor_to_bgr(reference_image),
            generated_bgr=image_tensor_to_bgr(generated_image),
            models=default_model_paths(node_dir),
            experiment_mode=experiment_mode,
            face_score_threshold=face_score_threshold,
            same_identity_threshold=same_identity_threshold,
            face_selection=face_selection,
        )
        if experiment_id:
            report["experiment_id"] = str(experiment_id)
        if run_id:
            report["run_id"] = str(run_id)

        if write_manifest:
            manifest_root = resolve_path(manifest_dir, Path(folder_paths.get_user_directory()))
            manifest_path = write_identity_manifest(report, manifest_root, run_label, prompt, extra_pnginfo)
            report["manifest_path"] = str(manifest_path)

        report_json = json.dumps(report, indent=2, ensure_ascii=False)
        metadata = dict(extra_metadata or {})
        metadata[metadata_key or "identity_score_report"] = report_json

        reference = report["reference_to_output"]
        base = report["base_to_output"]
        active = report["active_score"]
        rankable = bool(report["rankable"])
        status = "rankable" if rankable else "not_rankable"
        face_detection = report["face_detection"]
        score_text = lambda value: f"{float(value):.6f}" if value is not None else "unavailable"
        detection_text = "; ".join(
            f"{name} face {'detected' if face_detection[name] else 'not detected'}"
            for name in ("base", "reference", "generated")
        )
        text = (
            f"reference {score_text(reference['cosine_similarity'])}; "
            f"base {score_text(base['cosine_similarity'])}; "
            f"active ({active['source']}) {score_text(active['cosine_similarity'])}; {status}; {detection_text}"
        )
        result = (
            float(reference["cosine_similarity"] or 0.0),
            bool(face_detection["reference"]),
            bool(reference["same_identity"]),
            float(base["cosine_similarity"] or 0.0),
            bool(face_detection["base"]),
            bool(base["same_identity"]),
            bool(face_detection["generated"]),
            float(active["cosine_similarity"] or 0.0),
            bool(active["same_identity"]),
            rankable,
            report_json,
            metadata,
        )
        return {
            "ui": {
                "text": [text],
                "status": [status],
                "result_id": [str(run_id or "")],
                "face_detection": [face_detection],
            },
            "result": result,
        }


NODE_CLASS_MAPPINGS = {
    "OpenCVIdentityScore": OpenCVIdentityScore,
    "DualIdentityScore": DualIdentityScore,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "OpenCVIdentityScore": "arch-OpenCV Identity Score",
    "DualIdentityScore": "arch-Dual Identity Score",
}
