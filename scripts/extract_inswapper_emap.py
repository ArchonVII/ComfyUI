"""Extract INSwapper's local embedding map for runtimes that do not install onnx."""

import argparse
from pathlib import Path

import numpy as np
import onnx
from onnx import numpy_helper


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = REPO_ROOT / "models" / "insightface" / "inswapper_128.onnx"


def extract_emap(
    model_path: Path,
    output_path: Path | None = None,
    *,
    expected_shape: tuple[int, int] = (512, 512),
) -> tuple[int, ...]:
    model_path = Path(model_path)
    output_path = model_path.with_suffix(".emap.npy") if output_path is None else Path(output_path)
    model = onnx.load(str(model_path), load_external_data=False)
    initializer = next((item for item in model.graph.initializer if item.name == "buff2fs"), None)
    if initializer is None:
        raise ValueError("INSwapper model does not contain the named buff2fs embedding map")
    emap = numpy_helper.to_array(initializer).astype(np.float32)
    if emap.shape != expected_shape:
        raise ValueError(f"Unexpected INSwapper embedding map shape: {emap.shape}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, emap)
    return tuple(emap.shape)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", nargs="?", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.model.with_suffix(".emap.npy")
    shape = extract_emap(args.model, output)
    print(f"wrote {output} ({shape[0]}x{shape[1]})")


if __name__ == "__main__":
    main()
