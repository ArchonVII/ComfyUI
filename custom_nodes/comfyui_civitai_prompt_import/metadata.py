from __future__ import annotations

import html
import json
import os
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import asdict, dataclass, field
from io import BytesIO
from typing import Any, Iterable


MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
USER_AGENT = "ComfyUI Civitai prompt metadata import/0.1"


@dataclass
class CivitaiSetting:
    key: str
    value: str


@dataclass
class CivitaiModelResource:
    model_name: str
    version_name: str = ""
    model_type: str = "Model"
    base_model: str | None = None
    model_id: int | None = None
    model_version_id: int | None = None
    strength: float | None = None
    availability: str = "unchecked"
    matched_path: str | None = None
    match_basis: str | None = None


@dataclass
class CivitaiImageReport:
    source_url: str
    image_id: int | None = None
    image_url: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    settings: list[CivitaiSetting] = field(default_factory=list)
    resources: list[CivitaiModelResource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "image_id": self.image_id,
            "image_url": self.image_url,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "settings": [asdict(item) for item in self.settings],
            "resources": [asdict(item) for item in self.resources],
            "warnings": list(self.warnings),
        }


def analyze_civitai_image_url(url: str, model_roots: Iterable[str] | None = None) -> CivitaiImageReport:
    source_url = (url or "").strip()
    if not source_url:
        raise ValueError("Enter a Civitai image URL.")

    roots = [root.strip() for root in (model_roots or []) if str(root).strip()]
    image_id = extract_image_id_from_civitai_url(source_url)
    if image_id is not None:
        host = civitai_host(source_url)
        page_url = f"https://{host}/images/{image_id}"
        try:
            html_text = fetch_text(page_url, accept="text/html,application/json;q=0.8,*/*;q=0.5")
            page_json = extract_next_data_json(html_text)
            if page_json is not None:
                report = build_report_from_page_json(source_url, page_json, roots, image_id=image_id)
                if report.prompt or report.resources:
                    return report
        except Exception:
            pass

        api_url = f"https://{host}/api/v1/images?imageId={image_id}"
        api_json = fetch_json(api_url)
        report = build_report_from_page_json(source_url, api_json, roots, image_id=image_id)
        if not report.prompt:
            report.warnings.append(
                "Civitai did not expose prompt metadata for this image through the public page/API."
            )
        return report

    content_type, final_url, data = fetch_bytes(
        source_url,
        accept="image/*,text/html;q=0.8,*/*;q=0.5",
    )

    if "text/html" in content_type.lower():
        page_json = extract_next_data_json(data.decode("utf-8", errors="replace"))
        if page_json is not None:
            return build_report_from_page_json(source_url, page_json, roots)

    for text in extract_generation_texts_from_image_bytes(data):
        report = build_report_from_generation_text(source_url, text, roots)
        if report.prompt or report.settings:
            report.image_url = final_url
            if not report.resources:
                report.warnings.append(
                    "Direct image URLs may not include Civitai model resource records; paste the /images/{id} page URL when available."
                )
            return report

    return CivitaiImageReport(
        source_url=source_url,
        image_url=final_url,
        warnings=["No embedded generation metadata was found in the downloaded image."],
    )


def extract_image_id_from_civitai_url(url: str) -> int | None:
    match = re.search(r"/images/(\d+)", url)
    if match:
        return int(match.group(1))

    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    for key in ("imageId", "imageid"):
        if key in query and query[key]:
            digits = re.match(r"\d+", query[key][0] or "")
            if digits:
                return int(digits.group(0))
    return None


def civitai_host(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    if "civitai.red" in host or "civitaired.com" in host:
        return "civitai.red"
    return "civitai.com"


def fetch_text(url: str, accept: str) -> str:
    content_type, _final_url, data = fetch_bytes(url, accept=accept)
    encoding = "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type, flags=re.I)
    if match:
        encoding = match.group(1)
    return data.decode(encoding, errors="replace")


def fetch_json(url: str) -> Any:
    return json.loads(fetch_text(url, accept="application/json"))


def fetch_bytes(url: str, accept: str, timeout: int = 30) -> tuple[str, str, bytes]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            final_url = response.geturl()
            return content_type, final_url, response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Server returned {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch URL: {exc.reason}") from exc


def extract_next_data_json(html_text: str) -> Any | None:
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.I | re.S,
    )
    if not match:
        return None
    try:
        return json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def build_report_from_page_json(
    source_url: str,
    page_json: Any,
    model_roots: Iterable[str] | None = None,
    image_id: int | None = None,
) -> CivitaiImageReport:
    warnings: list[str] = []
    data = find_generation_data(page_json, image_id=image_id) or page_json
    meta = data.get("meta") if isinstance(data, dict) else None
    prompt = None
    negative_prompt = None
    settings: list[CivitaiSetting] = []
    resources = resources_from_value(data.get("resources") if isinstance(data, dict) else None)
    image_url = string_value(data.get("url")) if isinstance(data, dict) else None

    if isinstance(meta, dict):
        prompt = string_field(meta, ("prompt", "Prompt"))
        negative_prompt = string_field(meta, ("negativePrompt", "negative_prompt", "Negative prompt"))
        settings = settings_from_meta(meta)
        if not resources:
            resources = resources_from_meta(meta)
        if not prompt:
            warnings.append("The Civitai record did not include a prompt field.")
        if not meta:
            warnings.append("The Civitai metadata object was empty.")
    elif isinstance(meta, str):
        report = build_report_from_generation_text(source_url, meta, model_roots)
        prompt = report.prompt
        negative_prompt = report.negative_prompt
        settings = report.settings
        resources = report.resources
        warnings.extend(report.warnings)
    else:
        warnings.append("No structured generation metadata was found.")

    if not resources and isinstance(data, dict):
        resources = resources_from_model_version_ids(data.get("modelVersionIds"))

    warnings.extend(apply_model_availability(resources, model_roots or []))
    return CivitaiImageReport(
        source_url=source_url,
        image_id=image_id,
        image_url=image_url,
        prompt=non_empty(prompt),
        negative_prompt=non_empty(negative_prompt),
        settings=settings,
        resources=resources,
        warnings=warnings,
    )


def build_report_from_generation_text(
    source_url: str,
    generation_text: str,
    model_roots: Iterable[str] | None = None,
) -> CivitaiImageReport:
    text = generation_text.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            report = build_report_from_page_json(source_url, parsed, model_roots)
            if report.prompt or report.settings:
                return report

    prompt, negative_prompt, settings = parse_a1111_generation_text(generation_text)
    resources = resources_from_generation_text(prompt, settings)
    warnings = apply_model_availability(resources, model_roots or [])
    if not prompt.strip() and not settings:
        warnings.append("The embedded metadata did not match a known prompt format.")

    return CivitaiImageReport(
        source_url=source_url,
        prompt=non_empty(prompt),
        negative_prompt=non_empty(negative_prompt),
        settings=settings,
        resources=resources,
        warnings=warnings,
    )


def find_generation_data(value: Any, image_id: int | None = None) -> Any | None:
    matches: list[Any] = []
    collect_generation_data(value, matches)
    if image_id is not None:
        for candidate in matches:
            if value_has_image_id(candidate, image_id):
                return candidate
    return matches[0] if matches else None


def collect_generation_data(value: Any, matches: list[Any]) -> None:
    if isinstance(value, dict):
        meta = value.get("meta")
        has_meta = isinstance(meta, dict) or (isinstance(meta, str) and bool(meta.strip()))
        has_resources = isinstance(value.get("resources"), list) and bool(value.get("resources"))
        has_versions = isinstance(value.get("modelVersionIds"), list) and bool(value.get("modelVersionIds"))
        if has_meta or has_resources or has_versions:
            matches.append(value)
        for child in value.values():
            collect_generation_data(child, matches)
    elif isinstance(value, list):
        for child in value:
            collect_generation_data(child, matches)


def value_has_image_id(value: Any, image_id: int) -> bool:
    if isinstance(value, dict):
        if value.get("id") == image_id or value.get("imageId") == image_id:
            return True
        return any(value_has_image_id(child, image_id) for child in value.values())
    if isinstance(value, list):
        return any(value_has_image_id(child, image_id) for child in value)
    return False


def settings_from_meta(meta: dict[str, Any]) -> list[CivitaiSetting]:
    settings: list[CivitaiSetting] = []
    skipped = {"prompt", "Prompt", "negativePrompt", "negative_prompt", "Negative prompt"}
    for key, value in meta.items():
        if key in skipped:
            continue
        if key == "hashes" and isinstance(value, dict):
            for hash_key, hash_value in value.items():
                report_value = report_string(hash_value)
                if report_value:
                    settings.append(CivitaiSetting(f"Hash: {hash_key}", report_value))
            continue
        report_value = report_string(value)
        if report_value:
            settings.append(CivitaiSetting(display_setting_key(key), report_value))
    return settings


def report_string(value: Any) -> str | None:
    if isinstance(value, str):
        return non_empty(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return None


def display_setting_key(key: str) -> str:
    mapping = {
        "cfgScale": "CFG scale",
        "steps": "Steps",
        "sampler": "Sampler",
        "seed": "Seed",
    }
    if key in mapping:
        return mapping[key]
    return key[:1].upper() + key[1:]


def resources_from_value(value: Any) -> list[CivitaiModelResource]:
    if not isinstance(value, list):
        return []
    resources: list[CivitaiModelResource] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        model_name = string_value(item.get("modelName")) or string_value(item.get("name")) or ""
        version_name = string_value(item.get("versionName")) or ""
        model_type = string_value(item.get("modelType")) or string_value(item.get("type")) or "Model"
        if not model_name and not version_name:
            continue
        resources.append(
            CivitaiModelResource(
                model_name=model_name,
                version_name=version_name,
                model_type=model_type,
                base_model=string_value(item.get("baseModel")),
                model_id=int_value(item.get("modelId")),
                model_version_id=int_value(item.get("modelVersionId")) or int_value(item.get("versionId")),
                strength=float_value(item.get("strength")),
            )
        )
    return resources


def resources_from_model_version_ids(value: Any) -> list[CivitaiModelResource]:
    if not isinstance(value, list):
        return []
    resources = []
    for raw_id in value:
        version_id = int_value(raw_id)
        if version_id is not None:
            resources.append(
                CivitaiModelResource(
                    model_name=f"Model version {version_id}",
                    model_version_id=version_id,
                )
            )
    return resources


def resources_from_meta(meta: dict[str, Any]) -> list[CivitaiModelResource]:
    resources: list[CivitaiModelResource] = []
    model = string_field(meta, ("Model", "model"))
    if model:
        resources.append(CivitaiModelResource(model_name=model, model_type="Checkpoint"))
    prompt = string_field(meta, ("prompt", "Prompt"))
    if prompt:
        resources.extend(lora_resources_from_prompt(prompt))
    return dedupe_resources(resources)


def parse_a1111_generation_text(text: str) -> tuple[str, str | None, list[CivitaiSetting]]:
    prompt_lines: list[str] = []
    negative_lines: list[str] = []
    setting_lines: list[str] = []
    phase = "prompt"

    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("Negative prompt:"):
            phase = "negative"
            rest = trimmed.removeprefix("Negative prompt:").strip()
            if rest:
                negative_lines.append(rest)
            continue
        if looks_like_settings_line(trimmed):
            phase = "settings"
        if phase == "prompt":
            prompt_lines.append(line.rstrip())
        elif phase == "negative":
            negative_lines.append(line.rstrip())
        else:
            setting_lines.append(trimmed)

    prompt = "\n".join(prompt_lines).strip()
    negative_prompt = non_empty("\n".join(negative_lines).strip())
    settings = parse_settings_lines(", ".join(setting_lines))
    return prompt, negative_prompt, settings


def looks_like_settings_line(line: str) -> bool:
    return (
        line.startswith("Steps:")
        or ("Sampler:" in line and "Seed:" in line)
        or ("CFG scale:" in line and "Size:" in line)
    )


def parse_settings_lines(line: str) -> list[CivitaiSetting]:
    settings: list[CivitaiSetting] = []
    for part in line.split(", "):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            settings.append(CivitaiSetting(key, value))
    return settings


def resources_from_generation_text(prompt: str, settings: list[CivitaiSetting]) -> list[CivitaiModelResource]:
    resources: list[CivitaiModelResource] = []
    for setting in settings:
        if setting.key.lower() == "model":
            resources.append(CivitaiModelResource(model_name=setting.value, model_type="Checkpoint"))
            break
    resources.extend(lora_resources_from_prompt(prompt))
    return dedupe_resources(resources)


def lora_resources_from_prompt(prompt: str) -> list[CivitaiModelResource]:
    resources: list[CivitaiModelResource] = []
    for tag in re.findall(r"<lora:([^>]+)>", prompt or "", flags=re.I):
        name = tag.strip()
        strength = None
        if ":" in tag:
            maybe_name, maybe_strength = tag.rsplit(":", 1)
            try:
                strength = float(maybe_strength.strip())
                name = maybe_name.strip()
            except ValueError:
                name = tag.strip()
        if name:
            resources.append(CivitaiModelResource(model_name=name, model_type="LORA", strength=strength))
    return resources


def dedupe_resources(resources: Iterable[CivitaiModelResource]) -> list[CivitaiModelResource]:
    seen: set[str] = set()
    deduped: list[CivitaiModelResource] = []
    for resource in resources:
        key = ":".join(
            [
                normalize_match_text(resource.model_type),
                normalize_match_text(resource.model_name),
                normalize_match_text(resource.version_name),
            ]
        )
        if key not in seen:
            seen.add(key)
            deduped.append(resource)
    return deduped


def apply_model_availability(resources: list[CivitaiModelResource], model_roots: Iterable[str]) -> list[str]:
    roots = [root.strip() for root in model_roots if str(root).strip()]
    if not roots:
        for resource in resources:
            resource.availability = "unchecked"
        return []

    inventory, warnings = scan_model_inventory(roots)
    for resource in resources:
        match = find_matching_model_path(resource, inventory)
        if match:
            resource.availability = "found"
            resource.matched_path = match
            resource.match_basis = "file name"
        else:
            resource.availability = "missing"
    return warnings


def scan_model_inventory(model_roots: Iterable[str]) -> tuple[list[tuple[str, str]], list[str]]:
    inventory: list[tuple[str, str]] = []
    warnings: list[str] = []
    for root in model_roots:
        if not os.path.exists(root):
            warnings.append(f"Model folder not found: {root}")
            continue
        if not os.path.isdir(root):
            warnings.append(f"Model path is not a folder: {root}")
            continue
        for current_root, _dirs, files in os.walk(root):
            for file_name in files:
                stem, ext = os.path.splitext(file_name)
                if ext.lower() not in MODEL_EXTENSIONS:
                    continue
                path = os.path.join(current_root, file_name)
                inventory.append((normalize_match_text(stem), path))
    return inventory, warnings


def find_matching_model_path(
    resource: CivitaiModelResource,
    inventory: list[tuple[str, str]],
) -> str | None:
    candidates = [
        normalize_match_text(resource.model_name),
        normalize_match_text(resource.version_name),
    ]
    for file_name, path in inventory:
        for candidate in candidates:
            if len(candidate) >= 4 and (candidate in file_name or file_name in candidate):
                return path
    return None


def extract_generation_texts_from_image_bytes(data: bytes) -> list[str]:
    texts: list[str] = []
    texts.extend(exif_texts(data))
    texts.extend(png_text_chunks(data))
    return dedupe_texts(texts)


def exif_texts(data: bytes) -> list[str]:
    try:
        from PIL import Image
    except Exception:
        return []

    texts: list[str] = []
    try:
        with Image.open(BytesIO(data)) as image:
            for value in (image.info or {}).values():
                if isinstance(value, str) and value.strip():
                    texts.append(value)
            exif = image.getexif()
            for tag_id in (270, 305, 37510):
                value = exif.get(tag_id)
                if isinstance(value, bytes):
                    value = strip_user_comment_prefix(value).decode("utf-8", errors="replace")
                if isinstance(value, str) and value.strip():
                    texts.append(value)
    except Exception:
        return texts
    return texts


def png_text_chunks(data: bytes) -> list[str]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return []

    texts: list[str] = []
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        if offset + 12 + length > len(data):
            break

        if chunk_type == b"tEXt":
            _keyword, text = split_once_byte(chunk_data, 0)
            if text:
                decoded = text.decode("utf-8", errors="replace").strip()
                if decoded:
                    texts.append(decoded)
        elif chunk_type == b"zTXt":
            _keyword, rest = split_once_byte(chunk_data, 0)
            if len(rest) > 1 and rest[0] == 0:
                try:
                    decoded = zlib.decompress(rest[1:]).decode("utf-8", errors="replace").strip()
                    if decoded:
                        texts.append(decoded)
                except zlib.error:
                    pass
        elif chunk_type == b"iTXt":
            decoded = parse_itxt_chunk(chunk_data)
            if decoded:
                texts.append(decoded)
        offset += 12 + length
    return texts


def parse_itxt_chunk(data: bytes) -> str | None:
    _keyword, rest = split_once_byte(data, 0)
    if len(rest) < 2:
        return None
    compression_flag = rest[0]
    compression_method = rest[1]
    rest = rest[2:]
    _language, rest = split_once_byte(rest, 0)
    _translated, text = split_once_byte(rest, 0)
    if compression_flag == 1 and compression_method == 0:
        try:
            text = zlib.decompress(text)
        except zlib.error:
            return None
    elif compression_flag != 0:
        return None
    decoded = text.decode("utf-8", errors="replace").strip()
    return decoded or None


def split_once_byte(data: bytes, marker: int) -> tuple[bytes, bytes]:
    try:
        index = data.index(marker)
    except ValueError:
        return data, b""
    return data[:index], data[index + 1 :]


def dedupe_texts(texts: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for text in texts:
        value = text.strip()
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def string_field(value: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        candidate = string_value(value.get(key))
        if candidate:
            return candidate
    return None


def string_value(value: Any) -> str | None:
    return non_empty(value) if isinstance(value, str) else None


def int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        return int(value.strip())
    return None


def float_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def normalize_match_text(value: str | None) -> str:
    return "".join(ch.lower() for ch in (value or "") if ch.isascii() and ch.isalnum())


def strip_user_comment_prefix(data: bytes) -> bytes:
    for prefix in (b"ASCII\x00\x00\x00", b"UNICODE\x00", b"JIS\x00\x00\x00\x00\x00"):
        if data.startswith(prefix):
            return data[len(prefix) :]
    return data


def non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
