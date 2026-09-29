from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "extract_inswapper_emap.py"


def load_script():
    spec = importlib.util.spec_from_file_location("extract_inswapper_emap", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extracts_named_embedding_map_instead_of_last_initializer(tmp_path):
    module = load_script()
    wanted = np.arange(16, dtype=np.float32).reshape(4, 4)
    wrong = np.ones((2, 2), dtype=np.float32)
    graph = helper.make_graph(
        [],
        "emap-test",
        [],
        [],
        [numpy_helper.from_array(wanted, name="buff2fs"), numpy_helper.from_array(wrong, name="not_the_map")],
    )
    model_path = tmp_path / "inswapper.onnx"
    output_path = tmp_path / "inswapper.emap.npy"
    onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)]), model_path)

    shape = module.extract_emap(model_path, output_path, expected_shape=(4, 4))

    assert shape == (4, 4)
    assert np.array_equal(np.load(output_path), wanted)
