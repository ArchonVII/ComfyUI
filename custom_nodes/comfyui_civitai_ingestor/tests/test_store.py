import sqlite3
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_civitai_ingestor.store import (
    collection_payload,
    init_db,
    refresh_local_status,
    upsert_collection,
    upsert_image,
    upsert_image_resource_links,
    upsert_model_version,
)


class EmptyFolderPaths:
    def get_filename_list(self, folder):
        return []

    def get_full_path(self, folder, name):
        return None


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    return conn


def test_store_upserts_collection_image_resources_and_local_status():
    conn = make_conn()
    image = {
        "id": 100,
        "postId": 200,
        "url": "https://image.example/test.jpeg",
        "hash": "blurhash",
        "width": 832,
        "height": 1216,
        "nsfwLevel": "None",
        "type": "image",
        "username": "tester",
        "baseModel": "Pony",
        "createdAt": "2024-01-01T00:00:00Z",
        "meta": {
            "prompt": "score_9, portrait",
            "negativePrompt": "low quality",
            "seed": 123,
            "steps": 30,
            "sampler": "Euler a",
            "cfgScale": 7,
            "civitaiResources": [
                {"type": "checkpoint", "modelVersionId": 290640},
            ],
        },
        "modelVersionIds": [290640],
    }
    version = {
        "id": 290640,
        "modelId": 257749,
        "name": "V6",
        "baseModel": "Pony",
        "air": "urn:air:sdxl:checkpoint:civitai:257749@290640",
        "trainedWords": ["score_9"],
        "model": {"name": "Pony Diffusion", "type": "Checkpoint"},
        "files": [
            {
                "id": 1,
                "name": "pony.safetensors",
                "type": "Model",
                "sizeKB": 1000,
                "primary": True,
                "downloadUrl": "https://civitai.red/api/download/models/290640",
                "hashes": {"SHA256": "A" * 64, "AutoV2": "ABC"},
            }
        ],
    }

    upsert_collection(conn, collection_id=8081491, source_url="https://civitai.red/collections/8081491", api_base="https://civitai.red")
    upsert_image(conn, 8081491, image)
    assert upsert_image_resource_links(conn, image) == [290640]
    upsert_model_version(conn, version)
    counts = refresh_local_status(conn, collection_id=8081491, folder_paths_module=EmptyFolderPaths())
    conn.commit()

    payload = collection_payload(conn, 8081491)
    assert counts["missing"] == 1
    assert payload["summary"]["images_with_meta"] == 1
    assert payload["resources"][0]["target_folder"] == "checkpoints"
    assert payload["resources"][0]["trained_words"] == ["score_9"]

