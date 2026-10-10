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


@pytest.mark.parametrize("kind", ["subject", "environment"])
def test_collection_source_snapshot_filters_profiles_and_no_mutation(tmp_path, monkeypatch, kind):
    service = ReferenceLibraryService(tmp_path / "library")
    store = service.store
    collection = store.create_collection(kind, "Snapshot")
    cid = collection["id"]
    images = [service.import_image(cid, f"{color}.png", "image/png", png_bytes(color))["image"]
              for color in ("red", "blue")]
    tag = store.create_tag(name="chosen")
    store.batch_update_tags(cid, [images[0]["id"]], add_tag_ids=[tag["id"]])
    store.set_selection(cid, filters={"include_all": [tag["id"]], "include_any": [], "exclude": []})
    profile = store.create_profile(cid, name="Custom", positive_prompt="positive", negative_prompt="negative",
                                   loras=[{"name": "test.safetensors", "strength_model": 0.7, "strength_clip": 0.6, "enabled": True}])
    store.set_active_profile(cid, profile["id"])
    before = store.get_selection(cid)
    active_before = store.get_active(kind)
    monkeypatch.setattr(routes, "get_service", lambda: service)

    async def exercise():
        app = web.Application()
        routes.add_routes(app.router)
        async with TestClient(TestServer(app)) as client:
            url = f"/collections/{cid}/source"
            response = await client.get(url)
            assert response.status == 200, await response.text()
            payload = await response.json()
            assert payload["collection"] == {key: collection[key] for key in ("id", "name", "kind")}
            assert payload["profile"]["name"] == "Default"
            assert payload["paths"] == [str(service.managed_path(images[0]))]
            assert payload["pool_count"] == 1
            assert payload["total_count"] == 2
            assert payload["filtered"] is True
            assert payload["positive_prompt"] == ""
            response = await client.get(url, params={"filtered": "false", "profile_id": profile["id"]})
            assert response.status == 200
            payload = await response.json()
            assert payload["paths"] == [str(service.managed_path(image)) for image in images]
            assert payload["pool_count"] == 2
            assert payload["filtered"] is False
            assert payload["profile"] == profile
            assert payload["positive_prompt"] == "positive"
            assert payload["negative_prompt"] == "negative"
            assert payload["loras"] == profile["loras"]

    asyncio.run(exercise())
    assert store.get_selection(cid) == before
    assert store.get_active(kind) == active_before
    assert store.get_active_profile(cid) == profile


def test_collection_source_empty_pool_and_invalid_ids(tmp_path, monkeypatch):
    service = ReferenceLibraryService(tmp_path / "library")
    collection = service.store.create_collection("subject", "Empty")
    other = service.store.create_collection("environment", "Other")
    foreign_profile = service.store.list_profiles(other["id"])[0]
    monkeypatch.setattr(routes, "get_service", lambda: service)

    async def exercise():
        app = web.Application()
        routes.add_routes(app.router)
        async with TestClient(TestServer(app)) as client:
            url = f"/collections/{collection['id']}/source"
            response = await client.get(url)
            assert response.status == 200
            payload = await response.json()
            assert payload["paths"] == []
            assert payload["pool_count"] == payload["total_count"] == 0
            for query in ({"profile_id": foreign_profile["id"]}, {"profile_id": "bad"},
                          {"profile_id": ""}, {"filtered": "yes"}):
                assert (await client.get(url, params=query)).status == 400
            assert (await client.get("/collections/not-a-uuid/source")).status == 400
            assert (await client.get(f"/collections/{uuid4()}/source")).status == 404

    asyncio.run(exercise())


def test_browser_import_paths_copies_to_character_and_deduplicates(tmp_path, monkeypatch):
    service = ReferenceLibraryService(tmp_path / "library")
    monkeypatch.setattr(routes, "get_service", lambda: service)
    character = service.store.create_collection("subject", "Character")
    original = tmp_path / "source.png"
    content = png_bytes("blue")
    original.write_bytes(content)
    async def exercise():
        app = web.Application()
        routes.add_routes(app.router)
        async with TestClient(TestServer(app)) as client:
            url = f"/collections/{character['id']}/import-paths"
            for _ in range(2):
                response = await client.post(url, json={"paths": [str(original), str(original)]})
                assert response.status == 200, await response.text()
                assert len((await response.json())["imports"]) == 1
            bad = await client.post(url, json={"paths": ["relative.png", str(original)]})
            assert bad.status == 200
            partial = await bad.json()
            assert len(partial["imports"]) == 1
            assert partial["failures"][0]["path"] == "relative.png"
    asyncio.run(exercise())
    assert original.read_bytes() == content
    assert service.store.count_images(character["id"]) == 1
    image = service.store.list_images(character["id"])[0]
    assert service.managed_path(image).read_bytes() == content


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
