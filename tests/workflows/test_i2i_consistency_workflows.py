import json
import re
from collections import deque
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / "user" / "default" / "workflows" / "agent"
PLACEHOLDER = "wan_q4_placeholder.ppm"

MASKED_WORKFLOW = "35 - Klein 9B Masked Precision I2I.json"
PULID_WORKFLOW = "36 - Klein 9B PuLID Identity Lab.json"
QWEN_WORKFLOW = "37 - Qwen 2511 Q4KM Precision MultiRef.json"

WORKFLOW_SPECS = {
    MASKED_WORKFLOW: {
        "workflow_slug": "klein-9b-masked-precision-i2i",
        "version": 1,
        "target_model": "Flux2-Klein-9B",
    },
    PULID_WORKFLOW: {
        "workflow_slug": "klein-9b-pulid-identity-lab",
        "version": 1,
        "target_model": "Flux2-Klein-9B",
    },
    QWEN_WORKFLOW: {
        "workflow_slug": "qwen-2511-q4km-precision-multiref",
        "version": 1,
        "target_model": "Qwen-Image-Edit-2511-Q4_K_M.gguf",
    },
}

KLEIN_CONSISTENCY_LORA = (
    r"Flux\9b\1 ------ Helper\Flux2-Klein-9B-consistency-V2.safetensors"
)
QWEN_LIGHTNING_LORA = (
    r"Qwen\Qwen IE 2511"
    r"\Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors"
)

SAMPLER_TYPES = {"KSampler", "KSamplerAdvanced", "SamplerCustomAdvanced"}

# Positional widget serialization is node-schema-specific. Keep these positions
# explicit so a linked widget on an unrelated node cannot shift inferred indices.
WIDGET_POSITIONS = {
    "ApplyPuLIDFlux2": {"strength": 0},
    "BasicScheduler": {"steps": 1},
    "CFGGuider": {"cfg": 0},
    "CLIPLoader": {"clip_name": 0},
    "FluxGuidance": {"guidance": 0},
    "KSampler": {"steps": 2, "cfg": 3},
    "KSamplerAdvanced": {"steps": 3, "cfg": 4},
    "LoraLoaderModelOnly": {"lora_name": 0},
    "ImageCompositeMasked": {"resize_source": 2},
    "ModelSamplingAuraFlow": {"shift": 0},
    "PuLIDModelLoader": {"pulid_file": 0},
    "UnetLoaderGGUF": {"unet_name": 0},
    "VAELoader": {"vae_name": 0},
}


def load_workflow(name):
    path = WORKFLOW_DIR / name
    assert path.is_file(), f"missing workflow: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def nodes_of_type(workflow, node_type):
    return [node for node in workflow["nodes"] if node["type"] == node_type]


def node_of_type(workflow, node_type, *, title=None):
    matches = nodes_of_type(workflow, node_type)
    if title is not None:
        matches = [node for node in matches if node.get("title") == title]
    assert len(matches) == 1, (
        f"expected one {node_type!r} ({title or 'any title'}), found {len(matches)}"
    )
    return matches[0]


def input_slot(node, name):
    matches = [
        index for index, item in enumerate(node.get("inputs", ())) if item["name"] == name
    ]
    assert len(matches) == 1, (
        f"expected one input {name!r} on node {node['id']!r}, found {len(matches)}"
    )
    return matches[0]


def has_link(workflow, source, source_slot, target, target_input):
    target_slot = input_slot(target, target_input)
    return any(
        link[1] == source["id"]
        and link[2] == source_slot
        and link[3] == target["id"]
        and link[4] == target_slot
        for link in workflow["links"]
    )


def source_for_input(workflow, target, target_input):
    target_slot = input_slot(target, target_input)
    link_id = target["inputs"][target_slot].get("link")
    assert link_id is not None, (
        f"input {target_input!r} on node {target['id']!r} is not linked"
    )
    links = [link for link in workflow["links"] if link[0] == link_id]
    assert len(links) == 1, f"expected exactly one link record for {link_id!r}"
    link = links[0]
    assert link[3:5] == [target["id"], target_slot], (
        f"link {link_id!r} does not reciprocate target node/slot"
    )
    source = next(
        (node for node in workflow["nodes"] if node["id"] == link[1]),
        None,
    )
    assert source is not None, f"link {link_id!r} has missing source {link[1]!r}"
    return source, link[2]


def assert_input_from(
    workflow,
    target,
    target_input,
    source,
    source_slot=0,
):
    actual_source, actual_slot = source_for_input(workflow, target, target_input)
    assert (actual_source["id"], actual_slot) == (source["id"], source_slot), (
        f"{target['id']}.{target_input} must come from "
        f"{source['id']}[{source_slot}], got {actual_source['id']}[{actual_slot}]"
    )


def linked_targets(workflow, source, source_slot=None):
    nodes = {node["id"]: node for node in workflow["nodes"]}
    return [
        nodes[link[3]]
        for link in workflow["links"]
        if link[1] == source["id"]
        and (source_slot is None or link[2] == source_slot)
    ]


def widget_value(node, widget_name):
    values = node.get("widgets_values", ())
    if isinstance(values, dict):
        assert widget_name in values, (
            f"missing named widget {widget_name!r} on node {node['id']!r}"
        )
        return values[widget_name]

    positions = WIDGET_POSITIONS.get(node["type"], {})
    assert widget_name in positions, (
        f"no explicit {node['type']!r} widget position for {widget_name!r}"
    )
    position = positions[widget_name]
    assert position < len(values), (
        f"missing widget value {widget_name!r} at position {position} "
        f"on node {node['id']!r}"
    )
    return values[position]


def assert_active(*nodes):
    for node in nodes:
        assert node.get("mode", 0) == 0, (
            f"required active node {node['id']} ({node['type']}) is not active"
        )


def assert_linked_inputs_active(workflow, *nodes, allow_bypassed=()):
    allowed_ids = {node["id"] for node in allow_bypassed}
    for node in nodes:
        for item in node.get("inputs", ()):
            if item.get("link") is None:
                continue
            source, _ = source_for_input(workflow, node, item["name"])
            if source["id"] not in allowed_ids:
                assert_active(source)


def assert_dormant_qwen_sampler_is_runnable(
    workflow,
    sampler,
    qwen_lora,
    conditioners,
):
    input_names = {item["name"] for item in sampler.get("inputs", ())}
    if sampler["type"] in {"KSampler", "KSamplerAdvanced"}:
        required = {"model", "positive", "latent_image"}
        assert required <= input_names
        if "negative" in input_names:
            required.add("negative")
        for input_name in required:
            source_for_input(workflow, sampler, input_name)
        model_source, _ = source_for_input(workflow, sampler, "model")
        positive_source, _ = source_for_input(workflow, sampler, "positive")
    else:
        required = {"noise", "guider", "sampler", "sigmas", "latent_image"}
        assert required <= input_names
        for input_name in required:
            source_for_input(workflow, sampler, input_name)

        guider, _ = source_for_input(workflow, sampler, "guider")
        guider_inputs = {item["name"] for item in guider.get("inputs", ())}
        assert "model" in guider_inputs
        positive_input = (
            "positive"
            if "positive" in guider_inputs
            else "conditioning"
        )
        assert positive_input in guider_inputs
        required_guider_inputs = {"model", positive_input}
        if "negative" in guider_inputs:
            required_guider_inputs.add("negative")
        for input_name in required_guider_inputs:
            source_for_input(workflow, guider, input_name)
        model_source, _ = source_for_input(workflow, guider, "model")
        positive_source, _ = source_for_input(
            workflow,
            guider,
            positive_input,
        )

        sigmas_source, _ = source_for_input(workflow, sampler, "sigmas")
        if any(
            item["name"] == "model"
            for item in sigmas_source.get("inputs", ())
        ):
            scheduler_model, _ = source_for_input(
                workflow,
                sigmas_source,
                "model",
            )
            assert qwen_lora["id"] == scheduler_model["id"] or path_exists(
                workflow,
                qwen_lora,
                scheduler_model,
            )

    assert qwen_lora["id"] == model_source["id"] or path_exists(
        workflow,
        qwen_lora,
        model_source,
    )
    assert any(
        conditioner["id"] == positive_source["id"]
        or path_exists(workflow, conditioner, positive_source)
        for conditioner in conditioners
    ), "dormant sampler positive conditioning must come from optional Qwen edit"


def path_exists(workflow, source, target, *, allowed_modes=frozenset({0, 4})):
    if source["id"] == target["id"]:
        return True

    nodes = {node["id"]: node for node in workflow["nodes"]}
    adjacency = {}
    for link in workflow["links"]:
        adjacency.setdefault(link[1], set()).add(link[3])

    pending = deque([source["id"]])
    visited = {source["id"]}
    while pending:
        source_id = pending.popleft()
        for target_id in adjacency.get(source_id, ()):
            if target_id == target["id"]:
                return True
            node = nodes[target_id]
            if (
                target_id not in visited
                and node.get("mode", 0) in allowed_modes
            ):
                visited.add(target_id)
                pending.append(target_id)
    return False


def active_path_exists(workflow, source, target):
    return path_exists(workflow, source, target, allowed_modes=frozenset({0}))


def configured_sampler_steps(workflow, sampler):
    if sampler["type"] in {"KSampler", "KSamplerAdvanced"}:
        return widget_value(sampler, "steps")

    schedulers = [
        scheduler
        for scheduler in nodes_of_type(workflow, "BasicScheduler")
        if scheduler.get("mode", 0) == sampler.get("mode", 0)
        and path_exists(workflow, scheduler, sampler)
    ]
    assert len(schedulers) == 1, (
        f"expected one scheduler for sampler {sampler['id']}, found {len(schedulers)}"
    )
    return widget_value(schedulers[0], "steps")


def sampler_model_source(workflow, sampler):
    if sampler["type"] in {"KSampler", "KSamplerAdvanced"}:
        return source_for_input(workflow, sampler, "model")[0]

    guider = source_for_input(workflow, sampler, "guider")[0]
    return source_for_input(workflow, guider, "model")[0]


def qwen_official_sampling_branches(workflow):
    unet = node_of_type(workflow, "UnetLoaderGGUF")
    lora = node_of_type(workflow, "LoraLoaderModelOnly")
    assert widget_value(lora, "lora_name") == QWEN_LIGHTNING_LORA
    assert_input_from(workflow, lora, "model", unet)
    assert lora.get("mode", 0) == 4

    active_patches = [
        node
        for node in nodes_of_type(workflow, "ModelSamplingAuraFlow")
        if node.get("mode", 0) == 0
        and widget_value(node, "shift") == pytest.approx(3.1)
    ]
    dormant_patches = [
        node
        for node in nodes_of_type(workflow, "ModelSamplingAuraFlow")
        if node.get("mode", 0) == 4
        and widget_value(node, "shift") == pytest.approx(3.1)
    ]
    assert len(active_patches) == 1
    assert len(dormant_patches) == 1
    active_patch = active_patches[0]
    dormant_patch = dormant_patches[0]
    assert active_patch["id"] != dormant_patch["id"]
    assert_input_from(workflow, active_patch, "model", unet)
    assert_input_from(workflow, dormant_patch, "model", lora)

    active_samplers_for_patch = [
        sampler
        for sampler in active_samplers(workflow)
        if configured_sampler_steps(workflow, sampler) == 28
        and (
            sampler_model_source(workflow, sampler)["id"] == active_patch["id"]
            or path_exists(
                workflow,
                active_patch,
                sampler_model_source(workflow, sampler),
            )
        )
    ]
    assert len(active_samplers_for_patch) == 1
    active_sampler = active_samplers_for_patch[0]
    assert not path_exists(workflow, lora, active_sampler)

    dormant_samplers_for_patch = [
        sampler
        for sampler in workflow["nodes"]
        if sampler["type"] in SAMPLER_TYPES
        and sampler.get("mode", 0) == 4
        and configured_sampler_steps(workflow, sampler) == 4
        and (
            sampler_model_source(workflow, sampler)["id"] == dormant_patch["id"]
            or path_exists(
                workflow,
                dormant_patch,
                sampler_model_source(workflow, sampler),
            )
        )
    ]
    assert len(dormant_samplers_for_patch) == 1
    dormant_sampler = dormant_samplers_for_patch[0]
    assert path_exists(workflow, lora, dormant_sampler)
    assert dormant_sampler["id"] != active_sampler["id"]
    return active_patch, active_sampler, dormant_patch, dormant_sampler


def notes_text(workflow):
    return "\n".join(
        str(value)
        for note in nodes_of_type(workflow, "MarkdownNote")
        for value in note.get("widgets_values", ())
    ).casefold()


def active_samplers(workflow):
    return [
        node
        for node in workflow["nodes"]
        if node["type"] in SAMPLER_TYPES and node.get("mode", 0) == 0
    ]


def title_contains(node, *words):
    title = node.get("title", "").casefold()
    return all(word.casefold() in title for word in words)


def assert_link_integrity(workflow):
    nodes = workflow["nodes"]
    node_ids = [node["id"] for node in nodes]
    assert len(node_ids) == len(set(node_ids)), "node IDs must be unique"
    nodes_by_id = {node["id"]: node for node in nodes}

    links = workflow["links"]
    link_ids = [link[0] for link in links]
    assert len(link_ids) == len(set(link_ids)), "link IDs must be unique"
    links_by_id = {link[0]: link for link in links}

    for link in links:
        assert len(link) >= 5, f"malformed link: {link!r}"
        link_id, source_id, source_slot, target_id, target_slot = link[:5]
        assert source_id in nodes_by_id, f"link {link_id} has missing source {source_id}"
        assert target_id in nodes_by_id, f"link {link_id} has missing target {target_id}"

        source = nodes_by_id[source_id]
        target = nodes_by_id[target_id]
        assert 0 <= source_slot < len(source.get("outputs", ())), (
            f"link {link_id} has invalid source slot {source_slot}"
        )
        assert 0 <= target_slot < len(target.get("inputs", ())), (
            f"link {link_id} has invalid target slot {target_slot}"
        )
        assert link_id in (source["outputs"][source_slot].get("links") or ()), (
            f"link {link_id} is absent from its exact source output"
        )
        assert target["inputs"][target_slot].get("link") == link_id, (
            f"link {link_id} is absent from its exact target input"
        )

    for node in nodes:
        for source_slot, output in enumerate(node.get("outputs", ())):
            output_links = output.get("links") or ()
            assert len(output_links) == len(set(output_links)), (
                f"node {node['id']} output {source_slot} has duplicate link IDs"
            )
            for link_id in output_links:
                assert link_id in links_by_id, (
                    f"node {node['id']} output references missing link {link_id}"
                )
                link = links_by_id[link_id]
                assert link[1:3] == [node["id"], source_slot], (
                    f"output link {link_id} does not reciprocate node/slot "
                    f"{node['id']}/{source_slot}"
                )
        for target_slot, item in enumerate(node.get("inputs", ())):
            link_id = item.get("link")
            if link_id is not None:
                assert link_id in links_by_id, (
                    f"node {node['id']} input references missing link {link_id}"
                )
                link = links_by_id[link_id]
                assert link[3:5] == [node["id"], target_slot], (
                    f"input link {link_id} does not reciprocate node/slot "
                    f"{node['id']}/{target_slot}"
                )


def assert_optional_lora(
    workflow,
    expected_name,
    samplers,
    *,
    require_documented_bypass=False,
):
    lora = node_of_type(workflow, "LoraLoaderModelOnly")
    assert widget_value(lora, "lora_name") == expected_name
    assert lora.get("mode", 0) in {0, 4}, "LoRA must be active or bypassed"

    base_model, _ = source_for_input(workflow, lora, "model")
    assert base_model.get("mode", 0) == 0
    assert any(active_path_exists(workflow, lora, sampler) for sampler in samplers), (
        "LoRA output must remain on the sampler model path"
    )

    if lora.get("mode", 0) == 4 and require_documented_bypass:
        text = notes_text(workflow)
        assert "lora" in text
        assert any(term in text for term in ("optional", "bypass", "enable"))
    return lora, base_model


@pytest.mark.parametrize(("name", "expected"), WORKFLOW_SPECS.items())
def test_workflow_declares_stable_versioned_suite_identity(name, expected):
    workflow = load_workflow(name)
    metadata = workflow.get("extra", {}).get("i2i_consistency_suite")
    assert metadata == expected

    assert workflow["last_node_id"] == max(node["id"] for node in workflow["nodes"])
    assert workflow["last_link_id"] == max(link[0] for link in workflow["links"])


@pytest.mark.parametrize("name", WORKFLOW_SPECS)
def test_workflow_links_have_unique_exactly_reciprocal_endpoints(name):
    assert_link_integrity(load_workflow(name))


def test_image_loaders_use_the_stable_local_placeholder():
    assert (REPO_ROOT / "input" / PLACEHOLDER).is_file()
    for name in WORKFLOW_SPECS:
        image_nodes = nodes_of_type(load_workflow(name), "LoadImage")
        assert image_nodes, f"{name} must contain at least one LoadImage node"
        assert all(node["widgets_values"][0] == PLACEHOLDER for node in image_nodes)


def test_masked_klein_graph_is_one_coherent_edit_decode_composite_path():
    workflow = load_workflow(MASKED_WORKFLOW)
    original = node_of_type(workflow, "LoadImage")
    grow_mask = node_of_type(workflow, "GrowMask")
    latent_mask_nodes = nodes_of_type(workflow, "VAEEncodeForInpaint")
    latent_mask_nodes += nodes_of_type(workflow, "SetLatentNoiseMask")
    assert len(latent_mask_nodes) == 1, (
        "masked workflow needs one VAEEncodeForInpaint or SetLatentNoiseMask"
    )
    edit_latent = latent_mask_nodes[0]
    lora = node_of_type(workflow, "LoraLoaderModelOnly")

    assert_input_from(workflow, grow_mask, "mask", original, 1)
    assert_input_from(workflow, edit_latent, "mask", grow_mask)
    source_encoder = None
    if edit_latent["type"] == "VAEEncodeForInpaint":
        assert_input_from(workflow, edit_latent, "pixels", original)
    else:
        source_encoder, _ = source_for_input(workflow, edit_latent, "samples")
        assert source_encoder["type"] in {"VAEEncode", "VAEEncodeForInpaint"}
        assert_input_from(workflow, source_encoder, "pixels", original)

    samplers = [
        sampler
        for sampler in active_samplers(workflow)
        if has_link(workflow, edit_latent, 0, sampler, "latent_image")
        and active_path_exists(workflow, lora, sampler)
    ]
    assert len(samplers) == 1, (
        "one active sampler must consume both masked latent and LoRA model path"
    )
    sampler = samplers[0]
    assert_input_from(workflow, sampler, "latent_image", edit_latent)

    decoders = [
        decoder
        for decoder in nodes_of_type(workflow, "VAEDecode")
        if decoder.get("mode", 0) == 0
        and has_link(workflow, sampler, 0, decoder, "samples")
    ]
    assert len(decoders) == 1
    decoder = decoders[0]
    assert_input_from(workflow, decoder, "samples", sampler)
    vae_consumer = (
        edit_latent
        if edit_latent["type"] == "VAEEncodeForInpaint"
        else source_encoder
    )
    vae, _ = source_for_input(workflow, vae_consumer, "vae")
    assert_input_from(workflow, decoder, "vae", vae)

    composite = node_of_type(workflow, "ImageCompositeMasked")
    assert_input_from(workflow, composite, "source", decoder)
    assert_input_from(workflow, composite, "destination", original)
    assert_input_from(workflow, composite, "mask", grow_mask)

    output = node_of_type(workflow, "SaveImage")
    assert_input_from(workflow, output, "images", composite)
    required_active = [
        original,
        grow_mask,
        edit_latent,
        sampler,
        decoder,
        vae,
        composite,
        output,
    ]
    if source_encoder is not None:
        required_active.append(source_encoder)
    assert_active(*required_active)
    assert_linked_inputs_active(
        workflow,
        edit_latent,
        sampler,
        decoder,
        composite,
        output,
        allow_bypassed=(lora,),
    )


def test_masked_klein_model_path_and_identity_audit_are_wired():
    workflow = load_workflow(MASKED_WORKFLOW)
    edit_latent = (
        nodes_of_type(workflow, "VAEEncodeForInpaint")
        + nodes_of_type(workflow, "SetLatentNoiseMask")
    )
    assert len(edit_latent) == 1
    lora = node_of_type(workflow, "LoraLoaderModelOnly")
    samplers = [
        sampler
        for sampler in active_samplers(workflow)
        if has_link(workflow, edit_latent[0], 0, sampler, "latent_image")
        and active_path_exists(workflow, lora, sampler)
    ]
    assert len(samplers) == 1
    assert_optional_lora(
        workflow,
        KLEIN_CONSISTENCY_LORA,
        samplers,
        require_documented_bypass=True,
    )

    original = node_of_type(workflow, "LoadImage")
    composite = node_of_type(workflow, "ImageCompositeMasked")
    scorer = node_of_type(workflow, "OpenCVIdentityScore")
    assert_input_from(workflow, scorer, "reference_image", original)
    assert_input_from(workflow, scorer, "generated_image", composite)
    assert_active(original, composite, scorer, *samplers)


def test_pulid_graph_has_distinct_scene_and_face_identity_inputs():
    workflow = load_workflow(PULID_WORKFLOW)
    image_nodes = nodes_of_type(workflow, "LoadImage")
    assert len(image_nodes) == 2
    assert len(
        [node for node in image_nodes if title_contains(node, "scene", "reference")]
    ) == 1
    assert len(
        [node for node in image_nodes if title_contains(node, "face", "identity")]
    ) == 1


def test_pulid_components_apply_face_identity_on_the_sampled_model_path():
    workflow = load_workflow(PULID_WORKFLOW)
    scene_matches = [
        node
        for node in nodes_of_type(workflow, "LoadImage")
        if title_contains(node, "scene", "reference")
    ]
    face_matches = [
        node
        for node in nodes_of_type(workflow, "LoadImage")
        if title_contains(node, "face", "identity")
    ]
    assert len(scene_matches) == 1
    assert len(face_matches) == 1
    scene = scene_matches[0]
    face = face_matches[0]
    insightface = node_of_type(workflow, "PuLIDInsightFaceLoader")
    eva_clip = node_of_type(workflow, "PuLIDEVACLIPLoader")
    pulid_loader = node_of_type(workflow, "PuLIDModelLoader")
    apply_pulid = node_of_type(workflow, "ApplyPuLIDFlux2")

    assert widget_value(pulid_loader, "pulid_file") == (
        "pulid_flux2_klein_v2.safetensors"
    )
    assert widget_value(apply_pulid, "strength") == pytest.approx(1.4)
    assert_input_from(workflow, apply_pulid, "image", face)
    assert_input_from(workflow, apply_pulid, "face_analysis", insightface)
    assert_input_from(workflow, apply_pulid, "eva_clip", eva_clip)
    assert_input_from(workflow, apply_pulid, "pulid_model", pulid_loader)

    base_model, _ = source_for_input(workflow, apply_pulid, "model")
    assert base_model.get("mode", 0) == 0

    reference_nodes = [
        node
        for node in workflow["nodes"]
        if node["type"]
        in {
            "ReferenceLatent",
            "FluxKontextMultiReferenceLatentMethod",
            "TextEncodeQwenImageEdit",
            "TextEncodeQwenImageEditPlus",
        }
        and node.get("mode", 0) == 0
        and any(
            active_path_exists(workflow, first_consumer, node)
            for first_consumer in linked_targets(workflow, scene, 0)
            if first_consumer.get("mode", 0) == 0
        )
    ]
    assert reference_nodes, (
        "scene/reference image must feed active edit conditioning/reference latents"
    )

    samplers = [
        sampler
        for sampler in active_samplers(workflow)
        if active_path_exists(workflow, apply_pulid, sampler)
        and any(
            active_path_exists(workflow, reference_node, sampler)
            for reference_node in reference_nodes
        )
    ]
    assert len(samplers) == 1, (
        "one sampler must consume both PuLID model and scene reference conditioning"
    )
    sampler = samplers[0]

    decoders = [
        decoder
        for decoder in nodes_of_type(workflow, "VAEDecode")
        if decoder.get("mode", 0) == 0
        and has_link(workflow, sampler, 0, decoder, "samples")
    ]
    assert len(decoders) == 1
    decoder = decoders[0]
    assert_input_from(workflow, decoder, "samples", sampler)

    scorer = node_of_type(workflow, "OpenCVIdentityScore")
    assert_input_from(workflow, scorer, "reference_image", face)
    assert_input_from(workflow, scorer, "generated_image", decoder)

    output = node_of_type(workflow, "SaveImage")
    assert_input_from(workflow, output, "images", decoder)
    assert_active(
        scene,
        face,
        insightface,
        eva_clip,
        pulid_loader,
        apply_pulid,
        base_model,
        *reference_nodes,
        sampler,
        decoder,
        scorer,
        output,
    )
    assert_linked_inputs_active(
        workflow,
        apply_pulid,
        sampler,
        decoder,
        scorer,
        output,
    )


def test_pulid_identity_score_and_limitations_are_explicit():
    workflow = load_workflow(PULID_WORKFLOW)
    text = notes_text(workflow)
    assert "experimental" in text
    assert "face-only" in text or "face identity" in text
    assert "body consistency" in text
    assert any(term in text for term in ("unsupported", "not supported", "roadmap"))


def test_qwen_graph_uses_the_precision_q4km_model_stack():
    workflow = load_workflow(QWEN_WORKFLOW)
    unet = node_of_type(workflow, "UnetLoaderGGUF")
    clip = node_of_type(workflow, "CLIPLoader")
    vae = node_of_type(workflow, "VAELoader")

    assert widget_value(unet, "unet_name") == (
        r"Qwen\Qwen-Image-Edit-2511-Q4_K_M.gguf"
    )
    assert widget_value(clip, "clip_name") == (
        r"Qwen\qwen_2.5_vl_7b_fp8_scaled.safetensors"
    )
    assert widget_value(vae, "vae_name") == "qwen_image_vae.safetensors"


def test_qwen_primary_is_consumed_and_optional_references_are_disabled():
    workflow = load_workflow(QWEN_WORKFLOW)
    qwen_lora = node_of_type(workflow, "LoraLoaderModelOnly")
    qwen_vae = node_of_type(workflow, "VAELoader")
    image_nodes = nodes_of_type(workflow, "LoadImage")
    assert len(image_nodes) == 3

    primary = [node for node in image_nodes if title_contains(node, "primary")]
    assert len(primary) == 1
    primary = primary[0]
    assert primary.get("mode", 0) == 0

    conditioning_nodes = [
        node
        for node in workflow["nodes"]
        if node["type"] in {"TextEncodeQwenImageEdit", "TextEncodeQwenImageEditPlus"}
        and node.get("mode", 0) == 0
    ]
    assert len(conditioning_nodes) == 1
    conditioning = conditioning_nodes[0]
    image_input = (
        "image1"
        if conditioning["type"] == "TextEncodeQwenImageEditPlus"
        else "image"
    )
    assert has_link(workflow, primary, 0, conditioning, image_input)

    optional = [node for node in image_nodes if node["id"] != primary["id"]]
    assert all(node.get("mode", 0) == 4 for node in optional)
    nodes_by_id = {node["id"]: node for node in workflow["nodes"]}
    optional_conditioners = [
        node
        for node in nodes_of_type(workflow, "TextEncodeQwenImageEditPlus")
        if node.get("mode", 0) == 4
    ]
    assert optional_conditioners, (
        "optional references need a bypassed Qwen multi-reference conditioner"
    )
    for image_node in optional:
        outgoing = linked_targets(workflow, image_node, 0)
        assert outgoing, (
            f"optional reference image output {image_node['id']} must not be an orphan"
        )
        assert any(
            path_exists(workflow, first_consumer, conditioner)
            for first_consumer in outgoing
            for conditioner in optional_conditioners
        ), (
            f"optional reference {image_node['id']} must feed the bypassed "
            "Qwen multi-reference conditioning path"
        )
        route_conditioners = [
            conditioner
            for conditioner in optional_conditioners
            if any(
                path_exists(workflow, first_consumer, conditioner)
                for first_consumer in outgoing
            )
        ]
        dormant_samplers = [
            sampler
            for sampler in workflow["nodes"]
            if sampler["type"] in SAMPLER_TYPES
            and sampler.get("mode", 0) == 4
            and any(
                path_exists(workflow, conditioner, sampler)
                for conditioner in route_conditioners
            )
        ]
        assert len(dormant_samplers) == 1, (
            f"optional reference {image_node['id']} needs one exact "
            "bypassed sampler route"
        )
        dormant_sampler = dormant_samplers[0]
        assert_dormant_qwen_sampler_is_runnable(
            workflow,
            dormant_sampler,
            qwen_lora,
            route_conditioners,
        )
        dormant_decoders = [
            decoder
            for decoder in nodes_of_type(workflow, "VAEDecode")
            if decoder.get("mode", 0) == 4
            and has_link(workflow, dormant_sampler, 0, decoder, "samples")
        ]
        assert len(dormant_decoders) == 1, (
            f"optional reference {image_node['id']} needs one exact "
            "bypassed decoder route"
        )
        dormant_decoder = dormant_decoders[0]
        assert_input_from(
            workflow,
            dormant_decoder,
            "samples",
            dormant_sampler,
        )
        assert_input_from(workflow, dormant_decoder, "vae", qwen_vae)
        dormant_previews = [
            preview
            for preview in nodes_of_type(workflow, "PreviewImage")
            if preview.get("mode", 0) == 4
            and path_exists(workflow, dormant_decoder, preview)
        ]
        assert dormant_previews, (
            f"optional reference {image_node['id']} needs a bypassed output preview"
        )

        pending = deque(node["id"] for node in outgoing)
        visited = set()
        while pending:
            node_id = pending.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            target = nodes_by_id[node_id]
            assert target.get("mode", 0) != 0, (
                f"optional reference {image_node['id']} reaches active node {node_id}"
            )
            pending.extend(
                link[3] for link in workflow["links"] if link[1] == node_id
            )


def test_qwen_active_model_conditioning_and_accuracy_recipe_share_sampler():
    workflow = load_workflow(QWEN_WORKFLOW)
    unet = node_of_type(workflow, "UnetLoaderGGUF")
    clip = node_of_type(workflow, "CLIPLoader")
    vae = node_of_type(workflow, "VAELoader")
    lora = node_of_type(workflow, "LoraLoaderModelOnly")
    conditioning_matches = [
        node
        for node in workflow["nodes"]
        if node["type"] in {"TextEncodeQwenImageEdit", "TextEncodeQwenImageEditPlus"}
        and node.get("mode", 0) == 0
    ]
    assert len(conditioning_matches) == 1
    conditioning = conditioning_matches[0]
    assert_input_from(workflow, conditioning, "clip", clip)
    assert_input_from(workflow, conditioning, "vae", vae)

    assert widget_value(lora, "lora_name") == QWEN_LIGHTNING_LORA
    assert lora.get("mode", 0) == 4, "Lightning LoRA must default bypassed"
    assert_input_from(workflow, lora, "model", unet)

    active_patch, sampler, _, _ = qwen_official_sampling_branches(workflow)
    assert active_path_exists(workflow, conditioning, sampler)

    decoders = [
        decoder
        for decoder in nodes_of_type(workflow, "VAEDecode")
        if decoder.get("mode", 0) == 0
        and has_link(workflow, sampler, 0, decoder, "samples")
    ]
    assert len(decoders) == 1
    decoder = decoders[0]
    assert_input_from(workflow, decoder, "samples", sampler)
    assert_input_from(workflow, decoder, "vae", vae)
    output = node_of_type(workflow, "SaveImage")
    assert_input_from(workflow, output, "images", decoder)

    if sampler["type"] in {"KSampler", "KSamplerAdvanced"}:
        step_nodes = [sampler]
    else:
        step_nodes = [
            scheduler
            for scheduler in nodes_of_type(workflow, "BasicScheduler")
            if scheduler.get("mode", 0) == 0
            and active_path_exists(workflow, active_patch, scheduler)
            and active_path_exists(workflow, scheduler, sampler)
        ]
    assert step_nodes
    assert max(widget_value(node, "steps") for node in step_nodes) >= 20

    guidance_nodes = []
    if sampler["type"] in {"KSampler", "KSamplerAdvanced"}:
        guidance_nodes.append((sampler, "cfg"))
    for node_type, widget_name in (
        ("CFGGuider", "cfg"),
        ("FluxGuidance", "guidance"),
    ):
        guidance_nodes.extend(
            (node, widget_name)
            for node in nodes_of_type(workflow, node_type)
            if node.get("mode", 0) == 0
            and active_path_exists(workflow, conditioning, node)
            and active_path_exists(workflow, node, sampler)
        )
    assert any(
        2.5 <= widget_value(node, widget_name) <= 5.0
        for node, widget_name in guidance_nodes
    ), "active Qwen path needs CFG/guidance in the accuracy range 2.5-5.0"
    assert_active(
        unet,
        clip,
        vae,
        conditioning,
        sampler,
        decoder,
        output,
        *step_nodes,
        *(node for node, _ in guidance_nodes),
    )
    assert_linked_inputs_active(
        workflow,
        conditioning,
        sampler,
        decoder,
        output,
    )


def test_pulid_note_documents_numeric_conservative_and_strong_strengths():
    workflow = load_workflow(PULID_WORKFLOW)
    apply_pulid = node_of_type(workflow, "ApplyPuLIDFlux2")
    assert widget_value(apply_pulid, "strength") == pytest.approx(1.4)

    text = notes_text(workflow)
    assert "strength" in text
    sections = [
        section.strip()
        for section in re.split(r"(?<!\d)\.(?!\d)|[\n;]+", text)
        if section.strip()
    ]

    def values_near(label):
        values = []
        for section in sections:
            if label in section:
                values.extend(
                    float(value)
                    for value in re.findall(
                        r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])",
                        section,
                    )
                )
        return values

    conservative = values_near("conservative")
    strong = values_near("strong")
    assert conservative, "document a numeric conservative PuLID strength or range"
    assert strong, "document a numeric strong PuLID strength or range"
    assert max(strong) > max(conservative)

    default_is_explicit = re.search(
        r"(?:default|recommended)[^.\n]{0,60}\b1\.4\b"
        r"|\b1\.4\b[^.\n]{0,60}(?:default|recommended)",
        text,
    )
    default_is_conservative = min(conservative) <= 1.4 <= max(conservative)
    assert default_is_explicit or default_is_conservative


@pytest.mark.parametrize(
    ("name", "result_type"),
    (
        (MASKED_WORKFLOW, "ImageCompositeMasked"),
        (QWEN_WORKFLOW, "VAEDecode"),
    ),
)
def test_active_precision_result_has_an_active_preview(name, result_type):
    workflow = load_workflow(name)
    if result_type == "ImageCompositeMasked":
        result = node_of_type(workflow, result_type)
    else:
        active_decoders = [
            node
            for node in nodes_of_type(workflow, result_type)
            if node.get("mode", 0) == 0
        ]
        assert len(active_decoders) == 1
        result = active_decoders[0]

    previews = [
        preview
        for preview in nodes_of_type(workflow, "PreviewImage")
        if preview.get("mode", 0) == 0
        and has_link(workflow, result, 0, preview, "images")
    ]
    assert len(previews) == 1
    assert_input_from(workflow, previews[0], "images", result)


def test_qwen_has_distinct_four_step_dormant_lightning_route():
    workflow = load_workflow(QWEN_WORKFLOW)
    lora = node_of_type(workflow, "LoraLoaderModelOnly")
    assert widget_value(lora, "lora_name") == QWEN_LIGHTNING_LORA
    assert lora.get("mode", 0) == 4

    _, accuracy_sampler, _, dormant_sampler = qwen_official_sampling_branches(
        workflow
    )
    assert dormant_sampler["id"] != accuracy_sampler["id"]

    dormant_decoders = [
        decoder
        for decoder in nodes_of_type(workflow, "VAEDecode")
        if decoder.get("mode", 0) == 4
        and has_link(workflow, dormant_sampler, 0, decoder, "samples")
    ]
    assert len(dormant_decoders) == 1
    dormant_decoder = dormant_decoders[0]
    dormant_previews = [
        preview
        for preview in nodes_of_type(workflow, "PreviewImage")
        if preview.get("mode", 0) == 4
        and has_link(workflow, dormant_decoder, 0, preview, "images")
    ]
    assert len(dormant_previews) == 1


def test_qwen_official_31_sampling_patch_has_isolated_accuracy_and_lightning_paths():
    workflow = load_workflow(QWEN_WORKFLOW)
    active_patch, active_sampler, dormant_patch, dormant_sampler = (
        qwen_official_sampling_branches(workflow)
    )
    assert widget_value(active_patch, "shift") == pytest.approx(3.1)
    assert widget_value(dormant_patch, "shift") == pytest.approx(3.1)
    assert configured_sampler_steps(workflow, active_sampler) == 28
    assert configured_sampler_steps(workflow, dormant_sampler) == 4


def test_masked_composite_resizes_source_for_dimension_safe_restoration():
    workflow = load_workflow(MASKED_WORKFLOW)
    composite = node_of_type(workflow, "ImageCompositeMasked")
    assert widget_value(composite, "resize_source") is True
