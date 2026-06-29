"""Prompt Composer nodes.

Five nodes:
  * PromptComposerClothing     - per-region clothing slots + a "nude" toggle
  * PromptComposerBody         - per-aspect body/subject description slots
  * PromptComposerEnvironment  - per-aspect scene/environment slots
  * PromptComposerSnippets     - pick titled snippets from a saved library
  * PromptComposerCombine      - join several prompt strings into one

The three slot nodes share one engine (`_assemble_slots`); they differ only in
their field list (see fields.py).  Every node also emits a JSON string so the
structured form can be inspected or fed to anything that wants key/value pairs.

Nothing here depends on the JS frontend: each node produces correct output from
its raw widget values alone.  The frontend only adds convenience (preset
dropdowns, a snippet editor).  Run headless and it still works.
"""

import json

from .fields import BODY_SLOTS, CLOTHING_GARMENT_KEYS, CLOTHING_SLOTS, ENV_SLOTS
from . import store

CATEGORY = "arch-prompt/composer"


# --- string helpers -------------------------------------------------------
def _fragment(text):
    """Trim a slot value and strip stray surrounding commas/whitespace so we
    never emit a doubled ', ,' when slots are joined."""
    if not text:
        return ""
    return text.strip().strip(",").strip()


def _join(parts, separator=", "):
    out = []
    for part in parts:
        frag = _fragment(part)
        if frag:
            out.append(frag)
    return separator.join(out)


def _slot_input_types(slots):
    """Build a required-inputs dict (all multiline-off STRING widgets) from a
    [(key, label), ...] slot list."""
    required = {}
    for key, label in slots:
        required[key] = (
            "STRING",
            {"default": "", "multiline": False, "tooltip": label, "placeholder": label},
        )
    return required


def _assemble(values, slots, separator):
    """Return (prompt_string, ordered_dict) for a plain slot node."""
    ordered = {}
    parts = []
    for key, _label in slots:
        frag = _fragment(values.get(key, ""))
        if frag:
            ordered[key] = frag
            parts.append(frag)
    return separator.join(parts), ordered


# --- Clothing -------------------------------------------------------------
class PromptComposerClothing:
    @classmethod
    def INPUT_TYPES(cls):
        required = {
            # Toggle first so it reads as the master switch for the node.
            "nude": ("BOOLEAN", {"default": False, "label_on": "nude", "label_off": "clothed"}),
        }
        required.update(_slot_input_types(CLOTHING_SLOTS))
        # Text emitted in place of garments when `nude` is on.  Default chosen
        # as the most common SD descriptor; user-editable.
        required["nude_text"] = (
            "STRING",
            {"default": "nude", "multiline": False, "tooltip": "Used when 'nude' is on"},
        )
        required["separator"] = ("STRING", {"default": ", "})
        return {
            "required": required,
            "optional": {
                # Wire a previous node's prompt in here to chain inline.
                "prepend": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "prompt_json")
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, nude, nude_text, separator, prepend="", **slots):
        ordered = {}
        parts = []
        for key, _label in CLOTHING_SLOTS:
            # When nude, drop garment slots but keep accessories (hat, glasses,
            # socks...).  See CLOTHING_GARMENT_KEYS rationale in fields.py.
            if nude and key in CLOTHING_GARMENT_KEYS:
                continue
            frag = _fragment(slots.get(key, ""))
            if frag:
                ordered[key] = frag
                parts.append(frag)

        if nude:
            nude_frag = _fragment(nude_text) or "nude"
            # Lead with the nude descriptor, then any kept accessories.
            parts = [nude_frag] + parts
            ordered = {"state": nude_frag, **ordered}

        body = _join(parts, separator)
        prompt = _join([prepend, body], separator)
        return (prompt, json.dumps(ordered, ensure_ascii=False))


# --- Body -----------------------------------------------------------------
class PromptComposerBody:
    @classmethod
    def INPUT_TYPES(cls):
        required = _slot_input_types(BODY_SLOTS)
        required["separator"] = ("STRING", {"default": ", "})
        return {
            "required": required,
            "optional": {"prepend": ("STRING", {"forceInput": True})},
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "prompt_json")
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, separator, prepend="", **slots):
        body, ordered = _assemble(slots, BODY_SLOTS, separator)
        prompt = _join([prepend, body], separator)
        return (prompt, json.dumps(ordered, ensure_ascii=False))


# --- Environment ----------------------------------------------------------
class PromptComposerEnvironment:
    @classmethod
    def INPUT_TYPES(cls):
        required = _slot_input_types(ENV_SLOTS)
        required["separator"] = ("STRING", {"default": ", "})
        return {
            "required": required,
            "optional": {"prepend": ("STRING", {"forceInput": True})},
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "prompt_json")
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, separator, prepend="", **slots):
        body, ordered = _assemble(slots, ENV_SLOTS, separator)
        prompt = _join([prepend, body], separator)
        return (prompt, json.dumps(ordered, ensure_ascii=False))


# --- Snippets -------------------------------------------------------------
class PromptComposerSnippets:
    """Pick titled snippets from a saved library and chain the chosen ones.

    `library`  : name of a library in the data store (managed by the frontend).
    `selected` : JSON list of snippet titles, in the order to emit them.  The
                 frontend maintains this; you can also hand-edit it.
    Snippet *text* is resolved from the store at execution, so libraries behave
    like reusable server assets (similar to how LoRAs live on disk).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "library": ("STRING", {"default": "default"}),
                "selected": ("STRING", {"default": "[]", "multiline": False}),
                "separator": ("STRING", {"default": ", "}),
            },
            "optional": {"prepend": ("STRING", {"forceInput": True})},
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "prompt_json")
    FUNCTION = "build"
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, library, selected, separator, prepend=""):
        # The snippet text lives outside the graph (in the data store), so the
        # graph inputs can be identical while the library content changed.
        # Fold the resolved library into the change-signal so edits re-run.
        return json.dumps(store.get_library(library), sort_keys=True) + "|" + selected

    def build(self, library, selected, separator, prepend=""):
        lib = store.get_library(library)
        try:
            titles = json.loads(selected) if selected.strip() else []
            if not isinstance(titles, list):
                titles = []
        except (json.JSONDecodeError, AttributeError):
            titles = []

        ordered = {}
        parts = []
        for title in titles:
            if title in lib:
                frag = _fragment(lib[title])
                if frag:
                    ordered[title] = frag
                    parts.append(frag)

        body = _join(parts, separator)
        prompt = _join([prepend, body], separator)
        return (prompt, json.dumps(ordered, ensure_ascii=False))


# --- Combine --------------------------------------------------------------
class PromptComposerCombine:
    """Fan-in: join up to six prompt strings, optionally de-duplicating."""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            f"text_{i}": ("STRING", {"forceInput": True}) for i in range(1, 7)
        }
        return {
            "required": {
                "separator": ("STRING", {"default": ", "}),
                # Drop later fragments that exactly repeat an earlier one.
                "dedupe": ("BOOLEAN", {"default": True}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, separator, dedupe, **texts):
        # Preserve wiring order text_1..text_6.
        ordered = [texts.get(f"text_{i}", "") for i in range(1, 7)]
        frags = [_fragment(t) for t in ordered if _fragment(t)]
        if not dedupe:
            return (separator.join(frags),)
        # Dedupe at the comma-tag level: prompts are comma-separated tags, so
        # joining "a, b" with "b" should yield "a, b" -- not keep the repeat.
        seen = set()
        tokens = []
        for frag in frags:
            for token in frag.split(","):
                token = token.strip()
                if not token:
                    continue
                key = token.lower()
                if key not in seen:
                    seen.add(key)
                    tokens.append(token)
        return (separator.join(tokens),)


NODE_CLASS_MAPPINGS = {
    "PromptComposerClothing": PromptComposerClothing,
    "PromptComposerBody": PromptComposerBody,
    "PromptComposerEnvironment": PromptComposerEnvironment,
    "PromptComposerSnippets": PromptComposerSnippets,
    "PromptComposerCombine": PromptComposerCombine,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptComposerClothing": "arch-Clothing Prompt",
    "PromptComposerBody": "arch-Body Description",
    "PromptComposerEnvironment": "arch-Environment Prompt",
    "PromptComposerSnippets": "arch-Snippet Library",
    "PromptComposerCombine": "arch-Prompt Combine",
}
