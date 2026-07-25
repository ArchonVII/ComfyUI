"""Arch prompt-builder custom-node registration."""

from .nodes import (
    ArchPtCamera,
    ArchPtClothing,
    ArchPtCombine,
    ArchPtEnvironment,
    ArchPtIdentity,
    ArchPtLighting,
    ArchPtPose,
)
from .routes import register_routes


NODE_CLASS_MAPPINGS = {
    "ArchPtIdentity": ArchPtIdentity,
    "ArchPtPose": ArchPtPose,
    "ArchPtClothing": ArchPtClothing,
    "ArchPtEnvironment": ArchPtEnvironment,
    "ArchPtCamera": ArchPtCamera,
    "ArchPtLighting": ArchPtLighting,
    "ArchPtCombine": ArchPtCombine,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ArchPtIdentity": "arch-pt-Identity",
    "ArchPtPose": "arch-pt-Pose",
    "ArchPtClothing": "arch-pt-Clothing",
    "ArchPtEnvironment": "arch-pt-Environment",
    "ArchPtCamera": "arch-pt-Camera",
    "ArchPtLighting": "arch-pt-Lighting",
    "ArchPtCombine": "arch-pt-Combine",
}


register_routes()
