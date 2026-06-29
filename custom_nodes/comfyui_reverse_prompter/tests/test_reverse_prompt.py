import base64
import json
import sys
from io import BytesIO
from pathlib import Path

import torch
from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comfyui_reverse_prompter.reverse_prompt import (
    analyze_data_url,
    build_fallback_prompt,
    build_reverse_prompt_instruction,
    extract_response_text,
    generate_prompt_from_data_url,
    image_tensor_to_data_url,
)


def make_data_url(color=(240, 80, 40), size=(64, 32)):
    image = Image.new("RGB", size, color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def test_build_reverse_prompt_instruction_is_prompt_only():
    instruction = build_reverse_prompt_instruction(
        mode="detailed",
        extra_context="Make it useful for a Flux workflow.",
    )

    assert "reusable image-generation prompt" in instruction
    assert "one prompt only" in instruction.lower()
    assert "Flux workflow" in instruction
    assert "subject" in instruction.lower()
    assert "lighting" in instruction.lower()


def test_analyze_data_url_and_fallback_prompt_describe_image():
    analysis = analyze_data_url(make_data_url())
    prompt = build_fallback_prompt(analysis)

    assert analysis["width"] == 64
    assert analysis["height"] == 32
    assert analysis["mime_type"] == "image/png"
    assert analysis["palette"]
    assert "64x32" in prompt
    assert "wide 2:1" in prompt
    assert "palette" in prompt.lower()
    assert "undefined" not in prompt


def test_extract_response_text_supports_responses_api_shapes():
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "A detailed prompt."},
                ],
            }
        ]
    }

    assert extract_response_text(payload) == "A detailed prompt."
    assert extract_response_text({"output_text": "Top-level prompt."}) == "Top-level prompt."


def test_blank_key_uses_local_prompt_even_when_env_key_exists(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    result = generate_prompt_from_data_url(make_data_url(), api_key="")

    assert result["metadata"]["source"] == "local"


def test_image_tensor_to_data_url_uses_first_image_and_downscales():
    tensor = torch.zeros((2, 16, 32, 3), dtype=torch.float32)
    tensor[0, :, :, 0] = 1.0
    tensor[1, :, :, 1] = 1.0

    data_url = image_tensor_to_data_url(tensor, max_pixels=16 * 16)
    prefix, encoded = data_url.split(",", 1)
    decoded = Image.open(BytesIO(base64.b64decode(encoded)))

    assert prefix == "data:image/jpeg;base64"
    assert decoded.width * decoded.height <= 16 * 16
    assert decoded.getpixel((0, 0))[0] > decoded.getpixel((0, 0))[1]


def test_reverse_prompter_node_declares_image_to_string_contract(monkeypatch):
    import comfyui_reverse_prompter.nodes as nodes

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    input_types = nodes.ReversePrompter.INPUT_TYPES()

    assert input_types["required"]["image"] == ("IMAGE",)
    assert nodes.ReversePrompter.RETURN_TYPES == ("STRING", "STRING")
    assert json.loads(nodes.ReversePrompter().reverse_prompt(torch.zeros((1, 8, 8, 3)))[1])["source"] == "local"
