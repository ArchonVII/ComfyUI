"""Prompt Composer - composable, saveable prompt-building nodes for ComfyUI."""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from . import store  # noqa: F401  (import registers the /prompt_composer routes)

# Any .js in ./web is loaded by the ComfyUI frontend as an extension.
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
