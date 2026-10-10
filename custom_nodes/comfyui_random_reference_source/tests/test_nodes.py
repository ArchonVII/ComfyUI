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
    ReferencePromptCompose,
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


def test_empty_optional_source_validates_but_fails_if_actually_executed():
    args = dict(lane="generic", source_mode="selection", favorite="None",
                folder="", selected_images="", selection_policy="seeded", seed=0,
                include_subfolders=False)
    assert RandomReferenceImageSource.VALIDATE_INPUTS(**args) is True
    with pytest.raises(ValueError, match="selected_images is required"):
        RandomReferenceImageSource().load_random_reference(**args)


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


def test_browser_selection_uses_canonical_paths_and_bulk_selection_skips_thumbnails(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(tmp_path))
    for i in range(55):
        _png(tmp_path / f"{i}.png")
    source = dict(source_mode="selection", folder="", favorite="None",
                  selected_images="0.png\n1.png", selection_policy="seeded", seed=1, include_subfolders=False)
    page = build_reference_preview_payload(**source, browse=True, max_images=1)
    assert page["selection_paths"] == [str(tmp_path / "0.png"), str(tmp_path / "1.png")]
    source.update(source_mode="folder", folder=str(tmp_path))
    import custom_nodes.comfyui_random_reference_source.nodes as module
    monkeypatch.setattr(module, "_thumbnail_data_url", lambda *_: pytest.fail("bulk selection generated thumbnails"))
    assert len(build_reference_preview_payload(**source, paths_only=True)["paths"]) == 55


def test_blank_folder_requires_explicit_source(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(tmp_path))
    with pytest.raises(ValueError, match="Choose a reference folder"):
        resolve_source_folder("", "None")
    assert resolve_source_folder(".", "None") == tmp_path


def test_selection_favorite_preserves_filename_commas(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(tmp_path))
    image = tmp_path / "last, first.png"
    _png(image)
    assert build_image_pool(source_mode="selection", folder="", favorite="Chosen",
        selected_images="", include_subfolders=False,
        favorites={"Chosen": {"kind": "selection", "folder": "", "images": [str(image)]}}) == [image]


def test_absolute_selection_ignores_stale_folder_in_load_and_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(tmp_path))
    image = tmp_path / "chosen.png"
    _png(image)
    source = dict(source_mode="selection", folder=str(tmp_path / "missing"),
                  favorite="None", selected_images=str(image), include_subfolders=False)
    assert build_image_pool(**source) == [image]
    preview = build_reference_preview_payload(**source, selection_policy="seeded", seed=1)
    assert preview["images"][0]["path"] == str(image)
    result = RandomReferenceImageSource().load_random_reference(
        **source, lane="generic", selection_policy="seeded", seed=1)
    outputs = result["result"]
    assert len(outputs) == 6
    assert outputs[2] == str(image)
    assert isinstance(outputs[0], torch.Tensor)
    assert isinstance(outputs[1], torch.Tensor)
    assert outputs[3] == "generic"
    assert result["ui"]["arch_reference_last_used"] == [json.loads(outputs[4])]
    assert result["ui"]["arch_reference_last_used"][0]["selected_name"] == image.name


def test_browser_pages_cover_pool_and_seeded_preview_is_exact(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(tmp_path))
    for i in range(7):
        _png(tmp_path / f"{i}.png")
    source = dict(source_mode="folder", folder=str(tmp_path), favorite="None",
                  selected_images="", include_subfolders=False, selection_policy="seeded", seed=3)
    pages = [build_reference_preview_payload(**source, offset=i, max_images=3, browse=True)
             for i in (0, 3, 6)]
    assert [p["pool_size"] for p in pages] == [7, 7, 7]
    assert [len(p["images"]) for p in pages] == [3, 3, 1]
    assert len({im["path"] for p in pages for im in p["images"]}) == 7
    assert pages[-1]["has_more"] is False
    preview = build_reference_preview_payload(**source)
    assert len(preview["images"]) == 1
    assert preview["preview_is_exact_next"] is True


def test_selection_pool_is_not_misrepresented_as_exact_random_next(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(tmp_path))
    paths = [tmp_path / f"{i}.png" for i in range(2)]
    for path in paths:
        _png(path)
    preview = build_reference_preview_payload(
        "selection", str(tmp_path), "None", "\n".join(map(str, paths)),
        "random_each_queue", 1, False)
    assert preview["preview_is_exact_next"] is False


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


def test_build_image_pool_uses_images_saved_in_selection_preset(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "subjects"
    _png(source_dir / "a.png")
    _png(source_dir / "b.jpg")
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    pool = build_image_pool(
        source_mode="folder",
        folder="ignored",
        favorite="Chosen",
        selected_images="ignored.png",
        include_subfolders=False,
        favorites={
            "Chosen": {
                "kind": "selection",
                "folder": "subjects",
                "images": ["b.jpg", "a.png"],
                "include_subfolders": False,
                "prompt_text": "same person",
            }
        },
    )

    assert [path.name for path in pool] == ["b.jpg", "a.png"]


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
        browse=True,
    )

    assert payload["mode"] == "selection"
    assert [item["name"] for item in payload["images"]] == ["a.png", "b.jpg"]
    assert payload["images"][0]["thumbnail_data_url"].startswith(
        "data:image/png;base64,"
    )


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


def test_selection_policy_exposes_sequential_mode():
    policies = RandomReferenceImageSource.INPUT_TYPES()["required"]["selection_policy"][
        0
    ]

    assert "sequential" in policies


def test_seed_input_starts_at_one_and_rejects_zero():
    _, options = RandomReferenceImageSource.INPUT_TYPES()["required"]["seed"]

    assert options["default"] == 1
    assert options["min"] == 1


def test_seeded_policy_normalizes_legacy_zero_to_one(tmp_path):
    files = [tmp_path / f"{index}.png" for index in range(10)]

    assert choose_image(files, seed=0, selection_policy="seeded") == choose_image(
        files, seed=1, selection_policy="seeded"
    )


def test_choose_image_sequential_visits_each_image_before_wrapping(tmp_path):
    files = [tmp_path / f"{name}.png" for name in ("a", "b", "c")]

    selected = [
        choose_image(files, seed=seed, selection_policy="sequential")
        for seed in range(1, 5)
    ]

    assert selected == [files[0], files[1], files[2], files[0]]


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

    image, mask, selected_file, lane, metadata_json, prompt = (
        RandomReferenceImageSource().load_random_reference(
            lane="primary_subject",
            source_mode="folder",
            favorite=NONE_FAVORITE,
            folder="subjects",
            selected_images="",
            selection_policy="seeded",
            seed=1,
            include_subfolders=False,
            prompt="soft window light",
        )["result"]
    )

    metadata = json.loads(metadata_json)
    assert image.shape == (1, 1, 2, 3)
    assert mask.shape == (1, 64, 64)
    assert image.dtype == torch.float32
    assert Path(selected_file).name == "a.png"
    assert lane == "primary_subject"
    assert metadata["lane"] == "primary_subject"
    assert metadata["pool_size"] == 1
    assert prompt == "soft window light"


def test_random_reference_source_prefixes_saved_favorite_text(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "subjects"
    _png(source_dir / "a.png")
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))
    monkeypatch.setattr(
        "custom_nodes.comfyui_random_reference_source.nodes.load_presets",
        lambda: {
            "Hero": {
                "kind": "folder",
                "folder": "subjects",
                "images": [],
                "include_subfolders": False,
                "prompt_text": "same character",
            }
        },
    )

    result = RandomReferenceImageSource().load_random_reference(
        lane="primary_subject",
        source_mode="folder",
        favorite="Hero",
        folder="ignored",
        selected_images="",
        selection_policy="seeded",
        seed=1,
        include_subfolders=False,
        prompt="soft window light",
    )

    assert result["result"][-1] == "same character, soft window light"
    assert json.loads(result["result"][-2])["favorite_prompt_text"] == "same character"


def test_reference_lane_pack_passes_named_lanes_and_metadata():
    primary = torch.zeros((1, 1, 1, 3))
    environment = torch.ones((1, 1, 1, 3))

    result = ReferenceLanePack().pack(primary_subject=primary, environment=environment)
    metadata = json.loads(result[-1])

    assert result[0] is primary
    assert result[2] is environment
    assert metadata["present_lanes"] == ["primary_subject", "environment"]


def test_prompt_composer_uses_only_enabled_reference_lanes():
    node = ReferencePromptCompose()
    options = dict(text="edit instruction", use_identity=False, use_aux1=True, use_aux2=False, use_aux3=True)
    assert node.check_lazy_status(**options, main="main text", aux1=None, aux3="third") == ["aux1"]
    assert node.check_lazy_status(**options) == []
    assert node.compose(**options, main="main text", identity="disabled identity",
                        aux1="first", aux2="disabled second", aux3="third") == (
                            "edit instruction\n\nmain text\n\nfirst\n\nthird",)


@pytest.mark.parametrize("edited", ["edited text", ""])
def test_current_prompt_edits_override_saved_favorite(tmp_path, monkeypatch, edited):
    image = tmp_path / "image.png"
    _png(image)
    monkeypatch.setattr("custom_nodes.comfyui_random_reference_source.nodes.load_presets", lambda: {
        "Hero": {"kind": "selection", "folder": "", "images": [str(image)],
                 "include_subfolders": False, "prompt_text": "saved text"}})
    result = RandomReferenceImageSource().load_random_reference(
        lane="generic", source_mode="selection", favorite="Hero", folder="",
        selected_images="", selection_policy="seeded", seed=1, include_subfolders=False,
        favorite_prompt=edited, prompt="instruction")
    assert result["result"][-1] == (f"{edited}, instruction" if edited else "instruction")
