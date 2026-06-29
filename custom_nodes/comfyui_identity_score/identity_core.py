from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from PIL import Image, ImageOps


VALID_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DEFAULT_SAME_IDENTITY_THRESHOLD = 0.363


@dataclass(frozen=True)
class FaceEmbedding:
    feature: np.ndarray
    face: list[float]
    confidence: float
    box: tuple[int, int, int, int]
    image_size: tuple[int, int]


@dataclass(frozen=True)
class OpenCVFaceModels:
    detector_model: Path
    recognizer_model: Path


def default_model_paths(base_dir: Path) -> OpenCVFaceModels:
    models = base_dir / "models"
    return OpenCVFaceModels(
        detector_model=models / "face_detection_yunet_2023mar.onnx",
        recognizer_model=models / "face_recognition_sface_2021dec.onnx",
    )


def ensure_model_files(paths: OpenCVFaceModels) -> None:
    missing = [str(path) for path in [paths.detector_model, paths.recognizer_model] if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing OpenCV face identity model file(s): "
            + ", ".join(missing)
            + ". Run scripts/download_opencv_models.ps1 from this custom node folder."
        )


def image_tensor_to_bgr(image: Any) -> np.ndarray:
    arr = image
    if hasattr(arr, "detach"):
        arr = arr.detach().cpu().numpy()
    arr = np.asarray(arr)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim != 3 or arr.shape[2] < 3:
        raise ValueError("expected IMAGE tensor/array with shape [B,H,W,3] or [H,W,3]")
    arr = arr[:, :, :3]
    if arr.dtype != np.uint8:
        arr = np.clip(arr * 255.0 if arr.max(initial=0) <= 1.5 else arr, 0, 255).astype(np.uint8)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def load_image_bgr(path: str | Path) -> np.ndarray:
    path = Path(path)
    with Image.open(path) as image:
        frame = ImageOps.exif_transpose(image).convert("RGB")
        arr = np.asarray(frame, dtype=np.uint8)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def resolve_path(path_text: str, relative_base: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(str(path_text or "").strip().strip("\"'")))
    path = Path(expanded)
    if not path.is_absolute():
        path = relative_base / path
    return path.resolve()


def iter_image_files(folder: Path, include_subfolders: bool) -> list[Path]:
    iterator = folder.rglob("*") if include_subfolders else folder.iterdir()
    return sorted(
        [path for path in iterator if path.is_file() and path.suffix.lower() in VALID_IMAGE_EXTENSIONS],
        key=lambda item: item.as_posix().casefold(),
    )


def detect_best_face(
    bgr: np.ndarray,
    models: OpenCVFaceModels,
    score_threshold: float,
    face_selection: str,
) -> FaceEmbedding | None:
    ensure_model_files(models)
    height, width = bgr.shape[:2]
    detector = cv2.FaceDetectorYN.create(
        str(models.detector_model),
        "",
        (width, height),
        float(score_threshold),
        0.3,
        5000,
    )
    detector.setInputSize((width, height))
    _, faces = detector.detect(bgr)
    if faces is None or len(faces) == 0:
        return None

    face_rows = [np.asarray(face, dtype=np.float32) for face in faces]
    if face_selection == "largest":
        chosen = max(face_rows, key=lambda face: float(face[2] * face[3]))
    else:
        chosen = max(face_rows, key=lambda face: float(face[-1]))

    recognizer = cv2.FaceRecognizerSF.create(str(models.recognizer_model), "")
    aligned = recognizer.alignCrop(bgr, chosen)
    feature = np.asarray(recognizer.feature(aligned), dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(feature))
    if norm > 0:
        feature = feature / norm

    x, y, box_w, box_h = [int(round(float(value))) for value in chosen[:4]]
    return FaceEmbedding(
        feature=feature,
        face=[float(value) for value in chosen.tolist()],
        confidence=float(chosen[-1]),
        box=(x, y, box_w, box_h),
        image_size=(width, height),
    )


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    value = float(np.dot(left, right) / (left_norm * right_norm))
    if math.isnan(value):
        return 0.0
    return value


def face_summary(face: FaceEmbedding | None) -> dict[str, Any] | None:
    if face is None:
        return None
    width, height = face.image_size
    _, _, box_w, box_h = face.box
    return {
        "box": face.box,
        "confidence": round(face.confidence, 6),
        "image_size": face.image_size,
        "face_area_fraction": round((box_w * box_h) / float(max(1, width * height)), 6),
    }


def score_embeddings(
    reference: FaceEmbedding | None,
    generated: FaceEmbedding | None,
    threshold: float = DEFAULT_SAME_IDENTITY_THRESHOLD,
) -> dict[str, Any]:
    if reference is None or generated is None:
        issues = []
        if reference is None:
            issues.append("reference face not detected")
        if generated is None:
            issues.append("generated face not detected")
        return {
            "cosine_similarity": 0.0,
            "same_identity": False,
            "same_identity_threshold": threshold,
            "issues": issues,
            "reference_face": face_summary(reference),
            "generated_face": face_summary(generated),
        }

    cosine = cosine_similarity(reference.feature, generated.feature)
    return {
        "cosine_similarity": round(cosine, 6),
        "same_identity": cosine >= threshold,
        "same_identity_threshold": threshold,
        "issues": [],
        "reference_face": face_summary(reference),
        "generated_face": face_summary(generated),
    }


def catalog_entries(
    catalog_root: Path,
    subject_name: str,
    mode: str,
    include_subfolders: bool,
    max_images: int,
) -> list[tuple[str, Path]]:
    if not catalog_root.exists() or mode == "off":
        return []
    max_images = max(0, int(max_images))
    if max_images == 0:
        return []

    subject_name = str(subject_name or "").strip()
    entries: list[tuple[str, Path]] = []

    if mode == "subject" and subject_name:
        subject_dir = catalog_root / subject_name
        if subject_dir.is_dir():
            entries.extend((subject_name, path) for path in iter_image_files(subject_dir, include_subfolders))
        elif catalog_root.is_dir():
            entries.extend((subject_name, path) for path in iter_image_files(catalog_root, include_subfolders))
    elif mode == "all_subjects":
        subject_dirs = [path for path in sorted(catalog_root.iterdir(), key=lambda p: p.name.casefold()) if path.is_dir()]
        if subject_dirs:
            for subject_dir in subject_dirs:
                entries.extend((subject_dir.name, path) for path in iter_image_files(subject_dir, include_subfolders))
        else:
            entries.extend((catalog_root.name, path) for path in iter_image_files(catalog_root, include_subfolders))
    elif catalog_root.is_dir():
        entries.extend((subject_name or catalog_root.name, path) for path in iter_image_files(catalog_root, include_subfolders))

    return entries[:max_images]


def aggregate_scores(scores: list[float], method: str) -> float:
    if not scores:
        return 0.0
    ordered = sorted(scores, reverse=True)
    if method == "best":
        return ordered[0]
    if method == "mean":
        return float(sum(ordered) / len(ordered))
    if method == "mean_top5":
        top = ordered[:5]
        return float(sum(top) / len(top))
    top = ordered[:3]
    return float(sum(top) / len(top))


def score_catalog(
    generated: FaceEmbedding | None,
    models: OpenCVFaceModels,
    catalog_root: Path,
    subject_name: str,
    mode: str,
    include_subfolders: bool,
    max_images: int,
    aggregation: str,
    face_score_threshold: float,
    same_identity_threshold: float,
    face_selection: str,
) -> dict[str, Any]:
    entries = catalog_entries(catalog_root, subject_name, mode, include_subfolders, max_images)
    if generated is None or not entries:
        return {
            "mode": mode,
            "catalog_root": str(catalog_root),
            "images_scored": 0,
            "best_subject": "",
            "best_reference": "",
            "best_cosine_similarity": 0.0,
            "subject_scores": [],
            "errors": [] if entries else ["no catalog images found"],
        }

    subject_raw: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for subject, image_path in entries:
        try:
            reference = detect_best_face(load_image_bgr(image_path), models, face_score_threshold, face_selection)
            if reference is None:
                errors.append(f"no face: {image_path}")
                continue
            cosine = cosine_similarity(reference.feature, generated.feature)
            subject_raw.setdefault(subject, []).append(
                {
                    "path": str(image_path),
                    "cosine_similarity": round(cosine, 6),
                    "same_identity": cosine >= same_identity_threshold,
                    "face": face_summary(reference),
                }
            )
        except Exception as exc:  # keep batch runs alive and report bad catalog files
            errors.append(f"{image_path}: {exc}")

    subject_scores = []
    for subject, rows in subject_raw.items():
        values = [float(row["cosine_similarity"]) for row in rows]
        best_row = max(rows, key=lambda row: row["cosine_similarity"])
        subject_scores.append(
            {
                "subject": subject,
                "image_count": len(rows),
                "aggregate": aggregation,
                "aggregate_cosine_similarity": round(aggregate_scores(values, aggregation), 6),
                "best_reference": best_row["path"],
                "best_cosine_similarity": best_row["cosine_similarity"],
            }
        )
    subject_scores.sort(key=lambda row: row["aggregate_cosine_similarity"], reverse=True)
    best = subject_scores[0] if subject_scores else {}
    return {
        "mode": mode,
        "catalog_root": str(catalog_root),
        "images_scored": sum(row["image_count"] for row in subject_scores),
        "best_subject": best.get("subject", ""),
        "best_reference": best.get("best_reference", ""),
        "best_cosine_similarity": best.get("best_cosine_similarity", 0.0),
        "subject_scores": subject_scores,
        "errors": errors,
    }


def build_report(
    reference_bgr: np.ndarray,
    generated_bgr: np.ndarray,
    models: OpenCVFaceModels,
    input_dir: Path,
    catalog_root_text: str,
    subject_name: str,
    catalog_mode: str,
    catalog_aggregation: str,
    include_subfolders: bool,
    max_catalog_images: int,
    face_score_threshold: float,
    same_identity_threshold: float,
    face_selection: str,
) -> dict[str, Any]:
    reference = detect_best_face(reference_bgr, models, face_score_threshold, face_selection)
    generated = detect_best_face(generated_bgr, models, face_score_threshold, face_selection)
    source_score = score_embeddings(reference, generated, same_identity_threshold)

    catalog_root = resolve_path(catalog_root_text or ".", input_dir)
    catalog = score_catalog(
        generated=generated,
        models=models,
        catalog_root=catalog_root,
        subject_name=subject_name,
        mode=catalog_mode,
        include_subfolders=include_subfolders,
        max_images=max_catalog_images,
        aggregation=catalog_aggregation,
        face_score_threshold=face_score_threshold,
        same_identity_threshold=same_identity_threshold,
        face_selection=face_selection,
    )

    return {
        "scorer": "opencv_yunet_sface",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "models": {
            "detector": str(models.detector_model),
            "recognizer": str(models.recognizer_model),
        },
        "settings": {
            "face_score_threshold": face_score_threshold,
            "same_identity_threshold": same_identity_threshold,
            "face_selection": face_selection,
            "catalog_mode": catalog_mode,
            "catalog_aggregation": catalog_aggregation,
            "max_catalog_images": max_catalog_images,
            "include_subfolders": include_subfolders,
        },
        "source_identity": source_score,
        "catalog": catalog,
    }


def write_manifest(
    report: dict[str, Any],
    manifest_dir: Path,
    run_label: str,
    prompt: Any | None,
    extra_pnginfo: Any | None,
) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (run_label or "identity-score")).strip("-")
    safe_label = safe_label or "identity-score"
    path = manifest_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe_label}.json"
    payload = {
        "identity_report": report,
        "prompt": prompt,
        "extra_pnginfo": extra_pnginfo,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
