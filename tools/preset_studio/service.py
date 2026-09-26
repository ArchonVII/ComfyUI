"""Loopback-only standalone service. Run with --runtime pointing at ComfyUI."""
import argparse
import base64
import copy
import hashlib
import json
import mimetypes
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

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
        # A process stop during submission leaves its outcome uncertain. Never resubmit.
        changed = False
        for run in self.state['runs']:
            if run['status'] == 'submitting':
                run.update(status='uncertain', error='Service stopped during submission. Check ComfyUI history before retrying.')
                changed = True
        if changed:
            self.persist()

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

    def preview(self, data):
        composition = self.composition(data)
        workflow = next((w for w in self.state['workflows'] if w['id'] == data.get('workflow_id')), None)
        result = {'composition': composition, 'graph': None}
        if workflow:
            symbolic = {**composition, 'references': [f'preset-studio/{key}{self.reference_path(key).suffix.lower()}' for key in composition['references']]}
            result['graph'] = compile_graph(workflow['graph'], workflow['adapter'], symbolic, int(data.get('seed', 1)))
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

    def submit(self, data):
        preview = self.preview(data)
        if not preview['graph']:
            raise ValueError('Choose and map a workflow first')
        workflow = next(w for w in self.state['workflows'] if w['id'] == data['workflow_id'])
        count = int(data.get('count', 1))
        if not 1 <= count <= 8:
            raise ValueError('Choose 1–8 variations')
        if count > 1 and not workflow['adapter'].get('seed'):
            raise ValueError('Map a seed field before requesting seed variations')
        seed = int(data.get('seed', 1))
        if seed + count - 1 > 2**53 - 1:
            raise ValueError('Variation seeds exceed the safe integer range')
        composition = copy.deepcopy(preview['composition'])
        # Upload is only to the selected local ComfyUI, never a remote service.
        composition['references'] = [self.upload_to_comfy(key) for key in composition['references']]
        info = self.comfy('/object_info')
        graphs = [compile_graph(workflow['graph'], workflow['adapter'], composition, seed + i) for i in range(count)]
        for graph in graphs:
            validate_live(graph, info)
        created = []
        for i, graph in enumerate(graphs):
            run = {'id': uuid.uuid4().hex, 'created': time.time(), 'name': workflow['name'], 'status': 'submitting',
                   'seed': seed + i, 'composition': preview['composition'], 'request': {**data, 'seed': seed + i, 'count': 1},
                   'graph': graph, 'comfy_url': self.state['comfy_url'], 'outputs': []}
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
        self.persist()
        return self.public_runs()

    def public_runs(self):
        return [{key: value for key, value in run.items() if key not in ('graph', 'preset_snapshots', 'workflow_snapshot')} for run in self.state['runs'][:100]]

    def public_state(self):
        return {'presets': self.state['presets'], 'workflows': [{**w, 'fields': fields(w['graph'])} for w in self.state['workflows']],
                'comfy_url': self.state['comfy_url'], 'references': {k: {'name': v['name']} for k, v in self.state['references'].items()},
                'runs': self.public_runs()}


def make_server(studio, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, data, content_type='application/json', status=200):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode() if content_type == 'application/json' else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
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
                if route.path == '/api/output':
                    run = next((r for r in studio.state['runs'] if r['id'] == args.get('run', [''])[0]), None)
                    if not run or run['comfy_url'] != studio.state['comfy_url']:
                        raise ValueError('Connect to the original ComfyUI server to view this output')
                    asset = run['outputs'][int(args.get('index', ['0'])[0])]
                    query = urlencode({key: asset.get(key, '') for key in ('filename', 'subfolder', 'type')})
                    body, mime = studio.comfy('/view?' + query, raw=True)
                    return self.send(body, mime)
                names = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
                if route.path in names:
                    path = WEB / names[route.path]
                    return self.send(path.read_bytes(), {'html': 'text/html; charset=utf-8', 'js': 'text/javascript', 'css': 'text/css'}[path.suffix[1:]])
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
                               '/api/restore': studio.restore, '/api/run': studio.get_run,
                               '/api/settings': lambda d: studio.configure(d['comfy_url']),
                               '/api/refresh': lambda d: studio.refresh_runs()}
                    action = actions.get(self.path)
                    if not action:
                        return self.send({'error': 'Not found'}, status=404)
                    return self.send(action(data))
            except (ValueError, OSError, KeyError, TypeError, IndexError, sqlite3.Error) as error:
                self.send({'error': str(error)}, status=400)
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


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
