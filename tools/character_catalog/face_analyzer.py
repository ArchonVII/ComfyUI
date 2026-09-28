"""Local multi-face analysis backed by the OpenCV models already shipped here."""

from __future__ import annotations

from pathlib import Path
from typing import Any


# Matches the proven defaults in comfyui_identity_score.
DEFAULT_FACE_SCORE_THRESHOLD = 0.7


class OpenCVFaceAnalyzer:
    """Detect every face and return normalized SFace vectors.

    Heavy libraries and model files are loaded only after a user starts a scan.
    """

    key = "opencv-yunet-2023mar-sface-2021dec-v1"

    def __init__(self, models_directory: Path):
        self.models_directory = Path(models_directory).resolve()
        self.detector_model = self.models_directory / "face_detection_yunet_2023mar.onnx"
        self.recognizer_model = self.models_directory / "face_recognition_sface_2021dec.onnx"
        self._detector = None
        self._recognizer = None

    def analyze(self, path: Path) -> list[dict[str, Any]]:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps

        missing = [
            str(model)
            for model in (self.detector_model, self.recognizer_model)
            if not model.is_file()
        ]
        if missing:
            raise FileNotFoundError("Missing local face model(s): " + ", ".join(missing))
        with Image.open(path) as image:
            rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB"), dtype=np.uint8)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        height, width = bgr.shape[:2]
        if self._detector is None:
            self._detector = cv2.FaceDetectorYN.create(
                str(self.detector_model), "", (width, height),
                DEFAULT_FACE_SCORE_THRESHOLD, 0.3, 5000
            )
        self._detector.setInputSize((width, height))
        _, detected = self._detector.detect(bgr)
        if detected is None:
            return []
        if self._recognizer is None:
            self._recognizer = cv2.FaceRecognizerSF.create(
                str(self.recognizer_model), ""
            )
        faces = []
        for row in detected:
            face = np.asarray(row, dtype=np.float32)
            aligned = self._recognizer.alignCrop(bgr, face)
            vector = np.asarray(
                self._recognizer.feature(aligned), dtype=np.float32
            ).reshape(-1)
            norm = float(np.linalg.norm(vector))
            if norm:
                vector = vector / norm
            faces.append(
                {
                    "vector": vector.tolist(),
                    "box": [int(round(float(value))) for value in face[:4]],
                    "confidence": float(face[-1]),
                    "image_size": [width, height],
                }
            )
        return faces
