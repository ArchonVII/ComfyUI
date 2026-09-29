from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import torch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PACKAGE_ROOT / "canvas.py"


def load_canvas_module():
    assert MODULE_PATH.is_file(), "canvas node module has not been implemented"
    spec = importlib.util.spec_from_file_location("arch_image_canvas", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        ((1, 2200, 420, 3), (896, 1152, "3:4 portrait")),
        ((1, 1200, 1000, 3), (1024, 1024, "1:1 square")),
        ((1, 800, 1400, 3), (1152, 896, "4:3 landscape")),
        ((1, 5000, 300, 3), (896, 1152, "3:4 portrait")),
        ((1, 300, 5000, 3), (1152, 896, "4:3 landscape")),
    ],
)
def test_safe_auto_clamps_source_geometry_to_ordinary_canvas_families(shape, expected):
    module = load_canvas_module()
    image = type("Image", (), {"shape": shape})()

    assert module.ArchCanvasSize().select(image, "Auto (safe)") == expected


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("1:1", (1024, 1024, "1:1 square")),
        ("3:4", (896, 1152, "3:4 portrait")),
        ("2:3", (832, 1216, "2:3 portrait")),
        ("4:3", (1152, 896, "4:3 landscape")),
        ("3:2", (1216, 832, "3:2 landscape")),
        ("16:9", (1344, 768, "16:9 landscape")),
    ],
)
def test_manual_canvas_presets_are_near_one_megapixel_and_model_compatible(mode, expected):
    module = load_canvas_module()
    image = type("Image", (), {"shape": (1, 1024, 1024, 3)})()

    width, height, label = module.ArchCanvasSize().select(image, mode)

    assert (width, height, label) == expected
    assert width % 64 == 0
    assert height % 64 == 0
    assert 900_000 <= width * height <= 1_100_000


def test_canvas_node_rejects_empty_image_geometry():
    module = load_canvas_module()
    image = type("Image", (), {"shape": (1, 0, 0, 3)})()

    with pytest.raises(ValueError, match="positive width and height"):
        module.ArchCanvasSize().select(image, "Auto (safe)")


def test_require_mask_passes_detected_face_mask_through():
    module = load_canvas_module()
    mask = torch.zeros((1, 32, 32))
    mask[:, 8:24, 8:24] = 1.0

    assert module.ArchRequireMask().validate(mask)[0] is mask


def test_require_mask_fails_visibly_when_face_detection_is_empty():
    module = load_canvas_module()

    with pytest.raises(ValueError, match="No usable face mask"):
        module.ArchRequireMask().validate(torch.zeros((1, 32, 32)))
