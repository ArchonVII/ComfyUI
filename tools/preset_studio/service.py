"""Loopback-only standalone service. Run with --runtime pointing at ComfyUI."""
import argparse
import base64
import copy
import hashlib
import json
import mimetypes
import os
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.character_catalog import CharacterCatalog, OpenCVFaceAnalyzer
from builder import (
    BuilderStore, build_prompt_catalog, compile_builder_option,
    create_basic_image_workflow, import_workflow_document, render_prompt_board,
)
from core import compose, compile_graph, fields, suggest_adapter, validate_graph, validate_live

WEB = Path(__file__).parent / 'web'
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Backend redirects are disabled; use the direct local ComfyUI address')


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('ComfyUI address must be a local HTTP address, such as http://127.0.0.1:8188')
    if not parsed.port:
        raise ValueError('Include the ComfyUI port')
    return value.rstrip('/')


class Studio:
    def __init__(self, runtime):
        self.runtime = Path(runtime).resolve()
        self.root = self.runtime / 'user/preset_studio'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        path = self.root / 'state.json'
        if path.exists():
            self.state = json.loads(path.read_text(encoding='utf-8'))
            if self.state.get('version') != 1 or not all(isinstance(self.state.get(k), list) for k in ('presets', 'workflows', 'runs')):
                raise ValueError('Unsupported Studio state; existing file left untouched')
            local_url(self.state['comfy_url'])
        else:
            self.state = {'version': 1, 'comfy_url': 'http://127.0.0.1:8188', 'presets': [], 'workflows': [], 'runs': [], 'references': {}}
            for name, positive in [
                ('Amateur iPhone photo 1', 'amateur iPhone photo, candid snapshot, natural available light, casual imperfect framing'),
                ('Window light', 'soft window light, gentle shadows, natural skin texture'),
                ('Everyday moment', 'an unposed everyday moment, relaxed expression, believable surroundings'),
            ]:
                self.state['presets'].append({'id': uuid.uuid4().hex, 'name': name, 'kind': 'concept', 'positive': positive, 'negative': '', 'references': [], 'loras': []})
        self.character_catalog = CharacterCatalog(self.runtime / 'user/character_catalog')
        self.builder_store = BuilderStore(self.root / 'builder')
        self.character_catalog.recover_interrupted_assignment_jobs()
        self.face_analyzer_factory = lambda: OpenCVFaceAnalyzer(
            REPO_ROOT / 'custom_nodes/comfyui_identity_score/models'
        )
        self.discovery_threads = set()
        self.assignment_threads = set()
        self._closed = False
        self._sync_character_catalog()
        # A process stop during submission leaves its outcome uncertain. Never resubmit.
        changed = False
        for run in self.state['runs']:
            if run['status'] == 'submitting':
                run.update(status='uncertain', error='Service stopped during submission. Check ComfyUI history before retrying.')
                changed = True
        if changed:
            self.persist()

    def close(self):
        if self._closed:
            return
        self._closed = True
        for character in self.character_catalog.list_characters():
            for job in self.character_catalog.list_discovery_jobs(character['id']):
                if job['state'] in ('pending', 'running'):
                    self.character_catalog.request_discovery_cancel(job['id'])
        for worker in list(self.discovery_threads):
            worker.join(timeout=5)
        for worker in list(self.assignment_threads):
            worker.join(timeout=5)
        self.character_catalog.close()

    def _catalog_references(self):
        return {
            key: {**record, 'path': Path(record['path'])}
            for key, record in self.state.get('references', {}).items()
        }

    def _sync_character_catalog(self):
        references = self._catalog_references()
        for preset in self.state['presets']:
            self.character_catalog.sync_preset(preset, references)

    def persist(self):
        with self.lock:
            target = self.root / 'state.json'
            temporary = self.root / 'state.tmp'
            content = json.dumps(self.state, ensure_ascii=False, indent=2, allow_nan=False)
            with temporary.open('w', encoding='utf-8') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)

    def configure(self, url):
        self.state['comfy_url'] = local_url(url)
        self.persist()
        return {'comfy_url': self.state['comfy_url']}

    def builder_state(self, data):
        return self.builder_store.snapshot()

    def builder_catalog(self, data):
        query = data.get('query', '')
        if not isinstance(query, str):
            raise ValueError('Builder catalog query must be text')
        roots = [
            self.runtime / 'wildcards',
            self.runtime / 'custom_nodes/comfyui-adaptiveprompts/wildcards',
        ]
        return build_prompt_catalog(
            REPO_ROOT / 'custom_nodes/comfyui_arch_prompt_tools/data/builtin_options.json',
            self.state['presets'], roots, query=query,
        )

    def create_builder_experiment(self, data):
        return self.builder_store.create_experiment(data.get('name'))

    def update_builder_option(self, data):
        option_id, changes = data.get('option_id'), data.get('changes')
        if not isinstance(option_id, str) or not isinstance(changes, dict):
            raise ValueError('Builder option ID and changes required')
        option = self.builder_store.update_option(option_id, changes)
        return {**option, 'rendered_prompt': render_prompt_board(option['prompt_board'])}

    def branch_builder_option(self, data):
        option_id, name = data.get('option_id'), data.get('name')
        if not isinstance(option_id, str) or not isinstance(name, str):
            raise ValueError('Builder option ID and branch name required')
        return self.builder_store.branch_option(option_id, name)

    def delete_builder_option(self, data):
        option_id = data.get('option_id')
        if not isinstance(option_id, str):
            raise ValueError('Builder option ID required')
        return self.builder_store.delete_option(option_id)

    def attach_builder_workflow(self, data):
        option_id, workflow_id = data.get('option_id'), data.get('workflow_id')
        workflow = next(
            (item for item in self.state['workflows'] if item['id'] == workflow_id), None
        )
        if not isinstance(option_id, str) or workflow is None:
            raise ValueError('Builder option and saved workflow required')
        graph = import_workflow_document(workflow['graph'], workflow['adapter'])
        graph.update(source_workflow_id=workflow['id'], source_workflow_name=workflow['name'])
        return self.builder_store.update_option(option_id, {'workflow_graph': graph})

    def create_builder_basic_workflow(self, data):
        option_id = data.get('option_id')
        if not isinstance(option_id, str):
            raise ValueError('Builder option ID required')
        return self.builder_store.update_option(
            option_id, {'workflow_graph': create_basic_image_workflow()}
        )

    def save_builder_workflow(self, data):
        option_id, name = data.get('option_id'), data.get('name')
        if not isinstance(option_id, str) or not isinstance(name, str):
            raise ValueError('Builder option ID and workflow name required')
        option = self.builder_store.get_option(option_id)
        document = option.get('workflow_graph') or {}
        graph = copy.deepcopy(document.get('source_graph'))
        if not graph:
            raise ValueError('Build or load a workflow graph first')
        model = option.get('resources', {}).get('model')
        if model:
            for node in graph.values():
                if node.get('class_type') == 'CheckpointLoaderSimple':
                    node.get('inputs', {})['ckpt_name'] = model
        return self.save_workflow({
            'name': name, 'graph': graph, 'adapter': document.get('adapter'),
        })

    def toggle_builder_favorite(self, data):
        item_id = data.get('item_id')
        if not isinstance(item_id, str):
            raise ValueError('Builder favorite item ID required')
        return self.builder_store.toggle_favorite(item_id)

    def save_builder_bundle(self, data):
        name, board = data.get('name'), data.get('prompt_board')
        if not isinstance(name, str) or not isinstance(board, dict):
            raise ValueError('Bundle name and prompt board required')
        return self.builder_store.save_bundle(name, board)

    def generate_builder_option(self, data):
        option_id = data.get('option_id')
        if not isinstance(option_id, str):
            raise ValueError('Builder option ID required')
        option = self.builder_store.get_option(option_id)
        working = copy.deepcopy(option)
        references = working.get('resources', {}).get('references', [])
        uploaded = {key: self.upload_to_comfy(key) for key in dict.fromkeys(references)}
        working['resources']['references'] = [uploaded[key] for key in references]
        graph = compile_builder_option(working)
        validate_live(graph, self.comfy('/object_info'))
        revision = self.builder_store.create_revision(option_id, graph)
        rendered = render_prompt_board(option['prompt_board'])
        run = {
            'id': uuid.uuid4().hex, 'created': time.time(),
            'name': option['name'], 'status': 'submitting',
            'seed': int(option.get('settings', {}).get('seed', 1)),
            'composition': {**rendered, 'references': references,
                            'loras': option.get('resources', {}).get('loras', [])},
            'request': {'builder_option_id': option_id}, 'graph': graph,
            'comfy_url': self.state['comfy_url'], 'outputs': [],
            'builder_revision_id': revision['id'], 'lineage_sources': [],
            'preset_snapshots': [], 'workflow_snapshot': {
                'id': f"builder:{revision['id']}", 'name': option['name'],
                'graph': graph, 'adapter': option['workflow_graph'].get('adapter', {}),
            },
        }
        self.state['runs'].insert(0, run)
        self.persist()
        try:
            result = self.comfy('/prompt', {
                'prompt': graph, 'client_id': 'preset-studio',
                'extra_data': {'preset_studio_run': run['id'],
                               'builder_revision': revision['id']},
            })
            if not result.get('prompt_id'):
                raise ValueError(f'ComfyUI did not return a prompt ID: {result}')
            run.update(status='queued', prompt_id=result['prompt_id'])
        except ValueError as error:
            run.update(status='failed', error=str(error))
        except OSError as error:
            run.update(status='uncertain', error=f'Submission outcome unknown; check ComfyUI before retrying: {error}')
        self.persist()
        return {'run': run, 'revision': revision}

    def assign_character_folder(self, data):
        if (
            not isinstance(data.get('character_id'), str)
            or not isinstance(data.get('path'), str)
            or type(data.get('recursive', False)) is not bool
        ):
            raise ValueError('Choose a character, local folder, and recursion setting')
        return self.character_catalog.assign_folder(
            data['character_id'],
            data['path'],
            recursive=data.get('recursive', False),
        )

    def start_character_assignment(self, data):
        if (
            not isinstance(data.get('character_id'), str)
            or not isinstance(data.get('path'), str)
            or type(data.get('recursive', False)) is not bool
        ):
            raise ValueError('Choose a character, local folder, and recursion setting')
        job = self.character_catalog.create_assignment_job(
            data['character_id'], data['path'], recursive=data.get('recursive', False)
        )

        def run():
            catalog = CharacterCatalog(self.runtime / 'user/character_catalog')
            try:
                catalog.run_assignment_job(job['id'])
            except Exception:
                pass
            finally:
                catalog.close()
                self.assignment_threads.discard(threading.current_thread())

        worker = threading.Thread(
            target=run, name=f"character-assignment-{job['id'][:8]}", daemon=True
        )
        self.assignment_threads.add(worker)
        worker.start()
        return job

    def character_assignment(self, data):
        job_id = data.get('job_id')
        if not isinstance(job_id, str) or not job_id:
            raise ValueError('Assignment job ID required')
        return self.character_catalog.get_assignment_job(job_id)

    def browse_folders(self, data):
        raw_path = data.get('path')
        path = Path(raw_path) if isinstance(raw_path, str) and raw_path.strip() else (
            self.runtime / 'output' if (self.runtime / 'output').is_dir() else self.runtime
        )
        if not path.is_absolute():
            raise ValueError('Folder browser path must be absolute')
        path = path.resolve()
        if not path.is_dir():
            raise ValueError(f'Folder is unavailable: {path}')
        folders = []
        for child in path.iterdir():
            try:
                if child.is_dir():
                    folders.append({'name': child.name, 'path': str(child.resolve())})
            except OSError:
                continue
        folders.sort(key=lambda item: (item['name'].casefold(), item['name']))
        return {
            'path': str(path),
            'parent': str(path.parent),
            'folders': folders,
        }

    def start_character_discovery(self, data):
        if (
            not isinstance(data.get('character_id'), str)
            or not isinstance(data.get('path'), str)
            or type(data.get('recursive', False)) is not bool
        ):
            raise ValueError('Choose a character, local folder, and recursion setting')
        job = self.character_catalog.create_discovery_job(
            data['character_id'], data['path'], recursive=data.get('recursive', False)
        )

        def run():
            catalog = CharacterCatalog(self.runtime / 'user/character_catalog')
            try:
                catalog.run_discovery_job(job['id'], self.face_analyzer_factory())
            except Exception:
                # The durable job record contains the actionable error for the UI.
                pass
            finally:
                catalog.close()
                self.discovery_threads.discard(threading.current_thread())

        worker = threading.Thread(
            target=run, name=f"character-discovery-{job['id'][:8]}", daemon=True
        )
        self.discovery_threads.add(worker)
        worker.start()
        return job

    def character_discovery(self, data):
        job_id = data.get('job_id')
        if not isinstance(job_id, str) or not job_id:
            raise ValueError('Discovery job ID required')
        limit = data.get('limit', 250)
        offset = data.get('offset', 0)
        if type(limit) is not int or type(offset) is not int:
            raise ValueError('Review page limit and offset must be integers')
        return {
            'job': self.character_catalog.get_discovery_job(job_id),
            'review': self.character_catalog.list_review_items(
                job_id, limit=limit, offset=offset
            ),
            'review_total': self.character_catalog.review_item_count(job_id),
            'pending_total': self.character_catalog.review_item_count(
                job_id, decision='pending'
            ),
            'errors': self.character_catalog.list_discovery_errors(job_id),
        }

    def cancel_character_discovery(self, data):
        job_id = data.get('job_id')
        if not isinstance(job_id, str) or not job_id:
            raise ValueError('Discovery job ID required')
        return self.character_catalog.request_discovery_cancel(job_id)

    def apply_character_recommendations(self, data):
        job_id = data.get('job_id')
        review_ids = data.get('review_ids')
        all_pending = data.get('all_pending', False)
        if (
            not isinstance(job_id, str)
            or type(all_pending) is not bool
            or (not all_pending and not isinstance(review_ids, list))
            or (isinstance(review_ids, list) and any(
                not isinstance(value, str) for value in review_ids
            ))
        ):
            raise ValueError('Discovery job and review item IDs required')
        if all_pending:
            return self.character_catalog.apply_all_pending_recommended(job_id)
        return self.character_catalog.apply_recommended(job_id, review_ids)

    def decide_character_recommendations(self, data):
        job_id = data.get('job_id')
        review_ids = data.get('review_ids')
        decision = data.get('decision')
        if (
            not isinstance(job_id, str)
            or not isinstance(review_ids, list)
            or any(not isinstance(value, str) for value in review_ids)
            or decision not in ('rejected', 'deferred')
        ):
            raise ValueError('Discovery job, review IDs, and reject/defer decision required')
        return self.character_catalog.decide_review_items(
            job_id, review_ids, decision
        )

    def character_duplicates(self, data):
        character_id = data.get('character_id')
        if not isinstance(character_id, str) or not character_id:
            raise ValueError('Character ID required')
        return self.character_catalog.list_exact_duplicate_groups(character_id)

    def quarantine_character_duplicate(self, data):
        location_id = data.get('location_id')
        if not isinstance(location_id, str) or not location_id:
            raise ValueError('Duplicate location ID required')
        return self.character_catalog.quarantine_duplicate(location_id)

    def restore_character_duplicate(self, data):
        operation_id = data.get('operation_id')
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError('Quarantine operation ID required')
        return self.character_catalog.restore_quarantine(operation_id)

    def character_quarantine_history(self, data):
        character_id = data.get('character_id')
        if not isinstance(character_id, str) or not character_id:
            raise ValueError('Character ID required')
        return self.character_catalog.list_quarantine_operations(character_id)

    def character_images(self, data):
        character_id = data.get('character_id')
        if not isinstance(character_id, str) or not character_id:
            raise ValueError('Character ID required')
        limit = data.get('limit', 200)
        offset = data.get('offset', 0)
        query = data.get('query', '')
        sort = data.get('sort', 'oldest')
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not isinstance(offset, int)
            or isinstance(offset, bool)
        ):
            raise ValueError('Image limit and offset must be integers')
        if not isinstance(query, str) or not isinstance(sort, str):
            raise ValueError('Image query and sort must be strings')
        return {
            'items': self.character_catalog.list_character_assets(
                character_id, query=query, sort=sort, limit=limit, offset=offset
            ),
            'total': self.character_catalog.character_asset_count(
                character_id, query=query
            ),
            'limit': limit,
            'offset': offset,
            'query': query,
            'sort': sort,
        }

    def character_families(self, data):
        character_id = data.get('character_id')
        if not isinstance(character_id, str) or not character_id:
            raise ValueError('Character ID required')
        return self.character_catalog.list_families(character_id)

    def create_character_family(self, data):
        character_id = data.get('character_id')
        name = data.get('name')
        asset_ids = data.get('asset_ids', [])
        if (
            not isinstance(character_id, str)
            or not isinstance(name, str)
            or not isinstance(asset_ids, list)
            or any(not isinstance(value, str) for value in asset_ids)
        ):
            raise ValueError('Character, family name, and image IDs required')
        family = self.character_catalog.create_family(character_id, name)
        self.character_catalog.add_family_assets(family['id'], asset_ids)
        return family

    def update_character_family(self, data):
        family_id = data.get('family_id')
        name = data.get('name')
        asset_ids = data.get('asset_ids', [])
        if (
            not isinstance(family_id, str)
            or not isinstance(name, str)
            or not isinstance(asset_ids, list)
            or any(not isinstance(value, str) for value in asset_ids)
        ):
            raise ValueError('Family, name, and image IDs required')
        return self.character_catalog.update_family(family_id, name, asset_ids)

    def set_character_family_source(self, data):
        family_id = data.get('family_id')
        asset_id = data.get('asset_id')
        if not isinstance(family_id, str) or not isinstance(asset_id, str):
            raise ValueError('Family and source image IDs required')
        return self.character_catalog.set_family_source(family_id, asset_id)

    def character_generated(self, data):
        source_asset_id = data.get('source_asset_id')
        if not isinstance(source_asset_id, str) or not source_asset_id:
            raise ValueError('Source image ID required')
        return self.character_catalog.list_generated_from(source_asset_id)

    def use_character_image_in_compose(self, data):
        character_id = data.get('character_id')
        asset_id = data.get('asset_id')
        if not isinstance(character_id, str) or not isinstance(asset_id, str):
            raise ValueError('Character and image IDs required')
        character = next(
            (item for item in self.character_catalog.list_characters()
             if item['id'] == character_id),
            None,
        )
        if not character or not character.get('preset_id'):
            raise ValueError('Character is not linked to a Compose preset')
        if not self.character_catalog.character_has_asset(character_id, asset_id):
            raise ValueError('Image does not belong to this character')
        reference_id = self.register_reference(
            self.character_catalog.asset_path(asset_id)
        )
        preset = next(
            item for item in self.state['presets']
            if item['id'] == character['preset_id']
        )
        if reference_id not in preset['references']:
            preset = {**preset, 'references': [*preset['references'], reference_id]}
            self.save_preset(preset)
        else:
            self.persist()
        return {
            'preset_id': preset['id'],
            'reference_id': reference_id,
            'name': self.state['references'][reference_id]['name'],
        }

    def use_character_image_in_builder(self, data):
        character_id = data.get('character_id')
        asset_id = data.get('asset_id')
        option_id = data.get('option_id')
        if not all(isinstance(value, str) for value in (
            character_id, asset_id, option_id
        )):
            raise ValueError('Character, image, and Builder option IDs required')
        if not self.character_catalog.character_has_asset(character_id, asset_id):
            raise ValueError('Image does not belong to this character')
        reference_id = self.register_reference(
            self.character_catalog.asset_path(asset_id)
        )
        option = self.builder_store.get_option(option_id)
        resources = copy.deepcopy(option.get('resources') or {})
        references = list(resources.get('references') or [])
        if reference_id not in references:
            references.append(reference_id)
        resources['references'] = references
        self.builder_store.update_option(option_id, {'resources': resources})
        self.persist()
        return {
            'option_id': option_id, 'reference_id': reference_id,
            'name': self.state['references'][reference_id]['name'],
        }

    def comfy(self, path, data=None, raw=False, content_type='application/json'):
        url = local_url(self.state['comfy_url']) + path
        payload = json.dumps(data).encode() if data is not None and not isinstance(data, bytes) else data
        request = Request(url, data=payload, headers={'Content-Type': content_type} if payload is not None else {})
        try:
            with self.opener.open(request, timeout=20) as response:
                body = response.read()
                return (body, response.headers.get('Content-Type', 'application/octet-stream')) if raw else json.loads(body)
        except HTTPError as error:
            detail = error.read().decode('utf-8', errors='replace')[:3000]
            raise ValueError(f'ComfyUI returned {error.code}: {detail}') from None

    def status(self):
        try:
            stats = self.comfy('/system_stats')
            return {'online': True, 'url': self.state['comfy_url'], 'devices': stats.get('devices', [])}
        except (OSError, ValueError) as error:
            return {'online': False, 'url': self.state['comfy_url'], 'error': str(error)}

    def save_preset(self, source):
        item = {'id': source.get('id') or uuid.uuid4().hex, 'name': str(source.get('name', '')).strip(),
                'kind': source.get('kind', 'concept'), 'positive': str(source.get('positive', '')),
                'negative': str(source.get('negative', '')), 'references': source.get('references', []), 'loras': source.get('loras', [])}
        if not item['name'] or item['kind'] not in ('character', 'concept', 'environment'):
            raise ValueError('Choose a name and a valid preset type')
        if len(item['name']) > 160 or len(item['positive']) + len(item['negative']) > 50000:
            raise ValueError('Preset text is too long')
        compose([item])
        for ref in item['references']:
            self.reference_path(ref)
        self.state['presets'] = [p for p in self.state['presets'] if p['id'] != item['id']] + [item]
        self.persist()
        self.character_catalog.sync_preset(item, self._catalog_references())
        return item

    def register_reference(self, path):
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError('Choose an existing PNG, JPEG, WebP, or BMP image')
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Reference exceeds 20 MB')
        name = path.name
        content = path.read_bytes()
        folder = self.root / 'references'
        folder.mkdir(exist_ok=True)
        destination = folder / (hashlib.sha256(content).hexdigest() + path.suffix.lower())
        if not destination.exists():
            destination.write_bytes(content)
        path = destination
        for key, existing in self.state['references'].items():
            if existing['path'] == str(path):
                return key
        key = uuid.uuid4().hex
        self.state['references'][key] = {'path': str(path), 'name': name}
        return key

    def reference_path(self, key):
        record = self.state['references'].get(key)
        if not record:
            raise ValueError('Unknown reference')
        path = Path(record['path'])
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError('The reference image is missing or unsupported')
        return path

    def upload(self, data):
        extension = Path(data.get('name', '')).suffix.lower()
        if extension not in IMAGE_EXTENSIONS:
            raise ValueError('Supported references: PNG, JPEG, WebP, BMP')
        content = base64.b64decode(data['content'], validate=True)
        if len(content) > 20 * 1024 * 1024:
            raise ValueError('Reference exceeds 20 MB')
        signatures = {'.png': content.startswith(b'\x89PNG\r\n\x1a\n'), '.jpg': content.startswith(b'\xff\xd8'),
                      '.jpeg': content.startswith(b'\xff\xd8'), '.bmp': content.startswith(b'BM'),
                      '.webp': content[:4] == b'RIFF' and content[8:12] == b'WEBP'}
        if not signatures[extension]:
            raise ValueError('File contents do not match its image extension')
        folder = self.root / 'references'
        folder.mkdir(exist_ok=True)
        path = folder / (hashlib.sha256(content).hexdigest() + extension)
        path.write_bytes(content)
        key = self.register_reference(path)
        self.state['references'][key]['name'] = Path(data['name']).name
        self.persist()
        return {'id': key, 'name': self.state['references'][key]['name']}

    def save_workflow(self, data):
        graph = validate_graph(data['graph'])
        adapter = data.get('adapter') or suggest_adapter(graph)
        item = {'id': data.get('id') or uuid.uuid4().hex, 'name': str(data.get('name', 'Workflow')).strip(),
                'graph': graph, 'adapter': adapter}
        if not item['name']:
            raise ValueError('Workflow needs a name')
        self.state['workflows'] = [w for w in self.state['workflows'] if w['id'] != item['id']] + [item]
        self.persist()
        return {**item, 'fields': fields(graph)}

    def library(self):
        workflows = []
        base = self.runtime / 'user/default/api_workflows'
        if base.is_dir():
            workflows = [str(p.relative_to(base)) for p in base.rglob('*.json')][:300]
        collections = []
        catalog = self.runtime / 'user/reference_library/catalog.sqlite3'
        if catalog.exists():
            with closing(sqlite3.connect(catalog.as_uri() + '?mode=ro', uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                collections = [dict(row) for row in connection.execute('SELECT id, name, kind FROM collections ORDER BY name')]
        return {'workflows': workflows, 'collections': collections}

    def import_library(self, data):
        if data.get('workflow'):
            base = (self.runtime / 'user/default/api_workflows').resolve()
            path = (base / data['workflow']).resolve()
            if not path.is_relative_to(base) or path.suffix.lower() != '.json':
                raise ValueError('Invalid workflow path')
            graph = json.loads(path.read_text(encoding='utf-8-sig'))
            return self.save_workflow({'name': path.stem, 'graph': graph})
        catalog = self.runtime / 'user/reference_library/catalog.sqlite3'
        with closing(sqlite3.connect(catalog.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute('SELECT * FROM collections WHERE id=?', (data['collection'],)).fetchone()
            if not row:
                raise ValueError('Collection not found')
            profile = connection.execute('SELECT * FROM profiles WHERE collection_id=? ORDER BY CASE WHEN name=\'Default\' THEN 0 ELSE 1 END LIMIT 1', (row['id'],)).fetchone()
            images = connection.execute('SELECT i.relative_path FROM images i JOIN collection_images c ON i.id=c.image_id WHERE c.collection_id=? ORDER BY c.position LIMIT 200', (row['id'],)).fetchall()
            refs = [self.register_reference(catalog.parent / i['relative_path']) for i in images]
            loras = []
            if profile:
                loras = [{'name': l['lora_name'], 'model': l['strength_model'], 'clip': l['strength_clip'], 'enabled': bool(l['enabled'])}
                         for l in connection.execute('SELECT * FROM profile_loras WHERE profile_id=? ORDER BY position', (profile['id'],))]
            return self.save_preset({'name': row['name'], 'kind': 'character' if row['kind'] == 'subject' else 'environment',
                                     'positive': profile['positive_prompt'] if profile else '', 'negative': profile['negative_prompt'] if profile else '',
                                     'references': refs, 'loras': loras})

    def composition(self, data):
        by_id = {p['id']: p for p in self.state['presets']}
        try:
            selected = [by_id[key] for key in data.get('preset_ids', [])]
        except KeyError:
            raise ValueError('A selected preset no longer exists') from None
        result = compose(selected, data.get('extra', ''), data.get('negative', ''))
        if 'reference_ids' in data:
            result['references'] = data['reference_ids']
        for reference in result['references']:
            self.reference_path(reference)
        return result

    def plan_runs(self, data):
        composition = self.composition(data)
        seed = int(data.get('seed', 1))
        count = int(data.get('count', 1))
        batch = data.get('reference_batch')
        if batch is not None:
            if count != 1:
                raise ValueError('Run each image once: seed variations must be set to 1')
            if not isinstance(batch, dict):
                raise ValueError('Invalid character reference batch')
            preset = next((p for p in self.state['presets'] if p['id'] == batch.get('preset_id') and p['id'] in data.get('preset_ids', [])), None)
            if not preset or preset['kind'] != 'character':
                raise ValueError('Choose a selected character for the reference batch')
            images, slot = batch.get('image_ids'), batch.get('slot')
            if (not isinstance(images, list) or not 1 <= len(images) <= 200
                    or any(not isinstance(key, str) or key not in preset['references'] for key in images)
                    or len(set(images)) != len(images)):
                raise ValueError('Select 1–200 distinct images belonging to this character')
            if (type(slot) is not int or not 0 <= slot < len(composition['references'])
                    or composition['references'][slot] != images[0]):
                raise ValueError('The batch reference slot must contain the first selected character image')
            plans = []
            for key in images:
                self.reference_path(key)
                variant = copy.deepcopy(composition)
                variant['references'][slot] = key
                plans.append({'composition': variant, 'seed': seed, 'reference_id': key,
                              'reference_label': self.state['references'][key]['name']})
            return plans
        if not 1 <= count <= 8:
            raise ValueError('Choose 1–8 seed variations')
        if seed + count - 1 > 2**53 - 1:
            raise ValueError('Variation seeds exceed the safe integer range')
        return [{'composition': copy.deepcopy(composition), 'seed': seed + i} for i in range(count)]

    def preview(self, data):
        plans = self.plan_runs(data)
        composition = plans[0]['composition']
        workflow = next((w for w in self.state['workflows'] if w['id'] == data.get('workflow_id')), None)
        result = {'composition': composition, 'graph': None, 'run_count': len(plans),
                  'reference_plan': [{'reference_id': p.get('reference_id'), 'reference_label': p.get('reference_label'), 'seed': p['seed']} for p in plans]}
        if workflow:
            if len(plans) > 1 and not data.get('reference_batch') and not workflow['adapter'].get('seed'):
                raise ValueError('Map a seed field before requesting seed variations')
            for plan in plans:
                c = plan['composition']
                symbolic = {**c, 'references': [f'preset-studio/{key}{self.reference_path(key).suffix.lower()}' for key in c['references']]}
                graph = compile_graph(workflow['graph'], workflow['adapter'], symbolic, plan['seed'])
                if result['graph'] is None:
                    result['graph'] = graph
        return result

    def upload_to_comfy(self, key):
        path = self.reference_path(key)
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError('Reference exceeds 20 MB')
        name = f'{key}{path.suffix.lower()}'
        boundary = uuid.uuid4().hex
        pieces = []
        for field, value in [('type', 'input'), ('subfolder', 'preset-studio'), ('overwrite', 'false')]:
            pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode())
        pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\nContent-Type: {mimetypes.guess_type(name)[0]}\r\n\r\n'.encode())
        pieces.extend([path.read_bytes(), f'\r\n--{boundary}--\r\n'.encode()])
        response = self.comfy('/upload/image', b''.join(pieces), content_type=f'multipart/form-data; boundary={boundary}')
        return '/'.join(filter(None, [response.get('subfolder'), response['name']]))

    def _lineage_sources(self, preset_ids, reference_ids):
        sources = []
        for preset_id in preset_ids:
            preset = next((item for item in self.state['presets'] if item['id'] == preset_id), None)
            if not preset or preset.get('kind') != 'character':
                continue
            character = self.character_catalog.character_for_preset(preset_id)
            if not character:
                continue
            for reference_id in reference_ids:
                if reference_id not in preset.get('references', []):
                    continue
                path = self.reference_path(reference_id)
                asset_id = self.character_catalog.asset_id_for_path(path)
                if asset_id is None:
                    asset_id = self.character_catalog.register_file(path, kind='managed')['asset_id']
                    self.character_catalog.assign_asset(character['id'], asset_id, assignment_type='imported')
                sources.append({
                    'character_id': character['id'],
                    'source_asset_id': asset_id,
                    'reference_id': reference_id,
                })
        return [dict(item) for item in {(
            item['character_id'], item['source_asset_id'], item['reference_id']
        ): item for item in sources}.values()]

    def _local_output_path(self, asset):
        if asset.get('type') != 'output' or asset.get('kind') != 'images':
            return None
        filename = asset.get('filename')
        subfolder = asset.get('subfolder', '')
        if not isinstance(filename, str) or not filename or not isinstance(subfolder, str):
            return None
        root = (self.runtime / 'output').resolve()
        path = (root / subfolder / filename).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        return path

    def record_run_lineage(self, run):
        recorded = []
        for output in run.get('outputs', []):
            path = self._local_output_path(output)
            if path is None:
                continue
            for source in run.get('lineage_sources', []):
                recorded.append(self.character_catalog.record_generation(
                    run['id'], source['character_id'], source['source_asset_id'], path
                ))
        return recorded

    def submit(self, data):
        preview = self.preview(data)
        if not preview['graph']:
            raise ValueError('Choose and map a workflow first')
        workflow = next(w for w in self.state['workflows'] if w['id'] == data['workflow_id'])
        plans = self.plan_runs(data)
        # Upload is only to the selected local ComfyUI, never a remote service.
        uploaded = {key: self.upload_to_comfy(key) for key in dict.fromkeys(key for p in plans for key in p['composition']['references'])}
        info = self.comfy('/object_info')
        for plan in plans:
            composition = copy.deepcopy(plan['composition'])
            composition['references'] = [uploaded[key] for key in composition['references']]
            graph = compile_graph(workflow['graph'], workflow['adapter'], composition, plan['seed'])
            validate_live(graph, info)
            plan['graph'] = graph
        created = []
        for plan in plans:
            graph = plan['graph']
            run_request = {**data, 'seed': plan['seed'], 'count': 1, 'reference_ids': plan['composition']['references']}
            run_request.pop('reference_batch', None)
            run = {'id': uuid.uuid4().hex, 'created': time.time(), 'name': workflow['name'], 'status': 'submitting',
                   'seed': plan['seed'], 'composition': plan['composition'], 'request': run_request,
                   'graph': graph, 'comfy_url': self.state['comfy_url'], 'outputs': [],
                   'lineage_sources': self._lineage_sources(
                       data.get('preset_ids', []), plan['composition']['references']
                   )}
            if plan.get('reference_id'):
                run.update(reference_id=plan['reference_id'], reference_label=plan['reference_label'])
            run['preset_snapshots'] = copy.deepcopy([next(p for p in self.state['presets'] if p['id'] == key) for key in data.get('preset_ids', [])])
            run['workflow_snapshot'] = copy.deepcopy(workflow)
            self.state['runs'].insert(0, run)
            self.persist()
            try:
                result = self.comfy('/prompt', {'prompt': graph, 'client_id': 'preset-studio', 'extra_data': {'preset_studio_run': run['id']}})
                if not result.get('prompt_id'):
                    raise ValueError(f'ComfyUI did not return a prompt ID: {result}')
                run.update(status='queued', prompt_id=result['prompt_id'])
            except ValueError as error:
                run.update(status='failed', error=str(error))
            except OSError as error:
                run.update(status='uncertain', error=f'Submission outcome unknown; check ComfyUI before retrying: {error}')
            self.persist()
            created.append(run)
            if run['status'] != 'queued':
                break
        return {'runs': created}

    def get_run(self, data):
        run = next((r for r in self.state['runs'] if r['id'] == data['id']), None)
        if not run:
            raise ValueError('Run not found')
        return run

    def restore(self, data):
        run = self.get_run(data)
        if 'workflow_snapshot' not in run:
            raise ValueError('This run does not contain restorable snapshots')
        request = copy.deepcopy(run['request'])
        request['preset_ids'] = []
        for snapshot in run['preset_snapshots']:
            preset = copy.deepcopy(snapshot)
            preset['id'] = uuid.uuid4().hex
            preset['name'] += ' · restored'
            saved = self.save_preset(preset)
            request['preset_ids'].append(saved['id'])
        workflow = copy.deepcopy(run['workflow_snapshot'])
        workflow['id'] = uuid.uuid4().hex
        workflow['name'] += ' · restored'
        request['workflow_id'] = self.save_workflow(workflow)['id']
        request.setdefault('reference_ids', [])
        request.setdefault('extra', '')
        request.setdefault('negative', '')
        return request

    def refresh_runs(self):
        queue = self.comfy('/queue')
        running = {item[1] for item in queue.get('queue_running', [])}
        pending = {item[1] for item in queue.get('queue_pending', [])}
        for run in self.state['runs']:
            if run['status'] not in ('queued', 'running') or run['comfy_url'] != self.state['comfy_url']:
                continue
            history = self.comfy('/history/' + quote(run['prompt_id'], safe=''))
            entry = history.get(run['prompt_id'])
            if not entry:
                if run['prompt_id'] in running:
                    run['status'] = 'running'
                elif run['prompt_id'] in pending:
                    run['status'] = 'queued'
                else:
                    run.update(status='missing', error='This run is absent from the ComfyUI queue and history. It may have been removed or the server restarted. It was not resubmitted.')
                continue
            status = entry.get('status', {})
            run['status'] = 'failed' if status.get('status_str') == 'error' else ('done' if status.get('completed') else 'running')
            if run['status'] == 'failed':
                run['error'] = json.dumps(status.get('messages', []))[:3000]
            run['outputs'] = []
            for output in entry.get('outputs', {}).values():
                for kind in ('images', 'gifs', 'videos'):
                    for asset in output.get(kind, []):
                        if isinstance(asset, dict) and asset.get('filename'):
                            run['outputs'].append({**asset, 'kind': kind})
            if run['status'] == 'done':
                if run.get('builder_revision_id'):
                    self.builder_store.attach_revision_outputs(
                        run['builder_revision_id'], [
                            {**asset, 'run_id': run['id'], 'output_index': index}
                            for index, asset in enumerate(run['outputs'])
                        ]
                    )
                try:
                    self.record_run_lineage(run)
                    run.pop('lineage_error', None)
                except (ValueError, OSError, sqlite3.Error) as error:
                    run['lineage_error'] = str(error)
        self.persist()
        return self.public_runs()

    def public_runs(self):
        return [{key: value for key, value in run.items() if key not in ('graph', 'preset_snapshots', 'workflow_snapshot')} for run in self.state['runs'][:100]]

    def public_state(self):
        settings = self.character_catalog.settings()
        characters = []
        for character in self.character_catalog.list_characters():
            characters.append({
                **character,
                'asset_count': self.character_catalog.character_asset_count(character['id']),
                'discovery_jobs': self.character_catalog.list_discovery_jobs(character['id'])[:10],
                'assignment_jobs': self.character_catalog.list_assignment_jobs(character['id'])[:10],
            })
        return {'presets': self.state['presets'], 'workflows': [{**w, 'fields': fields(w['graph'])} for w in self.state['workflows']],
                'comfy_url': self.state['comfy_url'], 'references': {k: {'name': v['name']} for k, v in self.state['references'].items()},
                'runs': self.public_runs(), 'characters': characters,
                'character_catalog': {'root': str(self.character_catalog.root), 'watch_enabled': bool(settings['watch_enabled'])}}


def make_server(studio, port):
    class StudioServer(ThreadingHTTPServer):
        def server_close(self):
            try:
                super().server_close()
            finally:
                studio.close()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(
            self, data, content_type='application/json', status=200,
            cache_control='no-store'
        ):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode() if content_type == 'application/json' else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', cache_control)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, write=False):
            host = self.headers.get('Host', '')
            valid = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if host not in valid:
                self.send({'error': 'Local host required'}, status=403)
                return False
            if write and (self.headers.get('Origin') not in (None, f'http://{host}') or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.send({'error': 'Cross-origin writes are blocked'}, status=403)
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            try:
                route = urlsplit(self.path)
                args = parse_qs(route.query)
                if route.path == '/api/health':
                    return self.send({'app': 'preset-studio', 'version': 1})
                if route.path == '/api/state':
                    with studio.lock:
                        return self.send(studio.public_state())
                if route.path == '/api/status':
                    return self.send(studio.status())
                if route.path == '/api/library':
                    return self.send(studio.library())
                if route.path == '/api/models':
                    info = studio.comfy('/object_info')
                    loader = info.get('LoraLoader', info.get('LoraLoaderModelOnly', {}))
                    return self.send({'loras': loader.get('input', {}).get('required', {}).get('lora_name', [[]])[0], 'nodes': info})
                if route.path.startswith('/api/reference/'):
                    path = studio.reference_path(route.path.rsplit('/', 1)[-1])
                    return self.send(path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
                if route.path.startswith('/api/character/asset/'):
                    path = studio.character_catalog.asset_path(route.path.rsplit('/', 1)[-1])
                    return self.send(path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
                if route.path.startswith('/api/character/thumbnail/'):
                    asset_id = route.path.rsplit('/', 1)[-1]
                    size = int(args.get('size', ['256'])[0])
                    path = studio.character_catalog.thumbnail_path(asset_id, size=size)
                    return self.send(
                        path.read_bytes(), 'image/webp',
                        cache_control='private, max-age=31536000, immutable'
                    )
                if route.path.startswith('/api/character/review-face/'):
                    review_id = route.path.rsplit('/', 1)[-1]
                    size = int(args.get('size', ['192'])[0])
                    path = studio.character_catalog.review_face_thumbnail_path(
                        review_id, size=size
                    )
                    return self.send(
                        path.read_bytes(), 'image/webp',
                        cache_control='private, max-age=31536000, immutable'
                    )
                if route.path == '/api/output':
                    run = next((r for r in studio.state['runs'] if r['id'] == args.get('run', [''])[0]), None)
                    if not run or run['comfy_url'] != studio.state['comfy_url']:
                        raise ValueError('Connect to the original ComfyUI server to view this output')
                    asset = run['outputs'][int(args.get('index', ['0'])[0])]
                    query = urlencode({key: asset.get(key, '') for key in ('filename', 'subfolder', 'type')})
                    body, mime = studio.comfy('/view?' + query, raw=True)
                    return self.send(body, mime)
                names = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/reference-selection.mjs': 'reference-selection.mjs', '/studio-view-model.mjs': 'studio-view-model.mjs'}
                if route.path in names:
                    path = WEB / names[route.path]
                    return self.send(path.read_bytes(), {'html': 'text/html; charset=utf-8', 'js': 'text/javascript', 'mjs': 'text/javascript', 'css': 'text/css'}[path.suffix[1:]])
                self.send({'error': 'Not found'}, status=404)
            except (ValueError, OSError, KeyError, IndexError, sqlite3.Error) as error:
                self.send({'error': str(error)}, status=400)

        def do_POST(self):
            if not self.allowed(write=True):
                return
            try:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.send({'error': 'JSON required'}, status=415)
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 30 * 1024 * 1024:
                    return self.send({'error': 'Request must be 1 byte–30 MB'}, status=413)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('JSON object required')
                with studio.lock:
                    actions = {'/api/preset': studio.save_preset, '/api/workflow': studio.save_workflow,
                               '/api/preview': studio.preview, '/api/submit': studio.submit,
                               '/api/upload': studio.upload, '/api/import': studio.import_library,
                               '/api/character/assign-folder': studio.assign_character_folder,
                               '/api/character/assignment/start': studio.start_character_assignment,
                               '/api/character/assignment': studio.character_assignment,
                               '/api/builder/state': studio.builder_state,
                               '/api/builder/catalog': studio.builder_catalog,
                               '/api/builder/experiment/create': studio.create_builder_experiment,
                               '/api/builder/option/update': studio.update_builder_option,
                               '/api/builder/option/branch': studio.branch_builder_option,
                               '/api/builder/option/delete': studio.delete_builder_option,
                               '/api/builder/workflow/attach': studio.attach_builder_workflow,
                               '/api/builder/workflow/basic': studio.create_builder_basic_workflow,
                               '/api/builder/workflow/save': studio.save_builder_workflow,
                               '/api/builder/favorite/toggle': studio.toggle_builder_favorite,
                               '/api/builder/bundle/save': studio.save_builder_bundle,
                               '/api/builder/generate': studio.generate_builder_option,
                               '/api/character/discovery/start': studio.start_character_discovery,
                               '/api/character/discovery': studio.character_discovery,
                               '/api/character/discovery/cancel': studio.cancel_character_discovery,
                               '/api/character/review/apply': studio.apply_character_recommendations,
                               '/api/character/review/decide': studio.decide_character_recommendations,
                               '/api/character/duplicates': studio.character_duplicates,
                               '/api/character/duplicate/quarantine': studio.quarantine_character_duplicate,
                               '/api/character/duplicate/restore': studio.restore_character_duplicate,
                               '/api/character/quarantine/history': studio.character_quarantine_history,
                               '/api/character/images': studio.character_images,
                               '/api/character/families': studio.character_families,
                               '/api/character/family/create': studio.create_character_family,
                               '/api/character/family/update': studio.update_character_family,
                               '/api/character/family/source': studio.set_character_family_source,
                               '/api/character/generated': studio.character_generated,
                               '/api/character/use-in-compose': studio.use_character_image_in_compose,
                               '/api/character/use-in-builder': studio.use_character_image_in_builder,
                               '/api/folders': studio.browse_folders,
                               '/api/restore': studio.restore, '/api/run': studio.get_run,
                               '/api/settings': lambda d: studio.configure(d['comfy_url']),
                               '/api/refresh': lambda d: studio.refresh_runs()}
                    action = actions.get(self.path)
                    if not action:
                        return self.send({'error': 'Not found'}, status=404)
                    return self.send(action(data))
            except (ValueError, OSError, KeyError, TypeError, IndexError, sqlite3.Error) as error:
                self.send({'error': str(error)}, status=400)
    return StudioServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Local Preset Studio')
    parser.add_argument('--runtime', type=Path, required=True, help='Live ComfyUI base directory (private state lives here)')
    parser.add_argument('--port', type=int, default=8791)
    options = parser.parse_args()
    server = make_server(Studio(options.runtime), options.port)
    print(f'Preset Studio: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
