import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / "user" / "default" / "workflows" / "agent"
API_WORKFLOW_DIR = REPO_ROOT / "user" / "default" / "api_workflows" / "agent"
REACTOR_API_NAME = "44 - Face Swap Proof and ReActor Baseline API.json"
KREA_API_NAME = "42 - Krea 2 Identity Edit v1.2 API.json"

WORKFLOWS = {
    "40 - Z-Image Turbo Identity Anchor I2I.json": {
        "slug": "z-image-turbo-identity-anchor-i2i",
        "model": r"Z-Image\z_image_turbo-Q8_0.gguf",
    },
    "41 - Z-Image Base Two Stage Precision I2I.json": {
        "slug": "z-image-base-two-stage-precision-i2i",
        "model": r"Z-Image\z_image-Q8_0.gguf",
    },
    "42 - Krea 2 Identity Edit v1.2.json": {
        "slug": "krea-2-identity-edit-v1-2",
        "model": r"Krea2\krea2_turbo_fp8_scaled.safetensors",
    },
    "43 - FireRed 1.1 Identity MultiRef.json": {
        "slug": "firered-1-1-identity-multiref",
        "model": r"FireRed\FireRed-Image-Edit-1.1-Q4_K_M.gguf",
    },
    "44 - Face Swap Proof and ReActor Baseline.json": {
        "slug": "face-swap-proof-reactor-baseline",
        "model": "inswapper_128.onnx",
    },
}


def load_workflow(name):
    path = WORKFLOW_DIR / name
    assert path.is_file(), f"missing workflow: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def nodes(workflow, node_type):
    return [node for node in workflow["nodes"] if node["type"] == node_type]


def note_text(workflow):
    return "\n".join(
        str(value)
        for node in workflow["nodes"]
        if node["type"] in {"MarkdownNote", "Note"}
        for value in node.get("widgets_values", ())
    ).casefold()


def input_source(workflow, target, input_name):
    matches = [
        (index, item)
        for index, item in enumerate(target.get("inputs", ()))
        if item["name"] == input_name
    ]
    assert len(matches) == 1
    target_slot, item = matches[0]
    assert item.get("link") is not None
    link = next(link for link in workflow["links"] if link[0] == item["link"])
    assert link[3:5] == [target["id"], target_slot]
    return next(node for node in workflow["nodes"] if node["id"] == link[1])


def assert_link_integrity(workflow):
    by_node = {node["id"]: node for node in workflow["nodes"]}
    assert len(by_node) == len(workflow["nodes"])
    by_link = {link[0]: link for link in workflow["links"]}
    assert len(by_link) == len(workflow["links"])

    for link_id, source_id, source_slot, target_id, target_slot, *_ in workflow[
        "links"
    ]:
        source = by_node[source_id]
        target = by_node[target_id]
        assert link_id in (source["outputs"][source_slot].get("links") or ())
        assert target["inputs"][target_slot].get("link") == link_id


@pytest.mark.parametrize(("name", "spec"), WORKFLOWS.items())
def test_workflow_exists_and_declares_traceable_suite_metadata(name, spec):
    workflow = load_workflow(name)
    metadata = workflow["extra"]["modern_identity_suite"]
    assert metadata["workflow_slug"] == spec["slug"]
    assert metadata["version"] == 1
    assert metadata["model"] == spec["model"]
    assert metadata["research_sources"]
    assert metadata["license"]
    assert workflow["last_node_id"] == max(node["id"] for node in workflow["nodes"])
    assert workflow["last_link_id"] == max(link[0] for link in workflow["links"])
    assert_link_integrity(workflow)


@pytest.mark.parametrize("name", WORKFLOWS)
def test_each_workflow_has_visible_instructions_and_saved_evidence(name):
    workflow = load_workflow(name)
    assert nodes(workflow, "MarkdownNote") or nodes(workflow, "Note")
    assert nodes(workflow, "SaveImage")
    text = note_text(workflow)
    assert "identity" in text
    assert "source" in text or "reference" in text


def test_z_turbo_uses_q8_full_encoder_and_external_identity_anchor():
    workflow = load_workflow("40 - Z-Image Turbo Identity Anchor I2I.json")
    unet = nodes(workflow, "UnetLoaderGGUF")
    assert len(unet) == 1
    assert unet[0]["widgets_values"][0] == (
        r"Z-Image\z_image_turbo-Q8_0.gguf"
    )
    clip = nodes(workflow, "CLIPLoader")
    assert len(clip) == 1
    assert clip[0]["widgets_values"][:2] == [
        r"Z-Image\qwen_3_4b.safetensors",
        "lumina2",
    ]
    images = nodes(workflow, "LoadImage")
    assert len(images) >= 2
    assert any("identity" in node.get("title", "").casefold() for node in images)
    assert any("target" in node.get("title", "").casefold() for node in images)
    assert nodes(workflow, "ImageStitch")
    assert nodes(workflow, "SetLatentNoiseMask")


def test_z_base_has_distinct_generation_and_low_denoise_refinement_passes():
    workflow = load_workflow("41 - Z-Image Base Two Stage Precision I2I.json")
    unet = nodes(workflow, "UnetLoaderGGUF")
    assert len(unet) == 1
    assert unet[0]["widgets_values"][0] == r"Z-Image\z_image-Q8_0.gguf"
    samplers = nodes(workflow, "KSampler")
    assert len(samplers) == 2
    denoises = sorted(node["widgets_values"][6] for node in samplers)
    assert denoises[0] <= 0.2
    assert denoises[1] >= 0.45
    assert nodes(workflow, "OpenCVIdentityScore")


def test_krea_identity_edit_uses_current_patch_and_grounded_encoder():
    workflow = load_workflow("42 - Krea 2 Identity Edit v1.2.json")
    unet = nodes(workflow, "UNETLoader")
    assert len(unet) == 1
    assert unet[0]["widgets_values"][0] == (
        r"Krea2\krea2_turbo_fp8_scaled.safetensors"
    )
    patch = nodes(workflow, "Krea2EditModelPatch")
    grounded = nodes(workflow, "Krea2EditGroundedEncode")
    assert len(patch) == 1
    assert len(grounded) == 2
    assert any(
        "unconditional" in node.get("title", "").casefold()
        for node in grounded
    )
    assert "v1.2" in note_text(workflow)
    samplers = nodes(workflow, "KSampler")
    assert len(samplers) == 1
    assert samplers[0]["widgets_values"][2:4] == [8, 1.0]


def test_firered_uses_current_gguf_lightning_and_two_reference_roles():
    workflow = load_workflow("43 - FireRed 1.1 Identity MultiRef.json")
    unet = nodes(workflow, "UnetLoaderGGUF")
    assert len(unet) == 1
    assert unet[0]["widgets_values"][0] == (
        r"FireRed\FireRed-Image-Edit-1.1-Q4_K_M.gguf"
    )
    lora = nodes(workflow, "LoraLoaderModelOnly")
    assert len(lora) == 1
    assert "Lightning-8steps-v1.2" in lora[0]["widgets_values"][0]
    edit_encoders = nodes(workflow, "TextEncodeQwenImageEditPlus")
    assert len(edit_encoders) == 2
    assert any(
        "unconditional" in node.get("title", "").casefold()
        for node in edit_encoders
    )
    images = nodes(workflow, "LoadImage")
    assert len(images) >= 2
    assert nodes(workflow, "OpenCVIdentityScore")


def test_reactor_proof_graph_keeps_target_and_identity_roles_unambiguous():
    workflow = load_workflow("44 - Face Swap Proof and ReActor Baseline.json")
    swaps = nodes(workflow, "ReActorFaceSwap")
    assert len(swaps) == 1
    swap = swaps[0]
    source = input_source(workflow, swap, "source_image")
    target = input_source(workflow, swap, "input_image")
    assert "identity" in source.get("title", "").casefold()
    assert "target" in target.get("title", "").casefold()
    scores = nodes(workflow, "OpenCVIdentityScore")
    assert len(scores) == 1
    assert input_source(workflow, scores[0], "reference_image")["id"] == source["id"]
    assert input_source(workflow, scores[0], "generated_image")["id"] == swap["id"]


def test_reactor_proof_has_a_standalone_executable_api_graph():
    path = API_WORKFLOW_DIR / REACTOR_API_NAME
    assert path.is_file(), f"missing API workflow: {path}"
    prompt = json.loads(path.read_text(encoding="utf-8"))
    by_type = {}
    for node_id, node in prompt.items():
        by_type.setdefault(node["class_type"], []).append((node_id, node))

    assert len(by_type["ReActorFaceSwap"]) == 1
    swap_id, swap = by_type["ReActorFaceSwap"][0]
    assert swap["inputs"]["face_restore_model"] == "GFPGANv1.4.pth"
    assert swap["inputs"]["face_restore_visibility"] == pytest.approx(0.75)
    source_id = swap["inputs"]["source_image"][0]
    target_id = swap["inputs"]["input_image"][0]
    assert prompt[source_id]["inputs"]["image"] == (
        "identity-benchmark/source_identity.png"
    )
    assert prompt[target_id]["inputs"]["image"] == (
        "identity-benchmark/target_scene_v2.png"
    )

    assert len(by_type["OpenCVIdentityScore"]) == 1
    score = by_type["OpenCVIdentityScore"][0][1]
    assert score["inputs"]["reference_image"] == [source_id, 0]
    assert score["inputs"]["generated_image"] == [swap_id, 0]
    saves = by_type["SaveImage"]
    assert len(saves) == 1
    assert saves[0][1]["inputs"]["images"] == [swap_id, 0]


def test_krea_identity_has_a_two_reference_executable_api_graph():
    path = API_WORKFLOW_DIR / KREA_API_NAME
    assert path.is_file(), f"missing API workflow: {path}"
    prompt = json.loads(path.read_text(encoding="utf-8"))
    by_type = {}
    for node_id, node in prompt.items():
        by_type.setdefault(node["class_type"], []).append((node_id, node))

    assert len(by_type["UNETLoader"]) == 1
    assert by_type["UNETLoader"][0][1]["inputs"]["unet_name"] == (
        r"Krea2\krea2_turbo_fp8_scaled.safetensors"
    )
    assert len(by_type["Krea2EditModelPatch"]) == 1
    patch_id, patch = by_type["Krea2EditModelPatch"][0]
    assert patch["inputs"]["ref_boost"] == pytest.approx(1.5)
    assert patch["inputs"]["ref_boost_a"] == pytest.approx(1.0)
    assert patch["inputs"]["fit_mode"] == "fit"

    target_id = patch["inputs"]["source_image"][0]
    source_id = patch["inputs"]["source_image_b"][0]
    assert prompt[target_id]["inputs"]["image"] == (
        "identity-benchmark/target_scene_v2.png"
    )
    assert prompt[source_id]["inputs"]["image"] == (
        "identity-benchmark/source_identity.png"
    )

    assert len(by_type["Krea2EditGroundedEncode"]) == 2
    assert len(by_type["OpenCVIdentityScore"]) == 1
    score = by_type["OpenCVIdentityScore"][0][1]
    assert score["inputs"]["reference_image"] == [source_id, 0]
    decoder_id = by_type["VAEDecode"][0][0]
    assert score["inputs"]["generated_image"] == [decoder_id, 0]
    assert by_type["SaveImage"][0][1]["inputs"]["images"] == [decoder_id, 0]
    assert patch_id == by_type["KSampler"][0][1]["inputs"]["model"][0]


def test_controlled_face_swap_evidence_is_complete_and_not_cherry_picked():
    fixture_dir = REPO_ROOT / "input" / "identity-benchmark"
    evidence_dir = REPO_ROOT / "output" / "agent" / "identity-model-benchmark"
    report_dir = REPO_ROOT / "user" / "default" / "identity_score_runs"

    for name in (
        "source_identity.png",
        "target_scene.png",
        "target_scene_v2.png",
    ):
        path = fixture_dir / name
        assert path.is_file()
        assert path.stat().st_size > 1_000_000

    cases = (
        (
            "reactor-baseline_00001_.png",
            "20260726-170340-reactor-proof-baseline.json",
            0.680509,
        ),
        (
            "reactor-baseline_00002_.png",
            "20260726-170604-reactor-proof-baseline.json",
            0.812342,
        ),
        (
            "reactor-gfpgan_00001_.png",
            "20260726-170739-reactor-proof-gfpgan.json",
            0.780879,
        ),
    )
    for image_name, report_name, expected_similarity in cases:
        image_path = evidence_dir / image_name
        report_path = report_dir / report_name
        assert image_path.is_file()
        assert image_path.stat().st_size > 1_000_000
        report = json.loads(report_path.read_text(encoding="utf-8"))
        identity = report["identity_report"]["source_identity"]
        assert identity["same_identity"] is True
        assert identity["same_identity_threshold"] == pytest.approx(0.363)
        assert identity["cosine_similarity"] == pytest.approx(
            expected_similarity
        )
