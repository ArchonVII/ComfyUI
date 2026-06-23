import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_civitai_ingestor.local_models import find_local_match, target_folder_for_file


class FakeFolderPaths:
    data = {
        "checkpoints": ["ponyDiffusionV6XL_v6StartWithThisOne.safetensors"],
        "diffusion_models": [],
        "loras": ["fantasy/Cherry-Gig.safetensors"],
        "vae": [],
        "text_encoders": [],
        "embeddings": [],
        "controlnet": [],
        "upscale_models": [],
    }

    def get_filename_list(self, folder):
        return list(self.data.get(folder, []))

    def get_full_path(self, folder, name):
        return f"C:/models/{folder}/{name}"


def test_target_folder_for_lora_model_version():
    folder = target_folder_for_file(
        {"model": {"type": "LORA"}},
        {"name": "Cherry-Gig.safetensors", "type": "Model"},
    )

    assert folder == "loras"


def test_target_folder_uses_vae_for_vae_named_safetensors():
    folder = target_folder_for_file(
        {"model": {"type": "Checkpoint"}},
        {"name": "sdxl_vae.safetensors", "type": "Model"},
    )

    assert folder == "vae"


def test_target_folder_keeps_no_vae_checkpoint_in_checkpoints():
    folder = target_folder_for_file(
        {"model": {"type": "Checkpoint"}},
        {"name": "anime_model_noVAE.safetensors", "type": "Model"},
    )

    assert folder == "checkpoints"


def test_find_local_match_checks_target_folder_first():
    match = find_local_match(
        "fantasy/Cherry-Gig.safetensors",
        "loras",
        folder_paths_module=FakeFolderPaths(),
    )

    assert match["status"] == "present"
    assert match["local_folder"] == "loras"


def test_find_local_match_finds_file_elsewhere():
    match = find_local_match(
        "ponyDiffusionV6XL_v6StartWithThisOne.safetensors",
        "loras",
        folder_paths_module=FakeFolderPaths(),
    )

    assert match["status"] == "present_elsewhere"
    assert match["local_folder"] == "checkpoints"
