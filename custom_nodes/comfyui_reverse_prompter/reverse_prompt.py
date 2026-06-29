from __future__ import annotations

import base64
import json
import math
import os
import urllib.error
import urllib.request
from collections import Counter
from io import BytesIO
from typing import Any

import numpy as np
import torch
from PIL import Image


DEFAULT_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5"
MAX_DATA_URL_LENGTH = 20_000_000


def build_reverse_prompt_instruction(mode: str = "detailed", extra_context: str = "") -> str:
    mode = (mode or "detailed").strip().lower()
    if mode == "concise":
        style = "Write a concise, high-signal prompt in one compact paragraph."
    elif mode == "tags":
        style = "Write comma-separated prompt tags, ordered from most important to least important."
    else:
        style = (
            "Write a detailed prompt that captures subject, composition, environment, style, "
            "lighting, camera/framing, color palette, texture, mood, and notable details."
        )

    context = f"\nUser intent: {extra_context.strip()}" if extra_context and extra_context.strip() else ""
    return (
        "Convert the image into a reusable image-generation prompt. "
        "Do not explain the image, do not mention that you are analyzing an image, and do not add alternatives. "
        f"{style} Return one prompt only.{context}"
    )


def image_tensor_to_data_url(image: torch.Tensor, max_pixels: int = 2048 * 2048) -> str:
    if image is None:
        raise ValueError("Image input is required.")

    tensor = image.detach().cpu()
    if tensor.ndim == 4:
        tensor = tensor[0]
    if tensor.ndim != 3 or tensor.shape[-1] not in (1, 3, 4):
        raise ValueError(f"Expected IMAGE tensor shaped [B,H,W,C] or [H,W,C], got {tuple(image.shape)}.")

    array = tensor.numpy()
    array = np.clip(array * 255.0, 0, 255).astype(np.uint8)
    if array.shape[-1] == 1:
        array = np.repeat(array, 3, axis=-1)

    pil_image = Image.fromarray(array).convert("RGB")
    pil_image = _downscale_image(pil_image, int(max_pixels or 0))
    buffer = BytesIO()
    pil_image.save(buffer, format="JPEG", quality=92, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def analyze_data_url(data_url: str) -> dict[str, Any]:
    mime_type, raw = decode_data_url(data_url)
    image = Image.open(BytesIO(raw))
    width, height = image.size
    rgba = image.convert("RGBA")
    sample = rgba.resize((72, 72), Image.Resampling.LANCZOS)

    palette: Counter[str] = Counter()
    luminance_values: list[float] = []
    brightness_total = 0.0
    saturation_total = 0.0
    opaque_count = 0
    transparent_count = 0

    for red, green, blue, alpha in sample.getdata():
        if alpha < 250:
            transparent_count += 1
        if alpha < 32:
            continue

        luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
        saturation = _rgb_saturation(red, green, blue)
        luminance_values.append(luminance)
        brightness_total += luminance
        saturation_total += saturation
        palette[_quantize_hex(red, green, blue)] += 1
        opaque_count += 1

    count = max(opaque_count, 1)
    average_brightness = brightness_total / count
    contrast = math.sqrt(sum((value - average_brightness) ** 2 for value in luminance_values) / count)

    return {
        "width": width,
        "height": height,
        "mime_type": mime_type,
        "size_bytes": len(raw),
        "aspect": _aspect_label(width, height),
        "has_alpha": transparent_count > 72 * 72 * 0.01,
        "average_brightness": average_brightness,
        "average_saturation": saturation_total / count,
        "contrast": contrast,
        "palette": [color for color, _count in palette.most_common(5)],
    }


def decode_data_url(data_url: str) -> tuple[str, bytes]:
    if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
        raise ValueError("Expected an image data URL.")
    if len(data_url) > MAX_DATA_URL_LENGTH:
        raise ValueError("Image data URL is too large.")

    header, encoded = data_url.split(",", 1)
    if ";base64" not in header:
        raise ValueError("Image data URL must be base64 encoded.")
    mime_type = header[5:].split(";", 1)[0]
    return mime_type, base64.b64decode(encoded, validate=True)


def build_fallback_prompt(analysis: dict[str, Any]) -> str:
    width = int(analysis.get("width") or 0)
    height = int(analysis.get("height") or 0)
    aspect = analysis.get("aspect") or _aspect_label(width, height)
    palette = ", ".join(analysis.get("palette") or [])
    brightness = _brightness_label(float(analysis.get("average_brightness") or 0))
    contrast = _contrast_label(float(analysis.get("contrast") or 0))
    saturation = _saturation_label(float(analysis.get("average_saturation") or 0))
    alpha = "with transparent areas" if analysis.get("has_alpha") else "opaque background"

    return (
        f"{aspect} image, {width}x{height}, {alpha}, {brightness}, {contrast}, {saturation}, "
        f"dominant palette {palette or 'unknown colors'}, clean image-generation prompt describing the visible subject, "
        "composition, lighting, material detail, mood, and environment."
    )


def generate_prompt_from_data_url(
    image_data_url: str,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    detail: str = "high",
    mode: str = "detailed",
    extra_context: str = "",
    timeout: int = 90,
    fallback_on_error: bool = True,
    use_env_api_key: bool = False,
) -> dict[str, Any]:
    analysis = analyze_data_url(image_data_url)
    local_prompt = build_fallback_prompt(analysis)
    resolved_key = (api_key or "").strip()
    if not resolved_key and use_env_api_key:
        resolved_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    metadata = {
        "source": "local",
        "model": model,
        "endpoint": endpoint,
        "analysis": analysis,
    }

    if not resolved_key:
        return {"prompt": local_prompt, "metadata": metadata}

    instruction = build_reverse_prompt_instruction(mode=mode, extra_context=extra_context)
    try:
        prompt = call_openai_responses_api(
            api_key=resolved_key,
            image_data_url=image_data_url,
            model=model or DEFAULT_MODEL,
            endpoint=endpoint or DEFAULT_ENDPOINT,
            detail=detail or "high",
            instruction=instruction,
            timeout=timeout,
        )
    except Exception as exc:
        if not fallback_on_error:
            raise
        metadata["source"] = "local_after_error"
        metadata["error"] = str(exc)
        return {"prompt": local_prompt, "metadata": metadata}

    metadata["source"] = "openai"
    return {"prompt": prompt, "metadata": metadata}


def call_openai_responses_api(
    api_key: str,
    image_data_url: str,
    model: str,
    endpoint: str,
    detail: str,
    instruction: str,
    timeout: int = 90,
) -> str:
    payload = {
        "model": model,
        "store": False,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": instruction},
                    {"type": "input_image", "image_url": image_data_url, "detail": detail},
                ],
            }
        ],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout or 90))) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(_http_error_message(body) or f"OpenAI request failed with HTTP {exc.code}.") from exc

    text = extract_response_text(response_payload).strip()
    if not text:
        raise RuntimeError("OpenAI response did not include output text.")
    return text


def extract_response_text(payload: dict[str, Any]) -> str:
    top_level = payload.get("output_text")
    if isinstance(top_level, str) and top_level.strip():
        return top_level

    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return str(content["text"])

    return ""


def _http_error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error or "").strip()


def _downscale_image(image: Image.Image, max_pixels: int) -> Image.Image:
    if max_pixels <= 0 or image.width * image.height <= max_pixels:
        return image
    scale = math.sqrt(max_pixels / float(image.width * image.height))
    next_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(next_size, Image.Resampling.LANCZOS)


def _aspect_label(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "image"
    ratio = width / height
    if 0.95 <= ratio <= 1.05:
        orientation = "square"
    elif ratio > 1:
        orientation = "wide"
    else:
        orientation = "tall"

    divisor = math.gcd(width, height)
    reduced_width = width // divisor
    reduced_height = height // divisor
    if reduced_width <= 32 and reduced_height <= 32:
        return f"{orientation} {reduced_width}:{reduced_height}"
    return orientation


def _rgb_saturation(red: int, green: int, blue: int) -> float:
    high = max(red, green, blue) / 255.0
    low = min(red, green, blue) / 255.0
    if high <= 0:
        return 0.0
    return (high - low) / high


def _quantize_hex(red: int, green: int, blue: int) -> str:
    def quantize(value: int) -> int:
        return max(0, min(255, round(value / 32) * 32))

    return f"#{quantize(red):02x}{quantize(green):02x}{quantize(blue):02x}"


def _brightness_label(value: float) -> str:
    if value >= 0.68:
        return "bright exposure"
    if value <= 0.32:
        return "low-key exposure"
    return "balanced exposure"


def _contrast_label(value: float) -> str:
    if value >= 0.28:
        return "high contrast"
    if value <= 0.08:
        return "soft contrast"
    return "moderate contrast"


def _saturation_label(value: float) -> str:
    if value >= 0.55:
        return "saturated color"
    if value <= 0.2:
        return "muted color"
    return "natural color"
