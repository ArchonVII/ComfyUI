"""Exercise real local HTTP requests without loading models or submitting GPU work."""
import base64
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Studio, make_server


class PipelineTests(unittest.TestCase):
    def test_upload_two_seed_variations_results_and_restore_over_http(self):
        submitted = []
        class FakeComfy(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def reply(self, value):
                body = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                if self.path == '/object_info':
                    return self.reply({'LoadImage': {'input': {'required': {'image': [['preset-studio/ref.png']]}}, 'output': ['IMAGE']},
                        'Sample': {'input': {'required': {'image': ['IMAGE'], 'seed': ['INT'], 'text': ['STRING']}}, 'output': []}})
                if self.path.startswith('/history/'):
                    key = self.path.rsplit('/', 1)[-1]
                    return self.reply({key: {'status': {'completed': True, 'status_str': 'success'}, 'outputs': {'2': {'images': [{'filename': 'result.png', 'type': 'output', 'subfolder': ''}]}}}})
                self.reply({})
            def do_POST(self):
                content = self.rfile.read(int(self.headers['Content-Length']))
                if self.path == '/upload/image':
                    self.assert_upload = b'Content-Disposition' in content
                    return self.reply({'name': 'ref.png', 'subfolder': 'preset-studio'})
                submitted.append(json.loads(content))
                self.reply({'prompt_id': f'p{len(submitted)}'})
        backend = ThreadingHTTPServer(('127.0.0.1', 0), FakeComfy)
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        self.addCleanup(backend.server_close)
        self.addCleanup(backend.shutdown)
        with tempfile.TemporaryDirectory() as root:
            studio = Studio(root)
            studio.configure(f'http://127.0.0.1:{backend.server_port}')
            server = make_server(studio, 0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            def post(route, body):
                request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/{route}', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request) as response:
                    return json.load(response)
            try:
                ref = post('upload', {'name': 'ref.png', 'content': base64.b64encode(b'\x89PNG\r\n\x1a\nsample').decode()})
                preset = post('preset', {'name': 'Test', 'positive': 'portrait', 'references': [ref['id']]})
                workflow = post('workflow', {'name': 'Test workflow', 'graph': {
                    '1': {'class_type': 'LoadImage', 'inputs': {'image': 'old.png'}},
                    '2': {'class_type': 'Sample', 'inputs': {'image': ['1', 0], 'seed': 0, 'text': ''}},
                }, 'adapter': {'positive': ['2.text'], 'seed': ['2.seed'], 'references': ['1.image']}})
                runs = post('submit', {'preset_ids': [preset['id']], 'reference_ids': [ref['id']], 'workflow_id': workflow['id'], 'seed': 20, 'count': 2})['runs']
                self.assertEqual([r['status'] for r in runs], ['queued', 'queued'])
                self.assertEqual([p['prompt']['2']['inputs']['seed'] for p in submitted], [20, 21])
                self.assertEqual(submitted[0]['prompt']['1']['inputs']['image'], 'preset-studio/ref.png')
                results = post('refresh', {})
                self.assertTrue(all(r['status'] == 'done' and r['outputs'] for r in results))
                restored = post('restore', {'id': runs[0]['id']})
                self.assertEqual(post('preview', restored)['composition']['positive'], 'portrait')
                self.assertEqual(post('run', {'id': runs[0]['id']})['graph']['2']['inputs']['seed'], 20)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
