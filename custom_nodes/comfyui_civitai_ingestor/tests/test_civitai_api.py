import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_civitai_ingestor.civitai_api import image_resource_refs, parse_collection_target


def test_parse_collection_target_accepts_red_collection_url():
    target = parse_collection_target("https://civitai.red/collections/8081491")

    assert target.collection_id == 8081491
    assert target.api_base == "https://civitai.red"


def test_parse_collection_target_accepts_plain_id():
    target = parse_collection_target("8081491")

    assert target.collection_id == 8081491
    assert target.api_base == "https://civitai.com"


def test_image_resource_refs_prefers_civitai_resources_and_adds_missing_ids():
    refs = image_resource_refs(
        {
            "id": 1,
            "modelVersionIds": [10, 11],
            "meta": {
                "civitaiResources": [
                    {"type": "checkpoint", "modelVersionId": 10, "modelVersionName": "base"},
                    {"type": "lora", "modelVersionId": 12, "weight": 0.75, "modelVersionName": "style"},
                ]
            },
        }
    )

    assert [item["model_version_id"] for item in refs] == [10, 12, 11]
    assert refs[1]["weight"] == 0.75
    assert refs[2]["source"] == "image.modelVersionIds"

