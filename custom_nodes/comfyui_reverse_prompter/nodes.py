from __future__ import annotations

import json
from typing import Any

from .reverse_prompt import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    generate_prompt_from_data_url,
    image_tensor_to_data_url,
)


CATEGORY = "arch-prompt/reverse"


class ReversePrompter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "mode": (["detailed", "concise", "tags"], {"default": "detailed"}),
                "detail": (["high", "auto", "low"], {"default": "high"}),
                "model": ("STRING", {"default": DEFAULT_MODEL}),
                "endpoint": ("STRING", {"default": DEFAULT_ENDPOINT}),
                "api_key": ("STRING", {"default": "", "password": True}),
                "use_env_api_key": ("BOOLEAN", {"default": False}),
                "extra_context": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "fallback_on_error": ("BOOLEAN", {"default": True}),
                "timeout_seconds": ("INT", {"default": 90, "min": 5, "max": 300, "step": 5}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "metadata_json")
    FUNCTION = "reverse_prompt"
    CATEGORY = CATEGORY
    DESCRIPTION = "Turns an input image into a reusable image-generation prompt. Uses OpenAI when an API key is supplied, otherwise returns a local visual fallback prompt."

    def reverse_prompt(
        self,
        image,
        mode: str = "detailed",
        detail: str = "high",
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        api_key: str = "",
        use_env_api_key: bool = False,
        extra_context: str = "",
        fallback_on_error: bool = True,
        timeout_seconds: int = 90,
    ):
        image_data_url = image_tensor_to_data_url(image)
        result: dict[str, Any] = generate_prompt_from_data_url(
            image_data_url,
            api_key=api_key,
            model=model,
            endpoint=endpoint,
            detail=detail,
            mode=mode,
            extra_context=extra_context,
            timeout=timeout_seconds,
            fallback_on_error=bool(fallback_on_error),
            use_env_api_key=bool(use_env_api_key),
        )
        return (result["prompt"], json.dumps(result["metadata"], ensure_ascii=False))


NODE_CLASS_MAPPINGS = {
    "ReversePrompter": ReversePrompter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ReversePrompter": "arch-Reverse Prompter",
}
