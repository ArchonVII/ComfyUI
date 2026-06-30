import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_civitai_ingestor import civitai_api
from comfyui_civitai_ingestor.civitai_api import (
    CollectionTarget,
    image_resource_refs,
    parse_collection_target,
    parse_ingest_target,
)


def test_parse_collection_target_accepts_red_collection_url():
    target = parse_collection_target("https://civitai.red/collections/8081491")

    assert target.collection_id == 8081491
    assert target.api_base == "https://civitai.red"


def test_parse_collection_target_accepts_plain_id():
    target = parse_collection_target("8081491")

    assert target.collection_id == 8081491
    assert target.api_base == "https://civitai.com"


def test_parse_ingest_target_accepts_pasted_image_and_post_urls():
    target = parse_ingest_target(
        """
        https://civitai.com/images/12097475
        https://civitai.com/posts/2669960
        """
    )

    assert target.collection_id < 0
    assert target.kind == "urls"
    assert [(query.param, query.value) for query in target.queries] == [
        ("imageId", 12097475),
        ("postId", 2669960),
    ]


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


def test_fetch_collection_images_rejects_unfiltered_global_image_feed(monkeypatch):
    global_feed = {
        "items": [
            {"id": 12097475, "url": "https://image.example/a.jpeg", "postId": 2669960},
            {"id": 64399178, "url": "https://image.example/b.jpeg", "postId": 14356296},
        ],
        "metadata": {},
    }
    requested_urls = []

    def fake_request_json(url, token=None):
        requested_urls.append(url)
        return global_feed

    monkeypatch.setattr(civitai_api, "request_json", fake_request_json)

    with pytest.raises(RuntimeError, match="ignored collectionId"):
        civitai_api.fetch_collection_images(
            CollectionTarget(8081491, "https://civitai.com", "8081491"),
            limit=2,
        )

    assert "collectionId=8081491" in requested_urls[0]
    assert "collectionId=" not in requested_urls[1]


def test_fetch_collection_images_uses_documented_filters_for_pasted_urls(monkeypatch):
    requested_urls = []

    def fake_request_json(url, token=None):
        requested_urls.append(url)
        if "imageId=12097475" in url:
            return {
                "items": [
                    {
                        "id": 12097475,
                        "postId": 2669960,
                        "url": "https://image.example/a.jpeg",
                        "meta": {"id": 12097475, "meta": {"prompt": "nested prompt"}},
                        "modelVersionIds": [290640],
                    }
                ],
                "metadata": {},
            }
        if "postId=2669960" in url:
            return {
                "items": [
                    {
                        "id": 12097476,
                        "postId": 2669960,
                        "url": "https://image.example/b.jpeg",
                        "meta": {"prompt": "direct prompt"},
                        "modelVersionIds": [290640],
                    }
                ],
                "metadata": {},
            }
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(civitai_api, "request_json", fake_request_json)

    target = parse_ingest_target(
        "https://civitai.com/images/12097475\nhttps://civitai.com/posts/2669960"
    )
    images = civitai_api.fetch_collection_images(target)

    assert [image["id"] for image in images] == [12097475, 12097476]
    assert images[0]["meta"]["prompt"] == "nested prompt"
    assert all("collectionId=" not in url for url in requested_urls)
    assert any("imageId=12097475" in url for url in requested_urls)
    assert any("postId=2669960" in url for url in requested_urls)
