"""Local subject and environment Reference Library custom nodes."""

from .nodes import (
    ApplyReferenceProfileLoras,
    EnvironmentReferenceSelector,
    SubjectReferenceSelector,
)
from .routes import register_routes


NODE_CLASS_MAPPINGS = {
    "ArchSubjectReferenceSelector": SubjectReferenceSelector,
    "ArchEnvironmentReferenceSelector": EnvironmentReferenceSelector,
    "ArchApplyReferenceProfileLoras": ApplyReferenceProfileLoras,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ArchSubjectReferenceSelector": "arch-Subject Reference Selector",
    "ArchEnvironmentReferenceSelector": "arch-Environment Reference Selector",
    "ArchApplyReferenceProfileLoras": "arch-Apply Reference Profile LoRAs",
}

WEB_DIRECTORY = "./web"

register_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
