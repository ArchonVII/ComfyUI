import os
import asyncio
from pathlib import Path

import pytest
import torch
from PIL import Image

import folder_paths
from comfy_extras.nodes_dataset import (
    DatasetExtension,
    LoadRandomImageFromFolderNode,
    choose_random_image_file,
    find_image_files,
    load_image_and_mask,
    resolve_input_subfolder,
)


def test_random_folder_node_schema_and_extension_registration(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    (input_dir / "set").mkdir(parents=True)
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    schema = LoadRandomImageFromFolderNode.define_schema()
    node_list = asyncio.run(DatasetExtension().get_node_list())

    assert schema.node_id == "LoadRandomImageFromFolder"
    assert schema.display_name == "Load Random Image (from Folder)"
    assert LoadRandomImageFromFolderNode in node_list


def test_resolve_input_subfolder_stays_inside_input_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(tmp_path))

    (tmp_path / "portraits").mkdir()

    assert resolve_input_subfolder("portraits") == tmp_path / "portraits"
    assert resolve_input_subfolder("") == tmp_path

    with pytest.raises(ValueError, match="outside the input directory"):
        resolve_input_subfolder("../outside")


def test_find_image_files_filters_supported_images_and_sorts(tmp_path):
    folder = tmp_path / "images"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / "b.JPG").write_bytes(b"not actually loaded")
    (folder / "a.png").write_bytes(b"not actually loaded")
    (folder / "notes.txt").write_text("caption")
    (nested / "c.webp").write_bytes(b"not actually loaded")

    assert [path.name for path in find_image_files(folder, include_subfolders=False)] == [
        "a.png",
        "b.JPG",
    ]
    assert [path.name for path in find_image_files(folder, include_subfolders=True)] == [
        "a.png",
        "b.JPG",
        "c.webp",
    ]


def test_choose_random_image_file_is_seeded(tmp_path):
    files = [tmp_path / f"{name}.png" for name in ("a", "b", "c", "d")]

    first = choose_random_image_file(files, seed=123)
    second = choose_random_image_file(files, seed=123)
    different_seed = choose_random_image_file(files, seed=124)

    assert first == second
    assert different_seed in files


def test_load_image_and_mask_returns_single_rgb_image_and_alpha_mask(tmp_path):
    image_path = tmp_path / "rgba.png"
    rgba = Image.new("RGBA", (2, 1))
    rgba.putdata([(255, 0, 0, 255), (0, 0, 255, 0)])
    rgba.save(image_path)

    image, mask = load_image_and_mask(image_path)

    assert image.shape == (1, 1, 2, 3)
    assert mask.shape == (1, 1, 2)
    assert image.dtype == torch.float32
    assert mask.dtype == torch.float32
    assert torch.allclose(image[0, 0, 0], torch.tensor([1.0, 0.0, 0.0]))
    assert mask[0, 0, 0].item() == pytest.approx(0.0)
    assert mask[0, 0, 1].item() == pytest.approx(1.0)


def test_random_folder_node_outputs_one_image_and_selected_filename(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "set"
    source_dir.mkdir(parents=True)
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(source_dir / "red.png")
    Image.new("RGB", (1, 1), color=(0, 0, 255)).save(source_dir / "blue.png")
    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))

    result = LoadRandomImageFromFolderNode.execute("set", seed=99, include_subfolders=False)

    assert len(result.result) == 3
    assert result.result[0].shape == (1, 1, 1, 3)
    assert result.result[1].shape == (1, 64, 64)
    assert os.path.basename(result.result[2]) in {"blue.png", "red.png"}
