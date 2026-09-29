"""Small local image-geometry safeguards used by Archon workflows."""

from __future__ import annotations


class ArchCanvasSize:
    """Choose a predictable Flux canvas without inheriting pathological ratios."""

    MODES = ("Auto (safe)", "1:1", "3:4", "2:3", "4:3", "3:2", "16:9")
    PRESETS = {
        "1:1": (1024, 1024, "1:1 square"),
        "3:4": (896, 1152, "3:4 portrait"),
        "2:3": (832, 1216, "2:3 portrait"),
        "4:3": (1152, 896, "4:3 landscape"),
        "3:2": (1216, 832, "3:2 landscape"),
        "16:9": (1344, 768, "16:9 landscape"),
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": (list(cls.MODES), {"default": "Auto (safe)"}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "STRING")
    RETURN_NAMES = ("width", "height", "canvas")
    FUNCTION = "select"
    CATEGORY = "arch-image/geometry"
    DESCRIPTION = (
        "Select a near-1MP Flux canvas. Safe Auto uses only portrait 3:4, "
        "square 1:1, or landscape 4:3 so extreme source ratios cannot leak "
        "into the output latent."
    )

    def select(self, image, mode):
        if len(image.shape) < 3:
            raise ValueError("ArchCanvasSize requires an IMAGE batch")
        height = int(image.shape[1])
        width = int(image.shape[2])
        if width <= 0 or height <= 0:
            raise ValueError("ArchCanvasSize requires positive width and height")

        if mode == "Auto (safe)":
            ratio = width / height
            if ratio < 0.80:
                mode = "3:4"
            elif ratio > 1.25:
                mode = "4:3"
            else:
                mode = "1:1"
        try:
            return self.PRESETS[mode]
        except KeyError as exc:
            raise ValueError(f"Unknown canvas mode: {mode}") from exc


class ArchRequireMask:
    """Fail clearly instead of silently treating an empty face mask as success."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mask": ("MASK",)}}

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "validate"
    CATEGORY = "arch-image/geometry"
    DESCRIPTION = "Stop execution when face detection/SAM produced no usable mask."

    def validate(self, mask):
        if mask is None or mask.numel() == 0 or float(mask.max().item()) <= 0.0:
            raise ValueError(
                "No usable face mask was detected. Check the target face, detector "
                "threshold, or selected face before saving an identity result."
            )
        return (mask,)
