"""Derive g-workflows tags from what a workflow actually contains.

Filenames in this library are unreliable -- numeric prefixes are save-as
artefacts, not identifiers -- so tags are inferred from node types and model
filenames instead. The rules below are deliberately plain data: add a row and
the whole library re-tags on the next run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from .workflow_scan import Workflow


@dataclass(frozen=True)
class Rule:
    """Emit *tag* when *pattern* matches any haystack of the given kind."""

    tag: str
    pattern: str
    scope: str = "any"  # "model", "node" or "any"

    def matches(self, models: str, nodes: str) -> bool:
        haystack = {"model": models, "node": nodes, "any": models + "\n" + nodes}[self.scope]
        return re.search(self.pattern, haystack, re.IGNORECASE) is not None


# Model families. Matched against model filenames only (scope="model"):
# node types recycle family words across models (FluxKontextImageScale is a
# stock resize in Qwen edit graphs; 61 non-flux workflows fired "flux" from it
# in the 2026-08 library audit), so a loaded file is the only reliable signal.
# Patterns anchor at the start of a word but not the end: real checkpoint
# names carry version digits directly against the family name (flux1-dev,
# qwen2511, klein9b), so a trailing \b would never match them.
MODEL_RULES: tuple[Rule, ...] = (
    Rule("wan", r"\bwan[\s._-]?\d", scope="model"),
    Rule("wan-2.2", r"wan[\s._-]?2[._]2", scope="model"),
    Rule("ltxv", r"ltxv?[\s._-]?\d|ltx[\s._-]?video", scope="model"),
    Rule("flux", r"\bflux", scope="model"),
    # Qwen the *image model* (qwen_image_vae, Qwen-Image-Edit-2509/2511,
    # Qwen_Snofs finetunes), not Qwen the text encoder: qwen_3_8b / qwen3_4b /
    # qwen2.5vl serve Klein, Z-Image and Stable Audio graphs, and matching them
    # tagged 84% of the library "qwen" in the 2026-08 audit.
    Rule("qwen", r"qwen[\s._-]?image|qwen[\s._-]?edit|qwen[\s._-]?25\d\d|qwen[\s._-]?snofs", scope="model"),
    Rule("klein", r"\bklein", scope="model"),
    Rule("krea", r"\bkrea", scope="model"),
    # The finetune ecosystem abbreviates Z-Image Turbo to ZIT ("Mystic-XXX-ZIT-V5",
    # "moodyPornMix_zitV10DPO"), so the long form alone misses those files.
    Rule("z-image", r"\bz[\s._-]?image|\bzit", scope="model"),
    Rule("firered", r"\bfire[\s._-]?red", scope="model"),
    Rule("sdxl", r"\bsdxl|\bxl[\s._-]?base", scope="model"),
    # "illu" is the community shorthand in lora names ("skin texture illu xl v5").
    Rule("illustrious", r"illustrious|\billu\b", scope="model"),
    # fp8 deliberately excluded: it is the default dtype in this library (74% of
    # workflows fired on it in the 2026-08 audit), so it separates nothing.
    Rule("quantized", r"\bq\d[\s._-]?k?[\s._-]?[ms]?\b|\bgguf\b|\bnf4\b", scope="model"),
)

# Technique / capability, keyed off the node types present. No "lora" rule:
# 87% of the library loads a lora somewhere (2026-08 audit), so the tag
# filtered nothing.
TECHNIQUE_RULES: tuple[Rule, ...] = (
    Rule("controlnet", r"controlnet", scope="node"),
    Rule("ipadapter", r"ipadapter|ip_adapter", scope="node"),
    Rule("pulid", r"pulid", scope="node"),
    Rule("reactor", r"reactor", scope="node"),
    Rule("faceswap", r"faceswap|face_swap|inswapper", scope="node"),
    Rule("upscale", r"upscale|esrgan", scope="node"),
    Rule("inpaint", r"inpaint", scope="node"),
    Rule("mask", r"\bmask\b", scope="node"),
    Rule("detailer", r"detailer", scope="node"),
    Rule("teacache", r"teacache|magcache", scope="node"),
    Rule("sageattention", r"sage[\s._-]?attention|patchsage", scope="node"),
    Rule("seedvr", r"seedvr", scope="node"),
)

# What the graph consumes and emits. No "img-input" rule: 86% of the library
# loads an image (2026-08 audit) -- i2i is this library's default mode, so
# neither tag separates anything.
MODE_RULES: tuple[Rule, ...] = (
    Rule("video", r"videocombine|savewebm|savevideo|vhs_|createvideo", scope="node"),
    Rule("audio", r"\baudio|audio\b|voxcpm|melband|mmaudio", scope="any"),
    Rule("i2v", r"image[\s._-]?to[\s._-]?video|i2v|imagetovideo", scope="any"),
    Rule("t2v", r"text[\s._-]?to[\s._-]?video|\bt2v\b", scope="any"),
    Rule("i2i", r"\bi2i\b|image[\s._-]?to[\s._-]?image", scope="any"),
)

# Our own packs, so a workflow can be found by the tooling it depends on.
LOCAL_PACK_TAGS: dict[str, str] = {
    "comfyui_arch_prompt_tools": "arch-pt",
    "comfyui-prompt-composer": "prompt-composer",
    "comfyui_prompt_library": "prompt-library",
    "comfyui_identity_score": "identity-score",
    "comfyui_smart_model_loader": "smart-loader",
    "comfyui_reverse_prompter": "reverse-prompter",
    "comfyui_civitai_ingestor": "civitai-ingestor",
    "comfyui_civitai_prompt_import": "civitai-prompt-import",
    "comfyui_random_reference_source": "random-reference",
    "comfyui_image_metadata_extension": "image-metadata",
    "comfyui_session_watchdog": "session-watchdog",
}

_ALL_RULES = MODEL_RULES + TECHNIQUE_RULES + MODE_RULES


def derive_tags(
    workflow: Workflow,
    *,
    packs: Iterable[str] = (),
    duplicate_key: str | None = None,
    unresolved: Sequence[str] = (),
) -> list[str]:
    """Return the sorted tag set for one workflow.

    ``duplicate_key`` adds a ``dup:<hash>`` tag shared by every workflow with
    the same graph shape, which is what makes the save-as-a-new-number families
    selectable in a browser that can filter by tag.
    """
    models_blob = "\n".join(workflow.models)
    nodes_blob = "\n".join(workflow.node_types)

    tags: set[str] = set()
    for rule in _ALL_RULES:
        if rule.matches(models_blob, nodes_blob):
            tags.add(rule.tag)

    for pack in packs:
        mapped = LOCAL_PACK_TAGS.get(pack)
        if mapped:
            tags.add(mapped)

    if workflow.fmt == "api":
        tags.add("api-format")
    if unresolved:
        tags.add("needs-review")
    if duplicate_key:
        tags.add(f"dup:{duplicate_key}")

    return sorted(tags)


def format_sidecar(tags: Sequence[str]) -> str:
    """g-workflows reads ``.tags.txt`` as one lowercased tag per line."""
    seen: set[str] = set()
    lines: list[str] = []
    for tag in tags:
        lowered = tag.strip().lower()
        if lowered and lowered not in seen:
            seen.add(lowered)
            lines.append(lowered)
    return "\n".join(lines) + ("\n" if lines else "")
