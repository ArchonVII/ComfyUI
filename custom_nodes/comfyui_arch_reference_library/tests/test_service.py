from io import BytesIO
from pathlib import Path
import sys

from PIL import Image
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_arch_reference_library.service import ReferenceLibraryService


def png_bytes(color=(120, 40, 200), size=(48, 32)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def service(tmp_path):
    return ReferenceLibraryService(tmp_path / "reference_library")


@pytest.fixture
def subject(service):
    return service.store.create_collection("subject", "Alice")


def import_named(service, collection_id, name, color):
    return service.import_image(collection_id, name, "image/png", png_bytes(color))


def test_import_copies_without_changing_source_and_deduplicates_content(service, tmp_path):
    first_collection = service.store.create_collection("subject", "Alice")
    second_collection = service.store.create_collection("environment", "Studio")
    source = tmp_path / "source.png"
    source.write_bytes(png_bytes())
    original = source.read_bytes()

    first = service.import_image(
        first_collection["id"], source.name, "image/png", source.read_bytes()
    )
    second = service.import_image(
        second_collection["id"], "renamed.png", "image/png", source.read_bytes()
    )

    assert first["image"]["id"] == second["image"]["id"]
    assert source.read_bytes() == original
    assert service.managed_path(first["image"]).read_bytes() == original
    assert len(list(service.images_root.rglob("*.png"))) == 1
    assert first["image"]["width"] == 48
    assert first["image"]["height"] == 32
    assert service.store.list_images(first_collection["id"])[0]["tags"] == []
    assert service.store.list_images(second_collection["id"])[0]["tags"] == []


def test_failed_decode_and_oversized_upload_leave_no_rows_or_files(service, subject):
    with pytest.raises(ValueError, match="valid still image"):
        service.import_image(subject["id"], "bad.png", "image/png", b"not an image")
    with pytest.raises(ValueError, match="maximum"):
        service.import_image(
            subject["id"],
            "large.png",
            "image/png",
            b"x" * 11,
            max_bytes=10,
        )

    assert service.store.list_images(subject["id"]) == []
    assert [path for path in service.images_root.rglob("*") if path.is_file()] == []


def test_thumbnail_is_local_regenerable_and_confined_to_thumbnail_root(service, subject):
    imported = import_named(service, subject["id"], "face.png", (10, 20, 30))
    thumbnail = service.thumbnail_path(imported["image"]["id"])

    assert thumbnail.is_file()
    assert thumbnail.is_relative_to(service.thumbnails_root)
    with Image.open(thumbnail) as preview:
        assert max(preview.size) <= 320
        assert preview.format == "JPEG"

    thumbnail.unlink()
    assert service.ensure_thumbnail(imported["image"]["id"]) == thumbnail
    assert thumbnail.is_file()


def test_batch_tags_are_membership_specific_and_filter_supports_all_any_exclude(service):
    subject = service.store.create_collection("subject", "Alice")
    environment = service.store.create_collection("environment", "Studio")
    first = import_named(service, subject["id"], "first.png", (255, 0, 0))["image"]
    second = import_named(service, subject["id"], "second.png", (0, 255, 0))["image"]
    third = import_named(service, subject["id"], "third.png", (0, 0, 255))["image"]
    service.store.add_image_membership(environment["id"], first["id"])

    portrait = service.store.create_tag("portrait", "framing")
    looking = service.store.create_tag("looking at camera", "gaze")
    rejected = service.store.create_tag("reject", "quality")
    service.store.batch_update_tags(
        subject["id"],
        [first["id"], second["id"]],
        add_tag_ids=[portrait["id"]],
    )
    service.store.batch_update_tags(
        subject["id"],
        [first["id"]],
        add_tag_ids=[looking["id"]],
    )
    service.store.batch_update_tags(
        subject["id"],
        [second["id"]],
        add_tag_ids=[rejected["id"]],
    )

    all_match = service.store.list_images(
        subject["id"], include_all=[portrait["id"], looking["id"]]
    )
    any_match = service.store.list_images(
        subject["id"], include_any=[looking["id"], rejected["id"]]
    )
    clean_portraits = service.store.list_images(
        subject["id"], include_all=[portrait["id"]], exclude=[rejected["id"]]
    )

    assert [item["id"] for item in all_match] == [first["id"]]
    assert {item["id"] for item in any_match} == {first["id"], second["id"]}
    assert [item["id"] for item in clean_portraits] == [first["id"]]
    assert service.store.list_images(environment["id"])[0]["tags"] == []
    assert third["id"] not in {item["id"] for item in clean_portraits}

    service.store.batch_update_tags(
        subject["id"], [first["id"]], remove_tag_ids=[looking["id"]]
    )
    assert service.store.list_images(
        subject["id"], include_all=[looking["id"]]
    ) == []


def test_tag_vocabulary_is_editable_and_deletion_removes_associations(service, subject):
    image = import_named(service, subject["id"], "face.png", (1, 2, 3))["image"]
    tag = service.store.create_tag("face only", "framing")
    service.store.batch_update_tags(subject["id"], [image["id"]], add_tag_ids=[tag["id"]])

    updated = service.store.update_tag(tag["id"], name="close-up", group_name="shot")
    assert updated["name"] == "close-up"
    assert updated["group_name"] == "shot"
    assert service.store.list_images(subject["id"])[0]["tags"][0]["name"] == "close-up"

    service.store.delete_tag(tag["id"])
    assert service.store.list_images(subject["id"])[0]["tags"] == []


def test_reroll_keeps_pins_and_fills_automatic_slots_from_filtered_pool(service, subject):
    images = [
        import_named(service, subject["id"], f"{index}.png", (index, index, index))["image"]
        for index in range(1, 7)
    ]
    portrait = service.store.create_tag("portrait", "framing")
    service.store.batch_update_tags(
        subject["id"], [image["id"] for image in images], add_tag_ids=[portrait["id"]]
    )
    service.store.set_selection(
        subject["id"],
        filters={"include_all": [portrait["id"]], "include_any": [], "exclude": []},
        slots=[{"slot": 1, "image_id": images[0]["id"], "pinned": True}],
        policy="seeded",
        seed=42,
    )

    result = service.reroll(subject["id"])

    assert result["slots"][0]["image_id"] == images[0]["id"]
    assert result["slots"][0]["pinned"] is True
    assert len({slot["image_id"] for slot in result["slots"]}) == 4
    assert result["reroll_count"] == 1


def test_sequential_reroll_advances_and_empty_or_small_pools_are_clear_errors(service, subject):
    with pytest.raises(ValueError, match="four distinct"):
        service.reroll(subject["id"])

    images = [
        import_named(service, subject["id"], f"{index}.png", (index, 0, 0))["image"]
        for index in range(1, 6)
    ]
    service.store.set_selection(subject["id"], policy="sequential")
    first = service.reroll(subject["id"])
    second = service.reroll(subject["id"])

    assert [slot["image_id"] for slot in first["slots"]] != [
        slot["image_id"] for slot in second["slots"]
    ]
    assert second["cursor"] > first["cursor"]
    assert {slot["image_id"] for slot in first["slots"]} <= {image["id"] for image in images}


def test_unlink_does_not_delete_managed_image_and_delete_requires_zero_memberships(service):
    subject = service.store.create_collection("subject", "Alice")
    environment = service.store.create_collection("environment", "Studio")
    image = import_named(service, subject["id"], "shared.png", (4, 5, 6))["image"]
    service.store.add_image_membership(environment["id"], image["id"])
    managed = service.managed_path(image)

    service.unlink_image(subject["id"], image["id"])
    assert managed.is_file()
    with pytest.raises(ValueError, match="still belongs"):
        service.delete_managed_image(image["id"])

    service.unlink_image(environment["id"], image["id"])
    service.delete_managed_image(image["id"])
    assert not managed.exists()
    with pytest.raises(KeyError, match="not found"):
        service.store.get_image(image["id"])


def test_partial_slot_update_cannot_duplicate_an_image_already_locked_elsewhere(service):
    subject = service.store.create_collection("subject", "Alice")
    images = [
        import_named(service, subject["id"], f"{index}.png", (index, 1, 2))["image"]
        for index in range(4)
    ]
    service.store.set_selection(
        subject["id"],
        slots=[
            {"slot": index + 1, "image_id": image["id"], "pinned": False}
            for index, image in enumerate(images)
        ],
    )

    with pytest.raises(ValueError, match="distinct"):
        service.store.set_selection(
            subject["id"],
            slots=[{"slot": 1, "image_id": images[1]["id"], "pinned": True}],
        )

    assert [slot["image_id"] for slot in service.store.get_selection(subject["id"])["slots"]] == [
        image["id"] for image in images
    ]


def test_unlinked_images_are_discoverable_as_orphans_until_permanently_deleted(service):
    subject = service.store.create_collection("subject", "Alice")
    image = import_named(service, subject["id"], "orphan.png", (7, 8, 9))["image"]

    service.unlink_image(subject["id"], image["id"])

    assert [item["id"] for item in service.store.list_orphan_images()] == [image["id"]]
    service.delete_managed_image(image["id"])
    assert service.store.list_orphan_images() == []
