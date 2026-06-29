import json
from pathlib import Path

import pytest
import torch
from PIL import Image

import folder_paths
from custom_nodes.comfyui_random_reference_source.nodes import (
    NODE_DISPLAY_NAME_MAPPINGS,
    NONE_FAVORITE,
    RandomReferenceImageSource,
    ReferenceLanePack,
    build_reference_preview_payload,
    build_image_pool,
    choose_image,
    load_favorites,
    parse_selected_images,
    resolve_source_folder,
)


def _png(path: Path, color=(255, 0, 0)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 1), color=color).save(path)


def test_parse_selected_images_accepts_lines_commas_and_comments():
    selected = """
    # saved picks
    first.png
    second.png, third.png

    "fourth image.png"
    """

    assert parse_selected_images(selected) == [
        "first.png",
        "second.png",
        "third.png",
        "fourth image.png",
    ]


def test_nodes_are_arch_prefixed_for_searchability():
    assert (
        NODE_DISPLAY_NAME_MAPPINGS["RandomReferenceImageSource"]
        == "arch-Random Reference Image Source"
    )
    assert NODE_DISPLAY_NAME_MAPPINGS["ReferenceLanePack"] == "arch-Reference Lane Pack"
    assert RandomReferenceImageSource.CATEGORY == "arch-image/random reference"
    assert ReferenceLanePack.CATEGORY == "arch-image/random reference"


def test_resolve_source_folder_uses_input_relative_manual_folder(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "subjects"
    source_dir.mkdir(parents=True)
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    assert resolve_source_folder("subjects", NONE_FAVORITE, {}) == source_dir.resolve()


def test_resolve_source_folder_uses_favorite_over_manual_folder(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    favorite_dir = tmp_path / "favorite"
    favorite_dir.mkdir(parents=True)
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    favorites = {"Primary people": str(favorite_dir)}

    assert (
        resolve_source_folder("ignored", "Primary people", favorites)
        == favorite_dir.resolve()
    )


def test_load_favorites_accepts_wrapped_mapping(tmp_path):
    config = tmp_path / "favorites.json"
    config.write_text(
        json.dumps(
            {"favorites": {"Primary people": "subjects", "Environment": "places"}}
        ),
        encoding="utf-8",
    )

    assert load_favorites(config) == {
        "Primary people": "subjects",
        "Environment": "places",
    }


def test_build_image_pool_from_folder_or_selected_files(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "subjects"
    nested = source_dir / "nested"
    _png(source_dir / "a.png")
    _png(source_dir / "b.jpg")
    _png(nested / "c.webp")
    (source_dir / "notes.txt").write_text("ignore me", encoding="utf-8")
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    folder_pool = build_image_pool(
        source_mode="folder",
        folder="subjects",
        favorite=NONE_FAVORITE,
        selected_images="",
        include_subfolders=False,
        favorites={},
    )
    selected_pool = build_image_pool(
        source_mode="selection",
        folder="subjects",
        favorite=NONE_FAVORITE,
        selected_images="b.jpg\nnested/c.webp",
        include_subfolders=False,
        favorites={},
    )

    assert [path.name for path in folder_pool] == ["a.png", "b.jpg"]
    assert [path.name for path in selected_pool] == ["b.jpg", "c.webp"]


def test_build_image_pool_auto_uses_selection_when_files_are_selected(
    tmp_path, monkeypatch
):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "subjects"
    _png(source_dir / "a.png")
    _png(source_dir / "b.jpg")
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    pool = build_image_pool(
        source_mode="auto",
        folder="subjects",
        favorite=NONE_FAVORITE,
        selected_images="b.jpg",
        include_subfolders=False,
        favorites={},
    )

    assert [path.name for path in pool] == ["b.jpg"]


def test_build_image_pool_auto_uses_folder_when_no_files_are_selected(
    tmp_path, monkeypatch
):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "subjects"
    _png(source_dir / "a.png")
    _png(source_dir / "b.jpg")
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    pool = build_image_pool(
        source_mode="auto",
        folder="subjects",
        favorite=NONE_FAVORITE,
        selected_images="",
        include_subfolders=False,
        favorites={},
    )

    assert [path.name for path in pool] == ["a.png", "b.jpg"]


def test_reference_preview_payload_returns_thumbnail_data_urls(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "subjects"
    _png(source_dir / "a.png")
    _png(source_dir / "b.jpg")
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    payload = build_reference_preview_payload(
        source_mode="selection",
        folder="subjects",
        favorite=NONE_FAVORITE,
        selected_images="a.png\nb.jpg",
        selection_policy="seeded",
        seed=1,
        include_subfolders=False,
        favorites={},
    )

    assert payload["mode"] == "selection"
    assert [item["name"] for item in payload["images"]] == ["a.png", "b.jpg"]
    assert payload["images"][0]["thumbnail_data_url"].startswith("data:image/png;base64,")


def test_build_image_pool_rejects_empty_selection(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    (input_dir / "subjects").mkdir(parents=True)
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    with pytest.raises(ValueError, match="selected_images is required"):
        build_image_pool(
            source_mode="selection",
            folder="subjects",
            favorite=NONE_FAVORITE,
            selected_images="",
            include_subfolders=False,
            favorites={},
        )


def test_choose_image_seeded_is_stable(tmp_path):
    files = [tmp_path / f"{name}.png" for name in ("a", "b", "c")]

    assert choose_image(files, seed=42, selection_policy="seeded") == choose_image(
        files,
        seed=42,
        selection_policy="seeded",
    )


def test_random_reference_image_source_loads_image_mask_and_metadata(
    tmp_path, monkeypatch
):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "subjects"
    _png(source_dir / "a.png", color=(0, 255, 0))
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))
    monkeypatch.setattr(
        "custom_nodes.comfyui_random_reference_source.nodes.load_favorites",
        lambda _path=None: {},
    )

    image, mask, selected_file, lane, metadata_json = (
        RandomReferenceImageSource().load_random_reference(
            lane="primary_subject",
            source_mode="folder",
            favorite=NONE_FAVORITE,
            folder="subjects",
            selected_images="",
            selection_policy="seeded",
            seed=1,
            include_subfolders=False,
        )
    )

    metadata = json.loads(metadata_json)
    assert image.shape == (1, 1, 2, 3)
    assert mask.shape == (1, 64, 64)
    assert image.dtype == torch.float32
    assert Path(selected_file).name == "a.png"
    assert lane == "primary_subject"
    assert metadata["lane"] == "primary_subject"
    assert metadata["pool_size"] == 1


def test_reference_lane_pack_passes_named_lanes_and_metadata():
    primary = torch.zeros((1, 1, 1, 3))
    environment = torch.ones((1, 1, 1, 3))

    result = ReferenceLanePack().pack(primary_subject=primary, environment=environment)
    metadata = json.loads(result[-1])

    assert result[0] is primary
    assert result[2] is environment
    assert metadata["present_lanes"] == ["primary_subject", "environment"]
