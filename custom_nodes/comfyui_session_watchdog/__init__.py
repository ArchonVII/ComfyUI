from .routes import register_routes
from .watchdog import install_logging_handler, install_lora_context_hooks


NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./web"

register_routes()
install_lora_context_hooks()
install_logging_handler()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
