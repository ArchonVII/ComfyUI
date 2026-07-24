"""Render deterministic, local-only Musubi character LoRA run configs."""

from __future__ import annotations

import argparse
import json
import re
import sys
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


def _validate_model_paths(model: str, model_paths: Mapping[str, Path | str]) -> dict[str, Path]:
    missing = sorted({"dit", "vae", "text_encoder"} - set(model_paths))
    if missing:
        raise ModelCheckpointError("Missing model path(s): " + ", ".join(missing))
    resolved = {
        name: Path(model_paths[name]).expanduser().resolve()
        for name in ("dit", "vae", "text_encoder")
    }
    for label, path in resolved.items():
        if path.suffix.casefold() == ".gguf":
            raise ModelCheckpointError(
                f"GGUF checkpoint '{path.name}' is an inference weight and cannot be used as "
                f"the trainable {label}. Select the official BF16/base .safetensors checkpoint."
            )
        if not path.is_file():
            raise ModelCheckpointError(f"{label} checkpoint does not exist: {path}")
    dit_name = resolved["dit"].name.casefold()
    if model == "flux2-klein9b" and (
        "distill" in dit_name
        or ("klein-9b" in dit_name and "base" not in dit_name)
        or ("klein_9b" in dit_name and "base" not in dit_name)
    ):
        raise ModelCheckpointError(
            f"Checkpoint '{resolved['dit'].name}' appears distilled/inference-only. "
            "Train FLUX.2 with the BF16 klein-base-9b checkpoint."
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
    dataset_config = run / "dataset.toml"
    train_config = run / "train.toml"
    manifest_path = run / "dataset-manifest.json"
    existing = [path for path in (dataset_config, train_config, manifest_path) if path.exists()]
    if existing:
        raise ExistingRunError(
            "Safety guard will not overwrite existing run config(s): "
            + ", ".join(str(path) for path in existing)
            + ". Choose a new run name/directory."
        )

    run.mkdir(parents=True, exist_ok=True)
    dataset_config.write_text(dataset_text, encoding="utf-8", newline="\n")
    train_config.write_text(training_text, encoding="utf-8", newline="\n")
    manifest_path.write_text(
        json.dumps(manifest_data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return RenderResult(
        run_dir=run,
        dataset_config=dataset_config,
        train_config=train_config,
        manifest=manifest_path,
        warnings=tuple(manifest_data.get("warnings", [])),
    )


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
        "--vae_dtype",
        "bfloat16",
    )
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
            commands = build_musubi_commands(
                model=args.model,
                trainer_root=MUSUBI_ROOT,
                dataset_config=args.run_dir / "dataset.toml",
                train_config=args.run_dir / "train.toml",
                model_paths=model_paths,
            )
            print("VALID: dataset, checkpoints, trigger token, run name, and disk guard passed.")
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
