from __future__ import annotations

import json

from .prompt_store import PromptStore


CATEGORY = "arch-prompt/library"


def get_store() -> PromptStore:
    return PromptStore()


class PromptLibraryLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_name": (get_store().dropdown_names(),),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive", "negative", "metadata_json")
    FUNCTION = "load_prompt"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, prompt_name):
        return get_store().fingerprint()

    def load_prompt(self, prompt_name):
        record = get_store().get(prompt_name)
        return (
            record["positive"],
            record["negative"],
            json.dumps(record, ensure_ascii=False),
        )


class PromptLibrarySaver:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_name": ("STRING", {"default": "New prompt"}),
                "positive": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "negative": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "notes": ("STRING", {"default": "", "multiline": True, "dynamicPrompts": False}),
                "overwrite": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive", "negative")
    FUNCTION = "save_prompt"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def save_prompt(self, prompt_name, positive, negative="", notes="", overwrite=True):
        record = get_store().save(
            prompt_name,
            positive=positive,
            negative=negative,
            notes=notes,
            overwrite=bool(overwrite),
        )
        return (record["positive"], record["negative"])


NODE_CLASS_MAPPINGS = {
    "PromptLibraryLoader": PromptLibraryLoader,
    "PromptLibrarySaver": PromptLibrarySaver,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptLibraryLoader": "arch-Prompt Library",
    "PromptLibrarySaver": "arch-Save Prompt to Library",
}
