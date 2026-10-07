import json
import subprocess
from pathlib import Path

import pytest

from custom_nodes.comfyui_random_reference_source.nodes import ReferencePromptCompose


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).resolve().parents[1] / "web" / "prompt_preview.js"


def preview(graph):
    code = """
const fs = require('fs'), vm = require('vm');
const context = {};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8').replace(/^export /gm, ''), context);
process.stdout.write(JSON.stringify(context.buildCombinedPromptPreview(JSON.parse(fs.readFileSync(0, 'utf8')))));
"""
    result = subprocess.run(["node", "-e", code, str(SCRIPT)], input=json.dumps(graph),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("enabled", [(False, False, False, False), (True, True, True, True), (False, True, False, True)])
def test_live_preview_matches_backend_composer_for_all_reference_lanes(enabled):
    # A self-contained graph keeps package checks independent of owner workflows.
    graph = {str(index): {"class_type": "RandomReferenceImageSource", "inputs": {}}
             for index in range(1, 6)}
    graph.update({str(index): {"class_type": "PrimitiveBoolean", "inputs": {}}
                  for index in [6, 25, 32, 39]})
    graph["65"] = {"class_type": "ReferencePromptCompose", "inputs": {
        "text": "edit instruction", "main": ["1", 5], "identity": ["2", 5],
        "aux1": ["3", 5], "aux2": ["4", 5], "aux3": ["5", 5],
        "use_identity": ["6", 0], "use_aux1": ["25", 0],
        "use_aux2": ["32", 0], "use_aux3": ["39", 0]}}
    texts = ["main identity", "face detail", "clothing", "setting", "style"]
    for index, text in enumerate(texts, 1):
        graph[str(index)]["inputs"]["favorite_prompt"] = text
    for index, active in zip([6, 25, 32, 39], enabled):
        graph[str(index)]["inputs"]["value"] = active
    result = preview(graph)[0]
    expected = ReferencePromptCompose().compose(graph["65"]["inputs"]["text"], *enabled,
        **dict(zip(["main", "identity", "aux1", "aux2", "aux3"], texts)))[0]
    assert result["text"] == expected
    assert [part["enabled"] for part in result["contributions"]] == [True, True, *enabled]


def test_preview_handles_subgraph_execution_ids_and_disabled_dynamic_inputs():
    graph = {
        "70:1": {"class_type": "RandomReferenceImageSource", "inputs": {"favorite_prompt": "hero, ", "prompt": " , daylight"}},
        "70:2": {"class_type": "UnknownTextGenerator", "inputs": {}},
        "70:3": {"class_type": "ReferencePromptCompose", "inputs": {
            "text": "instruction", "main": ["70:1", 5], "identity": ["70:2", 0],
            "use_identity": False, "use_aux1": False, "use_aux2": False, "use_aux3": False}},
    }
    assert preview(graph)[0]["text"] == "instruction\n\nhero, daylight"
    graph["70:3"]["inputs"]["use_identity"] = True
    result = preview(graph)[0]
    assert "requires execution" in result["error"]
    assert "text" not in result


def test_preview_reports_cycles_instead_of_fabricating_text():
    graph = {"1": {"class_type": "ReferencePromptCompose", "inputs": {
        "text": ["1", 0], "use_identity": False, "use_aux1": False, "use_aux2": False, "use_aux3": False}}}
    assert "cycle" in preview(graph)[0]["error"]


def test_preview_uses_reference_card_titles_for_general_image_editing():
    graph = {
        "1": {"class_type": "RandomReferenceImageSource", "_meta": {"title": "Image to edit"}, "inputs": {}},
        "2": {"class_type": "RandomReferenceImageSource", "_meta": {"title": "Optional reference 1"}, "inputs": {}},
        "3": {"class_type": "ReferencePromptCompose", "inputs": {
            "text": "edit", "main": ["1", 5], "identity": ["2", 5],
            "use_identity": False, "use_aux1": False, "use_aux2": False, "use_aux3": False}},
    }
    parts = preview(graph)[0]["contributions"]
    assert parts[1]["label"] == "Image to edit"
    assert parts[2]["label"] == "Optional reference 1"
