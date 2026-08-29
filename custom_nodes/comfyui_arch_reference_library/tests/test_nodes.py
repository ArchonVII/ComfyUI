from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image
import pytest
import torch


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import comfyui_arch_reference_library as package
from comfyui_arch_reference_library import nodes
from comfyui_arch_reference_library.service import ReferenceLibraryService


def image_bytes(color, size=(16, 12)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def populated_collection(service, kind, name):
    collection = service.store.create_collection(kind, name)
    images = []
    for index in range(4):
        result = service.import_image(
            collection["id"],
            f"{index}.png",
            "image/png",
            image_bytes((index * 20, 40, 60), size=(16 + index, 12 + index)),
        )
        images.append(result["image"])
    service.reroll(collection["id"])
    return collection, images


@pytest.fixture
def service(tmp_path):
    return ReferenceLibraryService(tmp_path / "reference_library")


def test_package_registers_two_selectors_and_lora_applicator():
    assert package.WEB_DIRECTORY == "./web"
    assert package.NODE_CLASS_MAPPINGS == {
        "ArchSubjectReferenceSelector": nodes.SubjectReferenceSelector,
        "ArchEnvironmentReferenceSelector": nodes.EnvironmentReferenceSelector,
        "ArchApplyReferenceProfileLoras": nodes.ApplyReferenceProfileLoras,
    }


def test_subject_selector_follows_sidebar_and_returns_four_images_list_prompts_and_manifest(
    service, monkeypatch
):
    collection, _images = populated_collection(service, "subject", "Alice")
    default = service.store.get_active_profile(collection["id"])
    service.store.update_profile(
        default["id"],
        positive_prompt="alice token",
        negative_prompt="different person",
        loras=[
            {
                "name": "characters/alice.safetensors",
                "strength_model": 0.8,
                "strength_clip": 0.6,
                "enabled": True,
            }
        ],
    )
    service.store.set_active("subject", collection["id"])
    monkeypatch.setattr(nodes, "get_service", lambda: service)

    result = nodes.SubjectReferenceSelector().select("follow_sidebar", "", "")

    assert len(result) == 10
    assert all(isinstance(value, torch.Tensor) for value in result[:4])
    assert all(value.shape[0] == 1 and value.shape[-1] == 3 for value in result[:4])
    assert len(result[4]) == 4
    assert [tuple(value.shape[1:3]) for value in result[4]] == [
        tuple(value.shape[1:3]) for value in result[:4]
    ]
    assert result[5] == "alice token"
    assert result[6] == "different person"
    lora_manifest = json.loads(result[7])
    metadata = json.loads(result[8])
    assert lora_manifest["loras"][0]["name"] == "characters/alice.safetensors"
    assert metadata["collection"]["id"] == collection["id"]
    assert metadata["collection"]["kind"] == "subject"
    assert len(metadata["references"]) == 4
    assert result[9] == collection["id"]
    assert nodes.SubjectReferenceSelector.OUTPUT_IS_LIST[4] is True


def test_environment_selector_can_pin_stable_collection_and_profile_ids(
    service, monkeypatch
):
    environment, _images = populated_collection(service, "environment", "Apartment")
    profile = service.store.create_profile(
        environment["id"],
        name="Wan",
        model_family="wan",
        positive_prompt="warm apartment",
    )
    other, _ = populated_collection(service, "environment", "Forest")
    service.store.set_active("environment", other["id"])
    monkeypatch.setattr(nodes, "get_service", lambda: service)

    result = nodes.EnvironmentReferenceSelector().select(
        "pinned", environment["id"], profile["id"]
    )

    assert result[5] == "warm apartment"
    assert json.loads(result[8])["profile"]["id"] == profile["id"]
    assert result[9] == environment["id"]


def test_selector_loads_only_the_four_locked_memberships(service, monkeypatch):
    collection, _images = populated_collection(service, "subject", "Alice")
    service.store.set_active("subject", collection["id"])
    monkeypatch.setattr(nodes, "get_service", lambda: service)
    monkeypatch.setattr(
        service.store,
        "list_images",
        lambda *args, **kwargs: pytest.fail("selector should not scan the collection"),
    )

    result = nodes.SubjectReferenceSelector().select("follow_sidebar", "", "")

    assert len(result[4]) == 4


def test_selector_rejects_kind_mismatch_missing_active_collection_and_empty_slots(
    service, monkeypatch
):
    subject = service.store.create_collection("subject", "Alice")
    environment = service.store.create_collection("environment", "Apartment")
    monkeypatch.setattr(nodes, "get_service", lambda: service)

    with pytest.raises(ValueError, match="active subject"):
        nodes.SubjectReferenceSelector().select("follow_sidebar", "", "")
    with pytest.raises(ValueError, match="kind"):
        nodes.SubjectReferenceSelector().select("pinned", environment["id"], "")
    service.store.set_active("subject", subject["id"])
    with pytest.raises(ValueError, match="four locked"):
        nodes.SubjectReferenceSelector().select("follow_sidebar", "", "")


def test_selector_change_fingerprint_uses_catalog_state(service, monkeypatch):
    monkeypatch.setattr(nodes, "get_service", lambda: service)
    before = nodes.SubjectReferenceSelector.IS_CHANGED("follow_sidebar", "", "")
    service.store.create_collection("subject", "Alice")
    after = nodes.SubjectReferenceSelector.IS_CHANGED("follow_sidebar", "", "")
    assert before != after


class FakeFolderPaths:
    def __init__(self, paths):
        self.paths = paths

    def get_full_path_or_raise(self, kind, name):
        assert kind == "loras"
        if name not in self.paths:
            raise FileNotFoundError(name)
        return str(self.paths[name])


def test_lora_applicator_applies_enabled_entries_in_order_and_caches_loaded_files(
    tmp_path,
):
    first = tmp_path / "first.safetensors"
    second = tmp_path / "second.safetensors"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    loads = []
    applications = []

    def load_torch_file(path, *, safe_load, return_metadata):
        loads.append(path)
        assert safe_load is True
        assert return_metadata is True
        return {"path": path}, {"source": "test"}

    def apply_lora(model, clip, lora, strength_model, strength_clip, *, lora_metadata):
        applications.append(
            (lora["path"], strength_model, strength_clip, lora_metadata)
        )
        return f"{model}>{Path(lora['path']).stem}", f"{clip}>{Path(lora['path']).stem}"

    applicator = nodes.ApplyReferenceProfileLoras(
        folder_paths_module=FakeFolderPaths(
            {"first.safetensors": first, "second.safetensors": second}
        ),
        load_torch_file=load_torch_file,
        apply_lora=apply_lora,
    )
    manifest = json.dumps(
        {
            "version": 1,
            "loras": [
                {
                    "name": "first.safetensors",
                    "strength_model": 0.8,
                    "strength_clip": 0.6,
                    "enabled": True,
                },
                {
                    "name": "disabled.safetensors",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                    "enabled": False,
                },
                {
                    "name": "second.safetensors",
                    "strength_model": 0.3,
                    "strength_clip": 0.0,
                    "enabled": True,
                },
            ],
        }
    )

    model, clip, metadata_json = applicator.apply("model", "clip", manifest, True)
    applicator.apply("model", "clip", manifest, True)

    assert model == "model>first>second"
    assert clip == "clip>first>second"
    assert [Path(item[0]).name for item in applications[:2]] == [
        "first.safetensors",
        "second.safetensors",
    ]
    assert len(loads) == 2
    assert [item["name"] for item in json.loads(metadata_json)["applied"]] == [
        "first.safetensors",
        "second.safetensors",
    ]


def test_lora_applicator_passthrough_and_manifest_validation(tmp_path):
    applicator = nodes.ApplyReferenceProfileLoras(
        folder_paths_module=FakeFolderPaths({}),
        load_torch_file=lambda *args, **kwargs: pytest.fail("loader should not run"),
        apply_lora=lambda *args, **kwargs: pytest.fail("applicator should not run"),
    )

    model, clip, metadata = applicator.apply(
        "model", "clip", '{"version":1,"loras":[]}', True
    )
    assert (model, clip) == ("model", "clip")
    assert json.loads(metadata)["applied"] == []

    with pytest.raises(ValueError, match="valid JSON"):
        applicator.apply("model", "clip", "{bad", True)
    with pytest.raises(ValueError, match="unknown"):
        applicator.apply(
            "model",
            "clip",
            json.dumps(
                {
                    "version": 1,
                    "loras": [
                        {
                            "name": "x",
                            "strength_model": 1,
                            "strength_clip": 1,
                            "enabled": True,
                            "extra": 1,
                        }
                    ],
                }
            ),
            True,
        )


def test_lora_applicator_can_skip_missing_local_lora_when_not_strict():
    applicator = nodes.ApplyReferenceProfileLoras(
        folder_paths_module=FakeFolderPaths({}),
        load_torch_file=lambda *args, **kwargs: pytest.fail("loader should not run"),
        apply_lora=lambda *args, **kwargs: pytest.fail("applicator should not run"),
    )
    manifest = json.dumps(
        {
            "version": 1,
            "loras": [
                {
                    "name": "missing.safetensors",
                    "strength_model": 1.0,
                    "strength_clip": 1.0,
                    "enabled": True,
                }
            ],
        }
    )

    model, clip, metadata = applicator.apply("model", "clip", manifest, False)
    assert (model, clip) == ("model", "clip")
    assert json.loads(metadata)["skipped"][0]["reason"] == "missing"
    with pytest.raises(ValueError, match="not available"):
        applicator.apply("model", "clip", manifest, True)
