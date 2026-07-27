"""Build the Z-Image, Krea 2, FireRed, and ReActor identity workflow suite."""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path


OUTPUT_DIR = Path("user/default/workflows/agent")
PLACEHOLDER = "wan_q4_placeholder.ppm"
PROOF_SOURCE = "identity-benchmark/source_identity.png"
PROOF_TARGET = "identity-benchmark/target_scene_v2.png"

Z_TURBO_NAME = "40 - Z-Image Turbo Identity Anchor I2I.json"
Z_BASE_NAME = "41 - Z-Image Base Two Stage Precision I2I.json"
KREA_NAME = "42 - Krea 2 Identity Edit v1.2.json"
FIRERED_NAME = "43 - FireRed 1.1 Identity MultiRef.json"
REACTOR_NAME = "44 - Face Swap Proof and ReActor Baseline.json"

Z_TURBO_MODEL = "z_image_turbo-Q8_0.gguf"
Z_BASE_MODEL = "z_image-Q8_0.gguf"
Z_CLIP = "qwen_3_4b.safetensors"
Z_VAE = "ae.safetensors"

KREA_MODEL = "krea2_turbo_fp8_scaled.safetensors"
KREA_CLIP = "qwen3vl_4b_fp8_scaled.safetensors"
KREA_VAE = "qwen_image_vae.safetensors"
KREA_LORA = "krea2_identity_edit_v1_2.safetensors"

FIRERED_MODEL = "FireRed-Image-Edit-1.1-Q4_K_M.gguf"
FIRERED_CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
FIRERED_VAE = "qwen_image_vae.safetensors"
FIRERED_LORA = (
    "FireRed-Image-Edit-1.1-Lightning-8steps-v1.2.safetensors"
)

Z_SOURCES = [
    "https://huggingface.co/Tongyi-MAI/Z-Image-Turbo",
    "https://huggingface.co/jayn7/Z-Image-Turbo-GGUF",
    "https://www.reddit.com/r/comfyui/comments/1stylnr/anchor_workflow_zimage_turbo/",
]
Z_BASE_SOURCES = [
    "https://huggingface.co/Tongyi-MAI/Z-Image",
    "https://huggingface.co/jayn7/Z-Image-GGUF",
    "https://www.reddit.com/r/comfyui/comments/1qznc0z/zimage_base_simple_workflow_for_high_quality/",
]
KREA_SOURCES = [
    "https://github.com/krea-ai/krea-2",
    "https://github.com/lbouaraba/comfyui-krea2edit",
    "https://huggingface.co/conradlocke/krea2-identity-edit",
]
FIRERED_SOURCES = [
    "https://huggingface.co/FireRedTeam/FireRed-Image-Edit-1.1",
    "https://huggingface.co/FireRedTeam/FireRed-Image-Edit-1.1-ComfyUI",
    "https://www.reddit.com/r/comfyui/comments/1rqyn65/firered_image_edit_11_a_more_powerful_editing/",
]
REACTOR_SOURCES = [
    "https://github.com/Gourieff/ComfyUI-ReActor",
]


@dataclass
class Graph:
    slug: str
    model: str
    license_name: str
    research_sources: list[str]
    nodes: list[dict] = field(default_factory=list)
    links: list[list] = field(default_factory=list)

    def add(
        self,
        node_type: str,
        *,
        title: str,
        pos: tuple[int, int],
        inputs: tuple[tuple[str, str, bool, bool], ...] = (),
        outputs: tuple[tuple[str, str], ...] = (),
        widgets: tuple | list = (),
        mode: int = 0,
        size: tuple[int, int] = (310, 190),
    ) -> dict:
        node_id = len(self.nodes) + 1
        node_inputs = []
        for name, value_type, is_widget, optional in inputs:
            item = {"name": name, "type": value_type, "link": None}
            if is_widget:
                item["widget"] = {"name": name}
            if optional:
                item["shape"] = 7
            node_inputs.append(item)
        node_outputs = [
            {
                "name": name,
                "type": value_type,
                "slot_index": index,
                "links": [],
            }
            for index, (name, value_type) in enumerate(outputs)
        ]
        node = {
            "id": node_id,
            "type": node_type,
            "pos": list(pos),
            "size": list(size),
            "flags": {},
            "order": len(self.nodes),
            "mode": mode,
            "inputs": node_inputs,
            "outputs": node_outputs,
            "title": title,
            "properties": {"Node name for S&R": node_type},
            "widgets_values": list(widgets),
        }
        self.nodes.append(node)
        return node

    def connect(
        self,
        source: dict,
        source_slot: int,
        target: dict,
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
            [
                link_id,
                source["id"],
                source_slot,
                target["id"],
                target_slot,
                value_type,
            ]
        )
        source["outputs"][source_slot]["links"].append(link_id)
        target["inputs"][target_slot]["link"] = link_id

    def workflow(self) -> dict:
        return {
            "id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"modern-identity-suite:{self.slug}",
                )
            ),
            "revision": 0,
            "last_node_id": max(node["id"] for node in self.nodes),
            "last_link_id": max(link[0] for link in self.links),
            "nodes": self.nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {
                "modern_identity_suite": {
                    "workflow_slug": self.slug,
                    "version": 1,
                    "model": self.model,
                    "license": self.license_name,
                    "research_sources": self.research_sources,
                }
            },
            "version": 0.4,
        }


def graph(
    slug: str,
    model: str,
    license_name: str,
    research_sources: list[str],
) -> Graph:
    return Graph(slug, model, license_name, research_sources)


def load_image(
    workflow: Graph,
    *,
    title: str,
    pos: tuple[int, int],
    filename: str = PLACEHOLDER,
) -> dict:
    return workflow.add(
        "LoadImage",
        title=title,
        pos=pos,
        inputs=(
            ("image", "COMBO", True, False),
            ("upload", "IMAGEUPLOAD", True, False),
        ),
        outputs=(("IMAGE", "IMAGE"), ("MASK", "MASK")),
        widgets=(filename, "image"),
        size=(310, 320),
    )


def z_model_stack(workflow: Graph, model_name: str) -> tuple[dict, dict, dict]:
    model = workflow.add(
        "UnetLoaderGGUF",
        title="Z-Image GGUF Q8 model",
        pos=(-1540, -760),
        inputs=(("unet_name", "COMBO", True, False),),
        outputs=(("MODEL", "MODEL"),),
        widgets=(model_name,),
    )
    sampling = workflow.add(
        "ModelSamplingAuraFlow",
        title="Z-Image flow shift 3",
        pos=(-1180, -760),
        inputs=(
            ("model", "MODEL", False, False),
            ("shift", "FLOAT", True, False),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(3.0,),
    )
    clip = workflow.add(
        "CLIPLoader",
        title="Full Qwen3 4B encoder",
        pos=(-1540, -540),
        inputs=(
            ("clip_name", "COMBO", True, False),
            ("type", "COMBO", True, False),
            ("device", "COMBO", True, False),
        ),
        outputs=(("CLIP", "CLIP"),),
        widgets=(Z_CLIP, "lumina2", "default"),
    )
    vae = workflow.add(
        "VAELoader",
        title="Z-Image AE",
        pos=(-1180, -540),
        inputs=(("vae_name", "COMBO", True, False),),
        outputs=(("VAE", "VAE"),),
        widgets=(Z_VAE,),
    )
    workflow.connect(model, 0, sampling, "model")
    return sampling, clip, vae


def text_encode(
    workflow: Graph,
    *,
    title: str,
    prompt: str,
    pos: tuple[int, int],
) -> dict:
    return workflow.add(
        "CLIPTextEncode",
        title=title,
        pos=pos,
        inputs=(
            ("clip", "CLIP", False, False),
            ("text", "STRING", True, False),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
        widgets=(prompt,),
        size=(390, 210),
    )


def vae_encode(workflow: Graph, *, title: str, pos: tuple[int, int]) -> dict:
    return workflow.add(
        "VAEEncode",
        title=title,
        pos=pos,
        inputs=(
            ("pixels", "IMAGE", False, False),
            ("vae", "VAE", False, False),
        ),
        outputs=(("LATENT", "LATENT"),),
    )


def vae_decode(workflow: Graph, *, title: str, pos: tuple[int, int]) -> dict:
    return workflow.add(
        "VAEDecode",
        title=title,
        pos=pos,
        inputs=(
            ("samples", "LATENT", False, False),
            ("vae", "VAE", False, False),
        ),
        outputs=(("IMAGE", "IMAGE"),),
    )


def ksampler(
    workflow: Graph,
    *,
    title: str,
    pos: tuple[int, int],
    seed: int,
    steps: int,
    cfg: float,
    sampler_name: str,
    scheduler: str,
    denoise: float,
) -> dict:
    return workflow.add(
        "KSampler",
        title=title,
        pos=pos,
        inputs=(
            ("model", "MODEL", False, False),
            ("seed", "INT", True, False),
            ("steps", "INT", True, False),
            ("cfg", "FLOAT", True, False),
            ("sampler_name", "COMBO", True, False),
            ("scheduler", "COMBO", True, False),
            ("positive", "CONDITIONING", False, False),
            ("negative", "CONDITIONING", False, False),
            ("latent_image", "LATENT", False, False),
            ("denoise", "FLOAT", True, False),
        ),
        outputs=(("LATENT", "LATENT"),),
        widgets=(
            seed,
            "fixed",
            steps,
            cfg,
            sampler_name,
            scheduler,
            denoise,
        ),
        size=(330, 430),
    )


def save_image(
    workflow: Graph,
    *,
    title: str,
    prefix: str,
    pos: tuple[int, int],
) -> dict:
    return workflow.add(
        "SaveImage",
        title=title,
        pos=pos,
        inputs=(
            ("images", "IMAGE", False, False),
            ("filename_prefix", "STRING", True, False),
        ),
        outputs=(("images", "IMAGE"),),
        widgets=(prefix,),
        size=(320, 270),
    )


def preview_image(
    workflow: Graph,
    *,
    title: str,
    pos: tuple[int, int],
) -> dict:
    return workflow.add(
        "PreviewImage",
        title=title,
        pos=pos,
        inputs=(("images", "IMAGE", False, False),),
        outputs=(("images", "IMAGE"),),
        size=(320, 270),
    )


def identity_score(
    workflow: Graph,
    *,
    title: str,
    run_label: str,
    pos: tuple[int, int],
) -> dict:
    return workflow.add(
        "OpenCVIdentityScore",
        title=title,
        pos=pos,
        inputs=(
            ("reference_image", "IMAGE", False, False),
            ("generated_image", "IMAGE", False, False),
            ("extra_metadata", "EXTRA_METADATA", False, True),
            ("catalog_root", "STRING", True, False),
            ("subject_name", "STRING", True, False),
            ("catalog_mode", "COMBO", True, False),
            ("catalog_aggregation", "COMBO", True, False),
            ("max_catalog_images", "INT", True, False),
            ("include_subfolders", "BOOLEAN", True, False),
            ("face_score_threshold", "FLOAT", True, False),
            ("same_identity_threshold", "FLOAT", True, False),
            ("face_selection", "COMBO", True, False),
            ("write_manifest", "BOOLEAN", True, False),
            ("manifest_dir", "STRING", True, False),
            ("run_label", "STRING", True, False),
            ("metadata_key", "STRING", True, False),
        ),
        outputs=(
            ("source_cosine_similarity", "FLOAT"),
            ("source_same_identity", "BOOLEAN"),
            ("best_catalog_subject", "STRING"),
            ("best_catalog_reference", "STRING"),
            ("report_json", "STRING"),
            ("extra_metadata", "EXTRA_METADATA"),
        ),
        widgets=(
            "people",
            "",
            "off",
            "mean_top3",
            64,
            True,
            0.7,
            0.363,
            "largest",
            True,
            "default/identity_score_runs",
            run_label,
            "identity_score_report",
        ),
        size=(410, 450),
    )


def note(
    workflow: Graph,
    *,
    title: str,
    text: str,
    pos: tuple[int, int],
    size: tuple[int, int] = (520, 390),
) -> dict:
    return workflow.add(
        "MarkdownNote",
        title=title,
        pos=pos,
        widgets=(text,),
        size=size,
    )


def build_z_turbo_anchor() -> dict:
    workflow = graph(
        "z-image-turbo-identity-anchor-i2i",
        Z_TURBO_MODEL,
        "Apache-2.0 (Z-Image); GGUF conversion follows source terms",
        Z_SOURCES,
    )
    model, clip, vae = z_model_stack(workflow, Z_TURBO_MODEL)
    identity = load_image(
        workflow,
        title="Identity reference - clear synthetic/public portrait",
        pos=(-1540, -200),
    )
    target = load_image(
        workflow,
        title="Target scene - composition and pose",
        pos=(-1540, 180),
    )
    identity_scale = workflow.add(
        "ImageScale",
        title="Fit identity anchor to 640x832",
        pos=(-1180, -160),
        inputs=(
            ("image", "IMAGE", False, False),
            ("upscale_method", "COMBO", True, False),
            ("width", "INT", True, False),
            ("height", "INT", True, False),
            ("crop", "COMBO", True, False),
        ),
        outputs=(("IMAGE", "IMAGE"),),
        widgets=("lanczos", 640, 832, "center"),
    )
    target_scale = workflow.add(
        "ImageScale",
        title="Fit target center to 640x832",
        pos=(-1180, 180),
        inputs=(
            ("image", "IMAGE", False, False),
            ("upscale_method", "COMBO", True, False),
            ("width", "INT", True, False),
            ("height", "INT", True, False),
            ("crop", "COMBO", True, False),
        ),
        outputs=(("IMAGE", "IMAGE"),),
        widgets=("lanczos", 640, 832, "center"),
    )
    stitch_left = workflow.add(
        "ImageStitch",
        title="Anchor left + target center",
        pos=(-800, -20),
        inputs=(
            ("image1", "IMAGE", False, False),
            ("direction", "COMBO", True, False),
            ("match_image_size", "BOOLEAN", True, False),
            ("spacing_width", "INT", True, False),
            ("spacing_color", "COMBO", True, False),
            ("image2", "IMAGE", False, True),
        ),
        outputs=(("IMAGE", "IMAGE"),),
        widgets=("right", True, 0, "black"),
    )
    stitch_right = workflow.add(
        "ImageStitch",
        title="Duplicate identity on both sides",
        pos=(-420, -20),
        inputs=(
            ("image1", "IMAGE", False, False),
            ("direction", "COMBO", True, False),
            ("match_image_size", "BOOLEAN", True, False),
            ("spacing_width", "INT", True, False),
            ("spacing_color", "COMBO", True, False),
            ("image2", "IMAGE", False, True),
        ),
        outputs=(("IMAGE", "IMAGE"),),
        widgets=("right", True, 0, "black"),
    )
    stitched_latent = vae_encode(
        workflow,
        title="Encode identity-target-identity canvas",
        pos=(-20, -40),
    )
    empty_mask = workflow.add(
        "SolidMask",
        title="Protected anchor canvas",
        pos=(-420, 260),
        inputs=(
            ("value", "FLOAT", True, False),
            ("width", "INT", True, False),
            ("height", "INT", True, False),
        ),
        outputs=(("MASK", "MASK"),),
        widgets=(0.0, 1920, 832),
    )
    center_mask = workflow.add(
        "SolidMask",
        title="Editable center only",
        pos=(-80, 260),
        inputs=(
            ("value", "FLOAT", True, False),
            ("width", "INT", True, False),
            ("height", "INT", True, False),
        ),
        outputs=(("MASK", "MASK"),),
        widgets=(1.0, 640, 832),
    )
    mask_composite = workflow.add(
        "MaskComposite",
        title="Place editable mask at x=640",
        pos=(280, 260),
        inputs=(
            ("destination", "MASK", False, False),
            ("source", "MASK", False, False),
            ("x", "INT", True, False),
            ("y", "INT", True, False),
            ("operation", "COMBO", True, False),
        ),
        outputs=(("MASK", "MASK"),),
        widgets=(640, 0, "add"),
    )
    masked_latent = workflow.add(
        "SetLatentNoiseMask",
        title="Noise only the target center",
        pos=(640, 80),
        inputs=(
            ("samples", "LATENT", False, False),
            ("mask", "MASK", False, False),
        ),
        outputs=(("LATENT", "LATENT"),),
    )
    positive = text_encode(
        workflow,
        title="Anchor identity edit instruction",
        prompt=(
            "Create the center image using the target center composition, pose, "
            "clothing, background, and lighting. The same person shown in both "
            "side anchors must be the person in the center. Preserve realistic "
            "facial proportions and natural skin detail."
        ),
        pos=(-20, -580),
    )
    negative = text_encode(
        workflow,
        title="Artifact exclusions",
        prompt=(
            "different identity, duplicate person, deformed face, asymmetrical "
            "eyes, bad anatomy, text, watermark"
        ),
        pos=(400, -580),
    )
    sampler = ksampler(
        workflow,
        title="Experimental Z-Image identity anchor pass",
        pos=(980, -240),
        seed=402026,
        steps=9,
        cfg=1.0,
        sampler_name="euler",
        scheduler="simple",
        denoise=0.82,
    )
    decoded = vae_decode(
        workflow,
        title="Decode three-panel result",
        pos=(1360, -160),
    )
    crop = workflow.add(
        "ImageCrop",
        title="Extract generated center panel",
        pos=(1700, -160),
        inputs=(
            ("image", "IMAGE", False, False),
            ("width", "INT", True, False),
            ("height", "INT", True, False),
            ("x", "INT", True, False),
            ("y", "INT", True, False),
        ),
        outputs=(("IMAGE", "IMAGE"),),
        widgets=(640, 832, 640, 0),
    )
    output = save_image(
        workflow,
        title="Save native Z-Image anchor result",
        prefix="agent/modern-identity/z-turbo-anchor",
        pos=(2060, -220),
    )
    preview = preview_image(
        workflow,
        title="Preview native Z-Image result",
        pos=(2420, -220),
    )
    score = identity_score(
        workflow,
        title="Score anchor identity vs center result",
        run_label="z-turbo-anchor",
        pos=(2060, 120),
    )
    note(
        workflow,
        title="Z-Image anchor method and limits",
        text=(
            "## Z-Image Turbo identity anchor I2I\n\n"
            "This is an experimental community anchor technique, not a native "
            "identity-edit model. It places the identity portrait on both sides "
            "of the target, protects those anchors with a latent noise mask, and "
            "regenerates only the center. Expect roughly three times the pixels "
            "and slower sampling. Start at denoise 0.82; try 0.70-0.90. Compare "
            "the native crop and identity score honestly—do not treat a later "
            "ReActor pass as Z-Image identity performance.\n\n"
            "Sources: Tongyi-MAI Z-Image Turbo, jayn7 Q8 GGUF, and the highly "
            "upvoted community Anchor Workflow Z-Image Turbo."
        ),
        pos=(-1540, 560),
    )

    workflow.connect(identity, 0, identity_scale, "image")
    workflow.connect(target, 0, target_scale, "image")
    workflow.connect(identity_scale, 0, stitch_left, "image1")
    workflow.connect(target_scale, 0, stitch_left, "image2")
    workflow.connect(stitch_left, 0, stitch_right, "image1")
    workflow.connect(identity_scale, 0, stitch_right, "image2")
    workflow.connect(stitch_right, 0, stitched_latent, "pixels")
    workflow.connect(vae, 0, stitched_latent, "vae")
    workflow.connect(empty_mask, 0, mask_composite, "destination")
    workflow.connect(center_mask, 0, mask_composite, "source")
    workflow.connect(stitched_latent, 0, masked_latent, "samples")
    workflow.connect(mask_composite, 0, masked_latent, "mask")
    workflow.connect(clip, 0, positive, "clip")
    workflow.connect(clip, 0, negative, "clip")
    workflow.connect(model, 0, sampler, "model")
    workflow.connect(positive, 0, sampler, "positive")
    workflow.connect(negative, 0, sampler, "negative")
    workflow.connect(masked_latent, 0, sampler, "latent_image")
    workflow.connect(sampler, 0, decoded, "samples")
    workflow.connect(vae, 0, decoded, "vae")
    workflow.connect(decoded, 0, crop, "image")
    workflow.connect(crop, 0, output, "images")
    workflow.connect(crop, 0, preview, "images")
    workflow.connect(identity, 0, score, "reference_image")
    workflow.connect(crop, 0, score, "generated_image")
    return workflow.workflow()


def build_z_base_two_stage() -> dict:
    workflow = graph(
        "z-image-base-two-stage-precision-i2i",
        Z_BASE_MODEL,
        "Apache-2.0 (Z-Image); GGUF conversion follows source terms",
        Z_BASE_SOURCES,
    )
    model, clip, vae = z_model_stack(workflow, Z_BASE_MODEL)
    source = load_image(
        workflow,
        title="Source/target image - identity and composition",
        pos=(-1540, -160),
    )
    scale = workflow.add(
        "ImageScaleToTotalPixels",
        title="Bound input near one megapixel",
        pos=(-1160, -120),
        inputs=(
            ("image", "IMAGE", False, False),
            ("upscale_method", "COMBO", True, False),
            ("megapixels", "FLOAT", True, False),
            ("resolution_steps", "INT", True, False),
        ),
        outputs=(("IMAGE", "IMAGE"),),
        widgets=("lanczos", 1.0, 16),
    )
    source_latent = vae_encode(
        workflow,
        title="Encode source for first I2I pass",
        pos=(-760, -120),
    )
    positive = text_encode(
        workflow,
        title="Precision edit prompt",
        prompt=(
            "Preserve the same person, facial identity, camera, pose, lighting, "
            "and background. Apply only the requested edit: [describe edit here]."
        ),
        pos=(-760, -620),
    )
    negative = text_encode(
        workflow,
        title="Identity drift exclusions",
        prompt=(
            "different person, identity drift, altered face structure, duplicate "
            "subject, deformed face, bad anatomy, text, watermark"
        ),
        pos=(-320, -620),
    )
    first = ksampler(
        workflow,
        title="Community quality first pass",
        pos=(-260, -220),
        seed=412026,
        steps=25,
        cfg=4.0,
        sampler_name="res_multistep",
        scheduler="beta",
        denoise=0.55,
    )
    first_decode = vae_decode(
        workflow,
        title="Decode first-pass edit",
        pos=(120, -160),
    )
    refine_latent = vae_encode(
        workflow,
        title="Re-encode for low-denoise refinement",
        pos=(460, -160),
    )
    refine = ksampler(
        workflow,
        title="Low-denoise identity refinement",
        pos=(820, -220),
        seed=412026,
        steps=5,
        cfg=3.0,
        sampler_name="euler",
        scheduler="simple",
        denoise=0.15,
    )
    final = vae_decode(
        workflow,
        title="Decode refined Z-Image Base result",
        pos=(1200, -160),
    )
    output = save_image(
        workflow,
        title="Save Z-Image Base precision I2I",
        prefix="agent/modern-identity/z-base-two-stage",
        pos=(1560, -220),
    )
    preview = preview_image(
        workflow,
        title="Preview refined Z-Image Base result",
        pos=(1920, -220),
    )
    score = identity_score(
        workflow,
        title="Score source identity vs refined result",
        run_label="z-base-two-stage",
        pos=(1560, 120),
    )
    note(
        workflow,
        title="Z-Image Base community quality recipe",
        text=(
            "## Z-Image Base two-stage precision I2I\n\n"
            "Derived from current high-signal community Base workflows: a "
            "quality-oriented 25-step `res_multistep`/beta pass followed by a "
            "short 0.15-denoise refinement. Base is a generator rather than a "
            "native editor, so source identity preservation depends strongly on denoise. "
            "Try first-pass denoise 0.45-0.65. Full Qwen3 4B and Q8 GGUF are "
            "selected for quality on 16 GB VRAM."
        ),
        pos=(-1540, 340),
    )

    workflow.connect(source, 0, scale, "image")
    workflow.connect(scale, 0, source_latent, "pixels")
    workflow.connect(vae, 0, source_latent, "vae")
    workflow.connect(clip, 0, positive, "clip")
    workflow.connect(clip, 0, negative, "clip")
    workflow.connect(model, 0, first, "model")
    workflow.connect(positive, 0, first, "positive")
    workflow.connect(negative, 0, first, "negative")
    workflow.connect(source_latent, 0, first, "latent_image")
    workflow.connect(first, 0, first_decode, "samples")
    workflow.connect(vae, 0, first_decode, "vae")
    workflow.connect(first_decode, 0, refine_latent, "pixels")
    workflow.connect(vae, 0, refine_latent, "vae")
    workflow.connect(model, 0, refine, "model")
    workflow.connect(positive, 0, refine, "positive")
    workflow.connect(negative, 0, refine, "negative")
    workflow.connect(refine_latent, 0, refine, "latent_image")
    workflow.connect(refine, 0, final, "samples")
    workflow.connect(vae, 0, final, "vae")
    workflow.connect(final, 0, output, "images")
    workflow.connect(final, 0, preview, "images")
    workflow.connect(source, 0, score, "reference_image")
    workflow.connect(final, 0, score, "generated_image")
    return workflow.workflow()


def build_krea_identity() -> dict:
    workflow = graph(
        "krea-2-identity-edit-v1-2",
        KREA_MODEL,
        "Krea 2 Community License; Krea2Edit nodes Apache-2.0",
        KREA_SOURCES,
    )
    model = workflow.add(
        "UNETLoader",
        title="Krea 2 Turbo FP8",
        pos=(-1580, -760),
        inputs=(
            ("unet_name", "COMBO", True, False),
            ("weight_dtype", "COMBO", True, False),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(KREA_MODEL, "default"),
    )
    lora = workflow.add(
        "LoraLoaderModelOnly",
        title="Krea 2 Identity Edit v1.2 full-rank LoRA",
        pos=(-1200, -760),
        inputs=(
            ("model", "MODEL", False, False),
            ("lora_name", "COMBO", True, False),
            ("strength_model", "FLOAT", True, False),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(KREA_LORA, 1.0),
    )
    clip = workflow.add(
        "CLIPLoader",
        title="Krea 2 Qwen3-VL 4B encoder",
        pos=(-1580, -520),
        inputs=(
            ("clip_name", "COMBO", True, False),
            ("type", "COMBO", True, False),
            ("device", "COMBO", True, False),
        ),
        outputs=(("CLIP", "CLIP"),),
        widgets=(KREA_CLIP, "krea2", "default"),
    )
    vae = workflow.add(
        "VAELoader",
        title="Qwen image VAE",
        pos=(-1200, -520),
        inputs=(("vae_name", "COMBO", True, False),),
        outputs=(("VAE", "VAE"),),
        widgets=(KREA_VAE,),
    )
    target = load_image(
        workflow,
        title="Target scene - preserve pose/background",
        pos=(-1580, -140),
    )
    identity = load_image(
        workflow,
        title="Identity reference - face/head to transfer",
        pos=(-1580, 260),
    )
    target_latent = vae_encode(
        workflow,
        title="Encode target scene reference",
        pos=(-1180, -120),
    )
    identity_latent = vae_encode(
        workflow,
        title="Encode identity subject reference",
        pos=(-1180, 280),
    )
    patch = workflow.add(
        "Krea2EditModelPatch",
        title="Krea2Edit v1.2 dual-reference source patch",
        pos=(-720, -200),
        inputs=(
            ("model", "MODEL", False, False),
            ("source_latent", "LATENT", False, False),
            ("source_latent_b", "LATENT", False, True),
            ("ref_boost_mask", "MASK", False, True),
            ("vae", "VAE", False, True),
            ("source_image", "IMAGE", False, True),
            ("source_image_b", "IMAGE", False, True),
            ("ref_boost", "FLOAT", True, True),
            ("ref_boost_a", "FLOAT", True, True),
            ("fit_mode", "COMBO", True, True),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(1.5, 1.0, "fit"),
        size=(390, 380),
    )
    positive = workflow.add(
        "Krea2EditGroundedEncode",
        title="Grounded face/head replacement instruction",
        pos=(-700, -680),
        inputs=(
            ("clip", "CLIP", False, False),
            ("image", "IMAGE", False, True),
            ("image_b", "IMAGE", False, True),
            ("prompt", "STRING", True, False),
            ("grounding_px", "INT", True, True),
            ("system_prompt", "STRING", True, True),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
        widgets=(
            "Replace the face and head identity of the person in image 1 with "
            "the person in image 2. Preserve image 1's pose, expression, body, "
            "clothing, camera, lighting, and background.",
            1024,
            "Attend closely to facial identity, face shape, eyes, nose, mouth, "
            "hairline, and other stable likeness cues.",
        ),
        size=(450, 290),
    )
    negative = workflow.add(
        "Krea2EditGroundedEncode",
        title="Training-matched grounded unconditional",
        pos=(-200, -680),
        inputs=(
            ("clip", "CLIP", False, False),
            ("image", "IMAGE", False, True),
            ("image_b", "IMAGE", False, True),
            ("prompt", "STRING", True, False),
            ("grounding_px", "INT", True, True),
            ("system_prompt", "STRING", True, True),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
        widgets=("", 1024, ""),
        size=(430, 250),
    )
    empty = workflow.add(
        "EmptySD3LatentImage",
        title="1024x1024 Krea target latent",
        pos=(-180, -160),
        inputs=(
            ("width", "INT", True, False),
            ("height", "INT", True, False),
            ("batch_size", "INT", True, False),
        ),
        outputs=(("LATENT", "LATENT"),),
        widgets=(1024, 1024, 1),
    )
    sampler = ksampler(
        workflow,
        title="Krea 2 Turbo identity edit",
        pos=(300, -280),
        seed=422026,
        steps=8,
        cfg=1.0,
        sampler_name="euler",
        scheduler="simple",
        denoise=1.0,
    )
    decoded = vae_decode(
        workflow,
        title="Decode native Krea identity edit",
        pos=(700, -200),
    )
    output = save_image(
        workflow,
        title="Save native Krea 2 identity result",
        prefix="agent/modern-identity/krea2-identity-v1-2",
        pos=(1060, -260),
    )
    preview = preview_image(
        workflow,
        title="Preview native Krea 2 result",
        pos=(1420, -260),
    )
    score = identity_score(
        workflow,
        title="Score identity reference vs Krea result",
        run_label="krea2-identity-v1-2",
        pos=(1060, 80),
    )
    note(
        workflow,
        title="Krea2 Identity Edit v1.2 guidance",
        text=(
            "## Krea 2 Identity Edit v1.2\n\n"
            "Current community identity workflow: target scene first, identity "
            "subject second, both provided to the VAE source patch and Qwen3-VL "
            "grounded encoder. Turbo defaults are 8 steps / CFG 1 / Euler / "
            "simple. `fit` geometry is required for v1.2. Identity `ref_boost` "
            "starts at 1.5; try 1.0-4.0. Grounding 1024 favors likeness; lower "
            "toward 512-768 for stronger edit adherence. Stay at or below 2 MP.\n\n"
            "Krea 2 uses the Krea Community License. The v1.2 LoRA is SFW-trained "
            "and its author explicitly prohibits non-consensual sexual deepfakes."
        ),
        pos=(-1580, 680),
    )

    workflow.connect(model, 0, lora, "model")
    workflow.connect(target, 0, target_latent, "pixels")
    workflow.connect(vae, 0, target_latent, "vae")
    workflow.connect(identity, 0, identity_latent, "pixels")
    workflow.connect(vae, 0, identity_latent, "vae")
    workflow.connect(lora, 0, patch, "model")
    workflow.connect(target_latent, 0, patch, "source_latent")
    workflow.connect(identity_latent, 0, patch, "source_latent_b")
    workflow.connect(vae, 0, patch, "vae")
    workflow.connect(target, 0, patch, "source_image")
    workflow.connect(identity, 0, patch, "source_image_b")
    workflow.connect(clip, 0, positive, "clip")
    workflow.connect(target, 0, positive, "image")
    workflow.connect(identity, 0, positive, "image_b")
    workflow.connect(clip, 0, negative, "clip")
    workflow.connect(target, 0, negative, "image")
    workflow.connect(identity, 0, negative, "image_b")
    workflow.connect(patch, 0, sampler, "model")
    workflow.connect(positive, 0, sampler, "positive")
    workflow.connect(negative, 0, sampler, "negative")
    workflow.connect(empty, 0, sampler, "latent_image")
    workflow.connect(sampler, 0, decoded, "samples")
    workflow.connect(vae, 0, decoded, "vae")
    workflow.connect(decoded, 0, output, "images")
    workflow.connect(decoded, 0, preview, "images")
    workflow.connect(identity, 0, score, "reference_image")
    workflow.connect(decoded, 0, score, "generated_image")
    return workflow.workflow()


def build_firered_identity() -> dict:
    workflow = graph(
        "firered-1-1-identity-multiref",
        FIRERED_MODEL,
        "Apache-2.0",
        FIRERED_SOURCES,
    )
    model = workflow.add(
        "UnetLoaderGGUF",
        title="FireRed Image Edit 1.1 Q4_K_M",
        pos=(-1560, -760),
        inputs=(("unet_name", "COMBO", True, False),),
        outputs=(("MODEL", "MODEL"),),
        widgets=(FIRERED_MODEL,),
    )
    lora = workflow.add(
        "LoraLoaderModelOnly",
        title="FireRed 1.1 Lightning 8-step v1.2",
        pos=(-1180, -760),
        inputs=(
            ("model", "MODEL", False, False),
            ("lora_name", "COMBO", True, False),
            ("strength_model", "FLOAT", True, False),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(FIRERED_LORA, 1.0),
    )
    sampling = workflow.add(
        "ModelSamplingAuraFlow",
        title="FireRed/Qwen shift 3.1",
        pos=(-800, -760),
        inputs=(
            ("model", "MODEL", False, False),
            ("shift", "FLOAT", True, False),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(3.1,),
    )
    cfg_norm = workflow.add(
        "CFGNorm",
        title="FireRed CFG normalization",
        pos=(-440, -760),
        inputs=(
            ("model", "MODEL", False, False),
            ("strength", "FLOAT", True, False),
            ("pre_cfg", "BOOLEAN", True, True),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(1.0, False),
    )
    clip = workflow.add(
        "CLIPLoader",
        title="Existing Qwen2.5-VL 7B FP8 encoder",
        pos=(-1560, -520),
        inputs=(
            ("clip_name", "COMBO", True, False),
            ("type", "COMBO", True, False),
            ("device", "COMBO", True, False),
        ),
        outputs=(("CLIP", "CLIP"),),
        widgets=(FIRERED_CLIP, "qwen_image", "default"),
    )
    vae = workflow.add(
        "VAELoader",
        title="Existing Qwen image VAE",
        pos=(-1180, -520),
        inputs=(("vae_name", "COMBO", True, False),),
        outputs=(("VAE", "VAE"),),
        widgets=(FIRERED_VAE,),
    )
    target = load_image(
        workflow,
        title="Target scene - pose/body/background from image 1",
        pos=(-1560, -120),
    )
    identity = load_image(
        workflow,
        title="Identity reference - face/head from image 2",
        pos=(-1560, 280),
    )
    target_scale = workflow.add(
        "FluxKontextImageScale",
        title="FireRed target resolution normalization",
        pos=(-1180, -80),
        inputs=(("image", "IMAGE", False, False),),
        outputs=(("IMAGE", "IMAGE"),),
    )
    positive = workflow.add(
        "TextEncodeQwenImageEditPlus",
        title="FireRed two-reference identity instruction",
        pos=(-760, -420),
        inputs=(
            ("clip", "CLIP", False, False),
            ("prompt", "STRING", True, False),
            ("vae", "VAE", False, True),
            ("image1", "IMAGE", False, True),
            ("image2", "IMAGE", False, True),
            ("image3", "IMAGE", False, True),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
        widgets=(
            "Replace the person in image 1 with the face and head identity from "
            "image 2. Preserve image 1's pose, expression, body, clothing, camera, "
            "lighting, and background.",
        ),
        size=(450, 280),
    )
    negative = workflow.add(
        "TextEncodeQwenImageEditPlus",
        title="FireRed grounded unconditional",
        pos=(-760, -100),
        inputs=(
            ("clip", "CLIP", False, False),
            ("prompt", "STRING", True, False),
            ("vae", "VAE", False, True),
            ("image1", "IMAGE", False, True),
            ("image2", "IMAGE", False, True),
            ("image3", "IMAGE", False, True),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
        widgets=("",),
        size=(430, 240),
    )
    latent = vae_encode(
        workflow,
        title="Encode target scene latent",
        pos=(-760, 240),
    )
    sampler = ksampler(
        workflow,
        title="FireRed 1.1 Lightning identity edit",
        pos=(-220, -240),
        seed=432026,
        steps=8,
        cfg=1.0,
        sampler_name="euler",
        scheduler="simple",
        denoise=1.0,
    )
    decoded = vae_decode(
        workflow,
        title="Decode native FireRed identity edit",
        pos=(180, -160),
    )
    output = save_image(
        workflow,
        title="Save native FireRed identity result",
        prefix="agent/modern-identity/firered-1-1",
        pos=(540, -220),
    )
    preview = preview_image(
        workflow,
        title="Preview native FireRed result",
        pos=(900, -220),
    )
    score = identity_score(
        workflow,
        title="Score identity reference vs FireRed result",
        run_label="firered-1-1-identity",
        pos=(540, 120),
    )
    note(
        workflow,
        title="FireRed 1.1 identity workflow",
        text=(
            "## FireRed Image Edit 1.1 identity multi-reference\n\n"
            "FireRed is a native image editor and is the strongest additional "
            "identity candidate in this suite. Image 1 is the scene/pose source; "
            "image 2 is the identity source. The official current 1.1 Lightning "
            "v1.2 LoRA uses 8 steps, CFG 1, Euler/simple, shift 3.1, and CFGNorm. "
            "The installed Qwen2.5-VL FP8 encoder and Qwen VAE are reused."
        ),
        pos=(-1560, 680),
    )

    workflow.connect(model, 0, lora, "model")
    workflow.connect(lora, 0, sampling, "model")
    workflow.connect(sampling, 0, cfg_norm, "model")
    workflow.connect(target, 0, target_scale, "image")
    workflow.connect(clip, 0, positive, "clip")
    workflow.connect(vae, 0, positive, "vae")
    workflow.connect(target_scale, 0, positive, "image1")
    workflow.connect(identity, 0, positive, "image2")
    workflow.connect(clip, 0, negative, "clip")
    workflow.connect(vae, 0, negative, "vae")
    workflow.connect(target_scale, 0, negative, "image1")
    workflow.connect(identity, 0, negative, "image2")
    workflow.connect(target_scale, 0, latent, "pixels")
    workflow.connect(vae, 0, latent, "vae")
    workflow.connect(cfg_norm, 0, sampler, "model")
    workflow.connect(positive, 0, sampler, "positive")
    workflow.connect(negative, 0, sampler, "negative")
    workflow.connect(latent, 0, sampler, "latent_image")
    workflow.connect(sampler, 0, decoded, "samples")
    workflow.connect(vae, 0, decoded, "vae")
    workflow.connect(decoded, 0, output, "images")
    workflow.connect(decoded, 0, preview, "images")
    workflow.connect(identity, 0, score, "reference_image")
    workflow.connect(decoded, 0, score, "generated_image")
    return workflow.workflow()


def build_reactor_proof() -> dict:
    workflow = graph(
        "face-swap-proof-reactor-baseline",
        "inswapper_128.onnx",
        "ReActor and InsightFace model terms apply",
        REACTOR_SOURCES,
    )
    identity = load_image(
        workflow,
        title="Identity source - synthetic benchmark portrait",
        pos=(-1160, -240),
        filename=PROOF_SOURCE,
    )
    target = load_image(
        workflow,
        title="Target scene - synthetic benchmark portrait",
        pos=(-1160, 160),
        filename=PROOF_TARGET,
    )
    swap = workflow.add(
        "ReActorFaceSwap",
        title="ReActor baseline - identity source onto target",
        pos=(-700, -100),
        inputs=(
            ("input_image", "IMAGE", False, False),
            ("source_image", "IMAGE", False, True),
            ("face_model", "FACE_MODEL", False, True),
            ("face_boost", "FACE_BOOST", False, True),
            ("enabled", "BOOLEAN", True, False),
            ("swap_model", "COMBO", True, False),
            ("facedetection", "COMBO", True, False),
            ("face_restore_model", "COMBO", True, False),
            ("face_restore_visibility", "FLOAT", True, False),
            ("codeformer_weight", "FLOAT", True, False),
            ("detect_gender_input", "COMBO", True, False),
            ("detect_gender_source", "COMBO", True, False),
            ("input_faces_index", "STRING", True, False),
            ("source_faces_index", "STRING", True, False),
            ("console_log_level", "COMBO", True, False),
        ),
        outputs=(
            ("SWAPPED_IMAGE", "IMAGE"),
            ("FACE_MODEL", "FACE_MODEL"),
            ("ORIGINAL_IMAGE", "IMAGE"),
        ),
        widgets=(
            True,
            "inswapper_128.onnx",
            "retinaface_resnet50",
            "GFPGANv1.4.pth",
            0.75,
            0.5,
            "no",
            "no",
            "0",
            "0",
            1,
        ),
        size=(410, 520),
    )
    output = save_image(
        workflow,
        title="Save working ReActor baseline",
        prefix="agent/identity-model-benchmark/reactor-baseline",
        pos=(-180, -180),
    )
    preview = preview_image(
        workflow,
        title="Preview face-swap baseline",
        pos=(180, -180),
    )
    score = identity_score(
        workflow,
        title="Score source identity vs ReActor output",
        run_label="reactor-proof-baseline",
        pos=(-180, 160),
    )
    note(
        workflow,
        title="Controlled face-swap proof",
        text=(
            "## Face-swap proof and baseline\n\n"
            "This small graph is the controlled executable baseline used by the "
            "suite. It swaps the synthetic/public identity source onto the "
            "synthetic/public target, saves the result, and writes an identity "
            "similarity report. It proves the source/target test pair and local "
            "face-analysis stack work. It must remain labeled separately from "
            "native Krea 2 or FireRed results and must never be presented as "
            "their identity performance."
        ),
        pos=(-1160, 560),
        size=(520, 340),
    )

    workflow.connect(target, 0, swap, "input_image")
    workflow.connect(identity, 0, swap, "source_image")
    workflow.connect(swap, 0, output, "images")
    workflow.connect(swap, 0, preview, "images")
    workflow.connect(identity, 0, score, "reference_image")
    workflow.connect(swap, 0, score, "generated_image")
    return workflow.workflow()


def write_workflow(path: Path, workflow: dict) -> None:
    path.write_text(
        json.dumps(workflow, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the modern identity and I2I ComfyUI workflow suite."
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)

    for name, workflow in (
        (Z_TURBO_NAME, build_z_turbo_anchor()),
        (Z_BASE_NAME, build_z_base_two_stage()),
        (KREA_NAME, build_krea_identity()),
        (FIRERED_NAME, build_firered_identity()),
        (REACTOR_NAME, build_reactor_proof()),
    ):
        write_workflow(args.output_root / name, workflow)


if __name__ == "__main__":
    main()
