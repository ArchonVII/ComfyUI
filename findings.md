# Findings: Adaptive LTX and Wan I2V Workflows

## Current Workflow Defects

- All three numbered LTX workflows hard-code width and height.
- `22 - HQ LTXV I2V - Fast Draft 97f.json` documents `768x512` but its `LTXVImgToVideo` widget is `512x1280`.
- The current fast LTX graph contains an unrelated Flux LoRA loader.
- Four of six workflow placeholder images are missing from the live input folder.
- The regular Wan FP8 workflow references high/low diffusion files that are not present in the live `UNETLoader` catalog.
- Current Wan workflows are bare two-pass samplers with no adaptive sizing, tiled decode, or expert-specific acceleration controls.
- The five weak LTX/Wan files are ignored local assets rather than tracked files; only workflow 29 is currently forced into git. The replacement lane must generate and force-add the six scoped workflow files without carrying unrelated user workflows.
- The protected checkout's source workflow placeholders include one real portrait image at `2133x4096`; the other referenced defaults are missing. New tracked workflows will use the existing neutral `input/example.png` placeholder.

## Research Conclusions

- Official Wan 2.2 I2V follows the input image aspect ratio and treats 480p/720p as pixel-area targets, not fixed 16:9 dimensions.
- Wan 2.2 I2V-A14B uses separate high-noise and low-noise experts.
- Four-step distilled Wan inference is current and useful for drafts, but the acceleration LoRAs must be paired by expert and used with their intended schedule.
- NAG restores negative guidance in few-step sampling where ordinary CFG is weak.
- Enhance-A-Video is a training-free temporal-attention patch; it may improve cross-frame coherence but is not a substitute for correct conditioning.
- RIFLEx is intended for length extrapolation and should not be enabled for ordinary 81-frame generation by default.
- EasyCache is the current training-free cache node; KJNodes marks its Wan TeaCache node deprecated.
- LTX 2.3 is the current LTX generation and recommends a two-stage low-resolution generation plus latent upscaling/refinement path. Its 22B checkpoint, Gemma encoder, LoRA, and upscaler are not installed locally.

## Local Runtime Facts

- GPU: NVIDIA GeForce RTX 5070 Ti, 16,303 MiB VRAM.
- Isolated validation endpoint: `http://127.0.0.1:8190/` (worktree code with `C:\tools\image\ComfyUI` as its runtime base).
- Installed LTX base: `ltxv-13b-0.9.8-distilled-fp8.safetensors`.
- Installed Wan bases: `Wan\\Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf` and `Wan\\Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf`.
- Installed Wan VAE: `wan_2.1_vae.safetensors`.
- Installed general Wan text encoder: `umt5_xxl_fp8_e4m3fn_scaled.safetensors`.
- `ImageScaleToTotalPixels`, `GetImageSize`, `VAEDecodeTiled`, `WanFirstLastFrameToVideo`, `WanVideoNAG`, `WanVideoEnhanceAVideoKJ`, `ApplyRifleXRoPE_WanVideo`, `EasyCache`, and `RIFE VFI` are present in live object metadata.
- All executable node types and named inputs in the six generated workflows resolve against live `object_info`. `MarkdownNote` and `LoadImage.upload` are frontend-only graph metadata and are intentionally absent from the execution registry.
- A real `2133x4096` portrait scaled through the graph's 0.40 MP policy to `480x896`; both axes are multiples of 32 and the portrait orientation/aspect is preserved.
- The reduced-cost Wan fast smoke used the complete installed high/low GGUF expert path at 0.05 MP and 9 frames. It completed in 40.68 seconds and produced a coherent `224x224`, 9-frame, 24 fps H.264 MP4.
- ComfyUI-GGUF documents LoRA support as experimental. The installed Seko-V1 adapters emitted 331 unsupported residual/image-attention key warnings while loading their supported patches. The render completed, but the four-step preset should remain labeled a draft path; the 40-step no-LoRA workflows are the quality baseline.

## Primary Sources

- https://docs.comfy.org/tutorials/video/wan/wan2_2
- https://github.com/Wan-Video/Wan2.2
- https://github.com/ModelTC/lightx2v
- https://github.com/ModelTC/Wan2.2-Lightning
- https://arxiv.org/abs/2505.21179
- https://github.com/NUS-HPC-AI-Lab/Enhance-A-Video
- https://arxiv.org/abs/2502.15894
- https://arxiv.org/abs/2507.02860
- https://docs.comfy.org/tutorials/video/ltx/ltx-2-3
- https://github.com/Lightricks/ComfyUI-LTXVideo
- https://github.com/city96/ComfyUI-GGUF
