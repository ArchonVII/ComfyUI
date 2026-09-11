import json

import pytest

from custom_nodes.comfyui_random_reference_source.nodes import (
    compose_favorite_prompt,
    delete_preset,
    load_presets,
    save_preset,
)


def test_legacy_folder_favorites_are_normalized_when_user_store_is_absent(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps({"favorites": {"People": "subjects", "Places": "places"}}),
        encoding="utf-8",
    )

    presets = load_presets(tmp_path / "missing.json", legacy_path=legacy)

    assert presets["People"] == {
        "kind": "folder",
        "folder": "subjects",
        "images": [],
        "include_subfolders": False,
        "prompt_text": "",
    }


def test_folder_and_selection_presets_round_trip_in_versioned_user_json(tmp_path):
    store = tmp_path / "presets.json"
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps({"favorites": {"Existing": "existing"}}), encoding="utf-8"
    )

    save_preset(
        "Portraits",
        {
            "kind": "folder",
            "folder": "portraits",
            "images": [],
            "include_subfolders": True,
            "prompt_text": "tight portrait",
        },
        store_path=store,
        legacy_path=legacy,
    )
    save_preset(
        "Chosen faces",
        {
            "kind": "selection",
            "folder": "faces",
            "images": ["one.png", "nested/two.png"],
            "include_subfolders": False,
            "prompt_text": "same character",
        },
        store_path=store,
        legacy_path=legacy,
    )

    payload = json.loads(store.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert set(payload["presets"]) == {"Existing", "Portraits", "Chosen faces"}
    assert load_presets(store)["Chosen faces"]["images"] == [
        "one.png",
        "nested/two.png",
    ]


def test_delete_preset_keeps_other_presets(tmp_path):
    store = tmp_path / "presets.json"
    for name in ("Keep", "Remove"):
        save_preset(
            name,
            {"kind": "folder", "folder": name.lower()},
            store_path=store,
            legacy_path=tmp_path / "absent.json",
        )

    delete_preset("Remove", store_path=store)

    assert set(load_presets(store)) == {"Keep"}


@pytest.mark.parametrize(
    ("favorite_text", "prompt", "expected"),
    [
        ("cinematic portrait", "soft window light", "cinematic portrait, soft window light"),
        ("cinematic portrait, ", " soft window light", "cinematic portrait, soft window light"),
        ("cinematic portrait", "", "cinematic portrait"),
        ("", "soft window light", "soft window light"),
        ("", "", ""),
    ],
)
def test_favorite_text_is_cleanly_prefixed_to_incoming_prompt(
    favorite_text, prompt, expected
):
    assert compose_favorite_prompt(favorite_text, prompt) == expected


def test_selection_preset_requires_at_least_one_image(tmp_path):
    with pytest.raises(ValueError, match="at least one image"):
        save_preset(
            "Empty",
            {"kind": "selection", "folder": ".", "images": []},
            store_path=tmp_path / "presets.json",
            legacy_path=tmp_path / "absent.json",
        )
