from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_identity_score.nodes import NODE_DISPLAY_NAME_MAPPINGS, OpenCVIdentityScore


def test_identity_score_is_arch_prefixed_for_searchability():
    assert NODE_DISPLAY_NAME_MAPPINGS["OpenCVIdentityScore"] == "arch-OpenCV Identity Score"
    assert OpenCVIdentityScore.CATEGORY == "arch-image/identity"
