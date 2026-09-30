from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_flux9b_local_identity_i2i_workflow.py"


def load_builder():
    assert SCRIPT_PATH.is_file(), "workflow builder has not been implemented"
    spec = importlib.util.spec_from_file_location("flux9b_identity_builder", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def nodes(workflow, node_type):
    return [node for node in workflow["nodes"] if node["type"] == node_type]


def title_node(workflow, title_fragment):
    return next(
        node
        for node in workflow["nodes"]
        if title_fragment.casefold() in node.get("title", "").casefold()
    )


def test_workspace_uses_native_subgraphs_and_preserves_executable_graph():
    builder = load_builder()
    editor = builder.build_artifacts()["editor"]
    definitions = editor.get("definitions", {}).get("subgraphs", [])
    assert len(definitions) == 3
    assert builder.api_from_editor(editor) == builder.api_from_editor(builder.build_flat_editor())
    assert len(editor["nodes"]) <= 22
    assert len(nodes(editor, "RandomReferenceImageSource")) == 5
    assert len(nodes(editor, "SaveImage")) == 2
    assert not nodes(editor, "ComfySwitchNode")


def test_identity_bypass_selection_and_status_are_wired_end_to_end():
    builder = load_builder()
    editor = builder.build_editor()
    api = builder.api_from_editor(editor)
    assert api["58"]["inputs"]["enabled"] == ["8", 0]
    assert api["58"]["inputs"]["reference_face_selection"] == ["10", 5]
    assert api["58"]["inputs"]["target_face_selection"] == ["55", 3]
    flat = builder.flatten_editor(editor)
    links = {link[0]: link for link in flat["links"]}
    by_id = {node["id"]: node for node in flat["nodes"]}
    for preview, source, slot in [(63, 55, 2), (64, 59, 1), (67, 10, 3)]:
        assert links[by_id[preview]["inputs"][0]["link"]][1:3] == [source, slot]


def test_workspace_controls_are_exposed_and_do_not_overlap():
    builder = load_builder()
    editor = builder.build_artifacts()["editor"]
    proxies = [tuple(proxy) for node in editor["nodes"]
               for proxy in node.get("properties", {}).get("proxyWidgets", [])]
    for proxy in [("65", "text"), ("11", "mode"), ("48", "steps"), ("49", "cfg"),
                  ("58", "same_identity_threshold")]:
        assert proxy in proxies
    assert len(nodes(editor, "RandomNoise")) == 1
    assert len(nodes(editor, "PreviewAny")) == 3
    by_id = {node["id"]: node for node in editor["nodes"]}
    for image, switch in [(2, 6), (3, 25), (4, 32), (5, 39)]:
        assert abs(by_id[image]["pos"][0] - by_id[switch]["pos"][0]) < 10
        assert 0 < by_id[switch]["pos"][1] - by_id[image]["pos"][1] <= 400
    for index, left in enumerate(editor["nodes"]):
        x, y = left["pos"]
        w, h = left["size"]
        for right in editor["nodes"][index + 1:]:
            rx, ry = right["pos"]
            rw, rh = right["size"]
            assert x + w <= rx or rx + rw <= x or y + h + 30 <= ry or ry + rh + 30 <= y, (left["id"], right["id"])
    assert max(n["pos"][0] + n["size"][0] for n in editor["nodes"]) <= 1900
    assert max(n["pos"][1] + n["size"][1] for n in editor["nodes"]) <= 1400


def test_subgraph_ports_and_node_links_are_reciprocal():
    builder = load_builder()
    editor = builder.build_artifacts()["editor"]
    for graph in [editor, *editor.get("definitions", {}).get("subgraphs", [])]:
        by_id = {node["id"]: node for node in graph["nodes"]}
        for serialized in graph["links"]:
            link = serialized if isinstance(serialized, list) else [serialized[k] for k in
                    ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")]
            lid, source, source_slot, target, target_slot, _ = link
            if source == -10:
                assert lid in graph["inputs"][source_slot]["linkIds"]
            else:
                assert lid in by_id[source]["outputs"][source_slot]["links"]
            if target == -20:
                assert lid in graph["outputs"][target_slot]["linkIds"]
            else:
                assert by_id[target]["inputs"][target_slot]["link"] == lid


def test_builds_one_deterministic_editor_and_api_pair():
    builder = load_builder()

    first = builder.build_artifacts()
    second = builder.build_artifacts()

    assert first == second
    assert first["editor_name"] == "54 - Flux 9B Local Identity I2I.json"
    assert first["api_name"] == "54 - Flux 9B Local Identity I2I API.json"
    assert first["api"] == builder.api_from_editor(first["editor"])


def test_favorite_prompts_reach_encoder_and_follow_image_switches():
    api = load_builder().build_artifacts()["api"]
    assert api["20"]["inputs"]["text"] == ["65", 0]
    assert api["65"]["class_type"] == "ReferencePromptCompose"
    for source, lane in enumerate(("main", "identity", "aux1", "aux2", "aux3"), 1):
        assert api["65"]["inputs"][lane] == [str(source), 5]
    for source, lane in [(6, "identity"), (25, "aux1"), (32, "aux2"), (39, "aux3")]:
        assert api["65"]["inputs"][f"use_{lane}"] == [str(source), 0]
    flat = load_builder().build_flat_editor()
    assert any(link[1:5] == [65, 0, 66, 0] for link in flat["links"])


def test_inputs_have_one_main_one_identity_and_three_lazy_auxiliary_references():
    builder = load_builder()
    workflow = builder.flatten_editor(builder.build_artifacts()["editor"])

    loaders = nodes(workflow, "RandomReferenceImageSource")
    assert len(loaders) == 5
    assert "main i2i" in loaders[0]["title"].casefold()
    assert "identity" in loaders[1]["title"].casefold()
    assert ["auxiliary reference" in node["title"].casefold() for node in loaders[2:]] == [True] * 3

    # Identity uses one lazy image switch. Each auxiliary reference uses one
    # switch for positive and one for negative conditioning, driven by a shared
    # visible boolean control so the two paths cannot drift.
    switches = nodes(workflow, "ComfySwitchNode")
    assert len(switches) == 7
    assert title_node(workflow, "identity source:")["widgets_values"] == [False]
    for index in range(1, 4):
        assert title_node(workflow, f"enable auxiliary reference {index}")["widgets_values"] == [False]


def test_output_geometry_comes_only_from_safe_canvas_node():
    builder = load_builder()
    workflow = builder.flatten_editor(builder.build_artifacts()["editor"])
    canvas = nodes(workflow, "ArchCanvasSize")
    assert len(canvas) == 1
    assert canvas[0]["widgets_values"] == ["Auto (safe)"]

    size_nodes = nodes(workflow, "GetImageSize")
    assert size_nodes == []
    latent = nodes(workflow, "EmptyFlux2LatentImage")[0]
    scheduler = nodes(workflow, "Flux2Scheduler")[0]
    links = {link[0]: link for link in workflow["links"]}
    for node in (latent, scheduler):
        width = next(item for item in node["inputs"] if item["name"] == "width")
        height = next(item for item in node["inputs"] if item["name"] == "height")
        assert links[width["link"]][1:3] == [canvas[0]["id"], 0]
        assert links[height["link"]][1:3] == [canvas[0]["id"], 1]


def test_flux_path_keeps_baseline_stack_and_chains_optional_references():
    builder = load_builder()
    workflow = builder.flatten_editor(builder.build_artifacts()["editor"])

    assert nodes(workflow, "UNETLoader")[0]["widgets_values"] == [builder.KLEIN_MODEL, "default"]
    assert nodes(workflow, "CLIPLoader")[0]["widgets_values"] == [builder.KLEIN_CLIP, "flux2", "default"]
    assert nodes(workflow, "VAELoader")[0]["widgets_values"] == [builder.KLEIN_VAE]
    assert [node["widgets_values"] for node in nodes(workflow, "LoraLoaderModelOnly")] == [
        [builder.LOOK_LORA, 0.49],
        [builder.SKIN_LORA, 0.78],
    ]
    assert len(nodes(workflow, "ReferenceLatent")) == 8
    assert nodes(workflow, "ImageScaleToTotalPixels")


def test_identity_finish_is_landmark_aligned_sam_bounded_and_locally_scored():
    builder = load_builder()
    workflow = builder.flatten_editor(builder.build_artifacts()["editor"])

    transfer = nodes(workflow, "ArchLocalFaceIdentityTransfer")
    assert len(transfer) == 1
    assert transfer[0]["widgets_values"][-1] == 2
    preflight = nodes(workflow, "ArchFaceIdentityPreflight")[0]
    links = {link[0]: link for link in workflow["links"]}
    mask_mode = next(item for item in transfer[0]["inputs"] if item["name"] == "mask_mode")
    assert links[mask_mode["link"]][1:3] == [preflight["id"], 4]
    assert nodes(workflow, "DualIdentityScore")
    assert nodes(workflow, "OpenCVIdentityScore") == []
    assert nodes(workflow, "ArchIdentityGate")
    assert nodes(workflow, "ArchRequireMask") == []


def test_preflight_gates_flux_and_final_save_is_gated_by_dual_score():
    builder = load_builder()
    workflow = builder.flatten_editor(builder.build_artifacts()["editor"])
    links = {link[0]: link for link in workflow["links"]}
    preflight = nodes(workflow, "ArchFaceIdentityPreflight")[0]
    canvas = nodes(workflow, "ArchCanvasSize")[0]
    main_scale = title_node(workflow, "Normalize main reference")
    for node in (canvas, main_scale):
        image_input = next(item for item in node["inputs"] if item["name"] == "image")
        assert links[image_input["link"]][1:3] == [preflight["id"], 1]

    gate = nodes(workflow, "ArchIdentityGate")[0]
    dominance = next(item for item in gate["inputs"] if item["name"] == "require_reference_dominance")
    identity_selector = title_node(workflow, "Identity source:")
    assert links[dominance["link"]][1:3] == [identity_selector["id"], 0]
    final_save = title_node(workflow, "Save identity-preserved")
    save_input = next(item for item in final_save["inputs"] if item["name"] == "images")
    assert links[save_input["link"]][1:3] == [gate["id"], 0]


def test_new_runtime_assets_are_not_gitignored():
    paths = [
        "custom_nodes/comfyui_arch_image_tools/face_identity.py",
        "user/default/workflows/agent/54 - Flux 9B Local Identity I2I.json",
        "user/default/api_workflows/agent/54 - Flux 9B Local Identity I2I API.json",
        "input/arch_flux9b_placeholder.ppm",
    ]
    for path in paths:
        result = subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 1, f"runtime asset is still ignored: {path}"


def test_install_sync_writes_and_checks_the_8192_layout(tmp_path):
    builder = load_builder()
    artifacts = builder.build_artifacts()
    builder.install_runtime(artifacts, install_root=tmp_path, source_root=REPO_ROOT)
    assert builder.check_runtime(artifacts, install_root=tmp_path, source_root=REPO_ROOT) == []
    installed = tmp_path / "runtime/user/default/workflows/agent" / artifacts["editor_name"]
    installed.write_text("drift", encoding="utf-8")
    assert builder.check_runtime(artifacts, install_root=tmp_path, source_root=REPO_ROOT) == [installed]


def test_runtime_drift_paths_outside_the_repo_remain_reportable(tmp_path):
    builder = load_builder()
    outside_path = tmp_path / "runtime" / "missing.py"
    assert builder.display_path(outside_path) == str(outside_path)


def test_outputs_keep_base_and_identity_finished_results_distinct():
    builder = load_builder()
    workflow = builder.flatten_editor(builder.build_artifacts()["editor"])

    prefixes = [node["widgets_values"][0] for node in nodes(workflow, "SaveImage")]
    assert prefixes == [
        "Flux9B-Local-I2I/base",
        "Flux9B-Local-I2I/identity-finished",
    ]
    assert len(nodes(workflow, "PreviewImage")) >= 5


def test_generated_files_are_current_and_use_existing_synthetic_placeholder():
    builder = load_builder()
    artifacts = builder.build_artifacts()

    assert (REPO_ROOT / "input" / builder.PLACEHOLDER).is_file()
    assert builder.write_or_check(artifacts, repo_root=REPO_ROOT, check=True) == []

    editor_path = REPO_ROOT / builder.EDITOR_DIR / artifacts["editor_name"]
    api_path = REPO_ROOT / builder.API_DIR / artifacts["api_name"]
    assert json.loads(editor_path.read_text(encoding="utf-8")) == artifacts["editor"]
    assert json.loads(api_path.read_text(encoding="utf-8")) == artifacts["api"]
