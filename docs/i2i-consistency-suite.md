# I2I Consistency Suite

This suite adds three local image-to-image workflows and an isolated character-LoRA
training lane for this workstation:

- **35 - Klein 9B Masked Precision I2I** for fast, bounded edits with pixel-exact
  preservation outside the final mask.
- **36 - Klein 9B PuLID Identity Lab** for experimental face-identity conditioning.
- **37 - Qwen 2511 Q4KM Precision MultiRef** for slower, higher-precision edits.
  Its default accuracy lane uses only the primary reference; its separate dormant
  Lightning lane uses all three references.
- **Musubi character training helpers** for preparing and training a reusable
  character LoRA without installing trainer dependencies in ComfyUI's environment.

Generation and training data remain local. The workflows do not contain cloud
inference, dataset-upload, or reverse-prompting nodes. Installation uses the
network to download repositories, Python packages, and models; PuLID also downloads
its EVA vision model on first use.

## Before queuing a workflow

Open the workflow from `user/default/workflows/agent` and replace every
`wan_q4_placeholder.ppm` input with a real local image.

The installed runtime models are expected at these loader-visible paths:

| Purpose | ComfyUI model path |
| --- | --- |
| Klein 9B FP8 diffusion model | `models/diffusion_models/Flux/9b/DarkBeast-Klein9b-V2-BFS-FP8-ComfyUI.safetensors` |
| Klein Qwen3 8B text encoder | `models/text_encoders/Qwen/qwen_3_8b_fp8mixed.safetensors` |
| FLUX.2 VAE | `models/vae/flux2-vae.safetensors` |
| Klein consistency LoRA | `models/loras/Flux/9b/1 ------ Helper/Flux2-Klein-9B-consistency-V2.safetensors` |
| PuLID model | `models/pulid/pulid_flux2_klein_v2.safetensors` |
| Qwen Edit 2511 GGUF | `models/diffusion_models/Qwen/Qwen-Image-Edit-2511-Q4_K_M.gguf` |
| Qwen 2.5-VL text encoder | `models/text_encoders/Qwen/qwen_2.5_vl_7b_fp8_scaled.safetensors` |
| Qwen image VAE | `models/vae/qwen_image_vae.safetensors` |
| Optional Qwen Lightning LoRA | `models/loras/Qwen/Qwen IE 2511/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors` |

The Klein workflow requires the Qwen3 **8B** encoder listed above. A Qwen3 4B
encoder is dimensionally incompatible with this 9B model and fails during sampling.

## Workflow 35: Klein masked precision I2I

Use this workflow for fast edits that must not change unmasked pixels.

1. Load the source image.
2. In the `LoadImage` mask editor, paint the area that may change.
3. Write the edit instruction in the positive prompt.
4. Queue the workflow.

The graph grows and tapers the painted mask before generation, then uses
`ImageCompositeMasked` to composite the decoded edit over the original. The final
composite, not the raw decoded sample, is saved. This makes pixels outside the final
composite mask exactly equal to the source.

Default controls:

| Control | Default | Notes |
| --- | ---: | --- |
| Steps | 28 | Reduced only for smoke testing |
| CFG | 3.0 | Klein guidance |
| Denoise | 0.68 | Raise for larger structural changes |
| Sampler / scheduler | Euler / beta | Accuracy-oriented default |
| Consistency LoRA strength | 1.0 | Set to `0` to disable |
| Mask grow | 8 px | Tapered expansion before conditioning |
| VAE mask grow | 6 px | Reduces seams at the decoded boundary |

The default output prefix is `agent/i2i-consistency/klein-masked`.

## Workflow 36: Klein PuLID identity lab

Use this workflow when face identity matters more than exact pose or clothing.
Load the scene to edit and a separate, clean face reference. A frontal, well-lit,
single-person reference generally gives the identity extractor the clearest signal.

Default controls:

| Control | Default | Notes |
| --- | ---: | --- |
| Steps | 28 | Reduced only for smoke testing |
| CFG | 3.0 | Klein guidance |
| Denoise | 0.72 | Balances scene edit and identity |
| PuLID strength | 1.4 | Try `0.8-1.1` conservatively; `1.6-2.0` is strong |
| Face index | 0 | First detected face |
| Provider | CUDA | InsightFace also keeps CPU fallback available |

This path is experimental. PuLID conditions **face identity**; it does not promise
body identity, clothing continuity, or mature edit-mode consistency. Inspect the
generated image and the identity-score manifest rather than treating a single
similarity value as a quality guarantee. The suite deliberately defines no
pass/fail identity threshold.

The default output prefix is `agent/i2i-consistency/klein-pulid`.

On first use, the PuLID node lazily downloads the EVA vision model. The verified
download is 856,239,456 bytes (about 817 MiB), so allow extra time and network
access for that first run.

## Workflow 37: Qwen 2511 Q4KM precision multi-reference

Use this workflow for edits where instruction following or multiple visual
references matter more than speed. The active default lane uses:

- `Qwen-Image-Edit-2511-Q4_K_M.gguf`
- one required reference image
- AuraFlow shift `3.1`
- 28 steps, CFG `3.5`, Euler/beta, denoise `0.75`

The default accuracy lane consumes only reference input 1. References 2 and 3
belong to the separate dormant multi-reference Lightning lane; that lane expects
both extra loaders, for three total references. To use it, enable both extra image
loaders and its Lightning LoRA, shift, Plus conditioner, four-step sampler, decode,
and preview nodes together, then mute the active lane's Save/Preview nodes. Do not
partially toggle or enable only one extra reference without rewiring the graph;
the dormant lane's components are tuned as a unit.

The Q4_K_M route fits through model offloading on this 16 GB GPU, but it is not a
fast path. A two-step, 256 px smoke is only a compatibility test; a normal 28-step
edit will take substantially longer. The default output prefix is
`agent/i2i-consistency/qwen-2511-q4km`.

## Installed runtime and trainer revisions

The live validation used:

| Component | Verified revision / version |
| --- | --- |
| ComfyUI runtime base checkout | `63fe1e4b6aaeceec0106e76984c95b57713b53d2` |
| Suite worktree | `558f6acee39d95f9b1df7a319fd950b015a21dfe` |
| ComfyUI | `0.26.0` |
| Python / PyTorch | `3.12.10` / `2.11.0+cu130` |
| ComfyUI-PuLID-Flux2 | [`3a0a3f5f18260fc914f96a8c7f0f23c835e881cd`](https://github.com/iFayens/ComfyUI-PuLID-Flux2/tree/3a0a3f5f18260fc914f96a8c7f0f23c835e881cd) |
| ComfyUI-GGUF | [`6ea2651e7df66d7585f6ffee804b20e92fb38b8a`](https://github.com/city96/ComfyUI-GGUF/tree/6ea2651e7df66d7585f6ffee804b20e92fb38b8a) |
| Musubi Tuner | [`8934cfbbb4b9bcfa8071ce209129f0c5eb5df2e6`](https://github.com/kohya-ss/musubi-tuner/tree/8934cfbbb4b9bcfa8071ce209129f0c5eb5df2e6) |
| Musubi Python / PyTorch | `3.12.11` / `2.11.0+cu128` |
| ONNX Runtime GPU | `1.21.1` |
| InsightFace | `1.0.1` |

The selectively installed ComfyUI packages also include
`open-clip-torch==3.3.0`, `safetensors==0.8.0rc0`, `ml-dtypes==0.5.4`,
`numpy==2.3.5`, and `opencv-python==4.10.0.84`. Do not blindly reinstall a
custom node's entire requirements file over this working environment. The PuLID
node's own installation notes call for a selective install and warn against the
broken `eva_clip` package.

## Runtime asset manifest

The SHA-256 values below describe the exact local bytes used during validation.
Repository revisions identify a source only where its file metadata matched the
local size and hash.

| Asset | Bytes | SHA-256 | Source / license note |
| --- | ---: | --- | --- |
| DarkBeast Klein 9B FP8 | 9,078,610,848 | `b20b6f2744e152fd3efa2638e88a5feab478c778ee25c81b183fd80e03a099c3` | [Exact community file at `0725dc161e3761da90afecfc9fbccc23d6baa4ce`](https://huggingface.co/GuangyuanSD/FLUX.2-klein-9B-Blitz-ComfyUI/blob/0725dc161e3761da90afecfc9fbccc23d6baa4ce/DarkBeast-Klein9b-V2-BFS-FP8-ComfyUI.safetensors); repository declares no license. Upstream Klein has its own gated license. |
| Qwen3 8B FP8mixed encoder | 8,664,848,742 | `abad16806e0cbabc54e0325d6565847443fe396d5f0be38bb3cd3fe75a1201d6` | [Exact file at `23fbc8aa8b621f29f2249cd1bd9c47e5d0eebd83`](https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b/blob/23fbc8aa8b621f29f2249cd1bd9c47e5d0eebd83/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors); repository declares no license. |
| FLUX.2 VAE | 336,213,556 | `d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5` | Exact byte provenance not recovered; do not substitute a similarly named current Comfy file without revalidating its hash. |
| Klein consistency LoRA | 331,379,608 | `61db2017ce420b97bd5ef11984e5a894c90003a6bbf0dc9473f8d7b9ebb3ff93` | Exact upstream revision and license not recoverable from the local file; verify redistribution and usage authorization separately. |
| PuLID Klein v2 | 1,364,389,800 | `d5d291cb054eb6eceb25e3b46eff8f05f7b58f8f19a89ec76ba730a6ba8935bb` | [Fayens/Pulid-Flux2 at `550167db98d7169bfc83f9aa8225bd0da70f2d6b`](https://huggingface.co/Fayens/Pulid-Flux2/blob/550167db98d7169bfc83f9aa8225bd0da70f2d6b/pulid_flux2_klein_v2.safetensors), MIT |
| Qwen Edit 2511 Q4_K_M | 12,990,544,480 | `f2feaf9267a65d198cb4751db5dd8f5e69cb7bf53a924bdd36327ee167447638` | [vantagewithai/Qwen-Image-Edit-2511-GGUF at `e46674c6c19a2de7a7f7e0a42227c5bb70f114cd`](https://huggingface.co/vantagewithai/Qwen-Image-Edit-2511-GGUF/blob/e46674c6c19a2de7a7f7e0a42227c5bb70f114cd/Qwen-Image-Edit-2511-Q4_K_M.gguf), Apache-2.0 |
| Qwen 2.5-VL FP8 encoder | 9,384,670,680 | `cb5636d852a0ea6a9075ab1bef496c0db7aef13c02350571e388aea959c5c0b4` | [Comfy-Org/Qwen-Image_ComfyUI at `46839d338df81ce625d5fae27d7e370314c0fbc9`](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/blob/46839d338df81ce625d5fae27d7e370314c0fbc9/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors), Apache-2.0 |
| Qwen image VAE | 253,806,246 | `a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f` | [Comfy-Org/Qwen-Image_ComfyUI at `46839d338df81ce625d5fae27d7e370314c0fbc9`](https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/blob/46839d338df81ce625d5fae27d7e370314c0fbc9/split_files/vae/qwen_image_vae.safetensors), Apache-2.0 |
| Qwen Lightning four-step LoRA | 1,698,951,104 | `6f03a8cbb49f8dd422d23759b03cb254264c44aa3717d7903349ee42695baf18` | [lightx2v/Qwen-Image-Edit-2511-Lightning at `d74eba145674fd7e31b949324e148e21e7118abd`](https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning/blob/d74eba145674fd7e31b949324e148e21e7118abd/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors), Apache-2.0 |
| EVA02 vision model | 856,239,456 | `f753bca0e8327f77e8845b0af2510d599c3e4614237007b48078c791f2cf391c` | [timm/eva02_large_patch14_clip_336.merged2b_s6b_b61k at `4f62907359c8506be7021582f360564693b22c15`](https://huggingface.co/timm/eva02_large_patch14_clip_336.merged2b_s6b_b61k/tree/4f62907359c8506be7021582f360564693b22c15) |
| OpenCV YuNet face detector | 232,589 | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` | [OpenCV YuNet model](https://huggingface.co/opencv/face_detection_yunet) |
| OpenCV SFace recognizer | 38,696,353 | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` | [OpenCV SFace model](https://huggingface.co/opencv/face_recognition_sface) |

PuLID also uses the following AntelopeV2 files from
[MonsterMMORPG/InstantID_Models at `397cafa6d8310e96e302e96528c20a4c92a884f2`](https://huggingface.co/MonsterMMORPG/InstantID_Models/tree/397cafa6d8310e96e302e96528c20a4c92a884f2/models/antelopev2).
That repository does not declare a license:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `1k3d68.onnx` | 143,607,619 | `df5c06b8a0c12e422b2ed8947b8869faa4105387f199c477af038aa01f9a45cc` |
| `2d106det.onnx` | 5,030,888 | `f001b856447c413801ef5c42091ed0cd516fcd21f2d6b79635b1e733a7109dbf` |
| `genderage.onnx` | 1,322,532 | `4fde69b1c810857b88c64a335084f1c3fe8f01246c9a191b48c7bb756d6652fb` |
| `glintr100.onnx` | 260,665,334 | `4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf` |
| `scrfd_10g_bnkps.onnx` | 16,923,827 | `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91` |

The official upstream model pages are
[Qwen/Qwen-Image-Edit-2511](https://huggingface.co/Qwen/Qwen-Image-Edit-2511)
(Apache-2.0) and
[black-forest-labs/FLUX.2-klein-9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B)
(gated custom license). Downstream or quantized files do not replace those upstream
terms.

## Character-LoRA training

Training is intentionally isolated from ComfyUI:

- Trainer: `C:\tools\image\trainers\musubi-tuner`
- Datasets: `C:\tools\image\training\characters\datasets`
- Run metadata: `C:\tools\image\training\characters\runs`
- Caches: `C:\tools\image\training\characters\cache`
- Unapproved outputs: `C:\tools\image\training\characters\outputs`
- Approved ComfyUI LoRAs: `models/loras/trained/characters`

Install or restore the pinned trainer from the repository root:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\lora_training\install-musubi.ps1
```

The installer checks for at least 20 GiB free at the trainer location and at least
50 GiB free at the training root. On the documented layout both are on the shared
`C:` volume, so installation effectively requires at least 50 GiB free. A training
launch uses batch one, cached latents/text embeddings, gradient checkpointing, FP8,
and block swapping. The trainer venv has CUDA available. Nevertheless, 31 GiB
system RAM is below the practical 64 GiB recommendation for Qwen Edit training with
block swap. Both Klein 9B and Qwen training on this machine are experimental and
can page heavily or fail for memory.

### Dataset layout

Start with approximately 10-30 curated target images:

```text
C:\tools\image\training\characters\datasets\<character>\
├── targets\
│   ├── image-001.png
│   ├── image-001.txt
│   ├── image-002.png
│   └── image-002.txt
└── controls\                 # required for Qwen Edit, not the current Klein template
    ├── image-001.png
    └── image-002.png
```

Every target image needs a same-stem `.txt` caption. Include the chosen trigger
token in the captions. Qwen controls must use the same stems as their corresponding
targets. Keep datasets and captions local; the validator reads file metadata,
dimensions, and hashes but does not upload image content.

### Training checkpoints are deliberately deferred

The installed inference files are not valid training bases:

- Do not train Klein from the distilled DarkBeast FP8 checkpoint or a GGUF.
- Do not train Qwen Edit from the Q4_K_M GGUF, FP8 diffusion model, or
  `qwen_2.5_vl_7b_fp8_scaled.safetensors`.

For Klein, acquire the full, unquantized
[`black-forest-labs/FLUX.2-klein-base-9B`](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9B)
checkpoint, full `ae.safetensors`, and all four Qwen3 8B BF16 text-encoder shards.
Pass the first shard, `model-00001-of-00004.safetensors`, to the wrapper. Musubi's
[pinned FLUX.2 guide](https://github.com/kohya-ss/musubi-tuner/blob/8934cfbbb4b9bcfa8071ce209129f0c5eb5df2e6/docs/flux_2.md)
recommends the base 9B model for training; the distilled model is primarily for
inference.

For Qwen Edit, acquire BF16 training assets from
[`Comfy-Org/Qwen-Image-Edit_ComfyUI`](https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI):
`qwen_image_edit_2511_bf16.safetensors`, `qwen_2.5_vl_7b.safetensors`, and the
Qwen image VAE. The pinned
[Qwen guide](https://github.com/kohya-ss/musubi-tuner/blob/8934cfbbb4b9bcfa8071ce209129f0c5eb5df2e6/docs/qwen_image.md)
explicitly excludes the FP8-scaled encoder and FP8 E4M3FN diffusion model from
training.

### Dry-run and launch

Klein example:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\lora_training\start-character-training.ps1 `
  -Model flux2-klein9b -Character hero -RunName hero-klein-v1 -TriggerToken jmaHero `
  -Dit 'C:\models\flux2-klein-base-9b.safetensors' `
  -Vae 'C:\models\ae.safetensors' `
  -TextEncoder 'C:\models\qwen3-8b\model-00001-of-00004.safetensors' `
  -DryRun
```

Qwen Edit example:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\tools\lora_training\start-character-training.ps1 `
  -Model qwen-edit-2511 -Character hero -RunName hero-qwen-v1 -TriggerToken jmaHero `
  -Dit 'C:\models\qwen_image_edit_2511_bf16.safetensors' `
  -Vae 'C:\models\qwen_image_vae.safetensors' `
  -TextEncoder 'C:\models\qwen_2.5_vl_7b.safetensors' `
  -ControlDir 'C:\tools\image\training\characters\datasets\hero\controls' `
  -DryRun
```

Inspect the generated config and commands. Remove `-DryRun` to run the cache and
training phases. The wrapper refuses to overwrite an existing run.

After reviewing an output, rerun the same full command with `-ApproveOutput` in
place of `-DryRun`. Approval copies, without overwrite, to:

```text
models\loras\trained\characters\<run-name>-<model>.safetensors
```

### Recovery and updates

- Preserve a failed run's config, log, cache, and saved state.
- The wrapper does not expose Musubi's resume option. For a simple retry, fix the
  cause and use a new `-RunName`. For an advanced state resume, use the pinned
  Musubi documentation and its explicit `--resume` option against the saved state.
- Rerunning `install-musubi.ps1` fetches and detaches the pinned trainer revision.
  It refuses to update a dirty trainer checkout; inspect or preserve local trainer
  changes first.
- Runtime custom nodes update independently of Musubi. After any node, model, or
  trainer update, record the new revisions/hashes and rerun the schema and reduced
  smokes below.

## Live validation evidence

Validation ran against the generated workflows at suite head
`558f6acee39d95f9b1df7a319fd950b015a21dfe` using an isolated ComfyUI server with
the main runtime directory as its base.

### Live schema

`/object_info` reported 2,702 node types. All 52 executable workflow nodes
(15 masked Klein, 17 PuLID, and 20 Qwen) resolved, with zero missing node types and
zero unknown executable input names. All configured model, encoder, VAE, LoRA, and
provider choices were visible in their live loader schemas.

Six `LoadImage.upload` controls are editor-only `IMAGEUPLOAD` pseudo-inputs and are
intentionally absent from the backend schema.

### Reduced smokes

| Workflow | Reduced settings | Result |
| --- | --- | --- |
| Klein masked | 256x256, 2 steps | Completed in 6.609 s. Saved `output/validation/i2i-consistency-20260724/klein-masked-smoke-final-fresh_00001_.png`. Across 59,119 outside-mask pixels, zero differed; maximum channel delta was 0. Observed total GPU memory moved from 1,287 to 15,554 MiB. |
| Klein PuLID | 256x256, 2 steps, strength 1.4 | Completed in 61.131 s, including the first EVA lazy download. InsightFace used CUDA with CPU fallback. Reference/output faces were detected at confidence 0.946540/0.913089 and cosine similarity was 0.519441. This is observational evidence, not a suite threshold. Saved `output/validation/i2i-consistency-20260724/klein-pulid-smoke_00001_.png`; manifest `user/default/identity_score_runs/validation/20260724-133011-i2i-consistency-pulid-smoke.json`. The 14,618-to-15,478 MiB GPU observation began from an elevated prior-model baseline. |
| Qwen Q4_K_M | 256x256, 2 steps, one reference, accuracy lane | Completed in 32.558 s. The loader reported F32(1088), BF16(6), Q4_K(604), and Q6_K(236), with 6,355.68 MB loaded and 6,068.93 MB offloaded. Saved `output/validation/i2i-consistency-20260724/qwen-q4km-single-ref-smoke_00001_.png`. Observed total GPU memory moved from 3,516 to 12,444 MiB. |

During validation, an initial Klein sample exposed a 4B/9B encoder dimension
mismatch (`7680` versus `12288`). The workflows were corrected to the installed
Qwen3 8B encoder, contract tests were updated, and the fresh smoke above then
completed successfully.

These reduced runs prove wiring, loading, execution, output persistence, and the
masked composite invariant. They are not visual-quality benchmarks and do not
predict normal 28-step latency.
