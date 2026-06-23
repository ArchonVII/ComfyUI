import sqlite3
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_civitai_ingestor import ingest as ingest_module


def test_ingest_collection_uses_collection_images_and_model_versions(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ingest_module,
        "fetch_collection_images",
        lambda target, **kwargs: [
            {
                "id": 10,
                "postId": 20,
                "url": "https://image.example/10.jpeg",
                "width": 512,
                "height": 768,
                "meta": {
                    "prompt": "portrait",
                    "civitaiResources": [{"type": "lora", "modelVersionId": 99, "weight": 0.8}],
                },
                "modelVersionIds": [99],
            }
        ],
    )
    monkeypatch.setattr(
        ingest_module,
        "fetch_model_version",
        lambda api_base, model_version_id, token=None: {
            "id": model_version_id,
            "modelId": 1,
            "name": "v1",
            "baseModel": "SDXL 1.0",
            "model": {"name": "Test LoRA", "type": "LORA"},
            "trainedWords": ["trigger"],
            "files": [
                {
                    "id": 123,
                    "name": "test_lora.safetensors",
                    "type": "Model",
                    "sizeKB": 10,
                    "primary": True,
                    "downloadUrl": "https://civitai.red/api/download/models/99",
                    "hashes": {"SHA256": "B" * 64},
                }
            ],
        },
    )
    monkeypatch.setattr(
        ingest_module,
        "refresh_local_status",
        lambda conn, collection_id=None: {"present": 0, "present_elsewhere": 0, "missing": 1},
    )

    db_path = tmp_path / "ingest.sqlite3"
    payload = ingest_module.ingest_collection(
        "https://civitai.red/collections/8081491",
        max_items=1,
        db_path=str(db_path),
    )

    assert payload["ingest"]["collection_id"] == 8081491
    assert payload["summary"]["images"] == 1
    assert payload["resources"][0]["target_folder"] == "loras"
