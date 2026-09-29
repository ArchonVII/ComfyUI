"""Build the local Flux 9B identity-preserving multi-reference I2I workflow."""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EDITOR_DIR = Path("user/default/workflows/agent")
API_DIR = Path("user/default/api_workflows/agent")
EDITOR_NAME = "54 - Flux 9B Local Identity I2I.json"
API_NAME = "54 - Flux 9B Local Identity I2I API.json"
PLACEHOLDER = "arch_flux9b_placeholder.ppm"

KLEIN_MODEL = r"Flux\9b\DarkBeast-Klein9b-V2-BFS-FP8-ComfyUI.safetensors"
KLEIN_CLIP = r"Qwen\qwen_3_8b_fp8mixed.safetensors"
KLEIN_VAE = "full_encoder_small_decoder.safetensors"
LOOK_LORA = r"Flux\9b\Look\flux2Klein9BTrue_v20Bf16.safetensors"
SKIN_LORA = (
    r"Flux\9b\1 ------ Helper"
    r"\FLUX.2-klein-base-9B_LoRa_by-AI_Characters_CONCEPT_BetterSkin_v2_"
    r"TRIGGER$skin with textured detail$ with skin with textured detail.safetensors"
)

FRONTEND_ONLY_TYPES = {"MarkdownNote", "Note", "PreviewImage"}


@dataclass
class Graph:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    links: list[list[Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        node_type: str,
        *,
        title: str,
        pos: tuple[int, int],
        inputs: tuple[tuple[str, str, bool, bool], ...] = (),
        outputs: tuple[tuple[str, str], ...] = (),
        widgets: tuple[Any, ...] | list[Any] = (),
        size: tuple[int, int] = (310, 180),
        mode: int = 0,
    ) -> dict[str, Any]:
        node_id = len(self.nodes) + 1
        editor_inputs = []
        for name, value_type, widget, optional in inputs:
            item: dict[str, Any] = {"name": name, "type": value_type, "link": None}
            if widget:
                item["widget"] = {"name": name}
            if optional:
                item["shape"] = 7
            editor_inputs.append(item)
        editor_outputs = [
            {
                "name": name,
                "type": value_type,
                "slot_index": slot,
                "links": [],
            }
            for slot, (name, value_type) in enumerate(outputs)
        ]
        node = {
            "id": node_id,
            "type": node_type,
            "pos": list(pos),
            "size": list(size),
            "flags": {},
            "order": len(self.nodes),
            "mode": mode,
            "inputs": editor_inputs,
            "outputs": editor_outputs,
            "title": title,
            "properties": {"Node name for S&R": node_type},
            "widgets_values": list(widgets),
        }
        self.nodes.append(node)
        return node

    def connect(
        self,
        source: dict[str, Any],
        source_slot: int,
        target: dict[str, Any],
        target_input: str,
    ) -> None:
        matches = [
            index
            for index, item in enumerate(target["inputs"])
            if item["name"] == target_input
        ]
        if len(matches) != 1:
            raise ValueError(
                f"{target['type']} {target['id']} has no unique {target_input} input"
            )
        target_slot = matches[0]
        if target["inputs"][target_slot]["link"] is not None:
            raise ValueError(
                f"{target['type']} {target['id']}.{target_input} is already linked"
            )
        link_id = len(self.links) + 1
        value_type = source["outputs"][source_slot]["type"]
        self.links.append(
            [link_id, source["id"], source_slot, target["id"], target_slot, value_type]
        )
        source["outputs"][source_slot]["links"].append(link_id)
        target["inputs"][target_slot]["link"] = link_id

    def group(self, title: str, bounding: tuple[int, int, int, int]) -> None:
        self.groups.append(
            {
                "id": len(self.groups) + 1,
                "title": title,
                "bounding": list(bounding),
                "color": "#3f789e",
                "flags": {},
            }
        )

    def workflow(self) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "flux9b-local-identity-i2i:v3")),
            "revision": 0,
            "last_node_id": max(node["id"] for node in self.nodes),
            "last_link_id": max((link[0] for link in self.links), default=0),
            "nodes": self.nodes,
            "links": self.links,
            "groups": self.groups,
            "config": {},
            "extra": {
                "flux9b_local_identity_i2i": {
                    "version": 3,
                    "runtime": "http://127.0.0.1:8192",
                    "local_only": True,
                    "input_roles": ["main", "identity", "aux1", "aux2", "aux3"],
                    "canvas_source": "ArchCanvasSize",
                    "identity_finish": "Local ArcFace + INSwapper + SAM",
                }
            },
            "version": 0.4,
        }


def load_image(graph: Graph, title: str, pos: tuple[int, int]) -> dict[str, Any]:
    return graph.add(
        "LoadImage",
        title=title,
        pos=pos,
        inputs=(
            ("image", "COMBO", True, False),
            ("upload", "IMAGEUPLOAD", True, False),
        ),
        outputs=(("IMAGE", "IMAGE"), ("MASK", "MASK")),
        widgets=(PLACEHOLDER, "image"),
        size=(330, 330),
    )


def primitive_boolean(
    graph: Graph, title: str, pos: tuple[int, int], default: bool = False
) -> dict[str, Any]:
    return graph.add(
        "PrimitiveBoolean",
        title=title,
        pos=pos,
        inputs=(("value", "BOOLEAN", True, False),),
        outputs=(("BOOLEAN", "BOOLEAN"),),
        widgets=(default,),
        size=(300, 100),
    )


def lazy_switch(
    graph: Graph, title: str, pos: tuple[int, int], output_type: str = "*"
) -> dict[str, Any]:
    return graph.add(
        "ComfySwitchNode",
        title=title,
        pos=pos,
        inputs=(
            ("on_false", "*", False, False),
            ("on_true", "*", False, False),
            ("switch", "BOOLEAN", False, False),
        ),
        outputs=((output_type, output_type),),
        size=(320, 130),
    )


def scale_reference(graph: Graph, title: str, pos: tuple[int, int]) -> dict[str, Any]:
    return graph.add(
        "ImageScaleToTotalPixels",
        title=title,
        pos=pos,
        inputs=(
            ("image", "IMAGE", False, False),
            ("upscale_method", "COMBO", True, False),
            ("megapixels", "FLOAT", True, False),
            ("resolution_steps", "INT", True, False),
        ),
        outputs=(("IMAGE", "IMAGE"),),
        widgets=("lanczos", 1.0, 1),
        size=(310, 160),
    )


def vae_encode(graph: Graph, title: str, pos: tuple[int, int]) -> dict[str, Any]:
    return graph.add(
        "VAEEncode",
        title=title,
        pos=pos,
        inputs=(("pixels", "IMAGE", False, False), ("vae", "VAE", False, False)),
        outputs=(("LATENT", "LATENT"),),
    )


def reference_latent(graph: Graph, title: str, pos: tuple[int, int]) -> dict[str, Any]:
    return graph.add(
        "ReferenceLatent",
        title=title,
        pos=pos,
        inputs=(
            ("conditioning", "CONDITIONING", False, False),
            ("latent", "LATENT", False, False),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
    )


def preview(graph: Graph, title: str, pos: tuple[int, int]) -> dict[str, Any]:
    return graph.add(
        "PreviewImage",
        title=title,
        pos=pos,
        inputs=(("images", "IMAGE", False, False),),
        outputs=(("images", "IMAGE"),),
        size=(320, 260),
    )


def save(graph: Graph, title: str, prefix: str, pos: tuple[int, int]) -> dict[str, Any]:
    return graph.add(
        "SaveImage",
        title=title,
        pos=pos,
        inputs=(
            ("images", "IMAGE", False, False),
            ("filename_prefix", "STRING", True, False),
        ),
        outputs=(("images", "IMAGE"),),
        widgets=(prefix,),
        size=(320, 260),
    )


def build_editor() -> dict[str, Any]:
    graph = Graph()

    main = load_image(graph, "1 - Main I2I image (scene and composition)", (-1900, -420))
    identity = load_image(
        graph, "2 - Optional identity reference (clear face preferred)", (-1900, 0)
    )
    aux_loaders = [
        load_image(graph, f"{index + 2} - Auxiliary reference {index}", (-1900, 420 + 390 * (index - 1)))
        for index in range(1, 4)
    ]
    identity_enabled = primitive_boolean(
        graph,
        "Identity source selector - OFF uses main image; ON uses image 2",
        (-1510, -10),
    )
    identity_switch = lazy_switch(
        graph, "Select identity source lazily", (-1120, -100), output_type="*"
    )
    graph.connect(main, 0, identity_switch, "on_false")
    graph.connect(identity, 0, identity_switch, "on_true")
    graph.connect(identity_enabled, 0, identity_switch, "switch")

    identity_finish_enabled = primitive_boolean(
        graph, "Enable local identity finish", (-1120, 100), default=True
    )
    strict_identity_gate = primitive_boolean(
        graph, "Enforce identity threshold before final save", (-1120, 220), default=True
    )
    preflight = graph.add(
        "ArchFaceIdentityPreflight",
        title="Preflight identity face and required local model artifacts",
        pos=(-720, -420),
        inputs=(
            ("identity_image", "IMAGE", False, False),
            ("main_image", "IMAGE", False, False),
            ("enabled", "BOOLEAN", True, False),
            ("face_selection", "COMBO", True, False),
            ("source_face_index", "INT", True, False),
            ("face_threshold", "FLOAT", True, False),
            ("mask_mode", "COMBO", True, False),
            ("sam_model", "COMBO", True, False),
        ),
        outputs=(
            ("identity", "ARCH_FACE_IDENTITY"),
            ("main_image", "IMAGE"),
            ("face_preview", "IMAGE"),
            ("status", "STRING"),
            ("mask_mode", "STRING"),
        ),
        widgets=(True, "largest", 0, 0.7, "SAM local", "sam_vit_b_01ec64.pth"),
        size=(420, 340),
    )
    graph.connect(identity_switch, 0, preflight, "identity_image")
    graph.connect(main, 0, preflight, "main_image")
    graph.connect(identity_finish_enabled, 0, preflight, "enabled")

    canvas = graph.add(
        "ArchCanvasSize",
        title="Safe output canvas - independent from reference dimensions",
        pos=(-1510, -420),
        inputs=(("image", "IMAGE", False, False), ("mode", "COMBO", True, False)),
        outputs=(("width", "INT"), ("height", "INT"), ("canvas", "STRING")),
        widgets=("Auto (safe)",),
        size=(360, 150),
    )
    graph.connect(preflight, 1, canvas, "image")

    main_scale = scale_reference(
        graph, "Normalize main reference to 1MP without stretching", (-1510, -230)
    )
    graph.connect(preflight, 1, main_scale, "image")
    identity_preview = preview(
        graph, "Preview selected identity source", (-720, 20)
    )
    graph.connect(preflight, 2, identity_preview, "images")
    main_preview = preview(graph, "Preview normalized main reference", (-1120, -420))
    graph.connect(main_scale, 0, main_preview, "images")

    model = graph.add(
        "UNETLoader",
        title="Flux 9B DarkBeast diffusion model",
        pos=(-720, -940),
        inputs=(
            ("unet_name", "COMBO", True, False),
            ("weight_dtype", "COMBO", True, False),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(KLEIN_MODEL, "default"),
    )
    look_lora = graph.add(
        "LoraLoaderModelOnly",
        title="Existing Flux 9B look LoRA",
        pos=(-340, -940),
        inputs=(
            ("model", "MODEL", False, False),
            ("lora_name", "COMBO", True, False),
            ("strength_model", "FLOAT", True, False),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(LOOK_LORA, 0.49),
    )
    skin_lora = graph.add(
        "LoraLoaderModelOnly",
        title="Existing BetterSkin helper LoRA",
        pos=(40, -940),
        inputs=(
            ("model", "MODEL", False, False),
            ("lora_name", "COMBO", True, False),
            ("strength_model", "FLOAT", True, False),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(SKIN_LORA, 0.78),
    )
    clip = graph.add(
        "CLIPLoader",
        title="Flux 9B Qwen text encoder",
        pos=(-720, -720),
        inputs=(
            ("clip_name", "COMBO", True, False),
            ("type", "COMBO", True, False),
            ("device", "COMBO", True, True),
        ),
        outputs=(("CLIP", "CLIP"),),
        widgets=(KLEIN_CLIP, "flux2", "default"),
    )
    vae = graph.add(
        "VAELoader",
        title="Flux 9B compact encoder/decoder",
        pos=(-340, -720),
        inputs=(("vae_name", "COMBO", True, False),),
        outputs=(("VAE", "VAE"),),
        widgets=(KLEIN_VAE,),
    )
    graph.connect(model, 0, look_lora, "model")
    graph.connect(look_lora, 0, skin_lora, "model")

    positive = graph.add(
        "CLIPTextEncode",
        title="Edit instruction - image 1 is main; enabled extras are references",
        pos=(40, -700),
        inputs=(("clip", "CLIP", False, False), ("text", "STRING", True, False)),
        outputs=(("CONDITIONING", "CONDITIONING"),),
        widgets=((
            "Use image 1 as the main scene and composition. Apply the requested edit "
            "while preserving the same primary person's recognizable identity, facial "
            "structure, age, and natural proportions. Use only enabled additional "
            "images as visual references for clothing, pose, environment, style, or props."
        ),),
        size=(470, 260),
    )
    negative = graph.add(
        "ConditioningZeroOut",
        title="Flux unconditional conditioning",
        pos=(40, -390),
        inputs=(("conditioning", "CONDITIONING", False, False),),
        outputs=(("CONDITIONING", "CONDITIONING"),),
    )
    graph.connect(clip, 0, positive, "clip")
    graph.connect(positive, 0, negative, "conditioning")

    main_latent = vae_encode(graph, "Encode normalized main reference", (-720, -220))
    graph.connect(main_scale, 0, main_latent, "pixels")
    graph.connect(vae, 0, main_latent, "vae")
    pos_chain = reference_latent(graph, "Positive + main reference", (-340, -300))
    neg_chain = reference_latent(graph, "Negative + main reference", (-340, -100))
    graph.connect(positive, 0, pos_chain, "conditioning")
    graph.connect(negative, 0, neg_chain, "conditioning")
    graph.connect(main_latent, 0, pos_chain, "latent")
    graph.connect(main_latent, 0, neg_chain, "latent")

    for index, loader in enumerate(aux_loaders, start=1):
        y = 430 + (index - 1) * 390
        enabled = primitive_boolean(
            graph, f"Enable auxiliary reference {index}", (-1510, y)
        )
        scaled = scale_reference(
            graph, f"Normalize auxiliary reference {index} to 1MP", (-1120, y)
        )
        encoded = vae_encode(graph, f"Encode auxiliary reference {index}", (-730, y))
        pos_added = reference_latent(
            graph, f"Positive + auxiliary reference {index}", (-350, y - 70)
        )
        neg_added = reference_latent(
            graph, f"Negative + auxiliary reference {index}", (-350, y + 110)
        )
        pos_switch = lazy_switch(
            graph, f"Lazy positive auxiliary reference {index}", (40, y - 70), "CONDITIONING"
        )
        neg_switch = lazy_switch(
            graph, f"Lazy negative auxiliary reference {index}", (40, y + 110), "CONDITIONING"
        )
        graph.connect(loader, 0, scaled, "image")
        graph.connect(scaled, 0, encoded, "pixels")
        graph.connect(vae, 0, encoded, "vae")
        graph.connect(pos_chain, 0, pos_added, "conditioning")
        graph.connect(neg_chain, 0, neg_added, "conditioning")
        graph.connect(encoded, 0, pos_added, "latent")
        graph.connect(encoded, 0, neg_added, "latent")
        graph.connect(pos_chain, 0, pos_switch, "on_false")
        graph.connect(pos_added, 0, pos_switch, "on_true")
        graph.connect(enabled, 0, pos_switch, "switch")
        graph.connect(neg_chain, 0, neg_switch, "on_false")
        graph.connect(neg_added, 0, neg_switch, "on_true")
        graph.connect(enabled, 0, neg_switch, "switch")
        pos_chain = pos_switch
        neg_chain = neg_switch

    noise = graph.add(
        "RandomNoise",
        title="Generation seed",
        pos=(520, -620),
        inputs=(("noise_seed", "INT", True, False),),
        outputs=(("NOISE", "NOISE"),),
        widgets=(921621740546458, "randomize"),
    )
    sampler_select = graph.add(
        "KSamplerSelect",
        title="Euler sampler",
        pos=(520, -450),
        inputs=(("sampler_name", "COMBO", True, False),),
        outputs=(("SAMPLER", "SAMPLER"),),
        widgets=("euler",),
    )
    scheduler = graph.add(
        "Flux2Scheduler",
        title="Flux 9B four-step scheduler",
        pos=(520, -270),
        inputs=(
            ("steps", "INT", True, False),
            ("width", "INT", False, False),
            ("height", "INT", False, False),
        ),
        outputs=(("SIGMAS", "SIGMAS"),),
        widgets=(4,),
    )
    guider = graph.add(
        "CFGGuider",
        title="Flux guider",
        pos=(520, 0),
        inputs=(
            ("model", "MODEL", False, False),
            ("positive", "CONDITIONING", False, False),
            ("negative", "CONDITIONING", False, False),
            ("cfg", "FLOAT", True, False),
        ),
        outputs=(("GUIDER", "GUIDER"),),
        widgets=(1.0,),
    )
    empty = graph.add(
        "EmptyFlux2LatentImage",
        title="Output latent uses safe canvas, never source dimensions",
        pos=(520, 270),
        inputs=(
            ("width", "INT", False, False),
            ("height", "INT", False, False),
            ("batch_size", "INT", True, False),
        ),
        outputs=(("LATENT", "LATENT"),),
        widgets=(1,),
    )
    sampler = graph.add(
        "SamplerCustomAdvanced",
        title="Flux 9B local multi-reference sample",
        pos=(930, -260),
        inputs=(
            ("noise", "NOISE", False, False),
            ("guider", "GUIDER", False, False),
            ("sampler", "SAMPLER", False, False),
            ("sigmas", "SIGMAS", False, False),
            ("latent_image", "LATENT", False, False),
        ),
        outputs=(("output", "LATENT"), ("denoised_output", "LATENT")),
        size=(340, 250),
    )
    decode = graph.add(
        "VAEDecode",
        title="Decode base Flux result",
        pos=(1330, -180),
        inputs=(("samples", "LATENT", False, False), ("vae", "VAE", False, False)),
        outputs=(("IMAGE", "IMAGE"),),
    )
    graph.connect(canvas, 0, scheduler, "width")
    graph.connect(canvas, 1, scheduler, "height")
    graph.connect(canvas, 0, empty, "width")
    graph.connect(canvas, 1, empty, "height")
    graph.connect(noise, 0, sampler, "noise")
    graph.connect(sampler_select, 0, sampler, "sampler")
    graph.connect(scheduler, 0, sampler, "sigmas")
    graph.connect(skin_lora, 0, guider, "model")
    graph.connect(pos_chain, 0, guider, "positive")
    graph.connect(neg_chain, 0, guider, "negative")
    graph.connect(guider, 0, sampler, "guider")
    graph.connect(empty, 0, sampler, "latent_image")
    graph.connect(sampler, 0, decode, "samples")
    graph.connect(vae, 0, decode, "vae")

    base_save = save(graph, "Save base Flux result", "Flux9B-Local-I2I/base", (1680, -420))
    base_preview = preview(graph, "Preview base Flux result", (1680, -110))
    graph.connect(decode, 0, base_save, "images")
    graph.connect(decode, 0, base_preview, "images")

    identity_transfer = graph.add(
        "ArchLocalFaceIdentityTransfer",
        title="Local landmark-aligned identity transfer with SAM",
        pos=(2050, -430),
        inputs=(
            ("identity", "ARCH_FACE_IDENTITY", False, False),
            ("target_image", "IMAGE", False, False),
            ("enabled", "BOOLEAN", True, False),
            ("target_face_selection", "COMBO", True, False),
            ("target_face_index", "INT", True, False),
            ("mask_mode", "STRING", False, False),
            ("sam_model", "COMBO", True, False),
            ("sam_device", "COMBO", True, False),
            ("face_threshold", "FLOAT", True, False),
            ("feather", "INT", True, False),
            ("iterations", "INT", True, False),
        ),
        outputs=(
            ("image", "IMAGE"),
            ("face_mask", "MASK"),
            ("status", "STRING"),
        ),
        widgets=(
            True,
            "largest",
            0,
            "sam_vit_b_01ec64.pth",
            "Auto (unload models)",
            0.7,
            12,
            2,
        ),
        size=(430, 360),
    )
    graph.connect(preflight, 0, identity_transfer, "identity")
    graph.connect(preflight, 4, identity_transfer, "mask_mode")
    graph.connect(decode, 0, identity_transfer, "target_image")
    graph.connect(identity_finish_enabled, 0, identity_transfer, "enabled")

    mask_image = graph.add(
        "MaskToImage",
        title="Convert final SAM mask for preview",
        pos=(2900, 350),
        inputs=(("mask", "MASK", False, False),),
        outputs=(("IMAGE", "IMAGE"),),
    )
    mask_preview = preview(graph, "Preview final SAM identity mask", (3270, 350))
    graph.connect(identity_transfer, 1, mask_image, "mask")
    graph.connect(mask_image, 0, mask_preview, "images")

    score = graph.add(
        "DualIdentityScore",
        title="Visible local identity diagnostic - reference and base vs final",
        pos=(3620, 80),
        inputs=(
            ("base_image", "IMAGE", False, False),
            ("reference_image", "IMAGE", False, False),
            ("generated_image", "IMAGE", False, False),
            ("experiment_id", "STRING", False, True),
            ("run_id", "STRING", False, True),
            ("extra_metadata", "EXTRA_METADATA", False, True),
            ("experiment_mode", "COMBO", True, False),
            ("face_score_threshold", "FLOAT", True, False),
            ("same_identity_threshold", "FLOAT", True, False),
            ("face_selection", "COMBO", True, False),
            ("write_manifest", "BOOLEAN", True, False),
            ("manifest_dir", "STRING", True, False),
            ("run_label", "STRING", True, False),
            ("metadata_key", "STRING", True, False),
        ),
        outputs=(
            ("reference_cosine_similarity", "FLOAT"),
            ("reference_detected", "BOOLEAN"),
            ("reference_same_identity", "BOOLEAN"),
            ("base_cosine_similarity", "FLOAT"),
            ("base_detected", "BOOLEAN"),
            ("base_same_identity", "BOOLEAN"),
            ("generated_detected", "BOOLEAN"),
            ("active_cosine_similarity", "FLOAT"),
            ("active_same_identity", "BOOLEAN"),
            ("rankable", "BOOLEAN"),
            ("report_json", "STRING"),
            ("extra_metadata", "EXTRA_METADATA"),
        ),
        widgets=(
            "face_swap",
            0.7,
            0.363,
            "largest",
            True,
            "default/identity_score_runs",
            "flux9b-local-identity-i2i-dual",
            "identity_score_report",
        ),
        size=(420, 520),
    )
    graph.connect(decode, 0, score, "base_image")
    graph.connect(identity_switch, 0, score, "reference_image")
    graph.connect(identity_transfer, 0, score, "generated_image")

    gate = graph.add(
        "ArchIdentityGate",
        title="Optional strict identity gate before final save",
        pos=(2900, -260),
        inputs=(
            ("image", "IMAGE", False, False),
            ("face_mask", "MASK", False, False),
            ("transfer_enabled", "BOOLEAN", False, False),
            ("enforce_threshold", "BOOLEAN", False, False),
            ("require_reference_dominance", "BOOLEAN", False, False),
            ("reference_detected", "BOOLEAN", False, False),
            ("reference_same_identity", "BOOLEAN", False, False),
            ("reference_similarity", "FLOAT", False, False),
            ("base_similarity", "FLOAT", False, False),
        ),
        outputs=(("image", "IMAGE"), ("status", "STRING")),
        size=(420, 300),
    )
    graph.connect(identity_transfer, 0, gate, "image")
    graph.connect(identity_transfer, 1, gate, "face_mask")
    graph.connect(identity_finish_enabled, 0, gate, "transfer_enabled")
    graph.connect(strict_identity_gate, 0, gate, "enforce_threshold")
    graph.connect(identity_enabled, 0, gate, "require_reference_dominance")
    graph.connect(score, 1, gate, "reference_detected")
    graph.connect(score, 2, gate, "reference_same_identity")
    graph.connect(score, 0, gate, "reference_similarity")
    graph.connect(score, 3, gate, "base_similarity")

    final_preview = preview(graph, "Preview gated identity-preserved result", (3370, -260))
    final_save = save(
        graph,
        "Save identity-preserved result",
        "Flux9B-Local-I2I/identity-finished",
        (3740, -260),
    )
    graph.connect(gate, 0, final_preview, "images")
    graph.connect(gate, 0, final_save, "images")

    graph.add(
        "MarkdownNote",
        title="Local Flux 9B identity I2I usage",
        pos=(-1900, 1600),
        widgets=((
            "## Local identity-preserving Flux 9B I2I\n\n"
            "1. Replace image 1 with the main scene/reference.\n"
            "2. Leave the identity selector OFF to preserve image 1's face, or load "
            "image 2 and turn it ON.\n"
            "3. Enable identity finish to run preflight, transfer, and scoring. Disable "
            "it for a clean base-only passthrough.\n"
            "4. The strict identity gate defaults ON and blocks only the final identity "
            "save when the selected reference does not meet the local threshold. With "
            "image 2 selected, it also requires the result to be closer to image 2 than "
            "to the base Flux face.\n"
            "5. Source and target face index 0 select the largest face by default. "
            "Use the face previews and selection controls for multi-person images.\n"
            "6. Load and enable up to three optional visual references.\n"
            "7. Safe Auto prevents extreme input ratios from controlling the output; "
            "choose a manual canvas when composition requires it.\n"
            "8. ArcFace and INSwapper run on CPU to protect Flux VRAM. CUDA SAM first "
            "unloads ComfyUI-managed models; CPU SAM remains available as a safe fallback.\n\n"
            "The base Flux result always saves. The final identity result saves only after "
            "the configured gate passes. No image or face data leaves the machine."
        ),),
        size=(620, 430),
    )

    graph.group("Inputs and safe output canvas", (-1950, -500, 1260, 1960))
    graph.group("Flux 9B models and prompt", (-760, -1010, 1320, 930))
    graph.group("Optional reference conditioning", (-1160, 330, 1550, 1260))
    graph.group("Flux sampling", (470, -700, 1250, 1100))
    graph.group("Landmark + SAM identity transfer", (1980, -510, 960, 1100))
    graph.group("Local identity audit", (2880, -330, 900, 1100))
    return graph.workflow()


def api_from_editor(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Convert the executable editor graph to a queueable API prompt."""

    links = {link[0]: link for link in workflow["links"]}
    prompt: dict[str, dict[str, Any]] = {}
    for node in workflow["nodes"]:
        if node.get("mode", 0) != 0 or node["type"] in FRONTEND_ONLY_TYPES:
            continue
        widget_names = [
            item["name"] for item in node.get("inputs", []) if "widget" in item
        ]
        serialized_widgets = node.get("widgets_values", [])
        # RandomNoise stores the frontend-only seed control mode after the API
        # noise_seed value even though it is not an executable node input.
        if node["type"] == "RandomNoise" and len(serialized_widgets) == 2:
            serialized_widgets = serialized_widgets[:1]
        widget_values = dict(zip(widget_names, serialized_widgets, strict=True))
        inputs: dict[str, Any] = {}
        for item in node.get("inputs", []):
            if item.get("link") is not None:
                link = links[item["link"]]
                inputs[item["name"]] = [str(link[1]), link[2]]
            elif item["name"] in widget_values and item["name"] not in {
                "upload",
                "control_after_generate",
            }:
                inputs[item["name"]] = widget_values[item["name"]]
            elif "value" in item:
                inputs[item["name"]] = item["value"]
        prompt[str(node["id"])] = {"class_type": node["type"], "inputs": inputs}
    return prompt


def build_artifacts() -> dict[str, Any]:
    editor = build_editor()
    return {
        "editor_name": EDITOR_NAME,
        "api_name": API_NAME,
        "editor": editor,
        "api": api_from_editor(editor),
    }


def serialize(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def display_path(path: Path) -> str:
    """Show repo paths compactly while preserving external runtime paths."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def write_or_check(
    artifacts: dict[str, Any] | None = None,
    *,
    repo_root: Path = REPO_ROOT,
    check: bool = False,
) -> list[Path]:
    artifacts = build_artifacts() if artifacts is None else artifacts
    destinations = (
        (repo_root / EDITOR_DIR / artifacts["editor_name"], artifacts["editor"]),
        (repo_root / API_DIR / artifacts["api_name"], artifacts["api"]),
    )
    mismatches: list[Path] = []
    for path, value in destinations:
        expected = serialize(value)
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                mismatches.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8", newline="\n")
    return mismatches


def _runtime_files(
    artifacts: dict[str, Any], install_root: Path, source_root: Path
) -> tuple[tuple[Path, Path | str], ...]:
    package_source = source_root / "custom_nodes" / "comfyui_arch_image_tools"
    return (
        (
            install_root / "runtime" / "user" / "default" / "workflows" / "agent" / artifacts["editor_name"],
            serialize(artifacts["editor"]),
        ),
        (
            install_root / "runtime" / "user" / "default" / "api_workflows" / "agent" / artifacts["api_name"],
            serialize(artifacts["api"]),
        ),
        (install_root / "runtime" / "input" / PLACEHOLDER, source_root / "input" / PLACEHOLDER),
        (install_root / "custom_nodes" / "comfyui_arch_image_tools" / "__init__.py", package_source / "__init__.py"),
        (install_root / "custom_nodes" / "comfyui_arch_image_tools" / "canvas.py", package_source / "canvas.py"),
        (install_root / "custom_nodes" / "comfyui_arch_image_tools" / "face_identity.py", package_source / "face_identity.py"),
    )


def install_runtime(
    artifacts: dict[str, Any] | None = None,
    *,
    install_root: Path,
    source_root: Path = REPO_ROOT,
) -> None:
    artifacts = build_artifacts() if artifacts is None else artifacts
    for destination, source in _runtime_files(artifacts, Path(install_root), Path(source_root)):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, Path):
            shutil.copy2(source, destination)
        else:
            destination.write_text(source, encoding="utf-8", newline="\n")


def check_runtime(
    artifacts: dict[str, Any] | None = None,
    *,
    install_root: Path,
    source_root: Path = REPO_ROOT,
) -> list[Path]:
    artifacts = build_artifacts() if artifacts is None else artifacts
    mismatches: list[Path] = []
    for destination, source in _runtime_files(artifacts, Path(install_root), Path(source_root)):
        if not destination.is_file():
            mismatches.append(destination)
        elif isinstance(source, Path):
            if destination.read_bytes() != source.read_bytes():
                mismatches.append(destination)
        elif destination.read_text(encoding="utf-8") != source:
            mismatches.append(destination)
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when generated workflow artifacts are missing or stale",
    )
    parser.add_argument(
        "--install-root",
        type=Path,
        help="also install the generated workflow and node package into an isolated ComfyUI root",
    )
    parser.add_argument(
        "--check-install-root",
        type=Path,
        help="verify an isolated ComfyUI root matches the canonical generated artifacts",
    )
    args = parser.parse_args()
    artifacts = build_artifacts()
    mismatches = write_or_check(artifacts, check=args.check)
    if args.install_root:
        install_runtime(artifacts, install_root=args.install_root)
        print(f"installed runtime files into {args.install_root}")
    if args.check_install_root:
        mismatches.extend(
            check_runtime(artifacts, install_root=args.check_install_root)
        )
    if mismatches:
        for path in mismatches:
            print(f"stale or missing: {display_path(path)}")
        return 1
    action = "verified" if args.check else "wrote"
    print(f"{action} {EDITOR_NAME} and {API_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
