from .nodes import DualIdentityScore, NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS, OpenCVIdentityScore
from .routes import register_routes

WEB_DIRECTORY = "./web"

# This is a no-op in ordinary test/module imports; the ComfyUI server is discovered lazily.
register_routes()

__all__ = [
    "DualIdentityScore",
    "OpenCVIdentityScore",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
