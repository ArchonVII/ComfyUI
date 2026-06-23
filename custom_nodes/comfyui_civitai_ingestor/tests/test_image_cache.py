import sqlite3
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_civitai_ingestor.image_cache import cache_collection_images
from comfyui_civitai_ingestor.store import (
    collection_payload,
    init_db,
    upsert_collection,
    upsert_image,
)


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    return conn


def test_cache_collection_images_writes_file_and_updates_image_row(tmp_path):
    conn = make_conn()
    upsert_collection(
        conn,
        collection_id=8081491,
        source_url="https://civitai.red/collections/8081491",
        api_base="https://civitai.red",
    )
    upsert_image(
        conn,
        8081491,
        {
            "id": 100,
            "url": "https://image.example/100.jpeg",
            "width": 832,
            "height": 1216,
            "type": "image",
            "meta": {"prompt": "portrait"},
        },
    )
    conn.commit()

    def fetcher(url, token=None):
        assert url == "https://image.example/100.jpeg"
        assert token == "secret"
        return b"jpeg bytes", "image/jpeg"

    result = cache_collection_images(
        conn,
        8081491,
        cache_root=tmp_path,
        token="secret",
        fetcher=fetcher,
    )
    payload = collection_payload(conn, 8081491)
    image = payload["images"][0]

    assert result == {"cached": 1, "failed": 0, "skipped": 0}
    assert image["local_image_status"] == "cached"
    assert Path(image["local_image_path"]).suffix == ".jpg"
    assert Path(image["local_image_path"]).read_bytes() == b"jpeg bytes"

