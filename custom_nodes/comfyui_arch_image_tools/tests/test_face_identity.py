from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from custom_nodes.comfyui_arch_image_tools import face_identity


ArchLocalFaceIdentityTransfer = face_identity.ArchLocalFaceIdentityTransfer
_landmarks = face_identity._landmarks


def test_yunet_landmarks_are_extracted_as_five_xy_pairs():
    face = np.arange(15, dtype=np.float32)
    assert _landmarks(face).shape == (5, 2)
    assert _landmarks(face).tolist() == [[4, 5], [6, 7], [8, 9], [10, 11], [12, 13]]


def test_node_exposes_local_sam_and_landmark_fallback_modes():
    required = ArchLocalFaceIdentityTransfer.INPUT_TYPES()["required"]
    preflight_required = face_identity.ArchFaceIdentityPreflight.INPUT_TYPES()["required"]
    assert preflight_required["mask_mode"][0] == ["SAM local", "Landmark feather"]
    assert required["mask_mode"] == ("STRING", {"forceInput": True})
    assert required["iterations"][1]["default"] == 2
    assert "identity" in required
    assert "target_image" in required


def test_preflight_landmark_fallback_does_not_require_sam_artifacts():
    image = torch.ones((1, 32, 24, 3), dtype=torch.float32)
    face = np.array([1, 1, 10, 10, *range(10), 0.9], dtype=np.float32)
    with (
        patch.object(face_identity, "_model_paths", return_value={"swapper": object()}) as model_paths,
        patch.object(face_identity, "_detect_faces", return_value=np.array([face])),
        patch.object(face_identity, "_mapped_identity", return_value=np.ones((1, 512), dtype=np.float32)),
        patch.object(face_identity, "_face_preview", return_value=image),
    ):
        face_identity.ArchFaceIdentityPreflight().preflight(
            identity_image=image,
            main_image=image,
            enabled=True,
            face_selection="largest",
            source_face_index=0,
            face_threshold=0.7,
            sam_model="missing-sam.pth",
            mask_mode="Landmark feather",
        )
    model_paths.assert_called_once_with("missing-sam.pth", require_sam=False)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("sam_vit_b_01ec64.pth", "vit_b"),
        ("sam_vit_l_0b3195.pth", "vit_l"),
        ("sam_vit_h_4b8939.pth", "vit_h"),
    ],
)
def test_sam_architecture_is_derived_from_the_selected_checkpoint(filename, expected):
    assert face_identity._sam_architecture(filename) == expected


def test_unsupported_sam_checkpoint_fails_before_generation():
    with pytest.raises(ValueError, match="Unsupported SAM checkpoint"):
        face_identity._sam_architecture("sam2_hiera_large.pt")


def test_transfer_rejects_out_of_range_iterations_instead_of_silently_clamping():
    image = torch.ones((1, 32, 24, 3), dtype=torch.float32)
    with patch.object(face_identity, "_transfer") as transfer:
        with pytest.raises(ValueError, match="between 1 and 3"):
            ArchLocalFaceIdentityTransfer().transfer({"latent": object()}, image, iterations=4)
    transfer.assert_not_called()


def test_multiple_sam_passes_reuse_one_model_runtime_and_close_it():
    image = torch.ones((1, 4, 4, 3), dtype=torch.float32)
    bgr = np.zeros((4, 4, 3), dtype=np.uint8)
    mask = np.ones((4, 4), dtype=np.float32)
    runtime = MagicMock()
    with (
        patch.object(face_identity, "_SamRuntime", return_value=runtime) as runtime_factory,
        patch.object(face_identity, "_transfer", side_effect=[(bgr, mask), (bgr, mask)]) as transfer,
    ):
        ArchLocalFaceIdentityTransfer().transfer({"latent": object()}, image, iterations=2)
    runtime_factory.assert_called_once_with("sam_vit_b_01ec64.pth", "Auto (unload models)")
    assert all(call.kwargs["sam_runtime"] is runtime for call in transfer.call_args_list)
    runtime.close.assert_called_once_with()


def test_onnx_identity_models_stay_on_cpu_to_avoid_flux_vram_contention():
    assert face_identity._providers() == ["CPUExecutionProvider"]


def test_face_selection_supports_order_and_explicit_index():
    faces = np.array(
        [
            [0, 0, 10, 10, *range(10), 0.99],
            [0, 0, 20, 20, *range(10), 0.80],
        ],
        dtype=np.float32,
    )
    assert face_identity._select_face(faces, "largest", 0)[2] == 20
    assert face_identity._select_face(faces, "highest_confidence", 0)[-1] == pytest.approx(0.99)
    assert face_identity._select_face(faces, "largest", 1)[2] == 10
    with pytest.raises(ValueError, match="index 2"):
        face_identity._select_face(faces, "largest", 2)


def test_sam_box_is_clipped_to_image_bounds():
    face = np.array([95, 90, 20, 20, *range(10), 0.9], dtype=np.float32)
    assert face_identity._sam_box(face, image_width=100, image_height=100).tolist() == pytest.approx([92.6, 86.8, 100.0, 100.0])


def test_disabled_preflight_bypasses_detection_and_preserves_main_image():
    image = torch.ones((1, 32, 24, 3), dtype=torch.float32)
    with patch("custom_nodes.comfyui_arch_image_tools.face_identity._detect_faces") as detect:
        bundle, main, preview, status, mask_mode, selection = face_identity.ArchFaceIdentityPreflight().preflight(
            identity_image=image,
            main_image=image,
            enabled=False,
            face_selection="largest",
            source_face_index=0,
            face_threshold=0.7,
            sam_model="sam_vit_b_01ec64.pth",
        )
    detect.assert_not_called()
    assert bundle is None
    assert main is image
    assert preview is image
    assert "disabled" in status.lower()
    assert mask_mode == "SAM local"
    assert selection == dict(selection="largest", index=0, threshold=.7)
    assert face_identity.ArchFaceIdentityPreflight().check_lazy_status(enabled=False) == []


def test_strict_identity_gate_blocks_weak_results_but_disabled_transfer_bypasses():
    image = torch.ones((1, 32, 24, 3), dtype=torch.float32)
    mask = torch.ones((1, 32, 24), dtype=torch.float32)
    gate = face_identity.ArchIdentityGate()
    from comfy_execution.graph_utils import ExecutionBlocker
    blocked, status = gate.validate(image, mask, True, True, False, True, False, 0.2, 0.8)
    assert isinstance(blocked, ExecutionBlocker) and "0.200000" in status
    blocked, status = gate.validate(image, mask, True, True, True, True, True, 0.5, 0.8)
    assert isinstance(blocked, ExecutionBlocker) and "closer to the base" in status
    blocked, status = gate.validate(image, torch.zeros_like(mask), True, False, False, True, True, .9, .1)
    assert isinstance(blocked, ExecutionBlocker) and "no usable" in status
    result, status = gate.validate(image, torch.zeros_like(mask), False, True, True, False, False, 0.0, 0.0)
    assert result is image
    assert "disabled" in status.lower()


def test_disabled_transfer_is_zero_cost_passthrough():
    image = torch.ones((1, 32, 24, 3), dtype=torch.float32)
    result, mask, status, selection = ArchLocalFaceIdentityTransfer().transfer(None, image, enabled=False, target_face_index=2)
    assert result is image
    assert mask.shape == (1, 32, 24)
    assert not torch.any(mask)
    assert "bypassed" in status.lower()
    assert selection == dict(selection="largest", index=2, threshold=.7)


def test_detect_failure_is_clear():
    from custom_nodes.comfyui_arch_image_tools import face_identity

    fake = np.zeros((32, 32, 3), dtype=np.uint8)
    detector = type("Detector", (), {"setInputSize": lambda self, size: None, "detect": lambda self, image: (None, None)})()
    with patch.object(face_identity.cv2, "FaceDetectorYN") as factory:
        factory.create.return_value = detector
        with patch.object(face_identity, "_yunet_path", return_value=pytest.importorskip("pathlib").Path("yunet.onnx")):
            with pytest.raises(ValueError, match="No face detected"):
                face_identity._detect_largest(fake, 0.7)


def test_source_landmark_alignment_failure_is_clear_before_model_loading():
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    face = np.array([1, 1, 10, 10, *range(10), 0.9], dtype=np.float32)
    with (
        patch.object(face_identity.cv2, "estimateAffinePartial2D", return_value=(None, None)),
        patch.object(face_identity, "_session") as session,
    ):
        with pytest.raises(ValueError, match="Source face landmarks"):
            face_identity._source_embedding(image, face)
    session.assert_not_called()
