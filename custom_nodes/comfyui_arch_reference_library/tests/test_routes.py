import asyncio
from io import BytesIO
from pathlib import Path
import sys
from uuid import uuid4

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_arch_reference_library import routes
from comfyui_arch_reference_library.service import ReferenceLibraryService


def png_bytes(color):
    buffer = BytesIO()
    Image.new("RGB", (20, 16), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_payload_validators_reject_unknown_fields_bad_ids_and_unsafe_delete():
    with pytest.raises(ValueError, match="JSON object"):
        routes.require_object([])
    with pytest.raises(ValueError, match="canonical UUID"):
        routes.require_id("not-an-id")
    with pytest.raises(ValueError, match="unknown"):
        routes.validate_collection_create(
            {"kind": "subject", "name": "Alice", "extra": True}
        )
    with pytest.raises(ValueError, match="confirmation"):
        routes.validate_permanent_delete({"confirmation": "yes"})
    with pytest.raises(ValueError, match="unknown"):
        routes.validate_membership_tags(
            {
                "collection_id": str(uuid4()),
                "image_ids": [str(uuid4())],
                "add_tag_ids": [],
                "remove_tag_ids": [],
                "extra": True,
            }
        )


def test_bootstrap_mutation_upload_filter_reroll_profile_and_thumbnail_routes(
    tmp_path, monkeypatch
):
    service = ReferenceLibraryService(tmp_path / "reference_library")
    monkeypatch.setattr(routes, "get_service", lambda: service)
    monkeypatch.setattr(
        routes, "local_lora_names", lambda: ["characters/alice.safetensors"]
    )

    async def exercise():
        app = web.Application(client_max_size=2 * 1024 * 1024)
        routes.add_routes(app.router)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            empty = await client.get("/bootstrap?kind=subject")
            assert empty.status == 200
            assert (await empty.json())["collections"] == []

            created_response = await client.post(
                "/collections",
                json={"kind": "subject", "name": "Alice", "description": "Lead"},
            )
            assert created_response.status == 200
            collection = (await created_response.json())["collection"]

            active = await client.put(
                "/active/subject", json={"collection_id": collection["id"]}
            )
            assert active.status == 200

            form = FormData()
            for index in range(4):
                form.add_field(
                    "files",
                    png_bytes((index * 30, 40, 50)),
                    filename=f"{index}.png",
                    content_type="image/png",
                )
            uploaded = await client.post(f"/import/{collection['id']}", data=form)
            assert uploaded.status == 200
            images = (await uploaded.json())["imports"]
            assert len(images) == 4

            tag_response = await client.post(
                "/tags", json={"name": "portrait", "group_name": "framing"}
            )
            tag = (await tag_response.json())["tag"]
            image_ids = [item["image"]["id"] for item in images]
            batch = await client.patch(
                "/membership-tags",
                json={
                    "collection_id": collection["id"],
                    "image_ids": image_ids,
                    "add_tag_ids": [tag["id"]],
                    "remove_tag_ids": [],
                },
            )
            assert batch.status == 200
            assert (await batch.json()) == {"updated": 4}

            selection = await client.put(
                f"/selections/{collection['id']}",
                json={
                    "filters": {
                        "include_all": [tag["id"]],
                        "include_any": [],
                        "exclude": [],
                    },
                    "policy": "seeded",
                    "seed": 7,
                },
            )
            assert selection.status == 200
            rerolled = await client.post(
                f"/selections/{collection['id']}/reroll", json={}
            )
            assert rerolled.status == 200
            assert all(
                slot["image_id"]
                for slot in (await rerolled.json())["selection"]["slots"]
            )

            profile_response = await client.post(
                "/profiles",
                json={
                    "collection_id": collection["id"],
                    "name": "Flux",
                    "model_family": "flux",
                    "positive_prompt": "alice token",
                    "negative_prompt": "",
                    "loras": [
                        {
                            "name": "characters/alice.safetensors",
                            "strength_model": 0.8,
                            "strength_clip": 0.6,
                            "enabled": True,
                        }
                    ],
                },
            )
            assert profile_response.status == 200
            profile = (await profile_response.json())["profile"]
            set_profile = await client.put(
                "/active/subject",
                json={"collection_id": collection["id"], "profile_id": profile["id"]},
            )
            assert set_profile.status == 200

            bootstrap = await client.get(
                f"/bootstrap?kind=subject&collection_id={collection['id']}"
            )
            payload = await bootstrap.json()
            assert payload["active"]["subject"]["id"] == collection["id"]
            assert payload["detail"]["active_profile"]["id"] == profile["id"]
            assert len(payload["detail"]["images"]) == 4
            assert payload["loras"] == ["characters/alice.safetensors"]
            assert payload["orphans"] == []
            assert Path(payload["data_path"]) == service.root

            thumbnail = await client.get(f"/images/{image_ids[0]}/thumbnail")
            assert thumbnail.status == 200
            assert thumbnail.headers["X-Content-Type-Options"] == "nosniff"
            assert thumbnail.headers["Cache-Control"] == "private, no-store"
            assert (await thumbnail.read()).startswith(b"\xff\xd8")
        finally:
            await client.close()

    asyncio.run(exercise())


def test_unlink_and_permanent_delete_routes_are_separate_and_guarded(
    tmp_path, monkeypatch
):
    service = ReferenceLibraryService(tmp_path / "reference_library")
    collection = service.store.create_collection("environment", "Studio")
    imported = service.import_image(
        collection["id"], "studio.png", "image/png", png_bytes((1, 2, 3))
    )["image"]
    monkeypatch.setattr(routes, "get_service", lambda: service)

    async def exercise():
        app = web.Application()
        routes.add_routes(app.router)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            blocked = await client.delete(
                f"/images/{imported['id']}", json={"confirmation": "DELETE"}
            )
            assert blocked.status == 400
            assert "still belongs" in await blocked.text()

            unlinked = await client.delete(
                f"/collections/{collection['id']}/images/{imported['id']}"
            )
            assert unlinked.status == 200
            assert service.managed_path(imported).is_file()
            orphan_payload = await (
                await client.get("/bootstrap?kind=environment")
            ).json()
            assert orphan_payload["orphans"][0]["id"] == imported["id"]

            wrong = await client.delete(
                f"/images/{imported['id']}", json={"confirmation": "remove"}
            )
            assert wrong.status == 400
            deleted = await client.delete(
                f"/images/{imported['id']}", json={"confirmation": "DELETE"}
            )
            assert deleted.status == 200
            with pytest.raises(KeyError, match="not found"):
                service.store.get_image(imported["id"])
        finally:
            await client.close()

    asyncio.run(exercise())


def test_bootstrap_pages_large_filtered_galleries(tmp_path, monkeypatch):
    service = ReferenceLibraryService(tmp_path / "reference_library")
    collection = service.store.create_collection("subject", "Large library")
    for index in range(205):
        service.store.register_image(
            collection["id"],
            sha256=f"{index:064x}",
            relative_path=f"images/{index:02x}/{index:064x}.png",
            original_filename=f"{index:03}.png",
            media_type="image/png",
            width=16,
            height=16,
        )
    monkeypatch.setattr(routes, "get_service", lambda: service)
    monkeypatch.setattr(routes, "local_lora_names", lambda: [])

    first = routes.bootstrap_payload(
        kind="subject", collection_id=collection["id"], page=1, page_size=100
    )
    third = routes.bootstrap_payload(
        kind="subject", collection_id=collection["id"], page=3, page_size=100
    )

    assert len(first["detail"]["images"]) == 100
    assert first["detail"]["pagination"] == {
        "page": 1,
        "page_size": 100,
        "total": 205,
        "total_pages": 3,
    }
    assert len(third["detail"]["images"]) == 5


def test_bootstrap_pages_unassigned_managed_images(tmp_path, monkeypatch):
    service = ReferenceLibraryService(tmp_path / "reference_library")
    collection = service.store.create_collection("subject", "Temporary")
    for index in range(105):
        service.store.register_image(
            collection["id"],
            sha256=f"{index:064x}",
            relative_path=f"images/{index:02x}/{index:064x}.png",
            original_filename=f"{index:03}.png",
            media_type="image/png",
            width=16,
            height=16,
        )
    service.store.delete_collection(collection["id"])
    monkeypatch.setattr(routes, "get_service", lambda: service)
    monkeypatch.setattr(routes, "local_lora_names", lambda: [])

    payload = routes.bootstrap_payload(orphan_page=3, orphan_page_size=50)

    assert len(payload["orphans"]) == 5
    assert payload["orphan_pagination"] == {
        "page": 3,
        "page_size": 50,
        "total": 105,
        "total_pages": 3,
    }
