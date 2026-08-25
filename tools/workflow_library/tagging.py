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


# Model families. Matched against model filenames first, node types second,
# because a checkpoint name is the most reliable signal of what a graph is for.
# Patterns anchor at the start of a word but not the end: real checkpoint
# names carry version digits directly against the family name (flux1-dev,
# qwen2511, klein9b), so a trailing \b would never match them.
MODEL_RULES: tuple[Rule, ...] = (
    Rule("wan", r"\bwan[\s._-]?\d"),
    Rule("wan-2.2", r"wan[\s._-]?2[._]2"),
    Rule("ltxv", r"ltxv?[\s._-]?\d|ltx[\s._-]?video"),
    Rule("flux", r"\bflux"),
    Rule("qwen", r"\bqwen"),
    Rule("klein", r"\bklein"),
    Rule("krea", r"\bkrea"),
    Rule("z-image", r"\bz[\s._-]?image"),
    Rule("firered", r"\bfire[\s._-]?red"),
    Rule("sdxl", r"\bsdxl|\bxl[\s._-]?base"),
    Rule("quantized", r"\bq\d[\s._-]?k?[\s._-]?[ms]?\b|\bgguf\b|\bfp8\b|\bnf4\b"),
)

# Technique / capability, keyed off the node types present.
TECHNIQUE_RULES: tuple[Rule, ...] = (
    Rule("lora", r"lora", scope="node"),
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
)

# What the graph consumes and emits.
MODE_RULES: tuple[Rule, ...] = (
    Rule("video", r"videocombine|savewebm|savevideo|vhs_|createvideo", scope="node"),
    Rule("i2v", r"image[\s._-]?to[\s._-]?video|i2v|imagetovideo", scope="any"),
    Rule("t2v", r"text[\s._-]?to[\s._-]?video|\bt2v\b", scope="any"),
    Rule("i2i", r"\bi2i\b|image[\s._-]?to[\s._-]?image", scope="any"),
    Rule("img-input", r"loadimage", scope="node"),
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
