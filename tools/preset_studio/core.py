"""Pure composition and API-workflow adaptation; never edits source graphs."""
import copy
import math


def compose(presets, extra='', negative=''):
    result = {'positive': [], 'negative': [], 'references': [], 'loras': [], 'presets': []}
    seen = {}
    for preset in presets:
        result['presets'].append(preset.get('name', 'Untitled'))
        for key in ('positive', 'negative'):
            text = str(preset.get(key, '')).strip()
            if text:
                result[key].append(text)
        result['references'].extend(preset.get('references', []))
        for source in preset.get('loras', []):
            if source.get('enabled', True) is False:
                continue
            name = str(source.get('name', '')).strip()
            if not name:
                raise ValueError('A LoRA needs a filename')
            item = {'name': name, 'model': float(source.get('model', 1)), 'clip': float(source.get('clip', 1))}
            if not all(math.isfinite(item[k]) and -10 <= item[k] <= 10 for k in ('model', 'clip')):
                raise ValueError('LoRA strengths must be finite and between -10 and 10')
            if name in seen and seen[name] != item:
                raise ValueError(f'LoRA {name} has conflicting strengths in selected presets')
            if name not in seen:
                seen[name] = item
                result['loras'].append(item)
    for key, text in [('positive', extra), ('negative', negative)]:
        if text.strip():
            result[key].append(text.strip())
        result[key] = ', '.join(result[key])
    return result


def validate_graph(graph):
    if not isinstance(graph, dict) or not graph or 'nodes' in graph:
        raise ValueError('Import a ComfyUI API-format workflow, not an editor workflow')
    if len(graph) > 2000:
        raise ValueError('Workflow exceeds 2000 nodes')
    for key, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get('class_type'), str) or not isinstance(node.get('inputs'), dict):
            raise ValueError(f'Invalid API node: {key}')
    return graph


def fields(graph):
    validate_graph(graph)
    rows = []
    for key, node in graph.items():
        for name, value in node['inputs'].items():
            if not isinstance(value, (list, dict)):
                rows.append({'binding': f'{key}.{name}', 'node': key, 'input': name,
                             'title': node.get('_meta', {}).get('title', node['class_type']),
                             'class_type': node['class_type'], 'value': value})
    return rows


def suggest_adapter(graph):
    adapter = {'positive': [], 'negative': [], 'references': [], 'seed': [], 'model': None, 'clip': None}
    for field in fields(graph):
        name, kind = field['input'], field['class_type']
        if name in ('seed', 'noise_seed') and isinstance(field['value'], int):
            adapter['seed'].append(field['binding'])
        if kind == 'LoadImage' and name == 'image':
            adapter['references'].append(field['binding'])
        if kind == 'CLIPTextEncode' and name == 'text':
            role = 'negative' if 'negative' in field['title'].lower() else 'positive'
            adapter[role].append(field['binding'])
    # MODEL/CLIP insertion is deliberately chosen by the user.
    return adapter


def compile_graph(source, adapter, composition, seed):
    validate_graph(source)
    graph = copy.deepcopy(source)
    used = set()

    def patch(binding, value):
        try:
            node, field = binding.split('.', 1)
            if binding in used or field not in graph[node]['inputs'] or isinstance(graph[node]['inputs'][field], (list, dict)):
                raise KeyError(binding)
            original = graph[node]['inputs'][field]
        except (KeyError, ValueError, AttributeError):
            raise ValueError(f'Invalid or duplicate field binding: {binding}') from None
        if type(original) is not type(value):
            raise ValueError(f'Field binding {binding} has the wrong value type')
        graph[node]['inputs'][field] = value
        used.add(binding)

    if not isinstance(seed, int) or not 0 <= seed <= 2**53 - 1:
        raise ValueError('Seed must be a nonnegative safe integer')
    for role in ('positive', 'negative'):
        if composition[role] and not adapter.get(role):
            raise ValueError(f'Map a {role} prompt field before using {role} text')
        for binding in adapter.get(role, []):
            patch(binding, composition[role])
    for binding in adapter.get('seed', []):
        patch(binding, seed)
    slots = adapter.get('references', [])
    if len(composition['references']) != len(slots):
        raise ValueError(f'Workflow needs {len(slots)} reference(s); selected {len(composition["references"])}. Adjust references or mappings.')
    for binding, reference in zip(slots, composition['references']):
        patch(binding, reference)
    if composition['loras']:
        model, clip = adapter.get('model'), adapter.get('clip')
        if not model:
            raise ValueError('Map a MODEL insertion point to apply preset LoRAs')
        for link in (model, clip):
            if link is not None and (not isinstance(link, list) or len(link) != 2 or str(link[0]) not in graph or not isinstance(link[1], int) or link[1] < 0):
                raise ValueError('Invalid LoRA insertion point')
        current_model, current_clip = model, clip
        added = set()
        next_id = max([int(k) for k in graph if k.isdigit()] + [0]) + 1
        for lora in composition['loras']:
            key = str(next_id)
            next_id += 1
            inputs = {'model': current_model, 'lora_name': lora['name'], 'strength_model': lora['model']}
            if clip:
                inputs.update(clip=current_clip, strength_clip=lora['clip'])
            graph[key] = {'class_type': 'LoraLoader' if clip else 'LoraLoaderModelOnly', 'inputs': inputs}
            added.add(key)
            current_model = [key, 0]
            current_clip = [key, 1] if clip else None
        rewired = 0
        for key, node in graph.items():
            if key in added:
                continue
            for name, value in node['inputs'].items():
                if value == model:
                    node['inputs'][name] = current_model
                    rewired += 1
                elif clip and value == clip:
                    node['inputs'][name] = current_clip
        if not rewired:
            raise ValueError('LoRA MODEL insertion point has no consumers')
    return graph


def validate_live(graph, info):
    """Check installed classes, outputs, required inputs and dropdown choices."""
    for key, node in graph.items():
        kind = node['class_type']
        if kind not in info:
            raise ValueError(f'Node {key}: {kind} is not installed on this ComfyUI server')
        spec = info[kind]
        if spec.get('api_node'):
            raise ValueError(f'Node {key}: cloud API nodes are disabled in local Preset Studio')
        inputs = node['inputs']
        required = spec.get('input', {}).get('required', {})
        definitions = {**required, **spec.get('input', {}).get('optional', {})}
        for name in required:
            if name not in inputs:
                raise ValueError(f'Node {key} is missing required input {name}')
        for name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2:
                upstream, slot = str(value[0]), value[1]
                if upstream not in graph or not isinstance(slot, int) or slot < 0:
                    raise ValueError(f'Node {key}: broken link for {name}')
                outputs = info.get(graph[upstream]['class_type'], {}).get('output', [])
                if slot >= len(outputs):
                    raise ValueError(f'Node {key}: invalid output slot for {name}')
                expected = definitions.get(name, [None])[0]
                if isinstance(expected, str) and expected != '*' and outputs[slot] != '*' and not set(expected.split(',')).intersection(str(outputs[slot]).split(',')):
                    raise ValueError(f'Node {key}: {name} expects {expected}, got {outputs[slot]}')
            elif name in definitions:
                choices = definitions[name][0]
                if isinstance(choices, list) and value not in choices:
                    raise ValueError(f'Node {key}: {name} value {value!r} is unavailable')
    # Reject cycles before queueing, including accidental insertion into an upstream branch.
    visiting, done = set(), set()
    def visit(key):
        if key in visiting:
            raise ValueError('Workflow contains a cycle; check LoRA insertion points')
        if key in done:
            return
        visiting.add(key)
        for value in graph[key]['inputs'].values():
            if isinstance(value, list) and len(value) == 2:
                visit(str(value[0]))
        visiting.remove(key)
        done.add(key)
    for key in graph:
        visit(key)
