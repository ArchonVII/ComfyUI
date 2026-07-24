"""Build the tracked image-to-image consistency workflow suite.

The graphs are emitted directly in ComfyUI's editable editor format. Stable
node IDs, link IDs, layout, metadata, and JSON formatting make regeneration
byte-for-byte deterministic.
"""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path


OUTPUT_DIR = Path("user/default/workflows/agent")
PLACEHOLDER = "wan_q4_placeholder.ppm"

MASKED_NAME = "35 - Klein 9B Masked Precision I2I.json"
PULID_NAME = "36 - Klein 9B PuLID Identity Lab.json"
QWEN_NAME = "37 - Qwen 2511 Q4KM Precision MultiRef.json"

KLEIN_MODEL = r"Flux\9b\DarkBeast-Klein9b-V2-BFS-FP8-ComfyUI.safetensors"
KLEIN_CLIP = r"Flux\flux2-klein-qwen3-4b.safetensors"
KLEIN_VAE = "flux2-vae.safetensors"
KLEIN_LORA = r"Flux\9b\1 ------ Helper\Flux2-Klein-9B-consistency-V2.safetensors"

QWEN_MODEL = r"Qwen\Qwen-Image-Edit-2511-Q4_K_M.gguf"
QWEN_CLIP = r"Qwen\qwen_2.5_vl_7b_fp8_scaled.safetensors"
QWEN_VAE = "qwen_image_vae.safetensors"
QWEN_LORA = (
    r"Qwen\Qwen IE 2511"
    r"\Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors"
)


@dataclass
class Graph:
    slug: str
    target_model: str
    nodes: list[dict] = field(default_factory=list)
    links: list[list] = field(default_factory=list)

    def add(
        self,
        node_type: str,
        *,
        title: str,
        pos: tuple[int, int],
        inputs: tuple[tuple[str, str, bool], ...] = (),
        outputs: tuple[tuple[str, str], ...] = (),
        widgets: tuple | list = (),
        mode: int = 0,
        size: tuple[int, int] = (300, 180),
    ) -> dict:
        node_id = len(self.nodes) + 1
        node_inputs = []
        for name, value_type, is_widget in inputs:
            item = {"name": name, "type": value_type, "link": None}
            if is_widget:
                item["widget"] = {"name": name}
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
        target_matches = [
            index
            for index, item in enumerate(target["inputs"])
            if item["name"] == target_input
        ]
        if len(target_matches) != 1:
            raise ValueError(
                f"{target['type']} {target['id']} has no unique {target_input} input"
            )
        target_slot = target_matches[0]
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
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"i2i-consistency:{self.slug}")),
            "revision": 0,
            "last_node_id": max(node["id"] for node in self.nodes),
            "last_link_id": max(link[0] for link in self.links),
            "nodes": self.nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {
                "i2i_consistency_suite": {
                    "workflow_slug": self.slug,
                    "version": 1,
                    "target_model": self.target_model,
                }
            },
            "version": 0.4,
        }


def load_image(
    graph: Graph,
    *,
    title: str,
    pos: tuple[int, int],
    mode: int = 0,
) -> dict:
    return graph.add(
        "LoadImage",
        title=title,
        pos=pos,
        inputs=(
            ("image", "COMBO", True),
            ("upload", "IMAGEUPLOAD", True),
        ),
        outputs=(("IMAGE", "IMAGE"), ("MASK", "MASK")),
        widgets=(PLACEHOLDER, "image"),
        mode=mode,
        size=(300, 320),
    )


def unet_loader(graph: Graph, *, pos: tuple[int, int]) -> dict:
    return graph.add(
        "UNETLoader",
        title="Flux.2 Klein 9B diffusion model",
        pos=pos,
        inputs=(
            ("unet_name", "COMBO", True),
            ("weight_dtype", "COMBO", True),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(KLEIN_MODEL, "default"),
    )


def clip_loader(
    graph: Graph,
    *,
    name: str,
    clip_type: str,
    pos: tuple[int, int],
) -> dict:
    return graph.add(
        "CLIPLoader",
        title=f"{clip_type} text encoder",
        pos=pos,
        inputs=(
            ("clip_name", "COMBO", True),
            ("type", "COMBO", True),
            ("device", "COMBO", True),
        ),
        outputs=(("CLIP", "CLIP"),),
        widgets=(name, clip_type, "default"),
    )


def vae_loader(graph: Graph, *, name: str, pos: tuple[int, int]) -> dict:
    return graph.add(
        "VAELoader",
        title="Precision VAE",
        pos=pos,
        inputs=(("vae_name", "COMBO", True),),
        outputs=(("VAE", "VAE"),),
        widgets=(name,),
    )


def text_encode(
    graph: Graph,
    *,
    title: str,
    prompt: str,
    pos: tuple[int, int],
    mode: int = 0,
) -> dict:
    return graph.add(
        "CLIPTextEncode",
        title=title,
        pos=pos,
        inputs=(
            ("clip", "CLIP", False),
            ("text", "STRING", True),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
        widgets=(prompt,),
        mode=mode,
        size=(360, 190),
    )


def ksampler(
    graph: Graph,
    *,
    title: str,
    pos: tuple[int, int],
    mode: int = 0,
    steps: int = 28,
    cfg: float = 3.0,
    denoise: float = 0.72,
) -> dict:
    return graph.add(
        "KSampler",
        title=title,
        pos=pos,
        inputs=(
            ("model", "MODEL", False),
            ("seed", "INT", True),
            ("steps", "INT", True),
            ("cfg", "FLOAT", True),
            ("sampler_name", "COMBO", True),
            ("scheduler", "COMBO", True),
            ("positive", "CONDITIONING", False),
            ("negative", "CONDITIONING", False),
            ("latent_image", "LATENT", False),
            ("denoise", "FLOAT", True),
        ),
        outputs=(("LATENT", "LATENT"),),
        widgets=(347129883, "fixed", steps, cfg, "euler", "beta", denoise),
        mode=mode,
        size=(330, 430),
    )


def vae_decode(
    graph: Graph,
    *,
    title: str,
    pos: tuple[int, int],
    mode: int = 0,
) -> dict:
    return graph.add(
        "VAEDecode",
        title=title,
        pos=pos,
        inputs=(("samples", "LATENT", False), ("vae", "VAE", False)),
        outputs=(("IMAGE", "IMAGE"),),
        mode=mode,
    )


def save_image(
    graph: Graph,
    *,
    title: str,
    prefix: str,
    pos: tuple[int, int],
) -> dict:
    return graph.add(
        "SaveImage",
        title=title,
        pos=pos,
        inputs=(
            ("images", "IMAGE", False),
            ("filename_prefix", "STRING", True),
        ),
        outputs=(("images", "IMAGE"),),
        widgets=(prefix,),
        size=(320, 260),
    )


def identity_score(graph: Graph, *, title: str, pos: tuple[int, int]) -> dict:
    return graph.add(
        "OpenCVIdentityScore",
        title=title,
        pos=pos,
        inputs=(
            ("reference_image", "IMAGE", False),
            ("generated_image", "IMAGE", False),
            ("extra_metadata", "EXTRA_METADATA", False),
            ("catalog_root", "STRING", True),
            ("subject_name", "STRING", True),
            ("catalog_mode", "COMBO", True),
            ("catalog_aggregation", "COMBO", True),
            ("max_catalog_images", "INT", True),
            ("include_subfolders", "BOOLEAN", True),
            ("face_score_threshold", "FLOAT", True),
            ("same_identity_threshold", "FLOAT", True),
            ("face_selection", "COMBO", True),
            ("write_manifest", "BOOLEAN", True),
            ("manifest_dir", "STRING", True),
            ("run_label", "STRING", True),
            ("metadata_key", "STRING", True),
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
            "i2i-consistency",
            "identity_score_report",
        ),
        size=(390, 420),
    )


def note(graph: Graph, *, title: str, text: str, pos: tuple[int, int]) -> dict:
    return graph.add(
        "MarkdownNote",
        title=title,
        pos=pos,
        widgets=(text,),
        size=(500, 360),
    )


def build_masked() -> dict:
    graph = Graph("klein-9b-masked-precision-i2i", "Flux2-Klein-9B")
    original = load_image(
        graph,
        title="Original image + editable mask",
        pos=(-1400, -180),
    )
    grow = graph.add(
        "GrowMask",
        title="Grow mask for a clean seam",
        pos=(-1040, 160),
        inputs=(
            ("mask", "MASK", False),
            ("expand", "INT", True),
            ("tapered_corners", "BOOLEAN", True),
        ),
        outputs=(("MASK", "MASK"),),
        widgets=(8, True),
    )
    model = unet_loader(graph, pos=(-1400, -700))
    lora = graph.add(
        "LoraLoaderModelOnly",
        title="Klein consistency LoRA",
        pos=(-1040, -700),
        inputs=(
            ("model", "MODEL", False),
            ("lora_name", "COMBO", True),
            ("strength_model", "FLOAT", True),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(KLEIN_LORA, 1.0),
    )
    clip = clip_loader(
        graph,
        name=KLEIN_CLIP,
        clip_type="flux2",
        pos=(-1400, -490),
    )
    vae = vae_loader(graph, name=KLEIN_VAE, pos=(-1400, -310))
    positive = text_encode(
        graph,
        title="Precise masked edit instruction",
        prompt=(
            "Edit only the painted mask. Preserve the original identity, pose, "
            "camera, lighting, background, and every unmasked pixel."
        ),
        pos=(-660, -620),
    )
    negative = text_encode(
        graph,
        title="Artifact exclusions",
        prompt=(
            "identity drift, altered background, duplicate subject, warped face, "
            "bad anatomy, text, watermark"
        ),
        pos=(-660, -380),
    )
    inpaint = graph.add(
        "VAEEncodeForInpaint",
        title="Masked latent derived from original image",
        pos=(-660, -80),
        inputs=(
            ("pixels", "IMAGE", False),
            ("vae", "VAE", False),
            ("mask", "MASK", False),
            ("grow_mask_by", "INT", True),
        ),
        outputs=(("LATENT", "LATENT"),),
        widgets=(6,),
    )
    sampler = ksampler(
        graph,
        title="Sample one masked Klein edit",
        pos=(-180, -360),
        steps=28,
        cfg=3.0,
        denoise=0.68,
    )
    decode = vae_decode(
        graph,
        title="Decode masked edit",
        pos=(220, -280),
    )
    composite = graph.add(
        "ImageCompositeMasked",
        title="Composite edit over untouched original",
        pos=(560, -240),
        inputs=(
            ("destination", "IMAGE", False),
            ("source", "IMAGE", False),
            ("x", "INT", True),
            ("y", "INT", True),
            ("resize_source", "BOOLEAN", True),
            ("mask", "MASK", False),
        ),
        outputs=(("IMAGE", "IMAGE"),),
        widgets=(0, 0, False),
        size=(350, 260),
    )
    score = identity_score(
        graph,
        title="Audit identity: original vs masked result",
        pos=(980, 80),
    )
    output = save_image(
        graph,
        title="Save masked precision result",
        prefix="agent/i2i-consistency/klein-masked",
        pos=(980, -260),
    )
    note(
        graph,
        title="Masked precision instructions",
        text=(
            "## Klein 9B masked precision I2I\n\nPaint the mask in the Load Image "
            "node. The latent is encoded from the original pixels and grown mask, "
            "then the decoded edit is composited back over the untouched original. "
            "The consistency LoRA is active on the one sampler model path. It can "
            "be bypassed as an optional comparison without rewiring."
        ),
        pos=(-1400, 500),
    )

    graph.connect(original, 1, grow, "mask")
    graph.connect(model, 0, lora, "model")
    graph.connect(clip, 0, positive, "clip")
    graph.connect(clip, 0, negative, "clip")
    graph.connect(original, 0, inpaint, "pixels")
    graph.connect(vae, 0, inpaint, "vae")
    graph.connect(grow, 0, inpaint, "mask")
    graph.connect(lora, 0, sampler, "model")
    graph.connect(positive, 0, sampler, "positive")
    graph.connect(negative, 0, sampler, "negative")
    graph.connect(inpaint, 0, sampler, "latent_image")
    graph.connect(sampler, 0, decode, "samples")
    graph.connect(vae, 0, decode, "vae")
    graph.connect(original, 0, composite, "destination")
    graph.connect(decode, 0, composite, "source")
    graph.connect(grow, 0, composite, "mask")
    graph.connect(original, 0, score, "reference_image")
    graph.connect(composite, 0, score, "generated_image")
    graph.connect(composite, 0, output, "images")
    return graph.workflow()


def build_pulid() -> dict:
    graph = Graph("klein-9b-pulid-identity-lab", "Flux2-Klein-9B")
    scene = load_image(
        graph,
        title="Scene reference - composition and edit source",
        pos=(-1500, -260),
    )
    face = load_image(
        graph,
        title="Face identity reference - close clear portrait",
        pos=(-1500, 140),
    )
    model = unet_loader(graph, pos=(-1500, -760))
    clip = clip_loader(
        graph,
        name=KLEIN_CLIP,
        clip_type="flux2",
        pos=(-1140, -760),
    )
    vae = vae_loader(graph, name=KLEIN_VAE, pos=(-780, -760))
    insightface = graph.add(
        "PuLIDInsightFaceLoader",
        title="Load InsightFace (PuLID)",
        pos=(-1140, 140),
        inputs=(("provider", "COMBO", True),),
        outputs=(("INSIGHTFACE", "INSIGHTFACE"),),
        widgets=("CUDA",),
    )
    eva_clip = graph.add(
        "PuLIDEVACLIPLoader",
        title="Load EVA-CLIP (PuLID)",
        pos=(-780, 140),
        outputs=(("EVA_CLIP", "EVA_CLIP"),),
    )
    pulid_model = graph.add(
        "PuLIDModelLoader",
        title="Load PuLID Flux.2 Klein v2",
        pos=(-420, 140),
        inputs=(("pulid_file", "COMBO", True),),
        outputs=(("PULID_MODEL", "PULID_MODEL"),),
        widgets=("pulid_flux2_klein_v2.safetensors",),
    )
    apply_pulid = graph.add(
        "ApplyPuLIDFlux2",
        title="Apply face identity to Klein model",
        pos=(-60, -20),
        inputs=(
            ("model", "MODEL", False),
            ("pulid_model", "PULID_MODEL", False),
            ("strength", "FLOAT", True),
            ("eva_clip", "EVA_CLIP", False),
            ("face_analysis", "INSIGHTFACE", False),
            ("image", "IMAGE", False),
            ("face_index", "INT", True),
            ("debug_mode", "BOOLEAN", True),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(1.4, 0, False),
        size=(360, 300),
    )
    positive = text_encode(
        graph,
        title="Scene edit instruction",
        prompt=(
            "Preserve the scene reference composition, pose, lighting, wardrobe, "
            "and background while matching the face identity reference."
        ),
        pos=(-760, -500),
    )
    negative = text_encode(
        graph,
        title="Identity artifact exclusions",
        prompt=(
            "wrong identity, face distortion, duplicate face, altered background, "
            "bad anatomy, text, watermark"
        ),
        pos=(-360, -500),
    )
    scene_latent = graph.add(
        "VAEEncode",
        title="Encode scene reference latent",
        pos=(-760, -250),
        inputs=(("pixels", "IMAGE", False), ("vae", "VAE", False)),
        outputs=(("LATENT", "LATENT"),),
    )
    reference = graph.add(
        "ReferenceLatent",
        title="Attach scene reference to conditioning",
        pos=(-360, -250),
        inputs=(
            ("conditioning", "CONDITIONING", False),
            ("latent", "LATENT", False),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
    )
    sampler = ksampler(
        graph,
        title="Sample scene + PuLID identity",
        pos=(360, -300),
        steps=28,
        cfg=3.0,
        denoise=0.72,
    )
    decode = vae_decode(graph, title="Decode PuLID result", pos=(760, -220))
    output = save_image(
        graph,
        title="Save PuLID identity result",
        prefix="agent/i2i-consistency/klein-pulid",
        pos=(1120, -280),
    )
    score = identity_score(
        graph,
        title="Audit face identity reference vs result",
        pos=(1120, 80),
    )
    note(
        graph,
        title="PuLID scope and limitations",
        text=(
            "## Experimental PuLID identity lab\n\nPuLID is an experimental "
            "face-only / face identity control. The scene image controls composition "
            "and the separate face portrait controls identity. Body consistency is "
            "not supported by this node and remains on the upstream roadmap. Use the "
            "OpenCV score as an audit signal, not a guarantee."
        ),
        pos=(-1500, 540),
    )

    graph.connect(model, 0, apply_pulid, "model")
    graph.connect(pulid_model, 0, apply_pulid, "pulid_model")
    graph.connect(eva_clip, 0, apply_pulid, "eva_clip")
    graph.connect(insightface, 0, apply_pulid, "face_analysis")
    graph.connect(face, 0, apply_pulid, "image")
    graph.connect(clip, 0, positive, "clip")
    graph.connect(clip, 0, negative, "clip")
    graph.connect(scene, 0, scene_latent, "pixels")
    graph.connect(vae, 0, scene_latent, "vae")
    graph.connect(positive, 0, reference, "conditioning")
    graph.connect(scene_latent, 0, reference, "latent")
    graph.connect(apply_pulid, 0, sampler, "model")
    graph.connect(reference, 0, sampler, "positive")
    graph.connect(negative, 0, sampler, "negative")
    graph.connect(scene_latent, 0, sampler, "latent_image")
    graph.connect(sampler, 0, decode, "samples")
    graph.connect(vae, 0, decode, "vae")
    graph.connect(decode, 0, output, "images")
    graph.connect(face, 0, score, "reference_image")
    graph.connect(decode, 0, score, "generated_image")
    return graph.workflow()


def build_qwen() -> dict:
    graph = Graph(
        "qwen-2511-q4km-precision-multiref",
        "Qwen-Image-Edit-2511-Q4_K_M.gguf",
    )
    primary = load_image(
        graph,
        title="Primary reference - active edit source",
        pos=(-1600, -260),
    )
    optional_two = load_image(
        graph,
        title="Optional reference 2 - bypassed by default",
        pos=(-1600, 140),
        mode=4,
    )
    optional_three = load_image(
        graph,
        title="Optional reference 3 - bypassed by default",
        pos=(-1600, 540),
        mode=4,
    )
    unet = graph.add(
        "UnetLoaderGGUF",
        title="Qwen Image Edit 2511 Q4_K_M",
        pos=(-1600, -780),
        inputs=(("unet_name", "COMBO", True),),
        outputs=(("MODEL", "MODEL"),),
        widgets=(QWEN_MODEL,),
    )
    lora = graph.add(
        "LoraLoaderModelOnly",
        title="Optional Lightning 4-step LoRA - bypassed for accuracy",
        pos=(-1220, -780),
        inputs=(
            ("model", "MODEL", False),
            ("lora_name", "COMBO", True),
            ("strength_model", "FLOAT", True),
        ),
        outputs=(("MODEL", "MODEL"),),
        widgets=(QWEN_LORA, 1.0),
        mode=4,
        size=(370, 200),
    )
    clip = clip_loader(
        graph,
        name=QWEN_CLIP,
        clip_type="qwen_image",
        pos=(-820, -780),
    )
    vae = vae_loader(graph, name=QWEN_VAE, pos=(-440, -780))
    primary_conditioning = graph.add(
        "TextEncodeQwenImageEdit",
        title="Active single-reference precision edit",
        pos=(-1020, -320),
        inputs=(
            ("clip", "CLIP", False),
            ("prompt", "STRING", True),
            ("vae", "VAE", False),
            ("image", "IMAGE", False),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
        widgets=(
            "Edit the primary image precisely. Preserve identity, geometry, "
            "camera, lighting, and background unless explicitly requested.",
        ),
        size=(410, 240),
    )
    negative = text_encode(
        graph,
        title="Qwen artifact exclusions",
        prompt=(
            "low quality, identity drift, duplicate subject, distorted anatomy, "
            "mismatched perspective, text, watermark"
        ),
        pos=(-600, -440),
    )
    primary_latent = graph.add(
        "VAEEncode",
        title="Encode primary edit latent",
        pos=(-1020, -20),
        inputs=(("pixels", "IMAGE", False), ("vae", "VAE", False)),
        outputs=(("LATENT", "LATENT"),),
    )
    active_sampler = ksampler(
        graph,
        title="Active 28-step accuracy sampler",
        pos=(-120, -340),
        steps=28,
        cfg=3.5,
        denoise=0.75,
    )
    active_decode = vae_decode(
        graph,
        title="Decode active precision result",
        pos=(300, -260),
    )
    output = save_image(
        graph,
        title="Save active Qwen precision result",
        prefix="agent/i2i-consistency/qwen-2511-q4km",
        pos=(680, -280),
    )
    optional_conditioning = graph.add(
        "TextEncodeQwenImageEditPlus",
        title="Optional three-reference conditioner - enable together",
        pos=(-1020, 360),
        inputs=(
            ("clip", "CLIP", False),
            ("prompt", "STRING", True),
            ("vae", "VAE", False),
            ("image1", "IMAGE", False),
            ("image2", "IMAGE", False),
            ("image3", "IMAGE", False),
        ),
        outputs=(("CONDITIONING", "CONDITIONING"),),
        widgets=(
            "Use picture 1 as the edit source; borrow only the explicitly requested "
            "identity, outfit, or style cues from pictures 2 and 3.",
        ),
        mode=4,
        size=(430, 300),
    )
    dormant_sampler = ksampler(
        graph,
        title="Optional multi-reference sampler - bypassed",
        pos=(-420, 420),
        mode=4,
        steps=28,
        cfg=3.5,
        denoise=0.75,
    )
    dormant_decode = vae_decode(
        graph,
        title="Optional multi-reference decode - bypassed",
        pos=(20, 460),
        mode=4,
    )
    preview = graph.add(
        "PreviewImage",
        title="Optional multi-reference preview - bypassed",
        pos=(380, 460),
        inputs=(("images", "IMAGE", False),),
        outputs=(("images", "IMAGE"),),
        mode=4,
        size=(320, 260),
    )
    note(
        graph,
        title="Precision and multi-reference controls",
        text=(
            "## Qwen 2511 Q4_K_M precision I2I\n\nThe default active route uses "
            "only the primary reference, 28 steps, and CFG 3.5. The Lightning LoRA "
            "is bypassed for accuracy. References 2 and 3, the Plus conditioner, "
            "second sampler, decoder, and preview form one fully wired dormant lane. "
            "Enable that entire lane together; do not enable only an optional loader."
        ),
        pos=(-1600, 900),
    )

    graph.connect(unet, 0, lora, "model")
    graph.connect(clip, 0, primary_conditioning, "clip")
    graph.connect(vae, 0, primary_conditioning, "vae")
    graph.connect(primary, 0, primary_conditioning, "image")
    graph.connect(clip, 0, negative, "clip")
    graph.connect(primary, 0, primary_latent, "pixels")
    graph.connect(vae, 0, primary_latent, "vae")
    graph.connect(lora, 0, active_sampler, "model")
    graph.connect(primary_conditioning, 0, active_sampler, "positive")
    graph.connect(negative, 0, active_sampler, "negative")
    graph.connect(primary_latent, 0, active_sampler, "latent_image")
    graph.connect(active_sampler, 0, active_decode, "samples")
    graph.connect(vae, 0, active_decode, "vae")
    graph.connect(active_decode, 0, output, "images")

    graph.connect(clip, 0, optional_conditioning, "clip")
    graph.connect(vae, 0, optional_conditioning, "vae")
    graph.connect(primary, 0, optional_conditioning, "image1")
    graph.connect(optional_two, 0, optional_conditioning, "image2")
    graph.connect(optional_three, 0, optional_conditioning, "image3")
    graph.connect(lora, 0, dormant_sampler, "model")
    graph.connect(optional_conditioning, 0, dormant_sampler, "positive")
    graph.connect(negative, 0, dormant_sampler, "negative")
    graph.connect(primary_latent, 0, dormant_sampler, "latent_image")
    graph.connect(dormant_sampler, 0, dormant_decode, "samples")
    graph.connect(vae, 0, dormant_decode, "vae")
    graph.connect(dormant_decode, 0, preview, "images")
    return graph.workflow()


def write_workflow(path: Path, workflow: dict) -> None:
    path.write_text(
        json.dumps(workflow, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the deterministic i2i consistency workflow suite."
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)

    for name, workflow in (
        (MASKED_NAME, build_masked()),
        (PULID_NAME, build_pulid()),
        (QWEN_NAME, build_qwen()),
    ):
        write_workflow(args.output_root / name, workflow)


if __name__ == "__main__":
    main()
