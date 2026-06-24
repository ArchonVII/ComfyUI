import asyncio
import json

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import folder_paths
from comfy_extras.nodes_dataset import (
    DatasetExtension,
    LoadImageMetadataNode,
    read_image_metadata,
    resolve_image_metadata_path,
)


@pytest.fixture
def comfy_dirs(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"
    for directory in (input_dir, output_dir, temp_dir):
        directory.mkdir()

    monkeypatch.setattr(folder_paths, "get_input_directory", lambda: str(input_dir))
    monkeypatch.setattr(folder_paths, "get_output_directory", lambda: str(output_dir))
    monkeypatch.setattr(folder_paths, "get_temp_directory", lambda: str(temp_dir))
    return input_dir, output_dir, temp_dir


def save_metadata_png(path, prompt=None, workflow=None, parameters=None, custom=None):
    info = PngInfo()
    if prompt is not None:
        info.add_text("prompt", json.dumps(prompt))
    if workflow is not None:
        info.add_text("workflow", json.dumps(workflow))
    if parameters is not None:
        info.add_text("parameters", parameters)
    if custom is not None:
        info.add_text("custom", custom)

    Image.new("RGB", (2, 1), color=(12, 34, 56)).save(path, pnginfo=info)


def test_resolve_image_metadata_path_accepts_runtime_roots(comfy_dirs):
    input_dir, output_dir, _ = comfy_dirs
    input_image = input_dir / "source.png"
    output_image = output_dir / "generated.png"
    save_metadata_png(input_image)
    save_metadata_png(output_image)

    assert resolve_image_metadata_path(str(input_image)) == input_image
    assert resolve_image_metadata_path("source.png") == input_image
    assert resolve_image_metadata_path("generated.png [output]") == output_image


def test_resolve_image_metadata_path_rejects_outside_runtime_roots(comfy_dirs, tmp_path):
    outside = tmp_path / "outside.png"
    save_metadata_png(outside)

    with pytest.raises(ValueError, match="outside the ComfyUI input, output, or temp directories"):
        resolve_image_metadata_path(str(outside))


def test_read_image_metadata_extracts_comfy_png_chunks(comfy_dirs):
    input_dir, _, _ = comfy_dirs
    image_path = input_dir / "generated.png"
    prompt = {"1": {"class_type": "KSampler", "inputs": {"seed": 123}}}
    workflow = {"nodes": [{"id": 1, "type": "KSampler"}]}
    save_metadata_png(
        image_path,
        prompt=prompt,
        workflow=workflow,
        parameters="forest scene\nSteps: 20, CFG scale: 7",
        custom="kept",
    )

    metadata = read_image_metadata(image_path)
    raw = json.loads(metadata.raw_metadata_json)

    assert json.loads(metadata.prompt_json) == prompt
    assert json.loads(metadata.workflow_json) == workflow
    assert metadata.parameters == "forest scene\nSteps: 20, CFG scale: 7"
    assert raw["format"] == "PNG"
    assert raw["width"] == 2
    assert raw["height"] == 1
    assert raw["metadata"]["custom"] == "kept"


def test_load_image_metadata_node_outputs_metadata_strings(comfy_dirs):
    input_dir, _, _ = comfy_dirs
    image_path = input_dir / "generated.png"
    prompt = {"positive": "portrait"}
    workflow = {"nodes": []}
    save_metadata_png(image_path, prompt=prompt, workflow=workflow)

    result = LoadImageMetadataNode.execute(str(image_path))

    assert json.loads(result.result[0]) == prompt
    assert json.loads(result.result[1]) == workflow
    assert result.result[2] == ""
    assert json.loads(result.result[3])["metadata"]["prompt"] == json.dumps(prompt)


def test_load_image_metadata_node_schema_and_extension_registration(comfy_dirs):
    schema = LoadImageMetadataNode.define_schema()
    node_list = asyncio.run(DatasetExtension().get_node_list())

    assert schema.node_id == "LoadImageMetadata"
    assert schema.display_name == "Load Image Metadata"
    assert LoadImageMetadataNode in node_list
