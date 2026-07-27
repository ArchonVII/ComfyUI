# Modern Identity and I2I Workflows

Research and local compatibility were checked on 2026-07-26 against ComfyUI 0.26.0, Python 3.12, PyTorch 2.11/CUDA 13, and an RTX 5070 Ti with 16 GB VRAM.

## Workflow index

The editable workflows are under `user/default/workflows/agent`.

### 40 - Z-Image Turbo Identity Anchor I2I

Use this to test the community anchor technique with two explicit inputs:

1. Identity reference: a clear, front-facing portrait.
2. Target scene: the desired pose, clothing, camera, and background.

The graph builds an identity-target-identity strip, protects the side anchors, regenerates the center, then crops and scores the result. This is experimental: Z-Image Turbo is a generator, not a native identity editor.

Starting values:

- 9 steps
- CFG 1
- Euler / simple
- Denoise 0.82; test 0.70-0.90
- 640x832 center panel

The full three-panel canvas is 1920x832, so this lane is slower than a normal 640x832 generation.

### 41 - Z-Image Base Two Stage Precision I2I

Use this for source-preserving I2I and local refinement:

- First pass: 25 steps, CFG 4, `res_multistep` / beta, denoise 0.55.
- Refinement: 5 steps, CFG 3, Euler / simple, denoise 0.15.

The source image is normalized to approximately one megapixel. Lower the first-pass denoise toward 0.45 when likeness or composition drifts; raise it toward 0.65 when the requested edit is too weak.

### 42 - Krea 2 Identity Edit v1.2

This is the primary current native generative identity test:

1. Image 1 is the target scene, pose, body, clothing, camera, and background.
2. Image 2 is the identity reference whose face/head should replace the target identity.

Both images feed the v1.2 VAE source patch and Qwen3-VL grounded encoder. The graph uses the training-matched two-reference order: scene first, subject second.

Starting values:

- Krea 2 Turbo FP8
- Identity Edit v1.2 full-rank LoRA at 1.0
- 8 steps
- CFG 1
- Euler / simple
- Identity `ref_boost` 1.5; test 1.0-4.0
- Scene `ref_boost_a` 1.0
- `fit` geometry
- Grounding 1024 for likeness; try 512-768 for stronger edit adherence
- 1024x1024 output; stay at or below 2 MP

Krea 2 uses the Krea 2 Community License. The identity LoRA is SFW-trained, and its author explicitly rejects non-consensual sexual deepfake use.

### 43 - FireRed 1.1 Identity MultiRef

Use this for native Qwen-family identity editing:

1. Image 1 is the target scene.
2. Image 2 is the face/head identity reference.

The graph reuses the installed Qwen2.5-VL FP8 encoder and Qwen image VAE.

Starting values:

- FireRed Image Edit 1.1 Q4_K_M GGUF
- FireRed 1.1 Lightning 8-step v1.2 LoRA at 1.0
- Shift 3.1 plus CFGNorm 1.0
- 8 steps
- CFG 1
- Euler / simple
- Denoise 1

### 44 - Face Swap Proof and ReActor Baseline

This is a small controlled baseline, not a native-model claim. It uses the included synthetic benchmark identities, applies ReActor plus GFPGAN v1.4 at 0.75 visibility, saves the result, and writes an independent OpenCV SFace identity report.

An executable API graph is also provided at:

`user/default/api_workflows/agent/44 - Face Swap Proof and ReActor Baseline API.json`

The committed benchmark artifacts are:

- Source identity: `input/identity-benchmark/source_identity.png`
- Target scene: `input/identity-benchmark/target_scene_v2.png`
- Preferred restored output:
  `output/agent/identity-model-benchmark/reactor-gfpgan_00001_.png`
- Full attempt/result notes:
  `output/agent/identity-model-benchmark/README.md`
- Machine-readable identity report:
  `user/default/identity_score_runs/20260726-170739-reactor-proof-gfpgan.json`

The preferred restored output scored `0.780879` cosine similarity against the
configured `0.363` same-identity threshold. The highest raw output scored
`0.812342`; all attempts were retained to avoid reporting only the most
favorable result.

## Outputs and scoring

Native model workflows save under:

`output/agent/modern-identity`

The controlled proof saves under:

`output/agent/identity-model-benchmark`

Identity reports save under:

`user/default/identity_score_runs`

The scorer uses OpenCV YuNet for face detection and SFace embeddings for cosine similarity. Its configured same-identity threshold is 0.363. Scores are audit signals, not guarantees; inspect the image for face geometry, seams, texture, expression, and whether target pose/background were preserved.

## Model placement

Exact URLs, expected byte sizes, SHA-256 hashes, destinations, and licenses are recorded in:

`docs/modern-identity-model-manifest.json`

Selector-facing model files are intentionally placed directly in the
corresponding model-category root rather than nested subdirectories. ComfyUI
serializes discovered nested paths with host-native separators and strictly
validates combo values, so flat filenames keep the committed workflows valid on
both Windows and POSIX hosts. On the verified Windows installation, the
previously downloaded nested files are exposed at these portable names with
NTFS hardlinks, consuming no additional model storage.

Existing assets reused by these workflows:

- `models/vae/ae.safetensors`
- `models/vae/qwen_image_vae.safetensors`
- `models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors`
- `models/insightface/inswapper_128.onnx`
- installed ReActor, ComfyUI-GGUF, and OpenCV Identity Score nodes

If the reused Qwen2.5-VL encoder currently lives at
`models/text_encoders/Qwen/qwen_2.5_vl_7b_fp8_scaled.safetensors`, move, copy,
or link it to the selector-facing root path above. The verified Windows install
uses an NTFS hardlink, so this alias consumes no additional model storage.

The Krea workflow additionally requires:

`custom_nodes/comfyui-krea2edit`

The installed revision is pinned in the model manifest.

The ReActor/GFPGAN proof additionally requires
`models/facerestore_models/GFPGANv1.4.pth`. ReActor's `get_restorers()` downloads
its restorer set only when the restorer directory is empty, so an installation
with some other restorer may need this file downloaded explicitly. The exact
ReActor dataset URL, installed size, SHA-256 hash, and Apache-2.0 license are in
the manifest.

The first controlled ReActor run also provisioned its missing `buffalo_l`
face-analysis pack and safety-classifier files automatically. Their installed
paths and aggregate sizes are recorded in the manifest.

## Research basis

### Z-Image

- Official Z-Image Turbo model: <https://huggingface.co/Tongyi-MAI/Z-Image-Turbo>
- Official Z-Image Base model: <https://huggingface.co/Tongyi-MAI/Z-Image>
- Q8 GGUF conversions: <https://huggingface.co/jayn7/Z-Image-Turbo-GGUF> and <https://huggingface.co/jayn7/Z-Image-GGUF>
- Current high-engagement Base quality discussion: <https://www.reddit.com/r/comfyui/comments/1qznc0z/zimage_base_simple_workflow_for_high_quality/>
- Community anchor method: <https://www.reddit.com/r/comfyui/comments/1stylnr/anchor_workflow_zimage_turbo/>
- ZIT character/LoRA I2I method: <https://www.reddit.com/r/StableDiffusion/comments/1tae2yl/zit_i2i_character_lora_transformation_workflow/>

The latest top Civitai reference during research was “Z-Image Base & Turbo Pro Grade Workflow I2I/T2I,” model ID 2184844, version 18, with roughly 29,700 downloads and 787 likes. The local workflows use the useful model/sampling ideas without copying its large all-in-one graph.

### Krea 2

- Official Krea 2 repository: <https://github.com/krea-ai/krea-2>
- Comfy-format model pack: <https://huggingface.co/Comfy-Org/Krea-2>
- Identity Edit v1.2 weights: <https://huggingface.co/conradlocke/krea2-identity-edit>
- Current node implementation and reference graph: <https://github.com/lbouaraba/comfyui-krea2edit>
- High-engagement v1.2 identity examples: <https://www.reddit.com/r/StableDiffusion/comments/1v36waw/krea_2_identity_edit_samples_part_2_prompts/>

Krea 2, released in June 2026, is the current Krea target. The older FLUX.1 Krea model was not selected as the primary lane.

### FireRed

- Official FireRed Image Edit 1.1 model: <https://huggingface.co/FireRedTeam/FireRed-Image-Edit-1.1>
- Official Comfy model and Lightning pack: <https://huggingface.co/FireRedTeam/FireRed-Image-Edit-1.1-ComfyUI>
- Current community discussion: <https://www.reddit.com/r/comfyui/comments/1rqyn65/firered_image_edit_11_a_more_powerful_editing/>

FireRed was selected over LongCat for the first wave because it is purpose-built for image editing and explicitly emphasizes identity consistency and multi-image editing.

## Validation boundary

The native Z-Image, Krea 2, and FireRed graphs were checked against their
installed model selectors and registered node/input schemas. They are ready for
interactive evaluation after restarting ComfyUI so the newly installed Krea
node registers. No native output is presented here as benchmark evidence; the
saved and measured result is explicitly the ReActor/GFPGAN control baseline.
