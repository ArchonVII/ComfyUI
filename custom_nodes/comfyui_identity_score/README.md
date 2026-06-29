# ComfyUI Identity Score

Local identity-preservation scorer for ComfyUI image-to-image workflows.

It uses:
- OpenCV YuNet for face detection.
- OpenCV SFace for face embeddings and cosine similarity.

The node is `OpenCV Identity Score`. Connect the source/reference image and the final generated image. It is an output node, so it can write the run manifest directly even when it is not feeding another save node. It returns a raw cosine similarity, a same-identity boolean, catalog best-match fields, JSON report text, and optional `EXTRA_METADATA` for workflows that still want to consume it.

Default model files live in `models/`:
- `face_detection_yunet_2023mar.onnx`
- `face_recognition_sface_2021dec.onnx`

If they are missing, run:

```powershell
powershell -ExecutionPolicy Bypass -File C:\tools\image\ComfyUI\custom_nodes\comfyui_identity_score\scripts\download_opencv_models.ps1
```

Catalog scoring:
- `catalog_root` resolves relative to `C:\tools\image\ComfyUI\input`.
- `catalog_mode = subject` scores one subject folder.
- `catalog_mode = all_subjects` treats each subfolder as a subject.

The node only scores identity consistency for authorized/local reference subjects. It does not identify unknown people.
