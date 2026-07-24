"""Render deterministic, local-only Musubi character LoRA run configs."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:
    from .character_dataset import (
        DatasetValidationError,
        build_dataset_manifest,
        check_free_space,
    )
except ImportError:  # Direct script execution.
    from character_dataset import (  # type: ignore[no-redef]
        DatasetValidationError,
        build_dataset_manifest,
        check_free_space,
    )


MUSUBI_REVISION = "8934cfbbb4b9bcfa8071ce209129f0c5eb5df2e6"
MUSUBI_ROOT = Path(r"C:\tools\image\trainers\musubi-tuner")
TRAINING_ROOT = Path(r"C:\tools\image\training\characters")
APPROVED_LORA_RELATIVE_PATH = Path("models/loras/trained/characters")
MINIMUM_TRAINING_FREE_GIB = 50.0
_SAFE_RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
_INFERENCE_FILENAME_MARKERS = (
    "inference",
    "distill",
    "lightning",
    "turbo",
    "quantized",
    "quantised",
    "fp8",
    "e4m3",
    "int8",
    "int4",
    "q4_",
    "q5_",
    "q6_",
    "q8_",
)
_QUANTIZED_DTYPES = frozenset({"I8", "U8", "I4", "U4"})
_MAX_SAFETENSORS_HEADER_BYTES = 64 * 1024 * 1024


class ExistingRunError(FileExistsError):
    """Raised when rendering would replace an existing run config."""


class ModelCheckpointError(ValueError):
    """Raised when inference-only or unsupported weights are selected."""


@dataclass(frozen=True)
class ModelProfile:
    template: str
    model_version: str
    network_module: str
    latent_script: str
    text_script: str
    train_script: str
    text_fp8_flag: str
    blocks_to_swap: int


@dataclass(frozen=True)
class RenderResult:
    run_dir: Path
    dataset_config: Path
    train_config: Path
    manifest: Path
    warnings: tuple[str, ...]


MODEL_PROFILES = {
    "flux2-klein9b": ModelProfile(
        template="character-flux2-klein9b.toml",
        model_version="klein-base-9b",
        network_module="networks.lora_flux_2",
        latent_script="flux_2_cache_latents.py",
        text_script="flux_2_cache_text_encoder_outputs.py",
        train_script="flux_2_train_network.py",
        text_fp8_flag="--fp8_text_encoder",
        blocks_to_swap=16,
    ),
    "qwen-edit-2511": ModelProfile(
        template="character-qwen-edit-2511.toml",
        model_version="edit-2511",
        network_module="networks.lora_qwen_image",
        latent_script="qwen_image_cache_latents.py",
        text_script="qwen_image_cache_text_encoder_outputs.py",
        train_script="qwen_image_train_network.py",
        text_fp8_flag="--fp8_vl",
        blocks_to_swap=45,
    ),
}


def resource_warnings(model: str, vram_gib: float, ram_gib: float) -> list[str]:
    if model not in MODEL_PROFILES:
        raise ValueError(f"Unsupported model '{model}'.")
    warnings: list[str] = []
    if vram_gib <= 16.5:
        warnings.append(
            f"{model} LoRA training on {vram_gib:g} GiB VRAM is experimental; "
            "keep batch_size=1, FP8, gradient checkpointing, and block swap enabled."
        )
    if ram_gib <= 32:
        if model == "qwen-edit-2511":
            warnings.append(
                f"Qwen Edit block swap is documented with 64 GiB main RAM recommended; "
                f"this host has {ram_gib:g} GiB, so heavy paging or failure is possible."
            )
        else:
            warnings.append(
                f"FLUX.2 Klein 9B on {ram_gib:g} GiB RAM is experimental; "
                "block swap may exhaust RAM and use the Windows page file."
            )
    return warnings


def _profile(model: str) -> ModelProfile:
    try:
        return MODEL_PROFILES[model]
    except KeyError as exc:
        choices = ", ".join(sorted(MODEL_PROFILES))
        raise ValueError(f"Unsupported model '{model}'. Choose one of: {choices}.") from exc


def _validate_run_name(run_name: str) -> str:
    if not _SAFE_RUN_NAME.fullmatch(run_name):
        raise ValueError(
            "Unsafe run name: use 3-80 letters, digits, '.', '_' or '-', with no path separators."
        )
    return run_name


def _read_safetensors_dtypes(path: Path, label: str) -> frozenset[str]:
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        prefix = stream.read(8)
        if prefix[:4] == b"GGUF":
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' has GGUF file magic despite its name. "
                "GGUF is inference-only here; select an unquantized .safetensors training asset."
            )
        if len(prefix) != 8:
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' has no valid safetensors header."
            )
        header_length = int.from_bytes(prefix, "little")
        remaining = file_size - 8
        if (
            header_length <= 0
            or header_length > _MAX_SAFETENSORS_HEADER_BYTES
            or header_length > remaining
        ):
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' has an invalid safetensors header length."
            )
        header_bytes = stream.read(header_length)

    try:
        header = json.loads(header_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelCheckpointError(
            f"{label} checkpoint '{path.name}' has an unreadable safetensors JSON header."
        ) from exc
    if not isinstance(header, dict):
        raise ModelCheckpointError(
            f"{label} checkpoint '{path.name}' has an invalid safetensors header object."
        )

    payload_size = file_size - 8 - header_length
    dtypes: set[str] = set()
    intervals: list[tuple[int, int, str]] = []
    for tensor_name, tensor in header.items():
        if tensor_name == "__metadata__":
            continue
        if not isinstance(tensor, dict) or not isinstance(tensor.get("dtype"), str):
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' has malformed tensor metadata "
                f"for '{tensor_name}'."
            )
        offsets = tensor.get("data_offsets")
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or any(not isinstance(offset, int) or isinstance(offset, bool) for offset in offsets)
        ):
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' has malformed data_offsets "
                f"for '{tensor_name}'; offsets must be two integer payload positions."
            )
        start, end = offsets
        if start < 0 or end < start or end > payload_size:
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' has data_offsets [{start}, {end}] "
                f"outside its {payload_size}-byte payload for '{tensor_name}'."
            )
        intervals.append((start, end, tensor_name))
        dtypes.add(tensor["dtype"].upper())
    if not dtypes:
        raise ModelCheckpointError(
            f"{label} checkpoint '{path.name}' declares no tensors in its safetensors header."
        )
    cursor = 0
    for start, end, tensor_name in sorted(intervals):
        if start != cursor:
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' has non-contiguous or overlapping "
                f"data_offsets at '{tensor_name}' within its payload."
            )
        cursor = end
    if cursor != payload_size:
        raise ModelCheckpointError(
            f"{label} checkpoint '{path.name}' data_offsets cover {cursor} bytes but "
            f"the file payload contains {payload_size} bytes."
        )
    return frozenset(dtypes)


def _checkpoint_advice(model: str, label: str) -> str:
    if model == "flux2-klein9b" and label == "dit":
        return "Select the official unquantized BF16 klein-base-9b .safetensors checkpoint."
    if model == "qwen-edit-2511" and label == "dit":
        return "Select the unquantized Qwen-Image-Edit-2511 BF16 .safetensors checkpoint."
    if model == "qwen-edit-2511" and label == "text_encoder":
        return "Select the unquantized Qwen2.5-VL BF16 text encoder, not fp8_scaled."
    return f"Select an unquantized training-compatible .safetensors asset for {label}."


def _validate_model_paths(model: str, model_paths: Mapping[str, Path | str]) -> dict[str, Path]:
    missing = sorted({"dit", "vae", "text_encoder"} - set(model_paths))
    if missing:
        raise ModelCheckpointError("Missing model path(s): " + ", ".join(missing))
    resolved = {
        name: Path(model_paths[name]).expanduser().resolve()
        for name in ("dit", "vae", "text_encoder")
    }
    for label, path in resolved.items():
        if not path.is_file():
            raise ModelCheckpointError(f"{label} checkpoint does not exist: {path}")
        if path.suffix.casefold() == ".gguf":
            raise ModelCheckpointError(
                f"{label} GGUF checkpoint '{path.name}' is an inference weight and cannot be "
                "used for training. Select the official unquantized BF16/base .safetensors checkpoint."
            )
        if path.suffix.casefold() != ".safetensors":
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' must be a .safetensors training asset. "
                + _checkpoint_advice(model, label)
            )
        folded_name = path.name.casefold()
        marker = next(
            (candidate for candidate in _INFERENCE_FILENAME_MARKERS if candidate in folded_name),
            None,
        )
        if marker is not None:
            raise ModelCheckpointError(
                f"{label} checkpoint filename '{path.name}' contains inference/quantized marker "
                f"'{marker}'. {_checkpoint_advice(model, label)}"
            )

        dtypes = _read_safetensors_dtypes(path, label)
        quantized = sorted(
            dtype
            for dtype in dtypes
            if dtype.startswith("F8") or dtype in _QUANTIZED_DTYPES
        )
        if quantized:
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' contains unsupported quantized tensor "
                f"dtype(s): {', '.join(quantized)}. {_checkpoint_advice(model, label)}"
            )
        if model == "qwen-edit-2511" and label in {"dit", "text_encoder"} and "BF16" not in dtypes:
            observed = ", ".join(sorted(dtypes))
            raise ModelCheckpointError(
                f"{label} checkpoint '{path.name}' does not declare BF16 tensors "
                f"(observed: {observed}). {_checkpoint_advice(model, label)}"
            )
    return resolved


def _toml_string(value: Path | str) -> str:
    text = value.as_posix() if isinstance(value, Path) else str(value)
    return json.dumps(text, ensure_ascii=False)


def _render_template(template: str, values: Mapping[str, str]) -> str:
    rendered = template
    for name, value in values.items():
        rendered = rendered.replace("{{" + name + "}}", value)
    leftovers = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", rendered)))
    if leftovers:
        raise ValueError("Template has unresolved values: " + ", ".join(leftovers))
    return rendered.rstrip() + "\n"


def _dataset_toml(
    *,
    model: str,
    dataset_dir: Path,
    control_dir: Path | None,
    cache_dir: Path,
) -> str:
    lines = [
        "[general]",
        "resolution = [1024, 1024]",
        'caption_extension = ".txt"',
        "batch_size = 1",
        "enable_bucket = true",
        "bucket_no_upscale = false",
        "",
        "[[datasets]]",
        f"image_directory = {_toml_string(dataset_dir)}",
        f"cache_directory = {_toml_string(cache_dir)}",
        "num_repeats = 1",
    ]
    if model == "qwen-edit-2511":
        if control_dir is None:
            raise DatasetValidationError(
                "Qwen Edit 2511 requires a paired control directory with TARGET.png "
                "or TARGET_N.png controls for every target."
            )
        lines.extend(
            [
                f"control_directory = {_toml_string(control_dir)}",
                "no_resize_control = false",
                "control_resolution = [1024, 1024]",
            ]
        )
    return "\n".join(lines) + "\n"


def _prepare(
    *,
    model: str,
    dataset_dir: Path | str,
    control_dir: Path | str | None,
    run_dir: Path | str,
    run_name: str,
    trigger_token: str,
    model_paths: Mapping[str, Path | str],
    template_root: Path | str,
    available_bytes: int | None,
) -> tuple[ModelProfile, Path, Path | None, Path, dict[str, Path], dict, str, str]:
    profile = _profile(model)
    safe_name = _validate_run_name(run_name)
    dataset = Path(dataset_dir).expanduser().resolve()
    controls = Path(control_dir).expanduser().resolve() if control_dir is not None else None
    run = Path(run_dir).expanduser().resolve()
    check_free_space(run.parent, MINIMUM_TRAINING_FREE_GIB, available_bytes)
    paths = _validate_model_paths(model, model_paths)
    if model == "qwen-edit-2511" and controls is None:
        raise DatasetValidationError(
            "Qwen Edit 2511 requires a paired control directory; no control directory was provided."
        )
    manifest = build_dataset_manifest(dataset, trigger_token, controls)
    cache_dir = TRAINING_ROOT / "cache" / safe_name / model
    dataset_text = _dataset_toml(
        model=model,
        dataset_dir=dataset,
        control_dir=controls,
        cache_dir=cache_dir,
    )
    template_path = Path(template_root).expanduser().resolve() / profile.template
    if not template_path.is_file():
        raise FileNotFoundError(f"Musubi template not found: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    output_dir = TRAINING_ROOT / "outputs" / safe_name / model
    training_text = _render_template(
        template,
        {
            "DATASET_CONFIG": _toml_string("dataset.toml"),
            "DIT": _toml_string(paths["dit"]),
            "VAE": _toml_string(paths["vae"]),
            "TEXT_ENCODER": _toml_string(paths["text_encoder"]),
            "OUTPUT_DIR": _toml_string(output_dir),
            "OUTPUT_NAME": _toml_string(safe_name),
            "TRIGGER_TOKEN": _toml_string(trigger_token),
        },
    )
    return profile, dataset, controls, run, paths, manifest, dataset_text, training_text


def render_run(
    *,
    model: str,
    dataset_dir: Path | str,
    control_dir: Path | str | None = None,
    run_dir: Path | str,
    run_name: str,
    trigger_token: str,
    model_paths: Mapping[str, Path | str],
    template_root: Path | str | None = None,
    available_bytes: int | None = None,
) -> RenderResult:
    requested_run = Path(run_dir).expanduser().resolve()
    _assert_run_available(requested_run)
    templates = (
        Path(template_root)
        if template_root is not None
        else Path(__file__).resolve().parent / "templates"
    )
    _, _, _, run, _, manifest_data, dataset_text, training_text = _prepare(
        model=model,
        dataset_dir=dataset_dir,
        control_dir=control_dir,
        run_dir=run_dir,
        run_name=run_name,
        trigger_token=trigger_token,
        model_paths=model_paths,
        template_root=templates,
        available_bytes=available_bytes,
    )
    run.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _run_lock_path(run)
    try:
        lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ExistingRunError(
            f"Safety guard will not overwrite or mix run state while another render "
            f"holds '{lock_path}'. Choose a new run name/directory or remove a verified stale lock."
        ) from exc
    os.close(lock_descriptor)

    temporary_run = run.parent / f".{run.name}.tmp-{uuid.uuid4().hex}"
    try:
        _assert_run_available(run, include_lock=False)
        temporary_run.mkdir()
        _write_text_exclusive(temporary_run / "dataset.toml", dataset_text)
        _write_text_exclusive(temporary_run / "train.toml", training_text)
        _write_text_exclusive(
            temporary_run / "dataset-manifest.json",
            json.dumps(manifest_data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )
        _assert_run_available(run, include_lock=False)
        try:
            os.rename(temporary_run, run)
        except FileExistsError as exc:
            raise ExistingRunError(
                f"Safety guard will not overwrite run state created while publishing "
                f"'{run}'. Choose a new run name/directory."
            ) from exc
    finally:
        if temporary_run.exists():
            shutil.rmtree(temporary_run)
        lock_path.unlink(missing_ok=True)

    dataset_config = run / "dataset.toml"
    train_config = run / "train.toml"
    manifest_path = run / "dataset-manifest.json"
    return RenderResult(
        run_dir=run,
        dataset_config=dataset_config,
        train_config=train_config,
        manifest=manifest_path,
        warnings=tuple(manifest_data.get("warnings", [])),
    )


def _run_lock_path(run: Path) -> Path:
    return run.parent / f".{run.name}.lock"


def _assert_run_available(run: Path, *, include_lock: bool = True) -> None:
    if os.path.lexists(run):
        raise ExistingRunError(
            f"Safety guard will not overwrite existing run state at '{run}'. "
            "Choose a new run name/directory."
        )
    lock_path = _run_lock_path(run)
    if include_lock and os.path.lexists(lock_path):
        raise ExistingRunError(
            f"Safety guard will not overwrite or mix run state while another render "
            f"holds '{lock_path}'. Choose a new run name/directory or remove a verified stale lock."
        )


def _write_text_exclusive(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def build_musubi_commands(
    *,
    model: str,
    trainer_root: Path | str,
    dataset_config: Path | str,
    train_config: Path | str,
    model_paths: Mapping[str, Path | str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    profile = _profile(model)
    root = Path(trainer_root)
    python = root / ".venv" / "Scripts" / "python.exe"
    source = root / "src" / "musubi_tuner"
    paths = {name: Path(value) for name, value in model_paths.items()}
    latent = (
        str(python),
        str(source / profile.latent_script),
        "--dataset_config",
        str(Path(dataset_config)),
        "--vae",
        str(paths["vae"]),
        "--model_version",
        profile.model_version,
    )
    if model == "flux2-klein9b":
        latent += ("--vae_dtype", "bfloat16")
    text = (
        str(python),
        str(source / profile.text_script),
        "--dataset_config",
        str(Path(dataset_config)),
        "--text_encoder",
        str(paths["text_encoder"]),
        "--batch_size",
        "1",
        "--model_version",
        profile.model_version,
        profile.text_fp8_flag,
    )
    train = (
        str(python),
        "-m",
        "accelerate.commands.launch",
        "--num_cpu_threads_per_process",
        "1",
        "--mixed_precision",
        "bf16",
        str(source / profile.train_script),
        "--config_file",
        str(Path(train_config)),
    )
    return latent, text, train


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a local character dataset and render pinned Musubi run configs."
    )
    parser.add_argument("--model", choices=sorted(MODEL_PROFILES), required=True)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--control-dir", type=Path)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--trigger-token", required=True)
    parser.add_argument("--dit", type=Path, required=True)
    parser.add_argument("--vae", type=Path, required=True)
    parser.add_argument("--text-encoder", type=Path, required=True)
    parser.add_argument("--available-disk-gib", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _display_command(command: Sequence[str]) -> str:
    return subprocess_list2cmdline(command)


def subprocess_list2cmdline(command: Sequence[str]) -> str:
    # Windows-compatible quoting without importing or invoking a shell.
    import subprocess

    return subprocess.list2cmdline(list(command))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    model_paths = {
        "dit": args.dit,
        "vae": args.vae,
        "text_encoder": args.text_encoder,
    }
    available = (
        int(args.available_disk_gib * 1024**3)
        if args.available_disk_gib is not None
        else None
    )
    templates = Path(__file__).resolve().parent / "templates"
    try:
        if args.dry_run:
            run = args.run_dir.expanduser().resolve()
            _assert_run_available(run)
            _prepare(
                model=args.model,
                dataset_dir=args.dataset_dir,
                control_dir=args.control_dir,
                run_dir=args.run_dir,
                run_name=args.run_name,
                trigger_token=args.trigger_token,
                model_paths=model_paths,
                template_root=templates,
                available_bytes=available,
            )
            _assert_run_available(run)
            commands = build_musubi_commands(
                model=args.model,
                trainer_root=MUSUBI_ROOT,
                dataset_config=args.run_dir / "dataset.toml",
                train_config=args.run_dir / "train.toml",
                model_paths=model_paths,
            )
            print(
                "VALID: dataset and trigger/run syntax validated; safetensors "
                "container/dtype checks passed; semantic identity/provenance unverified; "
                "disk guard passed."
            )
            for phase, command in zip(("cache-latents", "cache-text", "train"), commands):
                print(f"{phase}: {_display_command(command)}")
            return 0

        result = render_run(
            model=args.model,
            dataset_dir=args.dataset_dir,
            control_dir=args.control_dir,
            run_dir=args.run_dir,
            run_name=args.run_name,
            trigger_token=args.trigger_token,
            model_paths=model_paths,
            template_root=templates,
            available_bytes=available,
        )
        print(f"Rendered run config: {result.train_config}")
        for warning in result.warnings:
            print(f"WARNING: {warning}")
        return 0
    except (DatasetValidationError, ExistingRunError, ModelCheckpointError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
