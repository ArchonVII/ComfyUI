"""Local, append-only image copies and explicit review classifications."""
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from uuid import UUID, uuid4

import folder_paths
import numpy as np
from PIL import Image

MAX_JSON_BYTES = 8 * 1024 * 1024


def review_root():
    return Path(folder_paths.get_user_directory()) / 'reference_reviews'


def parse_metadata(value):
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(value.encode('utf-8')) > MAX_JSON_BYTES:
        raise ValueError('Metadata exceeds 8 MiB')
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def hidden_metadata(value):
    """Copy Comfy graph metadata, preserving cache sentinels as explicit markers."""
    content = json.dumps(value, ensure_ascii=False)
    if len(content.encode('utf-8')) > MAX_JSON_BYTES:
        raise ValueError('Hidden metadata exceeds 8 MiB')
    return json.loads(content, parse_constant=lambda token: {'nonfinite_number': token})

def atomic_json(path, value):
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if len(content.encode('utf-8')) > MAX_JSON_BYTES:
        raise ValueError('Record exceeds 8 MiB')
    fd, temporary = tempfile.mkstemp(prefix='.record-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def review_directory(identifier):
    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError('Invalid review ID')
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Invalid review ID') from None
    root = review_root().resolve()
    directory = (root / identifier).resolve()
    if directory.parent != root:
        raise ValueError('Review path escapes storage')
    return directory


def load_review(identifier):
    directory = review_directory(identifier)
    path = directory / 'review.json'
    if path.resolve().parent != directory:
        raise ValueError('Review record escapes storage')
    with path.open('rb') as stream:
        content = stream.read(MAX_JSON_BYTES + 1)
    if len(content) > MAX_JSON_BYTES:
        raise ValueError('Review record exceeds 8 MiB')
    return json.loads(content)


def classify(identifier, classification):
    if classification not in ('keep', 'reject'):
        raise ValueError('Classification must be keep or reject')
    value = load_review(identifier)
    value['classification'] = classification
    value['classified_at'] = datetime.now(timezone.utc).isoformat()
    atomic_json(review_directory(identifier) / 'review.json', value)
    return value


def save_images(images, directory, stem, subfolder=None):
    if images.ndim != 4 or images.shape[-1] not in (1, 3, 4) or len(images) == 0:
        raise ValueError('Expected nonempty BHWC IMAGE batch with 1, 3 or 4 channels')
    result = []
    for index, tensor in enumerate(images):
        array = np.clip(tensor.detach().cpu().numpy() * 255, 0, 255).astype(np.uint8)
        if array.shape[-1] == 1:
            array = array[..., 0]
        filename = f'{stem}_{index:04d}.png'
        path = directory / filename
        # Exclusive creation protects even against an unexpected name collision.
        with path.open('xb') as stream:
            Image.fromarray(array).save(stream, format='PNG')
        entry = {'path': str(path.resolve()), 'filename': filename, 'index': index}
        if subfolder is not None:
            entry.update(subfolder=subfolder, type='output')
        result.append(entry)
    return result


class ArchResultReview:
    CATEGORY = 'Arch/Reference Workbench'
    FUNCTION = 'save'
    OUTPUT_NODE = True
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('manifest_json',)

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'reference_image': ('IMAGE',), 'result_image': ('IMAGE',)},
                'optional': {'score_report_json': ('STRING', {'default': '', 'multiline': True}),
                             'run_settings_json': ('STRING', {'default': '', 'multiline': True})}}

    def save(self, reference_image, result_image, score_report_json='', run_settings_json=''):
        score, settings = parse_metadata(score_report_json), parse_metadata(run_settings_json)
        identifier = str(uuid4())
        directory = review_directory(identifier)
        directory.mkdir(parents=True, exist_ok=False)
        value = {'schema_version': 1, 'id': identifier, 'created_at': datetime.now(timezone.utc).isoformat(),
                 'classification': 'unreviewed', 'score_report': score, 'run_settings': settings,
                 'references': save_images(reference_image, directory, 'reference'),
                 'results': save_images(result_image, directory, 'result')}
        atomic_json(directory / 'review.json', value)
        return {'ui': {'arch_review': [value]}, 'result': (json.dumps(value),)}


class ArchRunRecord:
    CATEGORY = 'Arch/Reference Workbench'
    FUNCTION = 'save'
    OUTPUT_NODE = True
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('manifest_json',)

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'filename_prefix': ('STRING', {'default': 'arch_run'})},
                'optional': {'reference_metadata_json': ('STRING', {'default': '', 'multiline': True}),
                             'positive_prompt': ('STRING', {'default': '', 'multiline': True}),
                             'negative_prompt': ('STRING', {'default': '', 'multiline': True}),
                             'seed': ('INT', {'default': 0, 'min': 0, 'max': 0xffffffffffffffff, 'control_after_generate': False}),
                             'model': ('STRING', {'default': ''}), 'loras_json': ('STRING', {'default': ''})},
                'hidden': {'prompt': 'PROMPT', 'extra_pnginfo': 'EXTRA_PNGINFO'}}

    def save(self, images, filename_prefix='arch_run', reference_metadata_json='', positive_prompt='',
             negative_prompt='', seed=0, model='', loras_json='', prompt=None, extra_pnginfo=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', filename_prefix):
            raise ValueError('Filename prefix must be 1–80 letters, digits, underscores or hyphens')
        identifier = str(uuid4())
        value = {'schema_version': 1, 'id': identifier, 'created_at': datetime.now(timezone.utc).isoformat(),
                 'reference_metadata': parse_metadata(reference_metadata_json),
                 'supplied_settings': {'positive_prompt': positive_prompt, 'negative_prompt': negative_prompt,
                                       'seed': seed, 'model': model, 'loras': parse_metadata(loras_json)},
                 'metadata_note': 'Reference choices and settings are supplied by connected inputs; not independently inferred from the image.',
                 'hidden_metadata_note': 'Non-finite numbers in hidden Comfy graph metadata (including cache sentinels) are preserved as nonfinite_number markers.',
                 'api_prompt': hidden_metadata(prompt), 'extra_pnginfo': hidden_metadata(extra_pnginfo)}
        # Validate combined metadata before creating any output files.
        parse_metadata(value)
        subfolder = f'reference_runs/{identifier}'
        directory = Path(folder_paths.get_output_directory()).resolve() / 'reference_runs' / identifier
        output_root = Path(folder_paths.get_output_directory()).resolve()
        if not directory.resolve().is_relative_to(output_root):
            raise ValueError('Run path escapes output storage')
        directory.mkdir(parents=True, exist_ok=False)
        value['images'] = save_images(images, directory, filename_prefix, subfolder)
        value['record_path'] = str(directory / f'{filename_prefix}.json')
        atomic_json(Path(value['record_path']), value)
        return {'ui': {'images': [{k: x[k] for k in ('filename', 'subfolder', 'type')} for x in value['images']],
                       'arch_run_record': [value]}, 'result': (json.dumps(value),)}
