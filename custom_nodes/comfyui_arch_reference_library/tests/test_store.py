from pathlib import Path
import sqlite3
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_arch_reference_library.store import ReferenceLibraryStore


@pytest.fixture
def store(tmp_path):
    return ReferenceLibraryStore(tmp_path / "catalog.sqlite3")


def test_new_store_creates_versioned_schema_and_default_settings(store):
    assert store.schema_version() == 1
    assert store.get_active("subject") is None
    assert store.get_active("environment") is None

    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "collections",
        "images",
        "collection_images",
        "tags",
        "collection_image_tags",
        "profiles",
        "profile_loras",
        "selection_state",
        "selection_slots",
        "settings",
    } <= tables


def test_collection_names_are_unique_per_kind_and_default_profile_is_created(store):
    subject = store.create_collection("subject", " Alice ")
    environment = store.create_collection("environment", "Alice")

    assert subject["name"] == "Alice"
    assert subject["kind"] == "subject"
    assert subject["id"] != environment["id"]
    assert store.list_profiles(subject["id"])[0]["name"] == "Default"
    assert store.get_selection(subject["id"])["slots"] == [
        {"slot": slot, "image_id": None, "pinned": False} for slot in range(1, 5)
    ]

    with pytest.raises(ValueError, match="already exists"):
        store.create_collection("subject", "alice")


def test_collections_can_be_updated_listed_activated_and_removed(store):
    first = store.create_collection("subject", "First")
    second = store.create_collection("subject", "Second")

    updated = store.update_collection(first["id"], name="Renamed", description="Lead")
    assert updated["name"] == "Renamed"
    assert updated["description"] == "Lead"
    assert [item["name"] for item in store.list_collections("subject")] == ["Renamed", "Second"]

    assert store.set_active("subject", second["id"])["id"] == second["id"]
    assert store.get_active("subject")["id"] == second["id"]
    with pytest.raises(ValueError, match="kind"):
        store.set_active("environment", second["id"])

    deleted = store.delete_collection(second["id"])
    assert deleted["id"] == second["id"]
    assert store.get_active("subject") is None
    with pytest.raises(KeyError, match="not found"):
        store.get_collection(second["id"])


@pytest.mark.parametrize("kind", ["", "character", "Subject", None])
def test_collection_kind_must_be_subject_or_environment(store, kind):
    with pytest.raises(ValueError, match="kind"):
        store.create_collection(kind, "Invalid")


@pytest.mark.parametrize("name", ["", "   ", "line\nbreak", "x" * 161, None])
def test_collection_names_are_validated(store, name):
    with pytest.raises(ValueError, match="name"):
        store.create_collection("subject", name)


def test_database_enforces_foreign_keys_for_every_store_connection(store):
    collection = store.create_collection("subject", "Foreign keys")
    with pytest.raises(KeyError, match="not found"):
        store.list_profiles("00000000-0000-0000-0000-000000000000")

    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO selection_slots(collection_id, slot, image_id, pinned) VALUES (?, 1, NULL, 0)",
                ("00000000-0000-0000-0000-000000000000",),
            )

    assert len(store.list_profiles(collection["id"])) == 1


def test_profiles_store_prompt_additions_and_ordered_lora_stacks(store):
    collection = store.create_collection("subject", "Alice")
    profile = store.create_profile(
        collection["id"],
        name="Flux",
        model_family="flux",
        positive_prompt="alice token",
        negative_prompt="different person",
        loras=[
            {
                "name": "characters/alice.safetensors",
                "strength_model": 0.8,
                "strength_clip": 0.6,
                "enabled": True,
            },
            {
                "name": "styles/portrait.safetensors",
                "strength_model": 0.35,
                "strength_clip": 0.0,
                "enabled": False,
            },
        ],
    )

    assert profile["model_family"] == "flux"
    assert profile["positive_prompt"] == "alice token"
    assert [item["position"] for item in profile["loras"]] == [0, 1]
    assert profile["loras"][0]["name"] == "characters/alice.safetensors"
    assert profile["loras"][1]["enabled"] is False

    updated = store.update_profile(
        profile["id"],
        positive_prompt="updated token",
        loras=[
            {
                "name": "characters/alice-v2.safetensors",
                "strength_model": 1.0,
                "strength_clip": 1.0,
                "enabled": True,
            }
        ],
    )
    assert updated["positive_prompt"] == "updated token"
    assert [item["name"] for item in updated["loras"]] == [
        "characters/alice-v2.safetensors"
    ]


def test_default_profile_is_active_initially_and_cannot_be_deleted(store):
    collection = store.create_collection("environment", "Apartment")
    default = store.list_profiles(collection["id"])[0]
    alternate = store.create_profile(collection["id"], name="Wan", model_family="wan")

    assert store.get_active_profile(collection["id"])["id"] == default["id"]
    assert store.set_active_profile(collection["id"], alternate["id"])["id"] == alternate["id"]
    assert store.get_active_profile(collection["id"])["id"] == alternate["id"]

    store.delete_profile(alternate["id"])
    assert store.get_active_profile(collection["id"])["id"] == default["id"]
    with pytest.raises(ValueError, match="Default"):
        store.delete_profile(default["id"])


def test_deleting_collection_clears_dynamic_active_profile_setting(store):
    collection = store.create_collection("subject", "Alice")
    profile = store.create_profile(collection["id"], name="Flux", model_family="flux")
    store.set_active_profile(collection["id"], profile["id"])

    store.delete_collection(collection["id"])

    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "SELECT value_json FROM settings WHERE key = ?",
            (f"active_profile_{collection['id']}",),
        ).fetchone() is None


@pytest.mark.parametrize(
    "loras,match",
    [
        ([{"name": "../escape.safetensors", "strength_model": 1.0, "strength_clip": 1.0, "enabled": True}], "relative"),
        ([{"name": "x.safetensors", "strength_model": float("inf"), "strength_clip": 1.0, "enabled": True}], "finite"),
        ([{"name": "x.safetensors", "strength_model": 1.0, "strength_clip": 1.0, "enabled": 1}], "boolean"),
        ([{"name": "x.safetensors", "strength_model": 1.0, "strength_clip": 1.0, "enabled": True, "extra": True}], "unknown"),
    ],
)
def test_profile_lora_entries_are_strictly_validated(store, loras, match):
    collection = store.create_collection("subject", "Alice")
    with pytest.raises(ValueError, match=match):
        store.create_profile(collection["id"], name="Invalid", loras=loras)
