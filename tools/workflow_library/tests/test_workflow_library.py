"""Tests for the workflow library tooling.

The load-bearing guarantees are that the structural hash ignores everything a
re-save changes, and that indexing never writes to a workflow file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.workflow_library import export_wildcards, index_workflows, tagging
from tools.workflow_library.workflow_scan import (
    WorkflowParseError,
    collect_known_nodes,
    iter_workflow_files,
    load_object_info,
    parse_workflow,
)


def ui_workflow(
    *,
    seed: int = 1,
    prompt: str = "a photograph of a lighthouse at dusk",
    checkpoint: str = "flux1-dev.safetensors",
    offset: int = 0,
) -> dict:
    """A minimal UI-format graph whose incidentals can be varied per call."""
    return {
        "nodes": [
            {
                "id": 1 + offset,
                "type": "CheckpointLoaderSimple",
                "pos": [10 + offset, 20],
                "widgets_values": [checkpoint],
            },
            {
                "id": 2 + offset,
                "type": "CLIPTextEncode",
                "pos": [200 + offset, 20],
                "widgets_values": [prompt],
            },
            {
                "id": 3 + offset,
                "type": "KSampler",
                "pos": [400 + offset, 20],
                "title": f"sampler {seed}",
                "widgets_values": [seed, "randomize", 20, 8.0],
            },
        ],
        "links": [
            [1, 1 + offset, 0, 3 + offset, 0, "MODEL"],
            [2, 2 + offset, 0, 3 + offset, 1, "CONDITIONING"],
        ],
    }


def write(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------- parsing


def test_parses_ui_format(tmp_path: Path) -> None:
    workflow = parse_workflow(write(tmp_path, "a.json", ui_workflow()))

    assert workflow.fmt == "ui"
    assert sorted(workflow.node_types) == [
        "CLIPTextEncode",
        "CheckpointLoaderSimple",
        "KSampler",
    ]
    assert workflow.models == ["flux1-dev.safetensors"]
    assert workflow.prompts == ["a photograph of a lighthouse at dusk"]
    assert len(workflow.edges) == 2


def test_parses_api_format(tmp_path: Path) -> None:
    payload = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd.safetensors"}},
        "2": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": 42}},
    }
    workflow = parse_workflow(write(tmp_path, "api.json", payload))

    assert workflow.fmt == "api"
    assert workflow.models == ["sd.safetensors"]
    assert [e.source_type for e in workflow.edges] == ["CheckpointLoaderSimple"]


def test_counts_nodes_inside_subgraph_definitions(tmp_path: Path) -> None:
    payload = ui_workflow()
    payload["definitions"] = {
        "subgraphs": [
            {
                "nodes": [{"id": 90, "type": "VAEDecode"}, {"id": 91, "type": "SaveImage"}],
                "links": [[9, 90, 0, 91, 0, "IMAGE"]],
            }
        ]
    }
    workflow = parse_workflow(write(tmp_path, "sub.json", payload))

    assert "VAEDecode" in workflow.node_types
    assert any(e.target_type == "SaveImage" for e in workflow.edges)


def test_accepts_object_style_links(tmp_path: Path) -> None:
    payload = ui_workflow()
    payload["links"] = [
        {"origin_id": 1, "origin_slot": 0, "target_id": 3, "target_slot": 0},
    ]
    workflow = parse_workflow(write(tmp_path, "obj.json", payload))

    assert len(workflow.edges) == 1


def test_rejects_non_workflow_json(tmp_path: Path) -> None:
    with pytest.raises(WorkflowParseError):
        parse_workflow(write(tmp_path, "settings.json", {"theme": "dark"}))


def test_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(WorkflowParseError):
        parse_workflow(path)


def test_iter_workflow_files_skips_caches(tmp_path: Path) -> None:
    write(tmp_path, "keep.json", ui_workflow())
    write(tmp_path, "__pycache__/skip.json", ui_workflow())
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    found = [p.name for p in iter_workflow_files([tmp_path])]

    assert found == ["keep.json"]


# ---------------------------------------------------------------- hashing


def test_structural_hash_ignores_what_a_resave_changes(tmp_path: Path) -> None:
    """The whole point: a re-save under a new number hashes identically."""
    original = parse_workflow(write(tmp_path, "31 - draft.json", ui_workflow()))
    resaved = parse_workflow(
        write(
            tmp_path,
            "32 - final.json",
            ui_workflow(seed=99, prompt="something else entirely", offset=100),
        )
    )

    assert original.structural_hash() == resaved.structural_hash()


def test_structural_hash_separates_different_graphs(tmp_path: Path) -> None:
    payload = ui_workflow()
    payload["nodes"].append({"id": 4, "type": "VAEDecode", "widgets_values": []})
    changed = parse_workflow(write(tmp_path, "b.json", payload))
    baseline = parse_workflow(write(tmp_path, "a.json", ui_workflow()))

    assert baseline.structural_hash() != changed.structural_hash()


def test_composition_hash_ignores_rewiring(tmp_path: Path) -> None:
    rewired = ui_workflow()
    rewired["links"] = [[1, 1, 0, 3, 1, "MODEL"]]
    baseline = parse_workflow(write(tmp_path, "a.json", ui_workflow()))
    variant = parse_workflow(write(tmp_path, "b.json", rewired))

    assert baseline.composition_hash() == variant.composition_hash()
    assert baseline.structural_hash() != variant.structural_hash()


# ---------------------------------------------------------------- node owners


def test_collect_known_nodes_reads_both_registration_styles(tmp_path: Path) -> None:
    pack = tmp_path / "custom_nodes" / "demo-pack"
    pack.mkdir(parents=True)
    (pack / "legacy.py").write_text(
        'NODE_CLASS_MAPPINGS = {\n    "LegacyNode": object,\n}\n', encoding="utf-8"
    )
    (pack / "modern.py").write_text(
        'def define_schema(cls):\n    return io.Schema(node_id="SchemaNode")\n',
        encoding="utf-8",
    )

    owners = collect_known_nodes(tmp_path)

    assert owners["LegacyNode"] == "demo-pack"
    assert owners["SchemaNode"] == "demo-pack"


def test_frontend_virtual_nodes_are_not_reported_missing(tmp_path: Path) -> None:
    owners = collect_known_nodes(tmp_path)

    assert owners["MarkdownNote"] == "comfyui-frontend"
    assert owners["Reroute"] == "comfyui-frontend"


def test_load_object_info_attributes_nodes_to_packs(tmp_path: Path) -> None:
    dump = tmp_path / "object_info.json"
    dump.write_text(
        json.dumps(
            {
                "KSampler": {"python_module": "nodes"},
                "UnetLoaderGGUF": {"python_module": "custom_nodes.ComfyUI-GGUF"},
            }
        ),
        encoding="utf-8",
    )

    owners = load_object_info(dump)

    assert owners["KSampler"] == "comfyui-core"
    assert owners["UnetLoaderGGUF"] == "ComfyUI-GGUF"


# ---------------------------------------------------------------- tagging


def test_derive_tags_reads_models_and_nodes(tmp_path: Path) -> None:
    payload = ui_workflow(checkpoint="wan2.2_i2v_Q4_K_M.gguf")
    payload["nodes"].append({"id": 5, "type": "LoraLoader", "widgets_values": []})
    workflow = parse_workflow(write(tmp_path, "w.json", payload))

    tags = tagging.derive_tags(workflow)

    assert "wan" in tags
    assert "wan-2.2" in tags
    assert "quantized" in tags
    assert "lora" in tags


def test_duplicate_tag_is_shared_across_a_family(tmp_path: Path) -> None:
    workflow = parse_workflow(write(tmp_path, "w.json", ui_workflow()))

    tags = tagging.derive_tags(workflow, duplicate_key="abc123")

    assert "dup:abc123" in tags


def test_unresolved_nodes_flag_for_review(tmp_path: Path) -> None:
    workflow = parse_workflow(write(tmp_path, "w.json", ui_workflow()))

    assert "needs-review" in tagging.derive_tags(workflow, unresolved=["MysteryNode"])


def test_sidecar_format_is_one_lowercased_tag_per_line() -> None:
    assert tagging.format_sidecar(["Flux", "flux", " LoRA "]) == "flux\nlora\n"
    assert tagging.format_sidecar([]) == ""


# ---------------------------------------------------------------- indexing


def test_build_index_groups_duplicate_families(tmp_path: Path) -> None:
    write(tmp_path, "31 - draft.json", ui_workflow())
    write(tmp_path, "32 - final.json", ui_workflow(seed=7, offset=50))
    write(tmp_path, "40 - other.json", {"nodes": [{"id": 1, "type": "SaveImage"}]})

    entries, skipped = index_workflows.build_index([tmp_path], tmp_path)

    assert skipped == []
    families = index_workflows.group_families(entries, "structural")
    assert len(families) == 1
    assert len(families[0]) == 2


def test_index_never_writes_to_workflow_files(tmp_path: Path) -> None:
    path = write(tmp_path, "a.json", ui_workflow())
    before = path.stat().st_mtime_ns
    out = tmp_path / "out"

    code = index_workflows.main(
        ["--root", str(tmp_path), "--comfy-root", str(tmp_path), "--out", str(out)]
    )

    assert code == 0
    assert path.stat().st_mtime_ns == before
    assert json.loads(path.read_text(encoding="utf-8")) == ui_workflow()


def test_write_tags_emits_sidecars_beside_workflows(tmp_path: Path) -> None:
    write(tmp_path, "a.json", ui_workflow(checkpoint="flux1-dev.safetensors"))
    out = tmp_path / "out"

    code = index_workflows.main(
        [
            "--root", str(tmp_path),
            "--comfy-root", str(tmp_path),
            "--out", str(out),
            "--write-tags",
        ]
    )

    sidecar = tmp_path / "a.tags.txt"
    assert code == 0
    assert "flux" in sidecar.read_text(encoding="utf-8").split()


def test_rerunning_write_tags_is_idempotent(tmp_path: Path) -> None:
    write(tmp_path, "a.json", ui_workflow())
    entries, _ = index_workflows.build_index([tmp_path], tmp_path)

    first = index_workflows.write_tag_sidecars(entries)
    second = index_workflows.write_tag_sidecars(entries)

    assert len(first) == 1
    assert second == []


def test_report_names_the_duplicate_family(tmp_path: Path) -> None:
    write(tmp_path, "31 - draft.json", ui_workflow())
    write(tmp_path, "32 - final.json", ui_workflow(seed=3, offset=50))
    entries, skipped = index_workflows.build_index([tmp_path], tmp_path)

    report = index_workflows.render_report(entries, skipped)

    assert "Duplicate families" in report
    assert "31 - draft.json" in report
    assert "32 - final.json" in report


def test_missing_root_is_an_error(tmp_path: Path) -> None:
    assert index_workflows.main(["--root", str(tmp_path / "nope")]) == 2


def test_unparseable_files_are_reported_not_fatal(tmp_path: Path) -> None:
    write(tmp_path, "good.json", ui_workflow())
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")

    entries, skipped = index_workflows.build_index([tmp_path], tmp_path)

    assert len(entries) == 1
    assert len(skipped) == 1


# ---------------------------------------------------------------- wildcards


def test_group_options_splits_by_family_node_and_field() -> None:
    options = [
        {
            "node": "camera",
            "field": "focal_length",
            "phrases": {"flux": "a 50mm lens", "qwen": "a 50 mm lens"},
        },
        {
            "node": "camera",
            "field": "focal_length",
            "phrases": {"flux": "an 85mm lens"},
        },
    ]

    grouped = export_wildcards.group_options(options)

    assert grouped[("flux", "camera", "focal_length")] == ["a 50mm lens", "an 85mm lens"]
    assert grouped[("qwen", "camera", "focal_length")] == ["a 50 mm lens"]


def test_group_options_deduplicates_identical_phrases() -> None:
    options = [
        {"node": "pose", "field": "base_pose", "phrases": {"flux": "standing"}},
        {"node": "pose", "field": "base_pose", "phrases": {"flux": "standing"}},
    ]

    assert export_wildcards.group_options(options)[("flux", "pose", "base_pose")] == [
        "standing"
    ]


def test_render_file_puts_one_phrase_per_line() -> None:
    text = export_wildcards.render_file("camera", "focal_length", ["a", "b"])
    lines = text.splitlines()

    assert lines[0].startswith("##")
    assert lines[1:] == ["a", "b"]


def test_write_tree_lays_out_namespace_family_node_field(tmp_path: Path) -> None:
    grouped = {("flux", "camera", "focal_length"): ["a 50mm lens"]}

    written = export_wildcards.write_tree(grouped, tmp_path)

    expected = tmp_path / "archpt" / "flux" / "camera" / "focal_length.txt"
    assert written == [expected]
    assert "a 50mm lens" in expected.read_text(encoding="utf-8")


def test_cheatsheet_lists_the_wildcard_tokens() -> None:
    grouped = {("flux", "camera", "focal_length"): ["a 50mm lens"]}

    text = export_wildcards.render_cheatsheet(grouped)

    assert "__archpt/flux/camera/focal_length__" in text
    assert "__archpt/flux/camera/*__" in text


def test_export_leaves_the_arch_pt_catalog_untouched(tmp_path: Path) -> None:
    catalog = tmp_path / "builtin_options.json"
    catalog.write_text(
        json.dumps(
            {
                "version": "3",
                "options": [
                    {"node": "camera", "field": "framing", "phrases": {"flux": "a wide shot"}}
                ],
            }
        ),
        encoding="utf-8",
    )
    before = catalog.stat().st_mtime_ns

    code = export_wildcards.main(
        ["--catalog", str(catalog), "--out", str(tmp_path / "wildcards")]
    )

    assert code == 0
    assert catalog.stat().st_mtime_ns == before


def test_export_reports_an_empty_catalog(tmp_path: Path) -> None:
    catalog = tmp_path / "empty.json"
    catalog.write_text(json.dumps({"options": []}), encoding="utf-8")

    assert export_wildcards.main(["--catalog", str(catalog), "--out", str(tmp_path)]) == 1
