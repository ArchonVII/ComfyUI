"""Emit deterministic, editable Flux 9B identity-lab experiment templates."""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path


OUTPUT_DIR = Path("user/default/workflows/agent")
PLACEHOLDER = "wan_q4_placeholder.ppm"
FACE_SWAP_NAME = "39 - Flux 9B Identity Lab - Face Swap.json"
IDENTITY_I2I_NAME = "40 - Flux 9B Identity Lab - Identity I2I.json"

MODEL = r"Flux\9b\DarkBeast-Klein9b-V2-BFS-FP8-ComfyUI.safetensors"
CLIP = r"Qwen\qwen_3_8b_fp8mixed.safetensors"
VAE = "flux2-vae.safetensors"
LORAS = (
    r"Flux\9b\1 ------ Helper\Flux2-Klein-9B-consistency-V2.safetensors",
    r"Flux\9b\1 ------ Helper\Flux2-Klein-Image-RestoreV1.safetensors",
    r"Flux\9b\1 ------ Helper\better_skin_darkbeast2_lora.safetensors",
)
PULID = "pulid_flux2_klein_v2.safetensors"


@dataclass
class Graph:
    slug: str
    mode: str
    nodes: list[dict] = field(default_factory=list)
    links: list[list] = field(default_factory=list)

    def add(self, node_type, *, title, pos, inputs=(), outputs=(), widgets=(), size=(320, 220)):
        node_id = len(self.nodes) + 1
        node = {
            "id": node_id,
            "type": node_type,
            "pos": list(pos),
            "size": list(size),
            "flags": {},
            "order": len(self.nodes),
            "mode": 0,
            "inputs": [
                {"name": name, "type": value_type, "link": None}
                for name, value_type in inputs
            ],
            "outputs": [
                {"name": name, "type": value_type, "slot_index": index, "links": []}
                for index, (name, value_type) in enumerate(outputs)
            ],
            "title": title,
            "properties": {"Node name for S&R": node_type},
            "widgets_values": list(widgets),
        }
        self.nodes.append(node)
        return node

    def connect(self, source, source_slot, target, input_name):
        target_slot = next(
            index for index, item in enumerate(target["inputs"])
            if item["name"] == input_name
        )
        if target["inputs"][target_slot]["link"] is not None:
            raise ValueError(f"{target['title']}.{input_name} is already connected")
        link_id = len(self.links) + 1
        value_type = source["outputs"][source_slot]["type"]
        self.links.append([link_id, source["id"], source_slot, target["id"], target_slot, value_type])
        source["outputs"][source_slot]["links"].append(link_id)
        target["inputs"][target_slot]["link"] = link_id

    def workflow(self):
        return {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"flux-identity-lab:{self.slug}")),
            "revision": 0,
            "last_node_id": max(item["id"] for item in self.nodes),
            "last_link_id": max(item[0] for item in self.links),
            "nodes": self.nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {
                "identity_lab_template": {
                    "mode": self.mode,
                    "version": 1,
                    "target_model": "Flux2-Klein-9B",
                }
            },
            "version": 0.4,
        }


def add(graph, node_type, title, pos, inputs=(), outputs=(), widgets=(), size=(320, 220)):
    return graph.add(node_type, title=title, pos=pos, inputs=inputs, outputs=outputs, widgets=widgets, size=size)


def load_image(graph, title, pos):
    return add(graph, "LoadImage", title, pos, (("image", "COMBO"),), (("IMAGE", "IMAGE"), ("MASK", "MASK")), (PLACEHOLDER,), (300, 280))


def model_stack(graph, pos):
    model = add(graph, "UNETLoader", "IDENTITY_LAB_MODEL", pos, (("unet_name", "COMBO"), ("weight_dtype", "COMBO")), (("MODEL", "MODEL"),), (MODEL, "default"))
    loras = []
    previous = model
    for index, name in enumerate(LORAS, 1):
        lora = add(graph, "LoraLoaderModelOnly", f"IDENTITY_LAB_LORA_{index}", (pos[0] + 360 * index, pos[1]), (("model", "MODEL"), ("lora_name", "COMBO"), ("strength_model", "FLOAT")), (("MODEL", "MODEL"),), (name, 0.0), (340, 210))
        graph.connect(previous, 0, lora, "model")
        loras.append(lora)
        previous = lora
    clip = add(graph, "CLIPLoader", "Flux.2 Qwen 8B text encoder", (pos[0], pos[1] + 300), (("clip_name", "COMBO"), ("type", "COMBO")), (("CLIP", "CLIP"),), (CLIP, "flux2"))
    vae = add(graph, "VAELoader", "Flux.2 VAE", (pos[0] + 360, pos[1] + 300), (("vae_name", "COMBO"),), (("VAE", "VAE"),), (VAE,))
    return previous, clip, vae


def sampler(graph, pos):
    return add(graph, "KSampler", "IDENTITY_LAB_SAMPLER", pos, (("model", "MODEL"), ("seed", "INT"), ("steps", "INT"), ("cfg", "FLOAT"), ("sampler_name", "COMBO"), ("scheduler", "COMBO"), ("positive", "CONDITIONING"), ("negative", "CONDITIONING"), ("latent_image", "LATENT"), ("denoise", "FLOAT")), (("LATENT", "LATENT"),), (347129883, "fixed", 28, 3.0, "euler", "beta", 0.72), (340, 430))


def score(graph, mode, pos):
    return add(graph, "DualIdentityScore", "IDENTITY_LAB_SCORE", pos, (("base_image", "IMAGE"), ("reference_image", "IMAGE"), ("generated_image", "IMAGE"), ("experiment_mode", "COMBO"), ("face_score_threshold", "FLOAT"), ("same_identity_threshold", "FLOAT"), ("face_selection", "COMBO"), ("write_manifest", "BOOLEAN"), ("manifest_dir", "STRING"), ("run_label", "STRING"), ("metadata_key", "STRING"), ("experiment_id", "STRING"), ("run_id", "STRING")), (("reference_cosine_similarity", "FLOAT"), ("reference_detected", "BOOLEAN"), ("reference_same_identity", "BOOLEAN"), ("base_cosine_similarity", "FLOAT"), ("base_detected", "BOOLEAN"), ("base_same_identity", "BOOLEAN"), ("generated_detected", "BOOLEAN"), ("active_cosine_similarity", "FLOAT"), ("active_same_identity", "BOOLEAN"), ("rankable", "BOOLEAN"), ("report_json", "STRING"), ("extra_metadata", "EXTRA_METADATA")), (mode, 0.7, 0.363, "largest", True, "default/identity_score_runs", f"identity-lab-{mode}", "identity_score_report"), (420, 390))


def output_nodes(graph, image, prefix, pos):
    save = add(graph, "SaveImage", "Save identity-lab output", pos, (("images", "IMAGE"), ("filename_prefix", "STRING")), (("IMAGE", "IMAGE"),), (prefix,), (320, 220))
    preview = add(graph, "PreviewImage", "Preview identity-lab final output", (pos[0] + 360, pos[1]), (("images", "IMAGE"),), (("IMAGE", "IMAGE"),), (), (320, 220))
    graph.connect(image, 0, save, "images")
    graph.connect(image, 0, preview, "images")


def build_face_swap():
    graph = Graph("flux-9b-identity-lab-face-swap", "face_swap")
    base = load_image(graph, "IDENTITY_LAB_BASE_IMAGE", (-1900, -100))
    reference = load_image(graph, "IDENTITY_LAB_REFERENCE_IMAGE", (-1900, 300))
    model, clip, vae = model_stack(graph, (-1900, -850))
    detector = add(graph, "UltralyticsDetectorProvider", "Face/head detector", (-1500, 700), (("model_name", "COMBO"),), (("BBOX_DETECTOR", "BBOX_DETECTOR"), ("SEGM_DETECTOR", "SEGM_DETECTOR")), ("bbox/face_yolov8m.pt",))
    sam = add(graph, "SAMLoader", "SAM refinement model", (-1500, 990), (("model_name", "COMBO"), ("device_mode", "COMBO")), (("SAM_MODEL", "SAM_MODEL"),), ("sam_vit_b_01ec64.pth", "AUTO"))
    detects = []
    masks = []
    crops = []
    for label, image, y in (("target", base, -100), ("source", reference, 350)):
        detected = add(graph, "BboxDetectorSEGS", f"Detect {label} face/head", (-1140, y), (("bbox_detector", "BBOX_DETECTOR"), ("image", "IMAGE"), ("threshold", "FLOAT"), ("dilation", "INT"), ("crop_factor", "FLOAT"), ("drop_size", "INT"), ("labels", "STRING")), (("SEGS", "SEGS"),), (0.55, 4, 3.0, 10, "all"), (350, 300))
        refined = add(graph, "SAMDetectorCombined", f"SAM refine {label} face/head", (-720, y), (("sam_model", "SAM_MODEL"), ("segs", "SEGS"), ("image", "IMAGE"), ("detection_hint", "COMBO"), ("dilation", "INT"), ("threshold", "FLOAT"), ("bbox_expansion", "INT"), ("mask_hint_threshold", "FLOAT"), ("mask_hint_use_negative", "COMBO")), (("MASK", "MASK"),), ("center-1", 0, 0.93, 24, 0.7, "False"), (370, 360))
        crop = add(graph, "BatchCropFromMaskAdvanced", f"Crop {label} head region", (-280, y), (("original_images", "IMAGE"), ("masks", "MASK"), ("crop_size_mult", "FLOAT"), ("bbox_smooth_alpha", "FLOAT")), (("original_images", "IMAGE"), ("cropped_images", "IMAGE"), ("cropped_masks", "MASK"), ("combined_crop_image", "IMAGE"), ("combined_crop_masks", "MASK"), ("bboxes", "BBOX"), ("combined_bounding_box", "BBOX"), ("bbox_width", "INT"), ("bbox_height", "INT")), (2.35 if label == "target" else 2.1, 0.5), (400, 300))
        graph.connect(detector, 0, detected, "bbox_detector")
        graph.connect(image, 0, detected, "image")
        graph.connect(sam, 0, refined, "sam_model")
        graph.connect(detected, 0, refined, "segs")
        graph.connect(image, 0, refined, "image")
        graph.connect(image, 0, crop, "original_images")
        graph.connect(refined, 0, crop, "masks")
        detects.append(detected); masks.append(refined); crops.append(crop)
    target_crop, source_crop = crops
    pixel_budget = add(graph, "ImageScaleToTotalPixels", "IDENTITY_LAB_PIXEL_BUDGET", (200, -100), (("image", "IMAGE"), ("upscale_method", "COMBO"), ("megapixels", "FLOAT"), ("resolution_steps", "INT")), (("IMAGE", "IMAGE"),), ("lanczos", 1.5, 1), (330, 260))
    source_scale = add(graph, "ImageScaleToTotalPixels", "Scale source identity crop", (200, 350), (("image", "IMAGE"), ("upscale_method", "COMBO"), ("megapixels", "FLOAT"), ("resolution_steps", "INT")), (("IMAGE", "IMAGE"),), ("lanczos", 1.0, 1), (330, 260))
    target_encode = add(graph, "VAEEncode", "Encode target crop", (580, -100), (("pixels", "IMAGE"), ("vae", "VAE")), (("LATENT", "LATENT"),))
    source_encode = add(graph, "VAEEncode", "Encode source identity crop", (580, 350), (("pixels", "IMAGE"), ("vae", "VAE")), (("LATENT", "LATENT"),))
    prompt = add(graph, "CLIPTextEncode", "Face swap instruction", (580, -500), (("clip", "CLIP"), ("text", "STRING")), (("CONDITIONING", "CONDITIONING"),), ("Replace only the target face, visible head identity, hairline, and local head details with the source identity. Preserve the target body, pose, clothing, lighting, scene, camera, and background. Blend seamless realistic skin and neck boundaries.",), (430, 250))
    negative = add(graph, "CLIPTextEncode", "Face swap exclusions", (1040, -500), (("clip", "CLIP"), ("text", "STRING")), (("CONDITIONING", "CONDITIONING"),), ("wrong identity, duplicate face, warped eyes, altered body, altered clothing, altered background, text, watermark",), (400, 230))
    source_reference = add(graph, "ReferenceLatent", "Source identity reference latent", (1040, 240), (("conditioning", "CONDITIONING"), ("latent", "LATENT")), (("CONDITIONING", "CONDITIONING"),))
    target_reference = add(graph, "ReferenceLatent", "Target crop reference latent", (1400, 240), (("conditioning", "CONDITIONING"), ("latent", "LATENT")), (("CONDITIONING", "CONDITIONING"),))
    dimensions = add(graph, "GetImageSize", "Target crop dimensions", (1040, -40), (("image", "IMAGE"),), (("width", "INT"), ("height", "INT"), ("batch_size", "INT")), ())
    empty = add(graph, "EmptyFlux2LatentImage", "Target crop generation latent", (1400, -80), (("width", "INT"), ("height", "INT"), ("batch_size", "INT")), (("LATENT", "LATENT"),), (1024, 1024, 1))
    sampled = sampler(graph, (1800, -150))
    decoded = add(graph, "VAEDecode", "Decode generated head crop", (2180, -100), (("samples", "LATENT"), ("vae", "VAE")), (("IMAGE", "IMAGE"),))
    uncrop = add(graph, "BatchUncropAdvanced", "Composite generated head back to base", (2540, -100), (("original_images", "IMAGE"), ("cropped_images", "IMAGE"), ("cropped_masks", "MASK"), ("combined_crop_mask", "MASK"), ("bboxes", "BBOX"), ("combined_bounding_box", "BBOX"), ("border_blending", "FLOAT"), ("crop_rescale", "FLOAT"), ("use_combined_mask", "BOOLEAN"), ("use_square_mask", "BOOLEAN")), (("IMAGE", "IMAGE"),), (0.35, 1.0, True, True), (400, 350))
    audit = score(graph, "face_swap", (2980, 280))
    output_nodes(graph, uncrop, "identity_lab/face_swap", (2980, -100))
    note = add(graph, "MarkdownNote", "Face-swap experiment notes", (-1900, 1320), (), (), ("## Flux 9B face-swap identity lab\n\nBase image supplies body and scene. Reference image supplies identity. Face/head detection is refined by SAM before target-crop generation and uncrop compositing. The three Flux LoRAs start at model strength 0 for controlled runner sweeps.",), (850, 260))
    graph.connect(target_crop, 1, pixel_budget, "image")
    graph.connect(source_crop, 1, source_scale, "image")
    graph.connect(pixel_budget, 0, target_encode, "pixels"); graph.connect(vae, 0, target_encode, "vae")
    graph.connect(source_scale, 0, source_encode, "pixels"); graph.connect(vae, 0, source_encode, "vae")
    graph.connect(clip, 0, prompt, "clip"); graph.connect(clip, 0, negative, "clip")
    graph.connect(prompt, 0, source_reference, "conditioning"); graph.connect(source_encode, 0, source_reference, "latent")
    graph.connect(source_reference, 0, target_reference, "conditioning"); graph.connect(target_encode, 0, target_reference, "latent")
    graph.connect(pixel_budget, 0, dimensions, "image")
    graph.connect(dimensions, 0, empty, "width"); graph.connect(dimensions, 1, empty, "height"); graph.connect(dimensions, 2, empty, "batch_size")
    graph.connect(model, 0, sampled, "model"); graph.connect(target_reference, 0, sampled, "positive"); graph.connect(negative, 0, sampled, "negative"); graph.connect(empty, 0, sampled, "latent_image")
    graph.connect(sampled, 0, decoded, "samples"); graph.connect(vae, 0, decoded, "vae")
    graph.connect(base, 0, uncrop, "original_images"); graph.connect(decoded, 0, uncrop, "cropped_images"); graph.connect(target_crop, 2, uncrop, "cropped_masks"); graph.connect(target_crop, 4, uncrop, "combined_crop_mask"); graph.connect(target_crop, 5, uncrop, "bboxes"); graph.connect(target_crop, 6, uncrop, "combined_bounding_box")
    graph.connect(base, 0, audit, "base_image"); graph.connect(reference, 0, audit, "reference_image"); graph.connect(uncrop, 0, audit, "generated_image")
    return graph.workflow()


def build_identity_i2i():
    graph = Graph("flux-9b-identity-lab-identity-i2i", "identity_i2i")
    base = load_image(graph, "IDENTITY_LAB_BASE_IMAGE", (-1750, -100))
    reference = load_image(graph, "IDENTITY_LAB_REFERENCE_IMAGE", (-1750, 300))
    model, clip, vae = model_stack(graph, (-1750, -850))
    pixel_budget = add(graph, "ImageScaleToTotalPixels", "IDENTITY_LAB_PIXEL_BUDGET", (-1350, -100), (("image", "IMAGE"), ("upscale_method", "COMBO"), ("megapixels", "FLOAT"), ("resolution_steps", "INT")), (("IMAGE", "IMAGE"),), ("lanczos", 1.0, 1), (330, 260))
    encoded = add(graph, "VAEEncode", "Encode scaled base image", (-960, -100), (("pixels", "IMAGE"), ("vae", "VAE")), (("LATENT", "LATENT"),))
    prompt = add(graph, "CLIPTextEncode", "Identity I2I instruction", (-960, -500), (("clip", "CLIP"), ("text", "STRING")), (("CONDITIONING", "CONDITIONING"),), ("Preserve the base composition, pose, body, wardrobe, lighting, camera, and background while matching the reference face identity naturally.",), (430, 220))
    negative = add(graph, "CLIPTextEncode", "Identity I2I exclusions", (-500, -500), (("clip", "CLIP"), ("text", "STRING")), (("CONDITIONING", "CONDITIONING"),), ("wrong identity, duplicate face, altered body, altered background, distorted anatomy, text, watermark",), (400, 220))
    reference_latent = add(graph, "ReferenceLatent", "Base composition reference latent", (-500, -100), (("conditioning", "CONDITIONING"), ("latent", "LATENT")), (("CONDITIONING", "CONDITIONING"),))
    insight = add(graph, "PuLIDInsightFaceLoader", "PuLID face analysis", (-960, 350), (("provider", "COMBO"),), (("INSIGHTFACE", "INSIGHTFACE"),), ("CUDA",))
    eva = add(graph, "PuLIDEVACLIPLoader", "PuLID EVA-CLIP", (-590, 350), (), (("EVA_CLIP", "EVA_CLIP"),))
    pulid_model = add(graph, "PuLIDModelLoader", "Load Flux 2 Klein PuLID", (-220, 350), (("pulid_file", "COMBO"),), (("PULID_MODEL", "PULID_MODEL"),), (PULID,))
    pulid = add(graph, "ApplyPuLIDFlux2", "Apply reference identity to Flux model", (180, 100), (("model", "MODEL"), ("pulid_model", "PULID_MODEL"), ("strength", "FLOAT"), ("eva_clip", "EVA_CLIP"), ("face_analysis", "INSIGHTFACE"), ("image", "IMAGE"), ("face_index", "INT"), ("debug_mode", "BOOLEAN")), (("MODEL", "MODEL"),), (1.2, 0, False), (380, 310))
    sampled = sampler(graph, (600, -100))
    decoded = add(graph, "VAEDecode", "Decode identity I2I result", (990, -100), (("samples", "LATENT"), ("vae", "VAE")), (("IMAGE", "IMAGE"),))
    audit = score(graph, "identity_i2i", (1360, 280))
    output_nodes(graph, decoded, "identity_lab/identity_i2i", (1360, -100))
    add(graph, "MarkdownNote", "Identity I2I experiment notes", (-1750, 800), (), (), ("## Flux 9B identity-i2i lab\n\nThe base image is scaled by the runner-controlled megapixel budget, encoded for both the i2i latent and reference-latent composition. The separate reference image drives PuLID identity conditioning. The three Flux LoRAs remain at model strength 0 until a run patches them.",), (850, 250))
    graph.connect(base, 0, pixel_budget, "image"); graph.connect(pixel_budget, 0, encoded, "pixels"); graph.connect(vae, 0, encoded, "vae")
    graph.connect(clip, 0, prompt, "clip"); graph.connect(clip, 0, negative, "clip")
    graph.connect(prompt, 0, reference_latent, "conditioning"); graph.connect(encoded, 0, reference_latent, "latent")
    graph.connect(model, 0, pulid, "model"); graph.connect(pulid_model, 0, pulid, "pulid_model"); graph.connect(eva, 0, pulid, "eva_clip"); graph.connect(insight, 0, pulid, "face_analysis"); graph.connect(reference, 0, pulid, "image")
    graph.connect(pulid, 0, sampled, "model"); graph.connect(reference_latent, 0, sampled, "positive"); graph.connect(negative, 0, sampled, "negative"); graph.connect(encoded, 0, sampled, "latent_image")
    graph.connect(sampled, 0, decoded, "samples"); graph.connect(vae, 0, decoded, "vae")
    graph.connect(base, 0, audit, "base_image"); graph.connect(reference, 0, audit, "reference_image"); graph.connect(decoded, 0, audit, "generated_image")
    return graph.workflow()


def write(path, workflow):
    path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Build deterministic Flux identity-lab workflow templates.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_DIR)
    output_root = parser.parse_args().output_root
    output_root.mkdir(parents=True, exist_ok=True)
    write(output_root / FACE_SWAP_NAME, build_face_swap())
    write(output_root / IDENTITY_I2I_NAME, build_identity_i2i())


if __name__ == "__main__":
    main()
