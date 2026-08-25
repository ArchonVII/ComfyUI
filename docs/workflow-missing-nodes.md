# Missing-node audit — pack findings (2026-08-25)

From the exact `/object_info` audit of 1,195 indexed workflows: 193 workflows
reference at least one node type this install cannot provide. Every installed
pack imported cleanly at startup (zero IMPORT FAILED), so nothing below is an
installed-but-broken pack; these are uninstalled packs. `comfyui_civitai_ingestor`
and `comfyui_session_watchdog` register zero nodes **by design** (server
extensions, `NODE_CLASS_MAPPINGS = {}`) — not failures. rgthree/kjnodes/mtb
JS-virtual nodes are resolved by the indexer since commit a36001ce and are not
listed here. **Nothing has been installed; this is a findings table.**

| pack | workflows | node types (sample) | status | recommended action |
| --- | ---: | --- | --- | --- |
| [ComfyUI-PromptChain](https://github.com/mobcat40/ComfyUI-PromptChain) | 63 | `SeedVR2LoadDiTModel`, `SeedVR2LoadVAEModel`, `SeedVR2VideoUpscaler` +1 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-RMBG](https://github.com/1038lab/ComfyUI-RMBG) | 57 | `AILab_ImageCrop`, `FaceSegment`, `FashionSegmentAccessories` +3 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | 28 | `VHS_GetImageCount`, `VHS_LoadAudio`, `VHS_LoadVideo` +9 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts) | 25 | `LoraLoader|pysssss`, `MathExpression|pysssss`, `PlaySound|pysssss` +1 | not installed | install via Manager if these workflows are still wanted |
| [comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux) | 22 | `AIO_Preprocessor`, `DWPreprocessor`, `DepthAnythingV2Preprocessor` +4 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-mxToolkit](https://github.com/Smirnov75/ComfyUI-mxToolkit) | 22 | `mxSlider`, `mxSlider2D`, `mxStop` | not installed | install via Manager if these workflows are still wanted |
| [was-node-suite-comfyui](https://github.com/ltdrdata/was-node-suite-comfyui) | 20 | `Bounded Image Blend with Mask`, `Conditioning Input Switch`, `Image Blank` +4 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-QwenVL](https://github.com/1038lab/ComfyUI-QwenVL) | 18 | `AILab_QwenVL`, `AILab_QwenVL_Advanced`, `AILab_QwenVL_GGUF_Advanced` +1 | not installed | install via Manager if these workflows are still wanted |
| [RES4LYF](https://github.com/ClownsharkBatwing/RES4LYF) | 14 | `ClownOptions_DetailBoost_Beta`, `ClownsharKSampler_Beta`, `Image Crop Location Exact` +5 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Lora-Manager](https://github.com/willmiao/ComfyUI-Lora-Manager) | 14 | `Lora Loader (LoraManager)` | not installed | install via Manager if these workflows are still wanted |
| [comfyui-find-perfect-resolution](https://github.com/ashtar1984/comfyui-find-perfect-resolution) | 13 | `FindPerfectResolution` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-MMAudio](https://github.com/kijai/ComfyUI-MMAudio) | 12 | `MMAudioFeatureUtilsLoader`, `MMAudioModelLoader`, `MMAudioSampler` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-post-processing-nodes](https://github.com/EllangoK/ComfyUI-post-processing-nodes) | 11 | `ChromaticAberration`, `ColorCorrect`, `FilmGrain` +1 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Painter-I2V-AIO](https://github.com/LDNKS094/ComfyUI-Painter-I2V-AIO) | 11 | `PainterI2V`, `PainterI2VAdvanced` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Image-Saver](https://github.com/alexopus/ComfyUI-Image-Saver) | 10 | `Any to String (Image Saver)`, `Checkpoint Loader with Name (Image Saver)`, `Image Saver` +4 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Qwen3.5-Uncensored-GGUF](https://github.com/Deaquay/ComfyUI-Qwen3.5-Uncensored-GGUF) | 10 | `StorySplitNode`, `VRAMCleanup` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-TBG-ETUR](https://github.com/Ltamann/ComfyUI-TBG-ETUR) | 10 | `DownloadAndLoadFlorence2Model`, `Florence2Run` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Upscaler-TensorRT-Auto](https://github.com/huchukato/ComfyUI-Upscaler-TensorRT-Auto) | 10 | `LoadUpscalerTensorrtModel`, `UpscalerTensorrt` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_Selectors](https://github.com/ComfyAssets/ComfyUI_Selectors) | 10 | `SamplerSelector`, `SchedulerSelector` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-WanMoeKSampler](https://github.com/stduhpf/ComfyUI-WanMoeKSampler) | 10 | `WanMoeKSamplerAdvanced` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-VFI](https://github.com/GACLove/ComfyUI-VFI) | 8 | `RIFEInterpolation` | not installed | install via Manager if these workflows are still wanted |
| [Derfuu_ComfyUI_ModdedNodes](https://github.com/Derfuu/Derfuu_ComfyUI_ModdedNodes) | 8 | `DF_Image_scale_to_side`, `DF_Int_to_Float`, `DF_Text` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-SuperNodes](https://github.com/sonnybox/ComfyUI-SuperNodes) | 8 | `GetCommonAspectRatio`, `ImageMaskCrop`, `ImageSizeCalculator` +2 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-AutoCropFaces](https://github.com/liusida/ComfyUI-AutoCropFaces) | 7 | `AutoCropFaces` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper) | 7 | `CreateCFGScheduleFloatList`, `DummyComfyWanModelObject`, `FantasyPortraitFaceDetector` +24 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-PainterLongVideo](https://github.com/princepainter/ComfyUI-PainterLongVideo) | 7 | `PainterLongVideo` | not installed | install via Manager if these workflows are still wanted |
| [cg-use-everywhere](https://github.com/chrisgoringe/cg-use-everywhere) | 6 | `Anything Everywhere` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-RIFE-TensorRT-RTX](https://github.com/ThreadsOfFate/ComfyUI-RIFE-TensorRT-RTX) | 6 | `AutoLoadRifeTensorrtModel`, `AutoRifeTensorrt` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Inspire-Pack](https://github.com/ltdrdata/ComfyUI-Inspire-Pack) | 5 | `LoadImagesFromDir //Inspire` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-RvTools](https://github.com/Rvage0815/ComfyUI-RvTools) | 5 | `Image Multi-Switch [RvTools]`, `Image to RGB [RvTools]`, `Latent Multi-Switch [RvTools]` +1 | not installed | install via Manager if these workflows are still wanted |
| [a-person-mask-generator](https://github.com/djbielejeski/a-person-mask-generator) | 5 | `APersonMaskGenerator` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Dynamic-Lora-Scheduler](https://github.com/LeonQ8/ComfyUI-Dynamic-Lora-Scheduler) | 5 | `WanVideoBlockSwap`, `WanVideoLoraSelect`, `WanVideoLoraSelectMulti` +4 | not installed | install via Manager if these workflows are still wanted |
| [comfyui-various](https://github.com/jamesWalker55/comfyui-various) | 5 | `JWDatetimeString`, `JWFloatToInteger`, `JWImageResizeByLongerSide` | not installed | install via Manager if these workflows are still wanted |
| [praveen-tools](https://github.com/Praveenhalder/praveen-tools) | 4 | `LoadImageWithFilename` | not installed | install via Manager if these workflows are still wanted |
| [Comfyui-QwenEditUtils](https://github.com/lrzjason/Comfyui-QwenEditUtils) | 4 | `TextEncodeQwenImageEditPlusAdvance_lrzjason` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-PainterNodes](https://github.com/princepainter/ComfyUI-PainterNodes) | 4 | `PainterFluxImageEdit` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-FBCNN](https://github.com/Miosp/ComfyUI-FBCNN) | 4 | `JPEG artifacts removal FBCNN` | not installed | install via Manager if these workflows are still wanted |
| [ComfyMath](https://github.com/evanspearman/ComfyMath) | 4 | `CM_FloatToInt`, `CM_IntToFloat` | not installed | install via Manager if these workflows are still wanted |
| [Comfyui-ergouzi-Nodes](https://github.com/11dogzi/Comfyui-ergouzi-Nodes) | 4 | `EG_WXZ_QH` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-FramePackWrapper_Plus](https://github.com/ShmuelRonen/ComfyUI-FramePackWrapper_Plus) | 4 | `FramePackFindNearestBucket` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Addoor](https://github.com/Eagle-CN/ComfyUI-Addoor) | 4 | `Incrementer 🪴` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-K3NKImageGrab](https://github.com/K3NK3/ComfyUI-K3NKImageGrab) | 4 | `K3NKFindNearestBucket`, `K3NKImageGrab`, `K3NKImageLoaderWithBlending` +2 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-MelBandRoFormer](https://github.com/kijai/ComfyUI-MelBandRoFormer) | 4 | `MelBandRoFormerModelLoader`, `MelBandRoFormerSampler` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-NovaSR](https://github.com/Saganaki22/ComfyUI-NovaSR) | 4 | `NovaSR` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-pause](https://github.com/wywywywy/ComfyUI-pause) | 4 | `PauseWorkflowNode` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_tinyterraNodes](https://github.com/TinyTerra/ComfyUI_tinyterraNodes) | 4 | `ttN concat`, `ttN int`, `ttN text` | not installed | install via Manager if these workflows are still wanted |
| [CRT-Nodes](https://github.com/PGCRT/CRT-Nodes) | 4 | `ArcaneBloomFX`, `ClarityFX`, `LensFX` +3 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Crystools](https://github.com/crystian/ComfyUI-Crystools) | 4 | `Get resolution [Crystools]`, `Switch any [Crystools]`, `Switch conditioning [Crystools]` +1 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Easy-Sam3](https://github.com/yolain/ComfyUI-Easy-Sam3) | 3 | `easy sam3ImageSegmentation`, `easy sam3ModelLoader` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Batch-Process](https://github.com/Zar4X/ComfyUI-Batch-Process) | 3 | `ImageBatchLoader` | not installed | install via Manager if these workflows are still wanted |
| [Comfyui_TTP_Toolset](https://github.com/TTPlanetPig/Comfyui_TTP_Toolset) | 3 | `TTP_Image_Assy`, `TTP_Image_Tile_Batch`, `TTP_Tile_image_size` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Easy-Loaders](https://github.com/RevengerNick/ComfyUI-Easy-Loaders) | 3 | `ClipLoaderGGUF` | not installed | install via Manager if these workflows are still wanted |
| [virtuoso-nodes](https://github.com/chrisfreilich/virtuoso-nodes) | 3 | `LensBlur` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Optical-Realism](https://github.com/skatardude10/ComfyUI-Optical-Realism) | 3 | `OpticalRealism`, `RemoveAlphaChannel` | not installed | install via Manager if these workflows are still wanted |
| [comfyui-propost](https://github.com/digitaljohn/comfyui-propost) | 3 | `ProPostApplyLUT` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-FairLab](https://github.com/yanhuifair/ComfyUI-FairLab) | 3 | `ResizeImageNode` | not installed | install via Manager if these workflows are still wanted |
| [comfy-image-saver](https://github.com/giriss/comfy-image-saver) | 3 | `Int Literal`, `Sampler Selector`, `Scheduler Selector` +1 | not installed | install via Manager if these workflows are still wanted |
| [comfyui-sentence-filter](https://github.com/Slartibart23/comfyui-sentence-filter) | 3 | `SentenceFilterNode` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-vslinx-nodes](https://github.com/vslinx/ComfyUI-vslinx-nodes) | 3 | `vsLinx_AppendLorasFromNodeToString` | not installed | install via Manager if these workflows are still wanted |
| [SeedVarianceEnhancer](https://github.com/ChangeTheConstants/SeedVarianceEnhancer) | 3 | `SeedVarianceEnhancer` | not installed | install via Manager if these workflows are still wanted |
| [Comfyui-Memory_Cleanup](https://github.com/LAOGOU-666/Comfyui-Memory_Cleanup) | 2 | `RAMCleanup` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-ReservedVRAM](https://github.com/Windecay/ComfyUI-ReservedVRAM) | 2 | `ReservedVRAMSetter` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) | 2 | `IPAdapter`, `IPAdapterUnifiedLoader` | not installed | install via Manager if these workflows are still wanted |
| [comfyui_segment_anything](https://github.com/storyicon/comfyui_segment_anything) | 2 | `GroundingDinoModelLoader (segment anything)`, `GroundingDinoSAMSegment (segment anything)`, `SAMModelLoader (segment anything)` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-NAG](https://github.com/ChenDarYen/ComfyUI-NAG) | 2 | `KSamplerWithNAG (Advanced)` | not installed | install via Manager if these workflows are still wanted |
| [comfyui-adaptiveprompts](https://github.com/Alectriciti/comfyui-adaptiveprompts) | 2 | `PromptGenerator` | not installed | install via Manager if these workflows are still wanted |
| [comfyui-ollama](https://github.com/stavsap/comfyui-ollama) | 2 | `OllamaConnectivityV2`, `OllamaGenerateV2`, `OllamaOptionsV2` | not installed | install via Manager if these workflows are still wanted |
| [wlsh_nodes](https://github.com/wallish77/wlsh_nodes) | 2 | `Resolutions by Ratio (WLSH)` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-FlashVSR_Ultra_Fast](https://github.com/lihaoyun6/ComfyUI-FlashVSR_Ultra_Fast) | 2 | `FlashVSRNode` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_ExtraModels](https://github.com/city96/ComfyUI_ExtraModels) | 2 | `OverrideCLIPDevice` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Unload-Model](https://github.com/SeanScripts/ComfyUI-Unload-Model) | 2 | `UnloadModel` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-AdvancedLivePortrait](https://github.com/PowerHouseMan/ComfyUI-AdvancedLivePortrait) | 2 | `ExpressionEditor` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Detail-Daemon](https://github.com/Jonseed/ComfyUI-Detail-Daemon) | 2 | `DetailDaemonGraphSigmasNode`, `DetailDaemonSamplerNode`, `MultiplySigmas` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Image-Size-Tools](https://github.com/TheLustriVA/ComfyUI-Image-Size-Tools) | 2 | `FluxResolutionNode` | not installed | install via Manager if these workflows are still wanted |
| [comfyui-all-on-one-image-generation-node](https://github.com/helto4real/comfyui-all-on-one-image-generation-node) | 1 | `InpaintCropImproved`, `InpaintStitchImproved` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_Steudio](https://github.com/Steudio/ComfyUI_Steudio) | 1 | `Combine Tiles`, `Display UI`, `Divide Image and Select Tile` +1 | not installed | install via Manager if these workflows are still wanted |
| [Comfyui_LG_Tools](https://github.com/LAOGOU-666/Comfyui_LG_Tools) | 1 | `LG_Noise` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-basic_data_handling](https://github.com/StableLlama/ComfyUI-basic_data_handling) | 1 | `Basic data handling: CastToInt`, `Basic data handling: MathFormula`, `Basic data handling: StringRsplitDataList` +1 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Olm-DragCrop](https://github.com/o-l-l-i/ComfyUI-Olm-DragCrop) | 1 | `OlmDragCrop` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Jjk-Nodes](https://github.com/jjkramhoeft/ComfyUI-Jjk-Nodes) | 1 | `JjkShowText` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_SLK_joy_caption_two](https://github.com/EvilBT/ComfyUI_SLK_joy_caption_two) | 1 | `Joy_caption_two`, `Joy_caption_two_load` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Flux2Klein-Enhancer](https://github.com/capitan01R/ComfyUI-Flux2Klein-Enhancer) | 1 | `Flux2KleinEnhancer` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Chibi-Nodes](https://github.com/chibiace/ComfyUI-Chibi-Nodes) | 1 | `Prompts` | not installed | install via Manager if these workflows are still wanted |
| [comfyui-timesaver](https://github.com/AlexYez/comfyui-timesaver) | 1 | `TS_Qwen3_VL_V3`, `TS_StylePromptSelector` | not installed | install via Manager if these workflows are still wanted |
| [facerestore_cf](https://github.com/mav-rik/facerestore_cf) | 1 | `FaceRestoreCFWithModel`, `FaceRestoreModelLoader` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Wan22FMLF](https://github.com/wallen0322/ComfyUI-Wan22FMLF) | 1 | `WanAdvancedI2V` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_Custom_Switch](https://github.com/tritant/ComfyUI_Custom_Switch) | 1 | `AutomaticImageSwitcher` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-checkpoint-Discovery-Hub](https://github.com/Light-x02/ComfyUI-checkpoint-Discovery-Hub) | 1 | `CheckpointDiscoveryHub` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Civitai-Discovery-Hub](https://github.com/Light-x02/ComfyUI-Civitai-Discovery-Hub) | 1 | `CivitaiDiscoveryHubNode`, `ClearLoraName` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Allor](https://github.com/Nourepide/ComfyUI-Allor) | 1 | `ConditioningClamp`, `ImageClamp`, `LatentClamp` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-FRED-Nodes_v2](https://github.com/Poukpalaova/ComfyUI-FRED-Nodes_v2) | 1 | `FRED_Image_Sharpening_Blur_Level`, `FRED_JpegArtifact_Simulator` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Lightx02-Nodes](https://github.com/Light-x02/ComfyUI-Lightx02-Nodes) | 1 | `LMMExtractPromptsNode`, `Loraloadertotext`, `PreviewMask` +1 | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_Local_Lora_Gallery](https://github.com/Firetheft/ComfyUI_Local_Lora_Gallery) | 1 | `LocalLoraGallery` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_Local_Media_Manager](https://github.com/Firetheft/ComfyUI_Local_Media_Manager) | 1 | `LocalMediaManagerNode` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_Text_Translation](https://github.com/TFL-TFL/ComfyUI_Text_Translation) | 1 | `Text` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI-Flux-Continuum](https://github.com/robertvoy/ComfyUI-Flux-Continuum) | 1 | `TextVersions` | not installed | install via Manager if these workflows are still wanted |
| [ComfyUI_YOLO_For_Multi_SDPose_Detection](https://github.com/judian17/ComfyUI_YOLO_For_Multi_SDPose_Detection) | 1 | `YOLOModelLoader` | not installed | install via Manager if these workflows are still wanted |

## Not in any registry

- **INSTARAW suite** — 56 node types across 14 workflows.
  Not in the Comfy registry or Manager DBs and nowhere in `custom_nodes`;
  distribution appears private (Patreon-style). The owner knows the source;
  reinstall from it or retire the INSTARAW workflows.
- `IdeogramEditImage` — 2 workflow(s); origin not identified.
- `LoraLoaderZImage` — 2 workflow(s); origin not identified.
- `DuckHideNode` — 1 workflow(s); origin not identified.
- `TT_img_enc` — 1 workflow(s); origin not identified.
- `CurrentPromptReader` — 1 workflow(s); origin not identified.
- `Pipe_10CH_Any` — 1 workflow(s); origin not identified.
- `Pipe_20CH_Any` — 1 workflow(s); origin not identified.
- `Pipe_30CH_Any` — 1 workflow(s); origin not identified.
- `GroundingDinoModelLoader_SDPose` — 1 workflow(s); origin not identified.
- `SDPoseOODLoader` — 1 workflow(s); origin not identified.
- `SDPoseOODProcessor` — 1 workflow(s); origin not identified.
