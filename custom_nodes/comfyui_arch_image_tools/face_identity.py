"""Local landmark-aligned identity transfer for the Arch image workflows."""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort
import torch

import folder_paths


ARCFACE_POINTS = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)
INSWAPPER_CROP_SIZE = 128
# INSwapper uses a 128px crop around ArcFace's standard 112px alignment.
INSWAPPER_ARCFACE_X_OFFSET = (INSWAPPER_CROP_SIZE - 112) / 2.0


def _providers() -> list[str]:
    return ["CPUExecutionProvider"]


def _full_model_path(kind: str, relative: str) -> Path:
    path = folder_paths.get_full_path(kind, relative)
    if path:
        return Path(path)
    roots = folder_paths.get_folder_paths(kind)
    if roots:
        return Path(roots[0]) / relative
    raise FileNotFoundError(f"No ComfyUI model folder is registered for {kind}")


def _yunet_path() -> Path:
    sibling = Path(__file__).resolve().parents[1] / "comfyui_identity_score" / "models" / "face_detection_yunet_2023mar.onnx"
    if not sibling.is_file():
        raise FileNotFoundError(f"Local YuNet face detector not found: {sibling}")
    return sibling


def _tensor_to_bgr(image: Any) -> np.ndarray:
    array = image.detach().cpu().numpy() if hasattr(image, "detach") else np.asarray(image)
    if array.ndim == 4:
        array = array[0]
    if array.ndim != 3 or array.shape[2] < 3:
        raise ValueError("Expected an IMAGE tensor shaped [B,H,W,3]")
    rgb = np.clip(array[:, :, :3] * 255.0, 0, 255).astype(np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _bgr_to_tensor(image: np.ndarray) -> torch.Tensor:
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return torch.from_numpy(rgb).unsqueeze(0)


def _detect_faces(image: np.ndarray, threshold: float) -> np.ndarray:
    height, width = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(str(_yunet_path()), "", (width, height), float(threshold), 0.3, 5000)
    detector.setInputSize((width, height))
    _, faces = detector.detect(image)
    if faces is None or not len(faces):
        raise ValueError("No face detected. Use a clearer, larger, front-visible face reference.")
    return np.asarray(faces, dtype=np.float32)


def _select_face(faces: np.ndarray, selection: str, index: int) -> np.ndarray:
    if selection == "highest_confidence":
        ordered = sorted(faces, key=lambda face: float(face[-1]), reverse=True)
    else:
        ordered = sorted(faces, key=lambda face: float(face[2] * face[3]), reverse=True)
    index = int(index)
    if index < 0 or index >= len(ordered):
        raise ValueError(f"Face index {index} is unavailable; detected {len(ordered)} face(s).")
    return np.asarray(ordered[index], dtype=np.float32)


def _detect_largest(image: np.ndarray, threshold: float) -> np.ndarray:
    return _select_face(_detect_faces(image, threshold), "largest", 0)


def _landmarks(face: np.ndarray) -> np.ndarray:
    return face[4:14].reshape(5, 2).astype(np.float32)


@lru_cache(maxsize=2)
def _session(path: str) -> ort.InferenceSession:
    return ort.InferenceSession(path, providers=_providers())


def _source_embedding(image: np.ndarray, face: np.ndarray) -> np.ndarray:
    matrix, _ = cv2.estimateAffinePartial2D(_landmarks(face), ARCFACE_POINTS)
    if matrix is None:
        raise ValueError("Source face landmarks could not produce a stable affine transform.")
    model_path = _full_model_path("insightface", "models/buffalo_l/w600k_r50.onnx")
    session = _session(str(model_path))
    aligned = cv2.warpAffine(image, matrix, (112, 112), borderValue=0.0)
    blob = cv2.dnn.blobFromImage(aligned, 1.0 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
    embedding = session.run(None, {session.get_inputs()[0].name: blob})[0].reshape(-1).astype(np.float32)
    return embedding / max(float(np.linalg.norm(embedding)), 1e-8)


def _emap(swapper_path: Path) -> np.ndarray:
    path = swapper_path.with_suffix(".emap.npy")
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing local INSwapper embedding map: {path}. Run scripts/extract_inswapper_emap.py once."
        )
    return np.load(path).astype(np.float32)


def _sam_architecture(model_name: str) -> str:
    lowered = Path(model_name).name.lower()
    for architecture in ("vit_b", "vit_l", "vit_h"):
        if architecture in lowered:
            return architecture
    raise ValueError(
        f"Unsupported SAM checkpoint {model_name!r}; select an original SAM ViT-B, ViT-L, or ViT-H checkpoint."
    )


def _model_paths(sam_model: str, *, require_sam: bool = True) -> dict[str, Path]:
    paths = {
        "swapper": _full_model_path("insightface", "inswapper_128.onnx"),
        "arcface": _full_model_path("insightface", "models/buffalo_l/w600k_r50.onnx"),
        "yunet": _yunet_path(),
    }
    if require_sam:
        _sam_architecture(sam_model)
        if importlib.util.find_spec("segment_anything") is None:
            raise ModuleNotFoundError(
                "Local SAM masking requires the segment_anything Python package. "
                "Use Landmark feather mode or install segment_anything into this ComfyUI environment."
            )
        paths["sam"] = _full_model_path("sams", sam_model)
    paths["emap"] = paths["swapper"].with_suffix(".emap.npy")
    missing = [f"{name}: {path}" for name, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing local identity model artifact(s): " + "; ".join(missing))
    return paths


def _mapped_identity(image: np.ndarray, face: np.ndarray, swapper_path: Path) -> np.ndarray:
    latent = _source_embedding(image, face).reshape(1, -1) @ _emap(swapper_path)
    return (latent / max(float(np.linalg.norm(latent)), 1e-8)).astype(np.float32)


def _face_preview(image: np.ndarray, face: np.ndarray) -> torch.Tensor:
    x, y, width, height = face[:4]
    pad_x, pad_y = width * 0.2, height * 0.25
    image_height, image_width = image.shape[:2]
    x1, y1 = max(0, int(x - pad_x)), max(0, int(y - pad_y))
    x2, y2 = min(image_width, int(x + width + pad_x)), min(image_height, int(y + height + pad_y))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError("Detected source face produced an empty preview crop.")
    return _bgr_to_tensor(cv2.resize(crop, (256, 256), interpolation=cv2.INTER_LANCZOS4))


def _sam_box(face: np.ndarray, image_width: int, image_height: int) -> np.ndarray:
    x, y, width, height = face[:4]
    pad_x, pad_y = width * 0.12, height * 0.16
    return np.array(
        [
            max(0.0, float(x - pad_x)),
            max(0.0, float(y - pad_y)),
            min(float(image_width), float(x + width + pad_x)),
            min(float(image_height), float(y + height + pad_y)),
        ],
        dtype=np.float32,
    )


class _SamRuntime:
    """Own one local SAM model while re-embedding each updated pass image."""

    def __init__(self, model_name: str, sam_device: str):
        from segment_anything import SamPredictor, sam_model_registry

        model_path = _full_model_path("sams", model_name)
        self.device = "cpu"
        if sam_device == "Auto (unload models)" and torch.cuda.is_available():
            import comfy.model_management as model_management

            model_management.unload_all_models()
            model_management.soft_empty_cache()
            self.device = "cuda"
        self.model = sam_model_registry[_sam_architecture(model_name)](checkpoint=str(model_path))
        self.predictor = SamPredictor(self.model.to(device=self.device))

    def mask(self, image: np.ndarray, face: np.ndarray) -> np.ndarray:
        self.predictor.set_image(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        box = _sam_box(face, image.shape[1], image.shape[0])
        masks, scores, _ = self.predictor.predict(box=box, multimask_output=True)
        return masks[int(np.argmax(scores))].astype(np.float32)

    def close(self) -> None:
        if self.predictor is not None and hasattr(self.predictor, "reset_image"):
            self.predictor.reset_image()
        self.predictor = None
        self.model = None
        if self.device == "cuda":
            torch.cuda.empty_cache()


def _sam_mask(image: np.ndarray, face: np.ndarray, model_name: str, sam_device: str) -> np.ndarray:
    runtime = _SamRuntime(model_name, sam_device)
    try:
        return runtime.mask(image, face)
    finally:
        runtime.close()


def _transfer(
    identity: dict[str, Any],
    target: np.ndarray,
    threshold: float,
    target_selection: str,
    target_face_index: int,
    mask_mode: str,
    sam_model: str,
    sam_device: str,
    feather: int,
    *,
    sam_runtime: _SamRuntime | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    if not identity or "latent" not in identity:
        raise ValueError("Identity preflight data is missing. Run ArchFaceIdentityPreflight first.")
    target_face = _select_face(_detect_faces(target, threshold), target_selection, target_face_index)
    swapper_path = _full_model_path("insightface", "inswapper_128.onnx")
    session = _session(str(swapper_path))

    destination_points = ARCFACE_POINTS.copy()
    destination_points[:, 0] += INSWAPPER_ARCFACE_X_OFFSET
    matrix, _ = cv2.estimateAffinePartial2D(_landmarks(target_face), destination_points)
    if matrix is None:
        raise ValueError("Target face landmarks could not produce a stable affine transform.")
    crop = cv2.warpAffine(target, matrix, (INSWAPPER_CROP_SIZE, INSWAPPER_CROP_SIZE), borderValue=0.0)
    target_blob = cv2.dnn.blobFromImage(
        crop,
        1.0 / 255.0,
        (INSWAPPER_CROP_SIZE, INSWAPPER_CROP_SIZE),
        (0, 0, 0),
        swapRB=True,
    )
    latent = np.asarray(identity["latent"], dtype=np.float32)
    inputs = session.get_inputs()
    prediction = session.run(None, {inputs[0].name: target_blob, inputs[1].name: latent.astype(np.float32)})[0]
    swapped_crop = np.clip(prediction[0].transpose(1, 2, 0)[:, :, ::-1] * 255.0, 0, 255).astype(np.uint8)

    inverse = cv2.invertAffineTransform(matrix)
    height, width = target.shape[:2]
    warped = cv2.warpAffine(swapped_crop, inverse, (width, height), borderValue=0.0)
    local_mask = np.full((INSWAPPER_CROP_SIZE, INSWAPPER_CROP_SIZE), 255, dtype=np.uint8)
    local_mask[:3, :] = local_mask[-3:, :] = local_mask[:, :3] = local_mask[:, -3:] = 0
    mask = cv2.warpAffine(local_mask, inverse, (width, height), borderValue=0.0).astype(np.float32) / 255.0
    if mask_mode == "SAM local":
        if sam_runtime is not None:
            mask *= sam_runtime.mask(target, target_face)
        else:
            mask *= _sam_mask(target, target_face, sam_model, sam_device)
    kernel = max(3, int(feather) * 2 + 1)
    if kernel % 2 == 0:
        kernel += 1
    mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)
    mask = np.clip(mask, 0.0, 1.0)
    merged = warped.astype(np.float32) * mask[:, :, None] + target.astype(np.float32) * (1.0 - mask[:, :, None])
    return np.clip(merged, 0, 255).astype(np.uint8), mask


class ArchFaceIdentityPreflight:
    @classmethod
    def INPUT_TYPES(cls):
        try:
            sam_models = folder_paths.get_filename_list("sams")
        except KeyError:
            sam_models = ["sam_vit_b_01ec64.pth"]
        return {
            "required": {
                "identity_image": ("IMAGE", {"lazy": True}),
                "main_image": ("IMAGE",),
                "enabled": ("BOOLEAN", {"default": True}),
                "face_selection": (["largest", "highest_confidence"],),
                "source_face_index": ("INT", {"default": 0, "min": 0, "max": 15, "step": 1}),
                "face_threshold": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 0.99, "step": 0.01}),
                "mask_mode": (["SAM local", "Landmark feather"], {"default": "SAM local"}),
                "sam_model": (sam_models,),
            }
        }

    RETURN_TYPES = ("ARCH_FACE_IDENTITY", "IMAGE", "IMAGE", "STRING", "STRING", "ARCH_FACE_SELECTION")
    RETURN_NAMES = ("identity", "main_image", "face_preview", "status", "mask_mode", "face_selection")
    FUNCTION = "preflight"
    CATEGORY = "arch-image/identity"
    DESCRIPTION = "Validate local identity models and source face before expensive generation begins."

    def check_lazy_status(self, enabled=True, identity_image=None, **kwargs):
        return ["identity_image"] if enabled and identity_image is None else []

    def preflight(
        self,
        identity_image,
        main_image,
        enabled,
        face_selection,
        source_face_index,
        face_threshold,
        mask_mode="SAM local",
        sam_model="sam_vit_b_01ec64.pth",
    ):
        selection = dict(selection=str(face_selection), index=int(source_face_index), threshold=float(face_threshold))
        if not enabled:
            return None, main_image, main_image, "Identity finish disabled; preflight bypassed", str(mask_mode), selection
        paths = _model_paths(str(sam_model), require_sam=str(mask_mode) == "SAM local")
        source = _tensor_to_bgr(identity_image)
        faces = _detect_faces(source, float(face_threshold))
        face = _select_face(faces, str(face_selection), int(source_face_index))
        latent = _mapped_identity(source, face, paths["swapper"])
        area = float(face[2] * face[3]) / float(max(1, source.shape[0] * source.shape[1]))
        status = (
            f"Identity preflight passed: {len(faces)} face(s), selected index {int(source_face_index)}, "
            f"confidence {float(face[-1]):.3f}, area {area:.3%}"
        )
        return {"latent": latent}, main_image, _face_preview(source, face), status, str(mask_mode), selection


class ArchLocalFaceIdentityTransfer:
    @classmethod
    def INPUT_TYPES(cls):
        try:
            sam_models = folder_paths.get_filename_list("sams")
        except KeyError:
            sam_models = ["sam_vit_b_01ec64.pth"]
        return {
            "required": {
                "identity": ("ARCH_FACE_IDENTITY",),
                "target_image": ("IMAGE",),
                "enabled": ("BOOLEAN", {"default": True}),
                "target_face_selection": (["largest", "highest_confidence"],),
                "target_face_index": ("INT", {"default": 0, "min": 0, "max": 15, "step": 1}),
                "mask_mode": ("STRING", {"forceInput": True}),
                "sam_model": (sam_models,),
                "sam_device": (["Auto (unload models)", "CPU safe"], {"default": "Auto (unload models)"}),
                "face_threshold": ("FLOAT", {"default": 0.7, "min": 0.1, "max": 0.99, "step": 0.01}),
                "feather": ("INT", {"default": 12, "min": 2, "max": 64, "step": 1}),
                "iterations": ("INT", {"default": 2, "min": 1, "max": 3, "step": 1}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "ARCH_FACE_SELECTION")
    RETURN_NAMES = ("image", "face_mask", "status", "face_selection")
    FUNCTION = "transfer"
    CATEGORY = "arch-image/identity"
    DESCRIPTION = "Fully local 5-landmark affine identity transfer using ArcFace, INSwapper, and optional local SAM masking."

    def transfer(
        self,
        identity,
        target_image,
        enabled=True,
        target_face_selection="largest",
        target_face_index=0,
        mask_mode="SAM local",
        sam_model="sam_vit_b_01ec64.pth",
        sam_device="Auto (unload models)",
        face_threshold=0.7,
        feather=12,
        iterations=2,
    ):
        selection = dict(selection=str(target_face_selection), index=int(target_face_index), threshold=float(face_threshold))
        if not enabled:
            height, width = int(target_image.shape[1]), int(target_image.shape[2])
            return target_image, torch.zeros((1, height, width), dtype=torch.float32), "Identity transfer bypassed", selection
        mode = str(mask_mode)
        if mode not in {"SAM local", "Landmark feather"}:
            raise ValueError(f"Unknown identity mask mode: {mode}")
        passes = int(iterations)
        if passes < 1 or passes > 3:
            raise ValueError(f"Identity transfer iterations must be between 1 and 3; got {passes}.")
        result = _tensor_to_bgr(target_image)
        combined_mask = np.zeros(result.shape[:2], dtype=np.float32)
        sam_runtime = _SamRuntime(str(sam_model), str(sam_device)) if mode == "SAM local" else None
        try:
            for _ in range(passes):
                result, mask = _transfer(
                    identity,
                    result,
                    float(face_threshold),
                    str(target_face_selection),
                    int(target_face_index),
                    mode,
                    str(sam_model),
                    str(sam_device),
                    int(feather),
                    sam_runtime=sam_runtime,
                )
                combined_mask = np.maximum(combined_mask, mask)
        finally:
            if sam_runtime is not None:
                sam_runtime.close()
        return (
            _bgr_to_tensor(result),
            torch.from_numpy(combined_mask).unsqueeze(0),
            f"Local landmark identity transfer complete ({mask_mode}, {passes} pass{'es' if passes != 1 else ''})",
            selection,
        )


class ArchIdentityGate:
    @staticmethod
    def _blocked(message):
        from comfy_execution.graph_utils import ExecutionBlocker
        # Block only image consumers; allow the status preview and base save.
        return ExecutionBlocker(None), message

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "face_mask": ("MASK",),
                "transfer_enabled": ("BOOLEAN", {"default": True}),
                "enforce_threshold": ("BOOLEAN", {"default": True}),
                "require_reference_dominance": ("BOOLEAN", {"default": False}),
                "reference_detected": ("BOOLEAN",),
                "reference_same_identity": ("BOOLEAN",),
                "reference_similarity": ("FLOAT",),
                "base_similarity": ("FLOAT",),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "status")
    FUNCTION = "validate"
    CATEGORY = "arch-image/identity"
    DESCRIPTION = "Optionally block the final identity save when local scoring does not confirm the selected identity."

    def validate(
        self,
        image,
        face_mask,
        transfer_enabled,
        enforce_threshold,
        require_reference_dominance,
        reference_detected,
        reference_same_identity,
        reference_similarity,
        base_similarity,
    ):
        if not transfer_enabled:
            return image, "Identity transfer disabled; strict gate bypassed"
        if face_mask is None or face_mask.numel() == 0 or float(face_mask.max().item()) <= 0.0:
            return self._blocked("Identity gate blocked final save: no usable transferred-face mask.")
        score = float(reference_similarity)
        if enforce_threshold and (not reference_detected or not reference_same_identity):
            return self._blocked(
                f"Identity gate blocked final save: selected reference similarity {score:.6f} did not meet the configured threshold."
            )
        base_score = float(base_similarity)
        if enforce_threshold and require_reference_dominance and score <= base_score:
            return self._blocked(
                "Identity gate blocked final save: the result is closer to the base face "
                f"({base_score:.6f}) than the selected reference ({score:.6f})."
            )
        mode = "enforced" if enforce_threshold else "diagnostic only"
        comparison = f", base {base_score:.6f}"
        return image, f"Identity gate passed: reference {score:.6f}{comparison} ({mode})"
