"""Semantic favorite lanes; lock state contains paths, never image tensors."""
from __future__ import annotations

import json
import sys

ROLES = ('subject', 'clothing', 'environment', 'style')


def _source_class():
    # Comfy loads custom nodes under runtime module names. Reuse the registered
    # class instead of importing its package again (which registers HTTP routes).
    registry = getattr(sys.modules.get('nodes'), 'NODE_CLASS_MAPPINGS', {})
    source = registry.get('RandomReferenceImageSource')
    if source is not None:
        return source
    for name, module in tuple(sys.modules.items()):
        if name.endswith('comfyui_random_reference_source.nodes'):
            source = getattr(module, 'RandomReferenceImageSource', None)
            if source is not None:
                return source
    raise RuntimeError('Reference Cast requires the Random Reference Source node pack.')


def _locks(value):
    try:
        parsed = json.loads(value or '{}')
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class ReferenceCast:
    @classmethod
    def INPUT_TYPES(cls):
        try:
            options = _source_class().INPUT_TYPES()['required']['favorite'][0]
        except RuntimeError:
            options = ['None']
        required = {}
        for role in ROLES:
            required[f'{role}_enabled'] = ('BOOLEAN', {'default': False})
            required[f'{role}_locked'] = ('BOOLEAN', {'default': False})
            required[f'{role}_favorite'] = (options, {'default': 'None'})
        required['seed'] = ('INT', {'default': 1, 'min': 1, 'max': 0xFFFFFFFFFFFFFFFF,
                                   'control_after_generate': False,
                                   'tooltip': 'Fixed seed for the first locked pick, including queued batches. Unlock to reroll.'})
        return {'required': required, 'optional': {'locked_paths': ('STRING', {'default': '{}'})}}

    RETURN_TYPES = ('IMAGE', 'IMAGE', 'IMAGE', 'IMAGE', 'STRING', 'STRING')
    RETURN_NAMES = (*ROLES, 'metadata_json', 'combined_prompt')
    FUNCTION = 'select'
    CATEGORY = 'Arch/Reference Workbench'
    DESCRIPTION = ('Select favorite groups by role. Disabled or unassigned lanes return None; '
                   'connect optional lanes through lazy switches before image-only consumers. '
                   'Locks retain paths in the workflow, not tensors. Changing a favorite resets its lock.')

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Even locked files may be replaced on disk. Reload on each execution;
        # deterministic selection/path locks preserve the choices.
        return float('nan')

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        # Allow workflows with deleted favorites in disabled lanes to load.
        return True

    def select(self, seed=1, locked_paths='{}', **kwargs):
        locks = _locks(locked_paths)
        images, lanes, prompts = [], {}, []
        for role in ROLES:
            enabled = bool(kwargs.get(f'{role}_enabled', False))
            locked = bool(kwargs.get(f'{role}_locked', False))
            favorite = str(kwargs.get(f'{role}_favorite', 'None'))
            lane = dict(enabled=enabled, locked=locked, favorite=favorite,
                        selected_file='', selected_name='', prompt='')
            lanes[role] = lane
            if not enabled or favorite == 'None':
                images.append(None)
                continue
            source = _source_class()
            if favorite not in source.INPUT_TYPES()['required']['favorite'][0]:
                raise ValueError(f'Favorite not found: {favorite}')
            old = locks.get(role, {})
            path = (old.get('selected_file') if locked and isinstance(old, dict)
                    and old.get('favorite') == favorite else None)
            args = dict(lane=role, source_mode='auto', favorite=favorite,
                        folder='', selected_images='', include_subfolders=False,
                        selection_policy='seeded' if locked else 'random_each_queue', seed=seed)
            if isinstance(path, str) and path:
                # The source resolves a favorite ahead of explicit files; detach
                # it for this fixed path while retaining its current prompt text.
                module = sys.modules.get(source.__module__)
                text = ''
                if hasattr(module, 'load_presets'):
                    preset = module._favorite_preset(favorite, module.load_presets())
                    text = str(preset.get('prompt_text', '')) if preset else ''
                args.update(source_mode='selection', favorite='None',
                            selected_images='"' + path.replace('"', '""') + '"',
                            favorite_prompt=text)
            loaded = source().load_random_reference(**args)
            result = loaded['result'] if isinstance(loaded, dict) else loaded
            images.append(result[0])
            lane.update(json.loads(result[4]))
            lane.update(enabled=enabled, locked=locked, favorite=favorite, prompt=result[5], lane=role)
            if result[5].strip():
                prompts.append(result[5].strip())
        metadata = {'lanes': lanes}
        return {'ui': {'arch_reference_cast': [metadata]},
                'result': (*images, json.dumps(metadata, ensure_ascii=False), '\n\n'.join(prompts))}
