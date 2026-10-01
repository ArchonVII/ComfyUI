from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from tools.lora_training.prepare_identity_dataset import (
    DatasetPreparationError,
    prepare_identity_dataset,
)


def _write_png(path: Path, color: int) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    width, height = 32, 24
    rows = b"".join(b"\x00" + bytes((color, 80, 120)) * width for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preparer_copies_only_selected_images_and_keeps_captions_out_of_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_png(source / "portrait.png", 30)
    _write_png(source / "standing.png", 60)
    _write_png(source / "excluded.png", 90)
    before = {path.name: _sha256(path) for path in source.iterdir()}
    selection = tmp_path / "selection.json"
    private_caption = "subjectToken, smiling woman in a blue shirt, waist-up portrait"
    selection.write_text(
        json.dumps(
            {
                "images": [
                    {"file": "portrait.png", "caption": private_caption, "reason": "clear face"},
                    {
                        "file": "standing.png",
                        "caption": "subjectToken, woman standing outdoors, full-body photograph",
                        "reason": "body coverage",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "private-dataset"

    result = prepare_identity_dataset(
        source_dir=source,
        destination_dir=destination,
        selection_file=selection,
        trigger_token="subjectToken",
    )

    assert result.image_count == 2
    assert sorted(path.name for path in destination.iterdir()) == [
        "identity-001.png",
        "identity-001.txt",
        "identity-002.png",
        "identity-002.txt",
        "selection-manifest.json",
    ]
    assert (destination / "identity-001.txt").read_text(encoding="utf-8") == private_caption + "\n"
    manifest_text = (destination / "selection-manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["trigger_token"] == "subjectToken"
    assert manifest["images"][0]["source"] == "portrait.png"
    assert manifest["images"][0]["reason"] == "clear face"
    assert "sha256" in manifest["images"][0]
    assert private_caption not in manifest_text
    assert {path.name: _sha256(path) for path in source.iterdir()} == before
    assert not (destination / "excluded.png").exists()


@pytest.mark.parametrize("unsafe_name", ["../escape.png", "folder/image.png", "C:\\escape.png"])
def test_preparer_rejects_selection_paths_outside_flat_source(
    tmp_path: Path, unsafe_name: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps({"images": [{"file": unsafe_name, "caption": "subjectToken, portrait"}]}),
        encoding="utf-8",
    )
    destination = tmp_path / "private-dataset"

    with pytest.raises(DatasetPreparationError, match="flat filename"):
        prepare_identity_dataset(source, destination, selection, "subjectToken")

    assert not destination.exists()


def test_preparer_refuses_to_replace_an_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_png(source / "portrait.png", 30)
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps({"images": [{"file": "portrait.png", "caption": "subjectToken, portrait"}]}),
        encoding="utf-8",
    )
    destination = tmp_path / "private-dataset"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(DatasetPreparationError, match="already exists"):
        prepare_identity_dataset(source, destination, selection, "subjectToken")

    assert marker.read_text(encoding="utf-8") == "preserve"
