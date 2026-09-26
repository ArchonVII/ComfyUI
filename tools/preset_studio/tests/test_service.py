import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'service.py').exists(), 'Local Studio service is not implemented')
        import service
        self.service = service
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.studio = service.Studio(self.runtime)

    def test_state_is_persisted_without_source_mutation(self):
        preset = self.studio.save_preset({'name': 'Test character', 'kind': 'character', 'positive': 'person', 'references': [], 'loras': []})
        restored = self.service.Studio(self.runtime)
        self.assertIn(preset, restored.state['presets'])
        self.assertTrue((self.runtime / 'user/preset_studio/state.json').exists())

    def test_nonlocal_backend_is_rejected(self):
        for url in ['https://example.com', 'http://127.0.0.1.evil.test:8188', 'http://user:pass@127.0.0.1:8188', 'http://127.0.0.1:8188/redirect']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.studio.configure(url)

    def test_bad_state_is_not_overwritten(self):
        self.studio.persist()
        path = self.runtime / 'user/preset_studio/state.json'
        path.write_text('{bad', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.service.Studio(self.runtime)
        self.assertEqual(path.read_text(), '{bad')

    def test_http_rejects_cross_origin_and_serves_state(self):
        server = self.service.make_server(self.studio, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(base + '/api/state') as response:
            self.assertIn('presets', json.load(response))
        request = urllib.request.Request(base + '/api/settings', data=b'{"comfy_url":"http://127.0.0.1:8188"}', headers={'Content-Type': 'application/json', 'Origin': 'https://evil.test'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_reference_paths_are_restricted_to_registered_files(self):
        with self.assertRaises(ValueError):
            self.studio.reference_path('../state.json')

    def test_imported_reference_is_a_stable_copy(self):
        source = self.runtime / 'source.png'
        source.write_bytes(b'\x89PNG\r\n\x1a\noriginal')
        key = self.studio.register_reference(source)
        source.write_bytes(b'changed')
        self.assertEqual(self.studio.reference_path(key).read_bytes(), b'\x89PNG\r\n\x1a\noriginal')

    def test_restore_uses_snapshots_after_presets_and_workflows_change(self):
        self.assertTrue(hasattr(self.studio, 'restore'), 'Run snapshot restoration is not implemented')
        self.studio.state['runs'].append({'id': 'r1', 'status': 'done', 'request': {'preset_ids': ['old'], 'reference_ids': [], 'extra': 'extra', 'negative': '', 'seed': 7},
            'preset_snapshots': [{'id': 'old', 'name': 'Before', 'kind': 'concept', 'positive': 'original', 'negative': '', 'references': [], 'loras': []}],
            'workflow_snapshot': {'id': 'w1', 'name': 'Original workflow', 'adapter': {}, 'graph': {'1': {'class_type': 'Test', 'inputs': {}}}}})
        restored = self.studio.restore({'id': 'r1'})
        preset = next(p for p in self.studio.state['presets'] if p['id'] == restored['preset_ids'][0])
        self.assertEqual(preset['positive'], 'original')
        self.assertNotEqual(restored['workflow_id'], 'w1')

    def test_seed_variations_capture_graph_and_stop_on_uncertain_submission(self):
        calls = []
        info = {'Text': {'input': {'required': {'text': ['STRING']}}, 'output': []},
                'Sample': {'input': {'required': {'seed': ['INT']}}, 'output': []}}
        def backend(path, data=None, **kwargs):
            if path == '/object_info':
                return info
            calls.append(copy_json(data))
            if len(calls) == 2:
                raise OSError('connection lost')
            return {'prompt_id': 'p1'}
        self.studio.comfy = backend
        preset = self.studio.save_preset({'name': 'A', 'kind': 'concept', 'positive': 'portrait'})
        workflow = self.studio.save_workflow({'name': 'W', 'graph': {'1': {'class_type': 'Text', 'inputs': {'text': ''}}, '2': {'class_type': 'Sample', 'inputs': {'seed': 0}}}, 'adapter': {'positive': ['1.text'], 'seed': ['2.seed']}})
        result = self.studio.submit({'workflow_id': workflow['id'], 'preset_ids': [preset['id']], 'reference_ids': [], 'seed': 10, 'count': 4})
        self.assertEqual([r['status'] for r in result['runs']], ['queued', 'uncertain'])
        self.assertEqual([c['prompt']['2']['inputs']['seed'] for c in calls], [10, 11])
        self.assertIn('preset_snapshots', result['runs'][0])
        self.assertEqual(workflow['graph']['2']['inputs']['seed'], 0)

    def test_history_refresh_distinguishes_running_and_removed_jobs(self):
        self.studio.state['runs'] = [
            {'id': 'a', 'prompt_id': 'p1', 'status': 'queued', 'comfy_url': self.studio.state['comfy_url'], 'outputs': []},
            {'id': 'b', 'prompt_id': 'p2', 'status': 'queued', 'comfy_url': self.studio.state['comfy_url'], 'outputs': []},
        ]
        self.studio.comfy = lambda path: {'queue_running': [[1, 'p1']], 'queue_pending': []} if path == '/queue' else {}
        result = self.studio.refresh_runs()
        self.assertEqual([r['status'] for r in result], ['running', 'missing'])


def copy_json(value):
    return json.loads(json.dumps(value))


if __name__ == '__main__':
    unittest.main()
