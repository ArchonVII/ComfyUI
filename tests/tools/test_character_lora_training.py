from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
import threading
import tomllib
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import tools.lora_training.render_musubi_config as render_module
from tools.lora_training.character_dataset import (
    DatasetValidationError,
    InsufficientDiskSpaceError,
    build_dataset_manifest,
    check_free_space,
    validate_character_dataset,
    validate_qwen_control_directory,
    validate_trigger_token,
)
from tools.lora_training.render_musubi_config import (
    APPROVED_LORA_RELATIVE_PATH,
    MUSUBI_REVISION,
    MUSUBI_ROOT,
    TRAINING_ROOT,
    ExistingRunError,
    ModelCheckpointError,
    _validate_model_paths,
    build_musubi_commands,
    render_run,
    resource_warnings,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = REPO_ROOT / "tools" / "lora_training" / "templates"


def _write_png(path: Path, width: int = 32, height: int = 24) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + (b"\x40\x80\xc0" * width) for _ in range(height))
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def _valid_dataset(root: Path, count: int = 10, token: str = "jmaHero") -> Path:
    root.mkdir(parents=True)
    for index in range(count):
        stem = f"portrait-{index:02d}"
        _write_png(root / f"{stem}.png", width=32 + index, height=24 + index)
        (root / f"{stem}.txt").write_text(
            f"{token}, studio portrait, angle {index}\n", encoding="utf-8"
        )
    return root


def _model_files(root: Path, model: str) -> dict[str, Path]:
    root.mkdir(parents=True)
    if model == "flux2-klein9b":
        names = {
            "dit": "flux2-klein-base-9b-bf16.safetensors",
            "vae": "flux2-ae.safetensors",
            "text_encoder": "qwen3-8b-bf16-00001-of-00004.safetensors",
        }
    else:
        names = {
            "dit": "qwen-image-edit-2511-bf16.safetensors",
            "vae": "qwen-image-vae.safetensors",
            "text_encoder": "qwen-2.5-vl-7b-bf16.safetensors",
        }
    result = {}
    for key, name in names.items():
        result[key] = root / name
        _write_safetensors(result[key])
    return result


def _write_safetensors(
    path: Path,
    *,
    dtype: str = "BF16",
    tensor_name: str = "model.weight",
    data_offsets: list[int] | None = None,
    payload_size: int | None = None,
) -> None:
    element_sizes = {
        "BF16": 2,
        "F16": 2,
        "F32": 4,
        "F8_E4M3": 1,
        "F8_E4M3FN": 1,
        "F8_E5M2": 1,
        "I8": 1,
        "U8": 1,
    }
    data_size = element_sizes[dtype]
    offsets = data_offsets if data_offsets is not None else [0, data_size]
    stored_payload_size = data_size if payload_size is None else payload_size
    header = json.dumps(
        {
            "__metadata__": {"format": "pt"},
            tensor_name: {
                "dtype": dtype,
                "shape": [1],
                "data_offsets": offsets,
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    path.write_bytes(
        struct.pack("<Q", len(header)) + header + (b"\0" * stored_payload_size)
    )


def _paired_controls(dataset: Path, root: Path) -> Path:
    root.mkdir(parents=True)
    for target in sorted(dataset.glob("*.png")):
        _write_png(root / target.name, width=40, height=40)
    return root


def test_valid_dataset_manifest_is_deterministic_and_omits_caption_content(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")

    first = build_dataset_manifest(dataset, "jmaHero")
    second = build_dataset_manifest(dataset, "jmaHero")

    assert first == second
    assert first["schema_version"] == 1
    assert first["trigger_token"] == "jmaHero"
    assert first["image_count"] == 10
    assert [item["image"] for item in first["images"]] == sorted(
        item["image"] for item in first["images"]
    )
    assert first["images"][0]["width"] == 32
    assert first["images"][0]["height"] == 24
    assert first["images"][0]["sha256"] == hashlib.sha256(
        (dataset / "portrait-00.png").read_bytes()
    ).hexdigest()
    assert "studio portrait" not in json.dumps(first)
    assert "caption_sha256" in first["images"][0]


def test_missing_sidecar_caption_is_an_actionable_error(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    _write_png(dataset / "uncaptioned.png")

    report = validate_character_dataset(dataset, "jmaHero")

    assert not report.ok
    assert any("uncaptioned.txt" in message and "sidecar caption" in message for message in report.errors)


def test_unsupported_files_and_orphan_captions_are_reported(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    (dataset / "notes.csv").write_text("private metadata", encoding="utf-8")
    (dataset / "orphan.txt").write_text("jmaHero", encoding="utf-8")

    report = validate_character_dataset(dataset, "jmaHero")

    assert any("notes.csv" in message and "unsupported" in message for message in report.errors)
    assert any("orphan.txt" in message and "matching image" in message for message in report.errors)


def test_duplicate_image_stems_are_case_insensitive(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    _write_png(dataset / "Portrait-00.jpg")

    report = validate_character_dataset(dataset, "jmaHero")

    assert any("duplicate image stem" in message and "portrait-00" in message.lower() for message in report.errors)


@pytest.mark.parametrize(
    ("count", "phrase"),
    [
        (9, "10-30"),
        (31, "10-30"),
    ],
)
def test_image_count_outside_recommended_range_warns(
    tmp_path: Path, count: int, phrase: str
) -> None:
    report = validate_character_dataset(_valid_dataset(tmp_path / "dataset", count), "jmaHero")

    assert report.ok
    assert any(phrase in warning and str(count) in warning for warning in report.warnings)


@pytest.mark.parametrize(
    "token",
    ["", "two words", "../escape", "hero,person", "-leading", "ab", "a" * 65],
)
def test_unsafe_trigger_tokens_are_rejected(token: str) -> None:
    with pytest.raises(ValueError, match="trigger token"):
        validate_trigger_token(token)


def test_caption_without_trigger_token_warns_without_exposing_caption(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    (dataset / "portrait-00.txt").write_text("a private description", encoding="utf-8")

    report = validate_character_dataset(dataset, "jmaHero")

    assert report.ok
    assert any("portrait-00.txt" in warning and "trigger token" in warning for warning in report.warnings)
    assert "private description" not in json.dumps(report.to_dict())


def test_invalid_dataset_raises_aggregate_exception(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    _write_png(dataset / "uncaptioned.png")

    with pytest.raises(DatasetValidationError, match="uncaptioned.txt"):
        build_dataset_manifest(dataset, "jmaHero")


def test_disk_guard_reports_required_and_available_space(tmp_path: Path) -> None:
    with pytest.raises(InsufficientDiskSpaceError, match=r"20\.0 GiB.*4\.0 GiB"):
        check_free_space(tmp_path, minimum_gib=20, available_bytes=4 * 1024**3)

    assert check_free_space(
        tmp_path, minimum_gib=20, available_bytes=25 * 1024**3
    ) == 25


def test_qwen_controls_match_same_stem_and_numbered_variants_deterministically(
    tmp_path: Path,
) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    controls = _paired_controls(dataset, tmp_path / "controls")
    (controls / "portrait-00.png").unlink()
    _write_png(controls / "portrait-00_10.png")
    _write_png(controls / "portrait-00_2.png")
    _write_png(controls / "portrait-00_0000.png")

    first = validate_qwen_control_directory(dataset, controls)
    second = validate_qwen_control_directory(dataset, controls)

    assert first == second
    assert first.ok
    assert first.pairs["portrait-00"] == [
        "portrait-00_0000.png",
        "portrait-00_2.png",
        "portrait-00_10.png",
    ]


def test_qwen_controls_report_missing_and_extra_files(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    controls = _paired_controls(dataset, tmp_path / "controls")
    (controls / "portrait-00.png").unlink()
    _write_png(controls / "not-a-target.png")

    report = validate_qwen_control_directory(dataset, controls)

    assert not report.ok
    assert any("portrait-00" in error and "control image" in error for error in report.errors)
    assert any("not-a-target.png" in error and "target" in error for error in report.errors)


def test_qwen_controls_reject_duplicate_numeric_slots_and_mixed_conventions(
    tmp_path: Path,
) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    controls = _paired_controls(dataset, tmp_path / "controls")
    (controls / "portrait-00.png").unlink()
    _write_png(controls / "portrait-00_0.png")
    _write_png(controls / "portrait-00_0000.jpg")
    _write_png(controls / "portrait-01_0.png")

    report = validate_qwen_control_directory(dataset, controls)

    assert any("portrait-00" in error and "duplicate control index 0" in error for error in report.errors)
    assert any("portrait-01" in error and "mixes" in error for error in report.errors)


def test_model_specific_resource_warnings_cover_this_workstation() -> None:
    flux = resource_warnings("flux2-klein9b", vram_gib=16, ram_gib=31)
    qwen = resource_warnings("qwen-edit-2511", vram_gib=16, ram_gib=31)

    assert any("16 GiB VRAM" in warning and "experimental" in warning for warning in flux)
    assert any("31 GiB RAM" in warning and "swap" in warning for warning in flux)
    assert any("64 GiB" in warning and "31 GiB" in warning for warning in qwen)


@pytest.mark.parametrize("model", ["flux2-klein9b", "qwen-edit-2511"])
def test_renderer_refuses_gguf_as_a_training_base(tmp_path: Path, model: str) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", model)
    models["dit"] = tmp_path / "models" / "inference-Q4_K_M.gguf"
    models["dit"].write_bytes(b"gguf")
    controls = (
        _paired_controls(dataset, tmp_path / "controls")
        if model == "qwen-edit-2511"
        else None
    )

    with pytest.raises(ModelCheckpointError, match="GGUF.*inference.*BF16"):
        render_run(
            model=model,
            dataset_dir=dataset,
            control_dir=controls,
            run_dir=tmp_path / "run",
            run_name="hero-lora",
            trigger_token="jmaHero",
            model_paths=models,
            template_root=TEMPLATE_ROOT,
            available_bytes=100 * 1024**3,
        )


def test_flux_distilled_checkpoint_is_not_accepted_as_base_training_model(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    models["dit"] = tmp_path / "models" / "flux2-klein-9b-distilled.safetensors"
    _write_safetensors(models["dit"])

    with pytest.raises(ModelCheckpointError, match="distilled.*klein-base-9b"):
        render_run(
            model="flux2-klein9b",
            dataset_dir=dataset,
            run_dir=tmp_path / "run",
            run_name="hero-lora",
            trigger_token="jmaHero",
            model_paths=models,
            template_root=TEMPLATE_ROOT,
            available_bytes=100 * 1024**3,
        )


@pytest.mark.parametrize("role", ["dit", "vae", "text_encoder"])
def test_renamed_gguf_magic_is_rejected_for_every_model_role(
    tmp_path: Path, role: str
) -> None:
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    renamed = tmp_path / "models" / f"apparently-safe-{role}-bf16.safetensors"
    renamed.write_bytes(b"GGUF" + (b"\0" * 64))
    models[role] = renamed

    with pytest.raises(ModelCheckpointError, match=rf"{role}.*GGUF.*magic"):
        _validate_model_paths("flux2-klein9b", models)


@pytest.mark.parametrize(
    ("role", "marker"),
    [
        ("dit", "inference"),
        ("dit", "distilled"),
        ("dit", "lightning"),
        ("vae", "turbo"),
        ("text_encoder", "quantized"),
    ],
)
def test_inference_filename_markers_are_rejected_for_all_roles(
    tmp_path: Path, role: str, marker: str
) -> None:
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    marked = tmp_path / "models" / f"asset-{marker}-bf16.safetensors"
    _write_safetensors(marked)
    models[role] = marked

    with pytest.raises(ModelCheckpointError, match=rf"{role}.*{marker}"):
        _validate_model_paths("flux2-klein9b", models)


@pytest.mark.parametrize("role", ["dit", "vae", "text_encoder"])
@pytest.mark.parametrize("dtype", ["F8_E4M3FN", "F8_E5M2", "I8"])
def test_quantized_safetensors_header_is_rejected_even_after_rename(
    tmp_path: Path, role: str, dtype: str
) -> None:
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    renamed = tmp_path / "models" / f"apparently-safe-{role}-bf16.safetensors"
    _write_safetensors(renamed, dtype=dtype)
    models[role] = renamed

    with pytest.raises(ModelCheckpointError, match=rf"{role}.*dtype.*{dtype}"):
        _validate_model_paths("flux2-klein9b", models)


@pytest.mark.parametrize(
    ("role", "filename"),
    [
        ("dit", "qwen-image-edit-2511-fp8_e4m3fn.safetensors"),
        ("dit", "qwen-image-edit-2511-FP8.safetensors"),
        ("dit", "qwen-image-edit-2511-quantized.safetensors"),
        ("text_encoder", "qwen-2.5-vl-7b-fp8_scaled.safetensors"),
    ],
)
def test_qwen_rejects_named_fp8_and_quantized_assets(
    tmp_path: Path, role: str, filename: str
) -> None:
    models = _model_files(tmp_path / "models", "qwen-edit-2511")
    unsafe = tmp_path / "models" / filename
    _write_safetensors(unsafe)
    models[role] = unsafe

    with pytest.raises(ModelCheckpointError, match=rf"{role}.*(?:FP8|fp8|quantized)"):
        _validate_model_paths("qwen-edit-2511", models)


@pytest.mark.parametrize("role", ["dit", "text_encoder"])
def test_qwen_trainable_assets_require_bf16_tensors(tmp_path: Path, role: str) -> None:
    models = _model_files(tmp_path / "models", "qwen-edit-2511")
    f32_only = tmp_path / "models" / f"qwen-{role}-base.safetensors"
    _write_safetensors(f32_only, dtype="F32")
    models[role] = f32_only

    with pytest.raises(ModelCheckpointError, match=rf"{role}.*BF16"):
        _validate_model_paths("qwen-edit-2511", models)


def test_all_model_roles_require_safetensors_files(tmp_path: Path) -> None:
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    models["vae"] = tmp_path / "models" / "vae.bin"
    models["vae"].write_bytes(b"not safetensors")

    with pytest.raises(ModelCheckpointError, match=r"vae.*\.safetensors"):
        _validate_model_paths("flux2-klein9b", models)


def test_truncated_safetensors_payload_is_rejected(tmp_path: Path) -> None:
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    truncated = models["vae"]
    truncated.write_bytes(truncated.read_bytes()[:-1])

    with pytest.raises(
        ModelCheckpointError, match=r"vae.*data_offsets.*payload"
    ):
        _validate_model_paths("flux2-klein9b", models)


def test_out_of_bounds_safetensors_offsets_are_rejected(tmp_path: Path) -> None:
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    malformed = models["vae"]
    _write_safetensors(malformed, data_offsets=[0, 8], payload_size=2)

    with pytest.raises(
        ModelCheckpointError, match=r"vae.*data_offsets.*payload"
    ):
        _validate_model_paths("flux2-klein9b", models)


def test_flux_render_is_deterministic_and_uses_low_memory_settings(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "flux2-klein9b")

    first = render_run(
        model="flux2-klein9b",
        dataset_dir=dataset,
        run_dir=tmp_path / "run-a",
        run_name="hero-lora",
        trigger_token="jmaHero",
        model_paths=models,
        template_root=TEMPLATE_ROOT,
        available_bytes=100 * 1024**3,
    )
    second = render_run(
        model="flux2-klein9b",
        dataset_dir=dataset,
        run_dir=tmp_path / "run-b",
        run_name="hero-lora",
        trigger_token="jmaHero",
        model_paths=models,
        template_root=TEMPLATE_ROOT,
        available_bytes=100 * 1024**3,
    )

    assert first.train_config.read_bytes() == second.train_config.read_bytes()
    assert first.dataset_config.read_bytes() == second.dataset_config.read_bytes()
    assert first.manifest.read_bytes() == second.manifest.read_bytes()
    dataset_toml = tomllib.loads(first.dataset_config.read_text(encoding="utf-8"))
    train_toml = tomllib.loads(first.train_config.read_text(encoding="utf-8"))
    assert dataset_toml["general"]["batch_size"] == 1
    assert dataset_toml["datasets"][0]["image_directory"] == dataset.as_posix()
    assert train_toml["model_version"] == "klein-base-9b"
    assert train_toml["network_module"] == "networks.lora_flux_2"
    assert train_toml["mixed_precision"] == "bf16"
    assert train_toml["fp8_base"] is True
    assert train_toml["fp8_scaled"] is True
    assert train_toml["fp8_text_encoder"] is True
    assert train_toml["gradient_checkpointing"] is True
    assert train_toml["blocks_to_swap"] == 16
    assert train_toml["block_swap_h2d_only"] is True
    assert train_toml["block_swap_ring_size"] == 1


def test_qwen_render_uses_real_edit_2511_keys_and_commands(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    controls = _paired_controls(dataset, tmp_path / "controls")
    models = _model_files(tmp_path / "models", "qwen-edit-2511")
    result = render_run(
        model="qwen-edit-2511",
        dataset_dir=dataset,
        control_dir=controls,
        run_dir=tmp_path / "run",
        run_name="hero-qwen-lora",
        trigger_token="jmaHero",
        model_paths=models,
        template_root=TEMPLATE_ROOT,
        available_bytes=100 * 1024**3,
    )

    train_toml = tomllib.loads(result.train_config.read_text(encoding="utf-8"))
    assert train_toml["model_version"] == "edit-2511"
    assert train_toml["network_module"] == "networks.lora_qwen_image"
    assert train_toml["fp8_vl"] is True
    assert train_toml["blocks_to_swap"] == 45
    assert train_toml["timestep_sampling"] == "qwen_shift"
    assert "cache_latents" not in train_toml
    assert "cache_text_encoder_outputs" not in train_toml
    dataset_toml = tomllib.loads(result.dataset_config.read_text(encoding="utf-8"))
    assert dataset_toml["datasets"][0]["control_directory"] == controls.as_posix()
    assert dataset_toml["datasets"][0]["control_resolution"] == [1024, 1024]
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["images"][0]["controls"][0]["image"] == "portrait-00.png"
    assert "sha256" in manifest["images"][0]["controls"][0]

def test_qwen_render_requires_a_valid_control_directory(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "qwen-edit-2511")

    with pytest.raises(DatasetValidationError, match="control directory"):
        render_run(
            model="qwen-edit-2511",
            dataset_dir=dataset,
            control_dir=None,
            run_dir=tmp_path / "run",
            run_name="hero-qwen-lora",
            trigger_token="jmaHero",
            model_paths=models,
            template_root=TEMPLATE_ROOT,
            available_bytes=100 * 1024**3,
        )


@pytest.mark.parametrize(
    ("model", "latent_script", "text_script", "train_script", "version", "text_flag"),
    [
        (
            "flux2-klein9b",
            "flux_2_cache_latents.py",
            "flux_2_cache_text_encoder_outputs.py",
            "flux_2_train_network.py",
            "klein-base-9b",
            "--fp8_text_encoder",
        ),
        (
            "qwen-edit-2511",
            "qwen_image_cache_latents.py",
            "qwen_image_cache_text_encoder_outputs.py",
            "qwen_image_train_network.py",
            "edit-2511",
            "--fp8_vl",
        ),
    ],
)
def test_musubi_commands_have_exact_model_specific_arguments(
    tmp_path: Path,
    model: str,
    latent_script: str,
    text_script: str,
    train_script: str,
    version: str,
    text_flag: str,
) -> None:
    models = _model_files(tmp_path / "models", model)
    dataset_config = tmp_path / "dataset.toml"
    train_config = tmp_path / "train.toml"
    python = MUSUBI_ROOT / ".venv" / "Scripts" / "python.exe"
    source = MUSUBI_ROOT / "src" / "musubi_tuner"

    latent, text, train = build_musubi_commands(
        model=model,
        trainer_root=MUSUBI_ROOT,
        dataset_config=dataset_config,
        train_config=train_config,
        model_paths=models,
    )

    expected_latent = (
        str(python),
        str(source / latent_script),
        "--dataset_config",
        str(dataset_config),
        "--vae",
        str(models["vae"]),
        "--model_version",
        version,
    )
    if model == "flux2-klein9b":
        expected_latent += ("--vae_dtype", "bfloat16")
    assert latent == expected_latent
    assert text == (
        str(python),
        str(source / text_script),
        "--dataset_config",
        str(dataset_config),
        "--text_encoder",
        str(models["text_encoder"]),
        "--batch_size",
        "1",
        "--model_version",
        version,
        text_flag,
    )
    assert train == (
        str(python),
        "-m",
        "accelerate.commands.launch",
        "--num_cpu_threads_per_process",
        "1",
        "--mixed_precision",
        "bf16",
        str(source / train_script),
        "--config_file",
        str(train_config),
    )


def test_existing_run_configs_are_never_overwritten(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    kwargs = {
        "model": "flux2-klein9b",
        "dataset_dir": dataset,
        "run_dir": tmp_path / "run",
        "run_name": "hero-lora",
        "trigger_token": "jmaHero",
        "model_paths": models,
        "template_root": TEMPLATE_ROOT,
        "available_bytes": 100 * 1024**3,
    }
    first = render_run(**kwargs)
    original = first.train_config.read_bytes()

    with pytest.raises(ExistingRunError, match="will not overwrite"):
        render_run(**kwargs)

    assert first.train_config.read_bytes() == original


def test_existing_empty_run_directory_is_never_populated(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(ExistingRunError, match="will not overwrite"):
        render_run(
            model="flux2-klein9b",
            dataset_dir=dataset,
            run_dir=run_dir,
            run_name="hero-lora",
            trigger_token="jmaHero",
            model_paths=models,
            template_root=TEMPLATE_ROOT,
            available_bytes=100 * 1024**3,
        )

    assert list(run_dir.iterdir()) == []


def test_concurrent_render_publishes_one_complete_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    run_dir = tmp_path / "run"
    barrier = threading.Barrier(2)
    original_write_text = Path.write_text

    def synchronized_legacy_write(path: Path, *args: object, **kwargs: object) -> int:
        if path == run_dir / "dataset.toml":
            barrier.wait(timeout=5)
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", synchronized_legacy_write)
    kwargs = {
        "model": "flux2-klein9b",
        "dataset_dir": dataset,
        "run_dir": run_dir,
        "run_name": "hero-lora",
        "trigger_token": "jmaHero",
        "model_paths": models,
        "template_root": TEMPLATE_ROOT,
        "available_bytes": 100 * 1024**3,
    }

    def attempt() -> object:
        try:
            return render_run(**kwargs)
        except Exception as exc:  # The losing publisher is the expected result.
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: attempt(), range(2)))

    assert sum(isinstance(item, render_module.RenderResult) for item in outcomes) == 1
    assert sum(isinstance(item, ExistingRunError) for item in outcomes) == 1
    assert sorted(path.name for path in run_dir.iterdir()) == [
        "dataset-manifest.json",
        "dataset.toml",
        "train.toml",
    ]


def test_render_failure_cleans_temporary_state_without_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    run_dir = tmp_path / "run"
    writes = 0

    def fail_second_write(path: Path, text: str) -> None:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("forced write failure")

    monkeypatch.setattr(
        render_module, "_write_text_exclusive", fail_second_write, raising=False
    )

    with pytest.raises(OSError, match="forced write failure"):
        render_run(
            model="flux2-klein9b",
            dataset_dir=dataset,
            run_dir=run_dir,
            run_name="hero-lora",
            trigger_token="jmaHero",
            model_paths=models,
            template_root=TEMPLATE_ROOT,
            available_bytes=100 * 1024**3,
        )

    assert not run_dir.exists()
    assert not list(tmp_path.glob(".run.tmp-*"))
    assert not (tmp_path / ".run.lock").exists()


def test_cli_dry_run_validates_without_writing_run(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    run_dir = tmp_path / "run"
    command = [
        sys.executable,
        str(REPO_ROOT / "tools" / "lora_training" / "render_musubi_config.py"),
        "--model",
        "flux2-klein9b",
        "--dataset-dir",
        str(dataset),
        "--run-dir",
        str(run_dir),
        "--run-name",
        "hero-lora",
        "--trigger-token",
        "jmaHero",
        "--dit",
        str(models["dit"]),
        "--vae",
        str(models["vae"]),
        "--text-encoder",
        str(models["text_encoder"]),
        "--available-disk-gib",
        "100",
        "--dry-run",
    ]

    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)

    assert completed.returncode == 0, completed.stderr
    assert (
        "safetensors container/dtype checks passed; "
        "semantic identity/provenance unverified"
    ) in completed.stdout
    assert "flux_2_cache_latents.py" in completed.stdout
    assert not run_dir.exists()


def test_cli_dry_run_rejects_existing_run_state_without_writes(tmp_path: Path) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    marker = run_dir / "reviewed.txt"
    marker.write_text("preserve", encoding="utf-8")
    command = [
        sys.executable,
        str(REPO_ROOT / "tools" / "lora_training" / "render_musubi_config.py"),
        "--model",
        "flux2-klein9b",
        "--dataset-dir",
        str(dataset),
        "--run-dir",
        str(run_dir),
        "--run-name",
        "hero-lora",
        "--trigger-token",
        "jmaHero",
        "--dit",
        str(models["dit"]),
        "--vae",
        str(models["vae"]),
        "--text-encoder",
        str(models["text_encoder"]),
        "--available-disk-gib",
        "100",
        "--dry-run",
    ]

    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)

    assert completed.returncode == 2
    assert "will not overwrite" in completed.stderr
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert list(run_dir.iterdir()) == [marker]


def _localized_starter(tmp_path: Path) -> tuple[Path, Path, Path]:
    starter = REPO_ROOT / "tools" / "lora_training" / "start-character-training.ps1"
    text = starter.read_text(encoding="utf-8")
    trainer_root = tmp_path / "missing-trainer"
    training_root = tmp_path / "training"
    repository_root = tmp_path / "repository"

    def quoted(path: Path) -> str:
        return str(path).replace("'", "''")

    text = text.replace(
        "$TrainerRoot = 'C:\\tools\\image\\trainers\\musubi-tuner'",
        f"$TrainerRoot = '{quoted(trainer_root)}'",
    )
    text = text.replace(
        "$TrainingRoot = 'C:\\tools\\image\\training\\characters'",
        f"$TrainingRoot = '{quoted(training_root)}'",
    )
    text = text.replace(
        "$RepositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\\..'))",
        f"$RepositoryRoot = '{quoted(repository_root)}'",
    )
    localized = tmp_path / "start-character-training.ps1"
    localized.write_text(text, encoding="utf-8")
    return localized, training_root, repository_root


def _approval_command(script: Path, run_name: str) -> list[str]:
    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "PowerShell 7 is required"
    return [
        pwsh,
        "-NoProfile",
        "-File",
        str(script),
        "-Model",
        "flux2-klein9b",
        "-Character",
        "review-hero",
        "-RunName",
        run_name,
        "-TriggerToken",
        "reviewHero",
        "-Dit",
        "unused-dit.safetensors",
        "-Vae",
        "unused-vae.safetensors",
        "-TextEncoder",
        "unused-text.safetensors",
        "-MinimumFreeGiB",
        "1",
        "-ApproveOutput",
    ]


def test_approval_only_copies_staged_output_without_trainer_or_overwrite(
    tmp_path: Path,
) -> None:
    script, training_root, repository_root = _localized_starter(tmp_path)
    run_name = "reviewed-hero"
    staged = (
        training_root
        / "outputs"
        / run_name
        / "flux2-klein9b"
        / f"{run_name}.safetensors"
    )
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"reviewed-lora")
    command = _approval_command(script, run_name)

    first = subprocess.run(command, text=True, capture_output=True)
    approved = (
        repository_root
        / "models"
        / "loras"
        / "trained"
        / "characters"
        / f"{run_name}-flux2-klein9b.safetensors"
    )

    assert first.returncode == 0, first.stderr
    assert approved.read_bytes() == b"reviewed-lora"
    assert "Approved LoRA copied" in first.stdout

    staged.write_bytes(b"changed-after-review")
    second = subprocess.run(command, text=True, capture_output=True)

    assert second.returncode != 0
    assert "already exists and will not be overwritten" in second.stderr
    assert approved.read_bytes() == b"reviewed-lora"


def test_approval_only_requires_an_existing_staged_output(tmp_path: Path) -> None:
    script, _, repository_root = _localized_starter(tmp_path)
    command = _approval_command(script, "missing-stage")

    completed = subprocess.run(command, text=True, capture_output=True)

    assert completed.returncode != 0
    assert "No staged training output was found" in completed.stderr
    assert not repository_root.exists()


def test_dry_run_and_approval_are_rejected_before_destination_write(
    tmp_path: Path,
) -> None:
    script, training_root, repository_root = _localized_starter(tmp_path)
    run_name = "switch-conflict"
    staged = (
        training_root
        / "outputs"
        / run_name
        / "flux2-klein9b"
        / f"{run_name}.safetensors"
    )
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"reviewed-lora")
    command = [*_approval_command(script, run_name), "-DryRun"]

    completed = subprocess.run(command, text=True, capture_output=True)

    assert completed.returncode != 0
    assert "-DryRun and -ApproveOutput are mutually exclusive" in completed.stderr
    assert staged.read_bytes() == b"reviewed-lora"
    assert not repository_root.exists()


def test_renderer_runs_with_the_exact_python_isolation_mode_used_by_wrapper(
    tmp_path: Path,
) -> None:
    dataset = _valid_dataset(tmp_path / "dataset")
    models = _model_files(tmp_path / "models", "flux2-klein9b")
    renderer = REPO_ROOT / "tools" / "lora_training" / "render_musubi_config.py"
    starter = (
        REPO_ROOT / "tools" / "lora_training" / "start-character-training.ps1"
    ).read_text(encoding="utf-8")
    assert "$RendererPython = (Get-Command py" in starter
    assert "'-3', $Renderer" in starter
    assert "Invoke-Checked -FilePath $RendererPython -ArgumentList $rendererArgs" in starter
    renderer_python = shutil.which("py")
    assert renderer_python is not None, "Windows Python launcher required by wrapper"
    command = [
        renderer_python,
        "-3",
        str(renderer),
        "--model",
        "flux2-klein9b",
        "--dataset-dir",
        str(dataset),
        "--run-dir",
        str(tmp_path / "wrapper-run"),
        "--run-name",
        "wrapper-hero",
        "--trigger-token",
        "jmaHero",
        "--dit",
        str(models["dit"]),
        "--vae",
        str(models["vae"]),
        "--text-encoder",
        str(models["text_encoder"]),
        "--available-disk-gib",
        "100",
        "--dry-run",
    ]

    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)

    assert completed.returncode == 0, completed.stderr
    assert "VALID" in completed.stdout


def test_fixed_roots_revision_templates_and_wrappers_are_explicit() -> None:
    assert MUSUBI_REVISION == "8934cfbbb4b9bcfa8071ce209129f0c5eb5df2e6"
    assert MUSUBI_ROOT == Path(r"C:\tools\image\trainers\musubi-tuner")
    assert TRAINING_ROOT == Path(r"C:\tools\image\training\characters")
    assert APPROVED_LORA_RELATIVE_PATH == Path("models/loras/trained/characters")

    for template in (
        TEMPLATE_ROOT / "character-flux2-klein9b.toml",
        TEMPLATE_ROOT / "character-qwen-edit-2511.toml",
    ):
        assert template.is_file()

    installer = (REPO_ROOT / "tools" / "lora_training" / "install-musubi.ps1").read_text(
        encoding="utf-8"
    )
    starter = (
        REPO_ROOT / "tools" / "lora_training" / "start-character-training.ps1"
    ).read_text(encoding="utf-8")
    assert MUSUBI_REVISION in installer
    assert r"C:\tools\image\trainers\musubi-tuner" in installer
    assert ".venv" in installer
    assert "ComfyUI\\venv" not in installer
    assert "DryRun" in starter
    assert r"C:\tools\image\training\characters" in starter
    assert r"models\loras\trained\characters" in starter
    assert "ComfyUI\\venv" not in starter
