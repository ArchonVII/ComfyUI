import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def module():
    path = Path(__file__).parents[1] / 'cast.py'
    assert path.exists(), 'Reference Cast implementation missing'
    spec = importlib.util.spec_from_file_location('cast_under_test', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def cast(monkeypatch):
    value = module()
    calls = []
    class Source:
        @classmethod
        def INPUT_TYPES(cls):
            return {'required': {'favorite': (['None', 'A', 'B'],)}}
        def load_random_reference(self, **kwargs):
            calls.append(kwargs)
            path = kwargs['selected_images'].strip('"') if kwargs['source_mode'] == 'selection' else 'picked.png'
            metadata = {'selected_file': path, 'selected_name': Path(path).name}
            return {'result': ('image', None, path, 'generic', json.dumps(metadata), kwargs.get('favorite_prompt', 'favorite text'))}
    monkeypatch.setitem(sys.modules, 'nodes', types.SimpleNamespace(NODE_CLASS_MAPPINGS={'RandomReferenceImageSource': Source}))
    return value, calls


def test_disabled_and_no_group_never_load(cast):
    value, calls = cast
    result = value.ReferenceCast().select(subject_enabled=False, subject_favorite='A')
    assert result['result'][:4] == (None,) * 4
    assert calls == []
    assert json.loads(result['result'][4])['lanes']['subject']['enabled'] is False


def test_locked_selection_replays_path_and_invalidates_changed_group(cast):
    value, calls = cast
    args = dict(subject_enabled=True, subject_locked=True, subject_favorite='A', seed=17)
    first = value.ReferenceCast().select(**args)
    assert calls[-1]['selection_policy'] == 'seeded'
    assert calls[-1]['seed'] == 17
    assert first['result'][5] == 'favorite text'
    locked = json.dumps({'subject': {'favorite': 'A', 'selected_file': 'old.png'}})
    result = value.ReferenceCast().select(**args, locked_paths=locked)
    assert calls[-1]['source_mode'] == 'selection'
    assert calls[-1]['favorite'] == 'None'
    assert json.loads(result['result'][4])['lanes']['subject']['selected_file'] == 'old.png'
    value.ReferenceCast().select(**{**args, 'subject_favorite': 'B'}, locked_paths=locked)
    assert calls[-1]['favorite'] == 'B'
    assert calls[-1]['source_mode'] == 'auto'


def test_unlocked_rerolls_and_registry_supplies_choices(cast):
    value, calls = cast
    value.ReferenceCast().select(subject_enabled=True, subject_favorite='A')
    assert calls[-1]['selection_policy'] == 'random_each_queue'
    assert value.ReferenceCast.INPUT_TYPES()['required']['subject_favorite'][0] == ['None', 'A', 'B']
    assert value.ReferenceCast.IS_CHANGED(subject_enabled=True, subject_favorite='A') != value.ReferenceCast.IS_CHANGED(subject_enabled=True, subject_favorite='A')


def test_seed_explicitly_disables_frontend_automatic_randomize(cast):
    value, _ = cast
    assert value.ReferenceCast.INPUT_TYPES()['required']['seed'][1]['control_after_generate'] is False


def test_malformed_lock_is_safe_and_missing_group_errors(cast):
    value, calls = cast
    value.ReferenceCast().select(subject_enabled=True, subject_locked=True, subject_favorite='A', locked_paths='[]')
    assert calls[-1]['favorite'] == 'A'
    with pytest.raises(ValueError, match='Favorite not found'):
        value.ReferenceCast().select(subject_enabled=True, subject_favorite='Gone')


def test_real_source_replays_locked_file_with_current_favorite_prompt(tmp_path, monkeypatch):
    from PIL import Image
    from custom_nodes.comfyui_random_reference_source import nodes as source
    value = module()
    for i in range(3):
        Image.new('RGB', (i + 2, 3)).save(tmp_path / f'{i}.png')
    monkeypatch.setattr(source, 'load_presets', lambda: {'A': {
        'kind': 'folder', 'folder': str(tmp_path), 'prompt_text': 'current favorite prompt'}})
    monkeypatch.setitem(sys.modules, 'nodes', types.SimpleNamespace(
        NODE_CLASS_MAPPINGS={'RandomReferenceImageSource': source.RandomReferenceImageSource}))
    args = dict(subject_enabled=True, subject_favorite='A', subject_locked=True, seed=3)
    first = value.ReferenceCast().select(**args)
    second = value.ReferenceCast().select(**args)
    lane = json.loads(first['result'][4])['lanes']['subject']
    assert lane['selected_file'] == json.loads(second['result'][4])['lanes']['subject']['selected_file']
    result = value.ReferenceCast().select(**args, locked_paths=json.dumps({'subject': {
        'favorite': 'A', 'selected_file': lane['selected_file']}}))
    assert result['result'][5] == 'current favorite prompt'
    assert json.loads(result['result'][4])['lanes']['subject']['favorite'] == 'A'
    assert result['result'][0].equal(first['result'][0])
