# WAN 2.2 Q4 Accuracy Workflows

This set replaces one-size-fits-all WAN testing with four workflows that answer
different questions. They are tuned for this machine's RTX 5070 Ti with 16.3 GB
VRAM and the FAST MOVE V2 Q4_K_M high/low checkpoint pair.

## Why the previous render estimated about 20 minutes

The local Q8 experts are approximately 15.4 GB each. One expert nearly fills
the GPU before video activations, VAE work, and other model data are allocated.
The edited older quality graph also combines those embedded-Lightning Q8 models
with shift 8, CFG 3.5, and 40 sampling steps.

The checkpoint publisher specifies a different recipe:

- FAST MOVE V2 already contains Lightning.
- Do not add another Lightning or LightX2V LoRA.
- Use shift 5, CFG 1, Euler/simple.
- Use 2+2 steps, or 2+3 for a modest quality improvement.

An 81-frame, 0.40 MP render is still a full five-second final, not a fast
composition check. The new set makes that cost explicit.

## Workflow set

| Workflow | Purpose | Default cost | Accuracy method |
| --- | --- | --- | --- |
| `31 - WAN Q4 FAST Preview 17f` | Reject bad prompts, seeds, and compositions quickly | 17 frames, 0.10 MP, 2+2 steps | Low-cost source-conditioned preview |
| `32 - WAN Q4 Prompt Camera 49f` | Test action sequence and camera compliance | 49 frames, 0.25 MP, 2+3 steps | Timestamped prompt clauses |
| `33 - WAN Q4 Identity Audit 81f` | Evaluate face retention across a full clip | 81 frames, 0.40 MP, 2+3 steps | Scores middle and final frames against image 1 |
| `34 - WAN Q4 First Last Control 81f` | Force known start and end compositions | 81 frames, 0.40 MP, 2+3 steps | Native first/last-frame latent conditioning |

All four preserve the source aspect ratio, round dimensions to a multiple of
32, decode in tiles, and save H.264 MP4 at 16 fps. At Wan's native cadence,
81 frames is approximately five seconds.

## Recommended use

1. Start with workflow 31. Do not judge fine detail at its deliberately small
   resolution.
2. Move the same seed and prompt to workflow 32. Rewrite the timestamped clauses
   to describe one continuous shot.
3. Use workflow 33 when a recognizable face matters. The identity node is an
   evaluation tool; it does not identify unknown people or improve the render.
4. Use workflow 34 when the ending composition is known. Image 2 is scaled to
   image 1's derived dimensions automatically.

Normal negative conditioning is ineffective at CFG 1. NAG can restore a form
of negative guidance, but the checkpoint publisher warns that it substantially
increases generation time. It is intentionally absent from these baseline
graphs.

## Checkpoint downloads

Download both files into `models/diffusion_models`:

- [Q4_K_M high expert](https://civitai.com/api/download/models/2500306)
  `wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KMH.gguf`
  SHA-256: `90EBBD34A858C0B6EACDFE259A83F5EB93D623FCD66BBFE5F36076AAE70C2826`
- [Q4_K_M low expert](https://civitai.com/api/download/models/2500309)
  `wan22EnhancedNSFWSVICamera_nsfwFASTMOVEV2Q4KML.gguf`
  SHA-256: `488D6ADF530B808F3811ADC2FFAAECDE07859649A39E47F025644F7E3A51BB04`

The files are approximately 9.65 GB each. Restart ComfyUI or refresh the model
catalog after both downloads finish.

Local transfer state on 2026-07-23:

- Low expert: complete and SHA-256 verified.
- High expert: publisher connection stopped at 1,811,582,656 bytes; the resumable
  `.part` file remains beside the models.

## Verification evidence

- Four workflow JSON files parse and pass 15 focused contract tests.
- Every `Load Image` node defaults to a local neutral placeholder rather than a
  missing file or a personal input image.
- The live ComfyUI registry recognizes all 78 nodes and every workflow input.
- A topology-only Q8 substitute smoke at 224×224, five frames, and 2+2 steps
  completed in 44.38 seconds.
- The smoke's final frame scored `0.789915` cosine similarity against its source
  face with the local OpenCV SFace evaluator (`0.363` same-identity threshold).
- The Q4_K_M low expert is complete and matches its published SHA-256.
- Q4 runtime speed remains unmeasured until the high Q4 file is complete and
  hash-verified.

## Research sources

- [Checkpoint publisher page and recommended settings](https://civitai.com/models/2053259)
- [Official Wan2.2 native ComfyUI workflows](https://docs.comfy.org/tutorials/video/wan/wan2_2)
- [Official Wan2.2 repository](https://github.com/Wan-Video/Wan2.2)
- [Wan2.2-Lightning model card](https://huggingface.co/lightx2v/Wan2.2-Lightning)
- [LightX2V inference framework](https://github.com/ModelTC/LightX2V)
- [TurboDiffusion](https://github.com/thu-ml/TurboDiffusion)

TurboDiffusion was researched but not selected for this set. It requires a
different checkpoint/runtime stack and a separate ComfyUI integration that is
not installed here; the goal of this set is to improve the current native
ComfyUI-GGUF installation without adding another experimental runtime.
