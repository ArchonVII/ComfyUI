"""Build the tracked adaptive LTX/Wan agent workflows from local editor graphs.

The source graphs are task artifacts from the main ComfyUI runtime. This builder
keeps their proven sampling topology, repairs sizing and loader defaults, and
emits deterministic editor-format JSON into the current worktree.
"""

from __future__ import annotations

import argparse
import copy
import json
import uuid
from pathlib import Path


LTX_NAMES = (
    "22 - HQ LTXV I2V - Fast Draft 97f.json",
    "23 - HQ LTXV I2V - Quality 121f.json",
    "24 - HQ LTXV I2V - Start End Guide 121f.json",
)
WAN_SOURCE = "wan-2-2-gguf-image-to-video.json"
WAN_SPECS = (
    ("25 - HQ Wan 2.2 I2V - Fast Draft 81f.json", 0.40, True, False),
    ("26 - HQ Wan 2.2 I2V - Quality 81f.json", 0.60, False, False),
    ("27 - HQ Wan 2.2 I2V - Start End Guide 81f.json", 0.60, False, True),
)

HIGH_GGUF = "Wan\\Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"
LOW_GGUF = "Wan\\Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf"
HIGH_LORA = "Wan\\wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors"
LOW_LORA = "Wan\\wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def node(workflow: dict, node_type: str, title_contains: str | None = None) -> dict:
    matches = [item for item in workflow["nodes"] if item["type"] == node_type]
    if title_contains:
        needle = title_contains.lower()
        matches = [item for item in matches if needle in item.get("title", "").lower()]
    if len(matches) != 1:
        raise ValueError(f"expected one {node_type}/{title_contains}, found {len(matches)}")
    return matches[0]


def nodes(workflow: dict, node_type: str) -> list[dict]:
    return [item for item in workflow["nodes"] if item["type"] == node_type]


def input_index(item: dict, name: str) -> int:
    for index, entry in enumerate(item.get("inputs", [])):
        if entry["name"] == name:
            return index
    raise ValueError(f"{item['type']} node {item['id']} has no {name} input")


def clear_links(item: dict) -> None:
    for entry in item.get("inputs", []):
        entry["link"] = None
    for entry in item.get("outputs", []):
        entry["links"] = []


def clone_node(workflow: dict, exemplar: dict, *, title: str, pos: list[float], widgets: list) -> dict:
    item = copy.deepcopy(exemplar)
    item["id"] = max(existing["id"] for existing in workflow["nodes"]) + 1
    item["title"] = title
    item["pos"] = pos
    item["widgets_values"] = widgets
    item["order"] = len(workflow["nodes"])
    item["mode"] = 0
    clear_links(item)
    workflow["nodes"].append(item)
    return item


def remove_link_to(workflow: dict, target: dict, target_slot: int) -> None:
    workflow["links"] = [
        link for link in workflow["links"] if not (link[3] == target["id"] and link[4] == target_slot)
    ]
    target["inputs"][target_slot]["link"] = None


def connect(workflow: dict, source: dict, source_slot: int, target: dict, target_name: str, value_type: str) -> None:
    target_slot = input_index(target, target_name)
    remove_link_to(workflow, target, target_slot)
    link_id = max((link[0] for link in workflow["links"]), default=0) + 1
    workflow["links"].append([link_id, source["id"], source_slot, target["id"], target_slot, value_type])
    target["inputs"][target_slot]["link"] = link_id
    output = source["outputs"][source_slot]
    output["links"] = list(output.get("links") or []) + [link_id]


def rebuild_links(workflow: dict) -> None:
    by_id = {item["id"]: item for item in workflow["nodes"]}
    valid = []
    for item in workflow["nodes"]:
        for entry in item.get("inputs", []):
            entry["link"] = None
        for entry in item.get("outputs", []):
            entry["links"] = []
    for link in workflow["links"]:
        _, source_id, source_slot, target_id, target_slot, _ = link
        if source_id not in by_id or target_id not in by_id:
            continue
        source = by_id[source_id]
        target = by_id[target_id]
        if source_slot >= len(source.get("outputs", [])) or target_slot >= len(target.get("inputs", [])):
            continue
        source["outputs"][source_slot]["links"].append(link[0])
        target["inputs"][target_slot]["link"] = link[0]
        valid.append(link)
    workflow["links"] = valid
    workflow["last_node_id"] = max(item["id"] for item in workflow["nodes"])
    workflow["last_link_id"] = max((link[0] for link in workflow["links"]), default=0)
    for order, item in enumerate(sorted(workflow["nodes"], key=lambda current: current.get("order", 0))):
        item["order"] = order


def image_scale_node(workflow: dict, *, title: str, pos: list[float]) -> dict:
    item = {
        "id": max(existing["id"] for existing in workflow["nodes"]) + 1,
        "type": "ImageScale",
        "pos": pos,
        "size": [300, 150],
        "flags": {},
        "order": len(workflow["nodes"]),
        "mode": 0,
        "inputs": [
            {"localized_name": "image", "name": "image", "type": "IMAGE", "link": None},
            {"localized_name": "upscale_method", "name": "upscale_method", "type": "COMBO", "widget": {"name": "upscale_method"}, "link": None},
            {"localized_name": "width", "name": "width", "type": "INT", "widget": {"name": "width"}, "link": None},
            {"localized_name": "height", "name": "height", "type": "INT", "widget": {"name": "height"}, "link": None},
            {"localized_name": "crop", "name": "crop", "type": "COMBO", "widget": {"name": "crop"}, "link": None},
        ],
        "outputs": [{"localized_name": "IMAGE", "name": "IMAGE", "type": "IMAGE", "slot_index": 0, "links": []}],
        "title": title,
        "properties": {"cnr_id": "comfy-core", "ver": "0.26.0", "Node name for S&R": "ImageScale"},
        "widgets_values": ["lanczos", 832, 480, "disabled"],
        "color": "#233",
        "bgcolor": "#355",
    }
    workflow["nodes"].append(item)
    return item


def model_extension_node(
    workflow: dict,
    *,
    node_type: str,
    title: str,
    pos: list[float],
    inputs: list[tuple[str, str, bool]],
    widgets: list,
) -> dict:
    item_inputs = []
    for name, value_type, is_widget in inputs:
        entry = {"name": name, "type": value_type, "link": None}
        if is_widget:
            entry["widget"] = {"name": name}
        item_inputs.append(entry)
    item = {
        "id": max(existing["id"] for existing in workflow["nodes"]) + 1,
        "type": node_type,
        "pos": pos,
        "size": [330, 180],
        "flags": {},
        "order": len(workflow["nodes"]),
        "mode": 4,
        "inputs": item_inputs,
        "outputs": [{"name": "MODEL", "type": "MODEL", "slot_index": 0, "links": []}],
        "title": title,
        "properties": {"Node name for S&R": node_type},
        "widgets_values": widgets,
        "color": "#432",
        "bgcolor": "#653",
    }
    workflow["nodes"].append(item)
    return item


def add_wan_quality_extensions(
    workflow: dict,
    *,
    conditioning: dict,
    source: dict,
    sampler: dict,
    lane: str,
    pos: list[float],
) -> None:
    """Insert live-installed modern Wan controls, bypassed by default.

    They form a single MODEL chain so any subset can be enabled without
    rewiring. Latent-aware techniques use the exact I2V latent produced by the
    conditioning node, and NAG uses its negative conditioning output.
    """
    cache = model_extension_node(
        workflow,
        node_type="EasyCache",
        title=f"OPT-IN {lane}: EasyCache acceleration",
        pos=pos,
        inputs=[
            ("model", "MODEL", False),
            ("reuse_threshold", "FLOAT", True),
            ("start_percent", "FLOAT", True),
            ("end_percent", "FLOAT", True),
            ("verbose", "BOOLEAN", True),
        ],
        widgets=[0.20, 0.15, 0.95, False],
    )
    enhance = model_extension_node(
        workflow,
        node_type="WanVideoEnhanceAVideoKJ",
        title=f"OPT-IN {lane}: Enhance-A-Video",
        pos=[pos[0] + 370, pos[1]],
        inputs=[("model", "MODEL", False), ("latent", "LATENT", False), ("weight", "FLOAT", True)],
        widgets=[2.0],
    )
    riflex = model_extension_node(
        workflow,
        node_type="ApplyRifleXRoPE_WanVideo",
        title=f"OPT-IN {lane}: RIFLEx long-video RoPE",
        pos=[pos[0] + 740, pos[1]],
        inputs=[("model", "MODEL", False), ("latent", "LATENT", False), ("k", "INT", True)],
        widgets=[6],
    )
    nag = model_extension_node(
        workflow,
        node_type="WanVideoNAG",
        title=f"OPT-IN {lane}: NAG guidance",
        pos=[pos[0] + 1110, pos[1]],
        inputs=[
            ("model", "MODEL", False),
            ("conditioning", "CONDITIONING", False),
            ("nag_scale", "FLOAT", True),
            ("nag_alpha", "FLOAT", True),
            ("nag_tau", "FLOAT", True),
            ("input_type", "COMBO", True),
            ("inplace", "BOOLEAN", True),
        ],
        widgets=[11.0, 0.25, 2.5, "default", False],
    )
    connect(workflow, source, 0, cache, "model", "MODEL")
    connect(workflow, cache, 0, enhance, "model", "MODEL")
    connect(workflow, conditioning, 2, enhance, "latent", "LATENT")
    connect(workflow, enhance, 0, riflex, "model", "MODEL")
    connect(workflow, conditioning, 2, riflex, "latent", "LATENT")
    connect(workflow, riflex, 0, nag, "model", "MODEL")
    connect(workflow, conditioning, 1, nag, "conditioning", "CONDITIONING")
    connect(workflow, nag, 0, sampler, "model", "MODEL")


def adaptive_nodes(workflow: dict, scale_exemplar: dict, size_exemplar: dict, megapixels: float) -> tuple[dict, dict, dict]:
    source = node(workflow, "LoadImage", "start frame")
    source["title"] = "Image 1 - start frame"
    source["widgets_values"] = ["example.png", "image"]
    scale = clone_node(
        workflow,
        scale_exemplar,
        title=f"Preserve aspect at {megapixels:.2f} MP",
        pos=[source["pos"][0] + 390, source["pos"][1]],
        widgets=["lanczos", megapixels, 32],
    )
    dimensions = clone_node(
        workflow,
        size_exemplar,
        title="Drive latent from scaled source",
        pos=[source["pos"][0] + 760, source["pos"][1]],
        widgets=[],
    )
    connect(workflow, source, 0, scale, "image", "IMAGE")
    connect(workflow, scale, 0, dimensions, "image", "IMAGE")
    return source, scale, dimensions


def update_note(workflow: dict, text: str, title: str) -> None:
    notes = nodes(workflow, "MarkdownNote")
    if notes:
        notes[0]["title"] = title
        notes[0]["widgets_values"] = [text]


def build_ltx(source_root: Path, output_root: Path, adaptive_exemplars: tuple[dict, dict]) -> None:
    source_dir = source_root / "user/default/workflows/agent"
    specs = {
        LTX_NAMES[0]: (0.40, 97, 12, 0.88, "agent/hq/ltxv-i2v-adaptive-fast-97f"),
        LTX_NAMES[1]: (0.55, 121, 24, 0.82, "agent/hq/ltxv-i2v-adaptive-quality-121f"),
        LTX_NAMES[2]: (0.55, 121, 26, 0.80, "agent/hq/ltxv-i2v-adaptive-start-end-121f"),
    }
    scale_exemplar, size_exemplar = adaptive_exemplars
    for name, (megapixels, frames, steps, strength, prefix) in specs.items():
        workflow = load_json(source_dir / name)
        workflow["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"adaptive-video:{name}"))
        _, scale, dimensions = adaptive_nodes(workflow, scale_exemplar, size_exemplar, megapixels)
        conditioning = node(workflow, "LTXVImgToVideo")
        conditioning["widgets_values"] = [832, 480, frames, 1, strength]
        preprocess = node(workflow, "LTXVPreprocess", "start")
        connect(workflow, scale, 0, preprocess, "image", "IMAGE")
        connect(workflow, dimensions, 0, conditioning, "width", "INT")
        connect(workflow, dimensions, 1, conditioning, "height", "INT")
        clip = node(workflow, "CLIPLoader")
        clip["widgets_values"] = ["t5xxl_fp8_e4m3fn_scaled.safetensors", "ltxv", "default"]
        scheduler = node(workflow, "LTXVScheduler")
        scheduler["widgets_values"][0] = steps
        save = node(workflow, "SaveVideo")
        save["widgets_values"] = [prefix, "mp4", "h264"]
        if "Start End" in name:
            end = node(workflow, "LoadImage", "end frame")
            end["title"] = "Image 2 - end frame guide"
            end["widgets_values"] = ["example.png", "image"]
            end_pre = node(workflow, "LTXVPreprocess", "end")
            end_scale = image_scale_node(workflow, title="Match end frame to image 1", pos=[end["pos"][0] + 370, end["pos"][1]])
            connect(workflow, end, 0, end_scale, "image", "IMAGE")
            connect(workflow, dimensions, 0, end_scale, "width", "INT")
            connect(workflow, dimensions, 1, end_scale, "height", "INT")
            connect(workflow, end_scale, 0, end_pre, "image", "IMAGE")
        update_note(
            workflow,
            f"## Adaptive LTXV I2V\n\nThe source image is scaled to {megapixels:.2f} megapixels while preserving its aspect ratio and rounding both dimensions to a multiple of 32. The derived width and height drive the LTX latent, so portrait, landscape, and square inputs no longer inherit a hard-coded shape.\n\nDefaults: {frames} frames (8n+1), 24 fps, {steps} steps, I2V strength {strength:.2f}. Use the 0.40 MP workflow for drafts and 0.55 MP for the 16 GB quality path. The installed LTX 0.9.8 model remains in use; LTX 2.3 requires a separate 32 GB+/100 GB model migration.",
            "Adaptive LTXV image-to-video",
        )
        rebuild_links(workflow)
        (output_root / name).write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")


def replace_wan_conditioning_with_first_last(workflow: dict) -> dict:
    conditioning = node(workflow, "WanImageToVideo")
    incoming = {}
    for link in workflow["links"]:
        if link[3] == conditioning["id"]:
            target_name = conditioning["inputs"][link[4]]["name"]
            incoming[target_name] = (link[1], link[2], link[5])
    workflow["links"] = [link for link in workflow["links"] if link[3] != conditioning["id"]]
    conditioning["type"] = "WanFirstLastFrameToVideo"
    conditioning["title"] = "Build Wan first/last-frame conditioning"
    conditioning["properties"]["Node name for S&R"] = "WanFirstLastFrameToVideo"
    conditioning["inputs"] = [
        {"name": "positive", "type": "CONDITIONING", "link": None},
        {"name": "negative", "type": "CONDITIONING", "link": None},
        {"name": "vae", "type": "VAE", "link": None},
        {"name": "width", "type": "INT", "widget": {"name": "width"}, "link": None},
        {"name": "height", "type": "INT", "widget": {"name": "height"}, "link": None},
        {"name": "length", "type": "INT", "widget": {"name": "length"}, "link": None},
        {"name": "batch_size", "type": "INT", "widget": {"name": "batch_size"}, "link": None},
        {"name": "clip_vision_start_image", "shape": 7, "type": "CLIP_VISION_OUTPUT", "link": None},
        {"name": "clip_vision_end_image", "shape": 7, "type": "CLIP_VISION_OUTPUT", "link": None},
        {"name": "start_image", "shape": 7, "type": "IMAGE", "link": None},
        {"name": "end_image", "shape": 7, "type": "IMAGE", "link": None},
    ]
    by_id = {item["id"]: item for item in workflow["nodes"]}
    for name in ("positive", "negative", "vae"):
        source_id, source_slot, value_type = incoming[name]
        connect(workflow, by_id[source_id], source_slot, conditioning, name, value_type)
    return conditioning


def replace_wan_outputs(workflow: dict, ltx_exemplars: dict[str, dict], prefix: str) -> None:
    remove_ids = {item["id"] for item in workflow["nodes"] if item["type"] in {"VAEDecode", "SaveWEBM", "SaveAnimatedWEBP"}}
    workflow["nodes"] = [item for item in workflow["nodes"] if item["id"] not in remove_ids]
    workflow["links"] = [link for link in workflow["links"] if link[1] not in remove_ids and link[3] not in remove_ids]
    low_sampler = node(workflow, "KSamplerAdvanced", "low-noise")
    vae = node(workflow, "VAELoader")
    decode = clone_node(workflow, ltx_exemplars["VAEDecodeTiled"], title="Tiled temporal decode", pos=[1900, -200], widgets=[512, 64, 24, 8])
    create = clone_node(workflow, ltx_exemplars["CreateVideo"], title="Create 24 fps MP4", pos=[2280, -200], widgets=[24, 8])
    save = clone_node(workflow, ltx_exemplars["SaveVideo"], title="Save MP4 result", pos=[2640, -200], widgets=[prefix, "mp4", "h264"])
    connect(workflow, low_sampler, 0, decode, "samples", "LATENT")
    connect(workflow, vae, 0, decode, "vae", "VAE")
    connect(workflow, decode, 0, create, "images", "IMAGE")
    connect(workflow, create, 0, save, "video", "VIDEO")


def add_draft_loras(workflow: dict, lora_exemplar: dict) -> None:
    for noise, lora_name in (("high-noise", HIGH_LORA), ("low-noise", LOW_LORA)):
        sampling = node(workflow, "ModelSamplingSD3", noise.split("-")[0])
        sampler = node(workflow, "KSamplerAdvanced", noise)
        lora = clone_node(
            workflow,
            lora_exemplar,
            title=f"Paired {noise} 4-step LoRA",
            pos=[sampling["pos"][0] + 320, sampling["pos"][1]],
            widgets=[lora_name, 1.0],
        )
        connect(workflow, sampling, 0, lora, "model", "MODEL")
        connect(workflow, lora, 0, sampler, "model", "MODEL")


def build_wan(source_root: Path, output_root: Path, adaptive_exemplars: tuple[dict, dict], ltx_exemplars: dict[str, dict], lora_exemplar: dict) -> None:
    source_path = source_root / "user/default/workflows/agent" / WAN_SOURCE
    scale_exemplar, size_exemplar = adaptive_exemplars
    for name, megapixels, accelerated, start_end in WAN_SPECS:
        workflow = load_json(source_path)
        workflow["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"adaptive-video:{name}"))
        _, scale, dimensions = adaptive_nodes(workflow, scale_exemplar, size_exemplar, megapixels)
        conditioning = replace_wan_conditioning_with_first_last(workflow) if start_end else node(workflow, "WanImageToVideo")
        conditioning["widgets_values"] = [832, 480, 81, 1]
        connect(workflow, dimensions, 0, conditioning, "width", "INT")
        connect(workflow, dimensions, 1, conditioning, "height", "INT")
        connect(workflow, scale, 0, conditioning, "start_image", "IMAGE")
        loaders = nodes(workflow, "UnetLoaderGGUF")
        loaders.sort(key=lambda item: 0 if "high-noise" in item.get("title", "").lower() else 1)
        loaders[0]["widgets_values"] = [HIGH_GGUF]
        loaders[1]["widgets_values"] = [LOW_GGUF]
        node(workflow, "CLIPLoader")["widgets_values"] = ["umt5_xxl_fp8_e4m3fn_scaled.safetensors", "wan", "default"]
        node(workflow, "VAELoader")["widgets_values"] = ["wan_2.1_vae.safetensors"]
        high_sampling = node(workflow, "ModelSamplingSD3", "high")
        low_sampling = node(workflow, "ModelSamplingSD3", "low")
        shift = 5 if accelerated else 8
        high_sampling["widgets_values"] = [shift]
        low_sampling["widgets_values"] = [shift]
        high_sampler = node(workflow, "KSamplerAdvanced", "high-noise")
        low_sampler = node(workflow, "KSamplerAdvanced", "low-noise")
        if accelerated:
            high_sampler["widgets_values"] = ["enable", 283090201, "fixed", 4, 1.0, "euler", "simple", 0, 2, "enable"]
            low_sampler["widgets_values"] = ["disable", 0, "fixed", 4, 1.0, "euler", "simple", 2, 4, "disable"]
            add_draft_loras(workflow, lora_exemplar)
        else:
            high_sampler["widgets_values"] = ["enable", 283090201, "fixed", 40, 3.5, "euler", "simple", 0, 20, "enable"]
            low_sampler["widgets_values"] = ["disable", 0, "fixed", 40, 3.5, "euler", "simple", 20, 40, "disable"]
        high_model_source = node(workflow, "LoraLoaderModelOnly", "high-noise") if accelerated else high_sampling
        low_model_source = node(workflow, "LoraLoaderModelOnly", "low-noise") if accelerated else low_sampling
        add_wan_quality_extensions(
            workflow,
            conditioning=conditioning,
            source=high_model_source,
            sampler=high_sampler,
            lane="high-noise",
            pos=[high_sampler["pos"][0] - 1480, high_sampler["pos"][1] - 360],
        )
        add_wan_quality_extensions(
            workflow,
            conditioning=conditioning,
            source=low_model_source,
            sampler=low_sampler,
            lane="low-noise",
            pos=[low_sampler["pos"][0] - 1480, low_sampler["pos"][1] + 360],
        )
        if start_end:
            start = node(workflow, "LoadImage", "start frame")
            end = clone_node(workflow, start, title="Image 2 - end frame guide", pos=[start["pos"][0], start["pos"][1] + 430], widgets=["example.png", "image"])
            end_scale = image_scale_node(workflow, title="Match end frame to image 1", pos=[end["pos"][0] + 390, end["pos"][1]])
            connect(workflow, end, 0, end_scale, "image", "IMAGE")
            connect(workflow, dimensions, 0, end_scale, "width", "INT")
            connect(workflow, dimensions, 1, end_scale, "height", "INT")
            connect(workflow, end_scale, 0, conditioning, "end_image", "IMAGE")
        prefix_slug = "fast-draft" if accelerated else ("start-end" if start_end else "quality")
        replace_wan_outputs(workflow, ltx_exemplars, f"agent/hq/wan22-i2v-adaptive-{prefix_slug}-81f")
        update_note(
            workflow,
            f"## Adaptive Wan 2.2 I2V\n\nImage 1 is scaled to {megapixels:.2f} megapixels while preserving its aspect ratio; width and height are rounded to a multiple of 32 and wired into Wan conditioning. This follows the official Wan I2V area policy instead of forcing landscape or portrait dimensions.\n\n{'Fast path: paired high/low LightX2V rank-64 LoRAs, 4 total steps, split at step 2, shift 5, CFG 1.' if accelerated else 'Quality path: installed Q4_K_M high/low GGUF experts, 40 total steps, split at step 20, shift 8, CFG 3.5.'}\n\nModern opt-ins are present in both expert lanes and bypassed by default: EasyCache for step reuse, Enhance-A-Video for stronger detail, RIFLEx only when extending beyond the trained duration, and NAG for normalized negative guidance. Enable the same module in both high/low lanes; test one technique at a time on 16 GB VRAM.\n\n81 frames obeys 4n+1. Output is a tiled 24 fps H.264 MP4. On 16 GB VRAM, lower the megapixel widget before changing any width/height values.",
            "Adaptive Wan 2.2 image-to-video",
        )
        rebuild_links(workflow)
        (output_root / name).write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("user/default/workflows/agent"))
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)

    reference = load_json(Path("user/default/workflows/agent/29 - Arch Flux Klein 9B - All Custom Nodes I2I Reference v2.json"))
    scale_exemplar = nodes(reference, "ImageScaleToTotalPixels")[0]
    size_exemplar = node(reference, "GetImageSize")
    ltx_reference = load_json(args.source_root / "user/default/workflows/agent" / LTX_NAMES[0])
    ltx_exemplars = {kind: node(ltx_reference, kind) for kind in ("VAEDecodeTiled", "CreateVideo", "SaveVideo")}
    lora_exemplar = node(ltx_reference, "LoraLoaderModelOnly")

    build_ltx(args.source_root, args.output_root, (scale_exemplar, size_exemplar))
    build_wan(args.source_root, args.output_root, (scale_exemplar, size_exemplar), ltx_exemplars, lora_exemplar)


if __name__ == "__main__":
    main()
