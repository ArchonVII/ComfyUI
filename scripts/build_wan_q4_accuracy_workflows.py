"""Build WAN 2.2 Q4_K_M accuracy workflows for the local 16 GB runtime."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from build_adaptive_video_workflows import (
    clone_node,
    connect,
    image_scale_node,
    load_json,
    node,
    nodes,
    rebuild_links,
    replace_wan_conditioning_with_first_last,
    update_note,
)


SOURCE_NAME = "25 - HQ Wan 2.2 I2V - Fast Draft 81f.json"
REFERENCE_NAME = "29 - Arch Flux Klein 9B - All Custom Nodes I2I Reference v2.json"
FRAME_BLUEPRINT = "blueprints/Get Any Video Frame.json"

HIGH_MODEL = "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KMH.gguf"
LOW_MODEL = "wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KML.gguf"
PLACEHOLDER_IMAGE = "wan_q4_placeholder.ppm"

FORBIDDEN_NODE_TYPES = {
    "LoraLoaderModelOnly",
    "EasyCache",
    "WanVideoEnhanceAVideoKJ",
    "ApplyRifleXRoPE_WanVideo",
    "WanVideoNAG",
    "PathchSageAttentionKJ",
    "PatchSageAttentionKJ",
}

SPECS = (
    {
        "name": "31 - WAN Q4 FAST Preview 17f.json",
        "frames": 17,
        "megapixels": 0.10,
        "steps": 4,
        "split": 2,
        "slug": "preview-17f",
        "title": "WAN Q4 FAST Preview",
        "prompt": (
            "Preserve the source composition and subject identity. Add one clear, "
            "natural motion with stable anatomy and a steady camera."
        ),
    },
    {
        "name": "32 - WAN Q4 Prompt Camera 49f.json",
        "frames": 49,
        "megapixels": 0.25,
        "steps": 5,
        "split": 2,
        "slug": "prompt-camera-49f",
        "title": "WAN Q4 Prompt and Camera Accuracy",
        "prompt": (
            "(At 0 seconds: Preserve the source composition, subject identity, "
            "lighting, and camera position; the subject begins one clear natural action.)\n"
            "(At 1 second: Continue the same action smoothly; keep anatomy, clothing, "
            "background geometry, and facial features stable.)\n"
            "(At 3 seconds: Complete the action in a coherent final pose; use a gentle "
            "camera settle with no abrupt cut or viewpoint jump.)"
        ),
    },
    {
        "name": "33 - WAN Q4 Identity Audit 81f.json",
        "frames": 81,
        "megapixels": 0.40,
        "steps": 5,
        "split": 2,
        "slug": "identity-audit-81f",
        "title": "WAN Q4 Identity Audit",
        "prompt": (
            "Static medium close-up. Preserve the source person's facial structure, "
            "hair, skin tone, clothing, and background. The subject makes subtle natural "
            "movements and maintains a recognizable face throughout. Camera locked."
        ),
        "identity_indices": (40, 80),
    },
    {
        "name": "34 - WAN Q4 First Last Control 81f.json",
        "frames": 81,
        "megapixels": 0.40,
        "steps": 5,
        "split": 2,
        "slug": "first-last-81f",
        "title": "WAN Q4 First and Last Frame Control",
        "prompt": (
            "Create a single continuous shot that begins exactly from image 1 and "
            "transitions naturally to image 2. Preserve subject identity, scene geometry, "
            "lighting continuity, and physically plausible motion throughout."
        ),
        "start_end": True,
    },
)


def remove_nodes_by_type(workflow: dict, node_types: set[str]) -> None:
    removed_ids = {
        item["id"] for item in workflow["nodes"] if item["type"] in node_types
    }
    workflow["nodes"] = [
        item for item in workflow["nodes"] if item["id"] not in removed_ids
    ]
    workflow["links"] = [
        link
        for link in workflow["links"]
        if link[1] not in removed_ids and link[3] not in removed_ids
    ]


def image_from_batch_exemplar(repo_root: Path) -> dict:
    blueprint = load_json(repo_root / FRAME_BLUEPRINT)
    matches = [
        item
        for subgraph in blueprint["definitions"]["subgraphs"]
        for item in subgraph["nodes"]
        if item["type"] == "ImageFromBatch"
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one ImageFromBatch exemplar, found {len(matches)}")
    return matches[0]


def add_identity_audit(
    workflow: dict,
    *,
    reference: dict,
    decode: dict,
    identity_exemplar: dict,
    selector_exemplar: dict,
    indices: tuple[int, int],
) -> None:
    for offset, (label, index) in enumerate(
        zip(("middle", "final"), indices, strict=True)
    ):
        selector = clone_node(
            workflow,
            selector_exemplar,
            title=f"Select {label} frame for identity scoring",
            pos=[2260, 120 + offset * 260],
            widgets=[index, 1],
        )
        scorer = clone_node(
            workflow,
            identity_exemplar,
            title=f"Score source identity vs {label} frame",
            pos=[2600, 80 + offset * 680],
            widgets=[
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
                f"wan-q4-identity-{label}",
                f"wan_q4_identity_{label}",
            ],
        )
        connect(workflow, decode, 0, selector, "image", "IMAGE")
        connect(workflow, reference, 0, scorer, "reference_image", "IMAGE")
        connect(workflow, selector, 0, scorer, "generated_image", "IMAGE")


def configure_conditioning(
    workflow: dict,
    *,
    spec: dict,
    source: dict,
    scaler: dict,
    dimensions: dict,
) -> dict:
    if spec.get("start_end"):
        conditioning = replace_wan_conditioning_with_first_last(workflow)
    else:
        conditioning = node(workflow, "WanImageToVideo")

    conditioning["widgets_values"] = [832, 480, spec["frames"], 1]
    connect(workflow, dimensions, 0, conditioning, "width", "INT")
    connect(workflow, dimensions, 1, conditioning, "height", "INT")
    connect(workflow, scaler, 0, conditioning, "start_image", "IMAGE")

    if spec.get("start_end"):
        end_image = clone_node(
            workflow,
            source,
            title="Image 2 - end frame guide",
            pos=[source["pos"][0], source["pos"][1] + 430],
            widgets=[PLACEHOLDER_IMAGE, "image"],
        )
        end_scaler = image_scale_node(
            workflow,
            title="Match end frame to image 1",
            pos=[end_image["pos"][0] + 390, end_image["pos"][1]],
        )
        connect(workflow, end_image, 0, end_scaler, "image", "IMAGE")
        connect(workflow, dimensions, 0, end_scaler, "width", "INT")
        connect(workflow, dimensions, 1, end_scaler, "height", "INT")
        connect(workflow, end_scaler, 0, conditioning, "end_image", "IMAGE")

    return conditioning


def configure_sampling(workflow: dict, spec: dict) -> None:
    loaders = nodes(workflow, "UnetLoaderGGUF")
    loaders.sort(
        key=lambda item: 0
        if "high-noise" in item.get("title", "").lower()
        else 1
    )
    if len(loaders) != 2:
        raise ValueError(f"expected two GGUF loaders, found {len(loaders)}")
    loaders[0]["widgets_values"] = [HIGH_MODEL]
    loaders[1]["widgets_values"] = [LOW_MODEL]

    high_sampling = node(workflow, "ModelSamplingSD3", "high")
    low_sampling = node(workflow, "ModelSamplingSD3", "low")
    high_sampling["widgets_values"] = [5]
    low_sampling["widgets_values"] = [5]

    high_sampler = node(workflow, "KSamplerAdvanced", "high-noise")
    low_sampler = node(workflow, "KSamplerAdvanced", "low-noise")
    high_sampler["widgets_values"] = [
        "enable",
        283090201,
        "fixed",
        spec["steps"],
        1.0,
        "euler",
        "simple",
        0,
        spec["split"],
        "enable",
    ]
    low_sampler["widgets_values"] = [
        "disable",
        0,
        "fixed",
        spec["steps"],
        1.0,
        "euler",
        "simple",
        spec["split"],
        spec["steps"],
        "disable",
    ]
    connect(workflow, high_sampling, 0, high_sampler, "model", "MODEL")
    connect(workflow, low_sampling, 0, low_sampler, "model", "MODEL")


def build_workflows(repo_root: Path, output_root: Path) -> None:
    source_path = repo_root / "user/default/workflows/agent" / SOURCE_NAME
    reference_path = repo_root / "user/default/workflows/agent" / REFERENCE_NAME
    reference_workflow = load_json(reference_path)
    identity_exemplar = node(reference_workflow, "OpenCVIdentityScore")
    selector_exemplar = image_from_batch_exemplar(repo_root)

    output_root.mkdir(parents=True, exist_ok=True)
    for spec in SPECS:
        workflow = load_json(source_path)
        workflow["id"] = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"wan-q4-accuracy:{spec['name']}")
        )
        remove_nodes_by_type(workflow, FORBIDDEN_NODE_TYPES)
        rebuild_links(workflow)

        source = node(workflow, "LoadImage", "start frame")
        source["title"] = "Image 1 - start frame"
        source["widgets_values"] = [PLACEHOLDER_IMAGE, "image"]
        scaler = node(workflow, "ImageScaleToTotalPixels")
        scaler["title"] = f"Preserve aspect at {spec['megapixels']:.2f} MP"
        scaler["widgets_values"] = ["lanczos", spec["megapixels"], 32]
        dimensions = node(workflow, "GetImageSize")

        prompt = node(workflow, "CLIPTextEncode", "positive")
        prompt["widgets_values"] = [spec["prompt"]]
        negative = node(workflow, "CLIPTextEncode", "negative")
        negative["widgets_values"] = [""]

        configure_conditioning(
            workflow,
            spec=spec,
            source=source,
            scaler=scaler,
            dimensions=dimensions,
        )
        configure_sampling(workflow, spec)

        decode = node(workflow, "VAEDecodeTiled")
        decode["widgets_values"] = [512, 64, 24, 8]
        create_video = node(workflow, "CreateVideo")
        create_video["widgets_values"] = [16, 8]
        save_video = node(workflow, "SaveVideo")
        save_video["widgets_values"] = [
            f"agent/wan-q4/{spec['slug']}",
            "mp4",
            "h264",
        ]

        if spec.get("identity_indices"):
            add_identity_audit(
                workflow,
                reference=source,
                decode=decode,
                identity_exemplar=identity_exemplar,
                selector_exemplar=selector_exemplar,
                indices=spec["identity_indices"],
            )

        schedule = (
            "2+2 steps"
            if spec["steps"] == 4
            else "2 high-noise + 3 low-noise steps"
        )
        method = (
            "First/last-frame latent conditioning constrains both endpoints."
            if spec.get("start_end")
            else (
                "Middle and final decoded frames are scored against image 1 with the "
                "local OpenCV face-identity node."
                if spec.get("identity_indices")
                else (
                    "Timestamped prompt clauses test action and camera adherence."
                    if spec.get("name", "").startswith("32")
                    else "A short, low-pixel render validates seed, prompt, and composition."
                )
            )
        )
        update_note(
            workflow,
            (
                f"## {spec['title']}\n\n"
                f"{method}\n\n"
                f"Defaults: {spec['frames']} frames, {spec['megapixels']:.2f} MP, "
                f"16 fps, {schedule}, shift 5, CFG 1, Euler/simple.\n\n"
                "The selected FAST MOVE V2 checkpoints already contain Lightning. "
                "Do not add another Lightning or LightX2V LoRA. Normal negative "
                "conditioning is intentionally empty at CFG 1; NAG is omitted because "
                "it adds substantial cost and is not part of the baseline.\n\n"
                "Q4_K_M high: https://civitai.com/api/download/models/2500306\n"
                "Q4_K_M low: https://civitai.com/api/download/models/2500309"
            ),
            spec["title"],
        )
        workflow["extra"] = dict(workflow.get("extra") or {})
        workflow["extra"]["wan_q4_accuracy_workflow"] = {
            "version": 1,
            "model_recipe": "FAST MOVE V2 Q4_K_M embedded Lightning",
            "frames": spec["frames"],
            "megapixels": spec["megapixels"],
            "steps": spec["steps"],
            "split": spec["split"],
            "fps": 16,
        }
        rebuild_links(workflow)
        (output_root / spec["name"]).write_text(
            json.dumps(workflow, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("user/default/workflows/agent"),
    )
    args = parser.parse_args()
    build_workflows(args.repo_root.resolve(), args.output_root)


if __name__ == "__main__":
    main()
