import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_smart_model_loader.catalog import AssetProfile, load_override_catalog, scan_local_profiles
from comfyui_smart_model_loader import routes


class FakeFolderPaths:
    filenames = {
        "diffusion_models": ["Flux\\4b\\flux-2-klein-4b.safetensors"],
        "checkpoints": ["sd_xl_base_1.0.safetensors"],
        "text_encoders": ["Flux\\flux2-klein-qwen3-4b.safetensors"],
        "vae": ["flux2-vae.safetensors"],
        "loras": ["Flux\\4b\\exact.safetensors"],
    }

    def get_filename_list(self, folder):
        return list(self.filenames[folder])

    def get_full_path(self, folder, name):
        return None


def test_scan_local_profiles_uses_comfy_folder_lists_without_loading_models():
    profiles = scan_local_profiles(folder_paths_module=FakeFolderPaths())

    by_name = {profile.name: profile for profile in profiles}

    assert by_name["Flux\\4b\\flux-2-klein-4b.safetensors"].kind == "diffusion_model"
    assert by_name["Flux\\4b\\flux-2-klein-4b.safetensors"].family == "flux"
    assert by_name["Flux\\4b\\exact.safetensors"].kind == "lora"
    assert by_name["Flux\\4b\\exact.safetensors"].family == "flux"


def test_route_payload_delegates_to_local_scan(monkeypatch):
    monkeypatch.setattr(
        routes,
        "scan_local_profiles",
        lambda: [
            AssetProfile(
                name="Flux\\4b\\flux-2-klein-4b.safetensors",
                kind="diffusion_model",
                family="flux",
                variant="flux2_klein_4b",
                confidence="high",
                evidence=[],
            ),
            AssetProfile(
                name="Flux\\4b\\exact.safetensors",
                kind="lora",
                family="flux",
                variant="flux2_klein_4b",
                confidence="high",
                evidence=[],
            ),
        ],
    )

    payload = routes.catalog_response_payload(
        selected_model="Flux\\4b\\flux-2-klein-4b.safetensors"
    )

    assert payload["selected_model"]["family"] == "flux"
    assert payload["filtered"]["loras"][0]["status"] == "compatible"


def test_load_override_catalog_returns_empty_schema_when_file_is_missing(tmp_path):
    catalog = load_override_catalog(tmp_path / "missing.json")

    assert catalog["version"] == 1
    assert catalog["diffusion_models"] == {}
    assert catalog["loras"] == {}
