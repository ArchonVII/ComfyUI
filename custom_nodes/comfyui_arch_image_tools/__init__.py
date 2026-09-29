"""Registration for local Arch image workflow safeguards."""

from .canvas import ArchCanvasSize, ArchRequireMask
from .face_identity import ArchFaceIdentityPreflight, ArchIdentityGate, ArchLocalFaceIdentityTransfer


NODE_CLASS_MAPPINGS = {
    "ArchCanvasSize": ArchCanvasSize,
    "ArchRequireMask": ArchRequireMask,
    "ArchLocalFaceIdentityTransfer": ArchLocalFaceIdentityTransfer,
    "ArchFaceIdentityPreflight": ArchFaceIdentityPreflight,
    "ArchIdentityGate": ArchIdentityGate,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ArchCanvasSize": "arch-image Safe Canvas Size",
    "ArchRequireMask": "arch-image Require Non-Empty Mask",
    "ArchLocalFaceIdentityTransfer": "arch-image Local Face Identity Transfer",
    "ArchFaceIdentityPreflight": "arch-image Face Identity Preflight",
    "ArchIdentityGate": "arch-image Identity Save Gate",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
