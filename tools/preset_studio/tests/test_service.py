import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

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
        self.addCleanup(self.studio.close)

    def test_character_presets_sync_into_reusable_catalog_and_public_state(self):
        source = self.runtime / 'alice.png'
        source.write_bytes(b'\x89PNG\r\n\x1a\nalice')
        reference_id = self.studio.register_reference(source)
        saved = self.studio.save_preset({
            'name': 'Alice',
            'kind': 'character',
            'positive': 'silver hair',
            'negative': '',
            'references': [reference_id],
            'loras': [],
        })

        characters = self.studio.character_catalog.list_characters()
        self.assertEqual(len(characters), 1)
        self.assertEqual(characters[0]['preset_id'], saved['id'])
        self.assertEqual(len(self.studio.character_catalog.list_character_assets(characters[0]['id'])), 1)
        public = self.studio.public_state()
        self.assertEqual(public['characters'][0]['name'], 'Alice')
        self.assertFalse(public['character_catalog']['watch_enabled'])
        self.assertEqual(
            Path(public['character_catalog']['root']),
            self.runtime / 'user/character_catalog',
        )

        saved['name'] = 'Alice Prime'
        self.studio.save_preset(saved)
        self.assertEqual(self.studio.character_catalog.list_characters()[0]['name'], 'Alice Prime')

        reopened = self.service.Studio(self.runtime)
        self.addCleanup(reopened.close)
        self.assertEqual(len(reopened.character_catalog.list_characters()), 1)

    def test_builder_experiment_lifecycle_is_available_through_service(self):
        experiment = self.studio.create_builder_experiment({'name': 'Portrait lab'})
        option = experiment['options'][0]
        updated = self.studio.update_builder_option({
            'option_id': option['id'],
            'changes': {'prompt_board': {'blocks': [{
                'id': 'light', 'lane': 'positive', 'text': 'window light',
                'weight': 1, 'enabled': True,
            }]}}
        })
        branch = self.studio.branch_builder_option({
            'option_id': option['id'], 'name': 'Variation B',
        })
        basic = self.studio.create_builder_basic_workflow({'option_id': branch['id']})
        favorites = self.studio.toggle_builder_favorite({'item_id': 'builtin:pose.wave'})
        bundle = self.studio.save_builder_bundle({
            'name': 'Window portrait', 'prompt_board': updated['prompt_board'],
        })
        state = self.studio.builder_state({})

        self.assertEqual(updated['rendered_prompt']['positive'], 'window light')
        self.assertEqual(branch['parent_option_id'], option['id'])
        self.assertIn('sampler', basic['workflow_graph']['source_graph'])
        self.assertEqual(favorites, ['builtin:pose.wave'])
        self.assertEqual(bundle['name'], 'Window portrait')
        self.assertEqual(len(state['experiments'][0]['options']), 2)

    def test_builder_imports_compiles_and_explicitly_submits_an_option_revision(self):
        workflow = self.studio.save_workflow({
            'name': 'Builder base',
            'graph': {
                '1': {'class_type': 'Text', 'inputs': {'text': ''}},
                '2': {'class_type': 'Sample', 'inputs': {'seed': 0}},
            },
            'adapter': {'positive': ['1.text'], 'seed': ['2.seed']},
        })
        experiment = self.studio.create_builder_experiment({'name': 'Lab'})
        option_id = experiment['options'][0]['id']
        self.studio.update_builder_option({'option_id': option_id, 'changes': {
            'prompt_board': {'blocks': [{
                'id': 'p', 'lane': 'positive', 'text': 'portrait',
                'weight': 1, 'enabled': True,
            }]},
        }})
        self.studio.attach_builder_workflow({
            'option_id': option_id, 'workflow_id': workflow['id'],
        })
        calls = []
        self.studio.comfy = lambda path, data=None, **kwargs: (
            {'Text': {'input': {'required': {'text': ['STRING']}}, 'output': []},
             'Sample': {'input': {'required': {'seed': ['INT']}}, 'output': []}}
            if path == '/object_info' else calls.append(data) or {'prompt_id': 'builder-prompt'}
        )

        result = self.studio.generate_builder_option({'option_id': option_id})

        self.assertEqual(result['run']['status'], 'queued')
        self.assertEqual(calls[0]['prompt']['1']['inputs']['text'], 'portrait')
        self.assertEqual(
            self.studio.builder_store.get_revision(result['revision']['id'])['option_id'],
            option_id,
        )

    def test_character_image_can_be_staged_directly_in_builder(self):
        source = self.runtime / 'alice.png'
        Image.new('RGB', (16, 16), 'red').save(source)
        preset = self.studio.save_preset({
            'name': 'Alice', 'kind': 'character', 'references': [], 'loras': []
        })
        character = self.studio.character_catalog.character_for_preset(preset['id'])
        self.studio.character_catalog.assign_folder(
            character['id'], str(self.runtime), recursive=False
        )
        asset = self.studio.character_catalog.list_character_assets(character['id'])[0]
        experiment = self.studio.create_builder_experiment({'name': 'Alice study'})
        option_id = experiment['options'][0]['id']

        result = self.studio.use_character_image_in_builder({
            'character_id': character['id'], 'asset_id': asset['id'],
            'option_id': option_id,
        })

        option = self.studio.builder_store.get_option(option_id)
        self.assertEqual(option['resources']['references'], [result['reference_id']])
        self.assertIn(result['reference_id'], self.studio.state['references'])

    def test_builder_graph_can_be_promoted_to_saved_workflow_and_option_scrapped(self):
        experiment = self.studio.create_builder_experiment({'name': 'Graph lab'})
        option_id = experiment['options'][0]['id']
        self.studio.create_builder_basic_workflow({'option_id': option_id})

        workflow = self.studio.save_builder_workflow({
            'option_id': option_id, 'name': 'Portrait graph'
        })
        deleted = self.studio.delete_builder_option({'option_id': option_id})

        self.assertEqual(workflow['name'], 'Portrait graph')
        self.assertIn('sampler', workflow['graph'])
        self.assertEqual(deleted['deleted_experiment_id'], experiment['id'])

    def test_assign_character_folder_updates_character_summary_only_on_request(self):
        preset = self.studio.save_preset({
            'name': 'Alice', 'kind': 'character', 'references': [], 'loras': []
        })
        character = next(
            item for item in self.studio.character_catalog.list_characters()
            if item['preset_id'] == preset['id']
        )
        folder = self.runtime / 'character-pictures'
        folder.mkdir()
        (folder / 'alice.webp').write_bytes(b'webp fixture')
        (folder / 'ignore.txt').write_text('ignore', encoding='utf-8')

        before = self.studio.public_state()['characters'][0]
        result = self.studio.assign_character_folder({
            'character_id': character['id'],
            'path': str(folder),
            'recursive': False,
        })
        after = self.studio.public_state()['characters'][0]

        self.assertEqual(before['asset_count'], 0)
        self.assertEqual(result['assigned'], 1)
        self.assertEqual(after['asset_count'], 1)
        self.assertEqual(self.studio.character_catalog.list_scan_roots(), [])

    def test_folder_assignment_can_run_as_a_background_job(self):
        preset = self.studio.save_preset({
            'name': 'Alice', 'kind': 'character', 'references': [], 'loras': []
        })
        character = self.studio.character_catalog.character_for_preset(preset['id'])
        folder = self.runtime / 'many-pictures'
        folder.mkdir()
        Image.new('RGB', (16, 16), 'red').save(folder / 'alice.png')

        started = self.studio.start_character_assignment({
            'character_id': character['id'], 'path': str(folder), 'recursive': False,
        })
        deadline = time.time() + 3
        current = started
        while current['state'] in ('pending', 'running') and time.time() < deadline:
            time.sleep(0.02)
            current = self.studio.character_assignment({'job_id': started['id']})

        self.assertEqual(current['state'], 'completed')
        self.assertEqual(current['assigned_count'], 1)
        self.assertEqual(self.studio.character_catalog.character_asset_count(character['id']), 1)

    def test_local_folder_browser_lists_directories_without_scanning_them(self):
        root = self.runtime / 'pictures'
        (root / 'Beta').mkdir(parents=True)
        (root / 'alpha').mkdir()
        (root / 'image.png').write_bytes(b'image')

        result = self.studio.browse_folders({'path': str(root)})

        self.assertEqual(Path(result['path']), root.resolve())
        self.assertEqual([item['name'] for item in result['folders']], ['alpha', 'Beta'])
        self.assertNotIn('image.png', json.dumps(result))
        self.assertEqual(Path(result['parent']), root.resolve().parent)
        with self.assertRaisesRegex(ValueError, 'absolute'):
            self.studio.browse_folders({'path': 'relative/path'})

    def test_discovery_starts_only_on_request_and_returns_review_queue(self):
        class FakeAnalyzer:
            key = 'service-fake-v1'

            def analyze(self, path):
                return [{
                    'vector': [1.0, 0.0], 'box': [0, 0, 8, 8],
                    'confidence': 0.99, 'image_size': [10, 10],
                }]

        preset = self.studio.save_preset({
            'name': 'Alice', 'kind': 'character', 'references': [], 'loras': []
        })
        character = next(
            item for item in self.studio.character_catalog.list_characters()
            if item['preset_id'] == preset['id']
        )
        reference = self.runtime / 'alice.png'
        reference.write_bytes(b'reference')
        registered = self.studio.character_catalog.register_file(reference)
        self.studio.character_catalog.assign_asset(
            character['id'], registered['asset_id'], assignment_type='manual'
        )
        folder = self.runtime / 'outputs'
        folder.mkdir()
        (folder / 'match.png').write_bytes(b'match')
        self.studio.face_analyzer_factory = lambda: FakeAnalyzer()

        self.assertEqual(self.studio.character_catalog.list_discovery_jobs(character['id']), [])
        started = self.studio.start_character_discovery({
            'character_id': character['id'], 'path': str(folder), 'recursive': False,
        })
        for _ in range(100):
            status = self.studio.character_discovery({'job_id': started['id']})
            if status['job']['state'] in ('completed', 'failed'):
                break
            time.sleep(0.01)

        self.assertEqual(status['job']['state'], 'completed')
        self.assertEqual(len(status['review']), 1)
        self.assertEqual(status['review_total'], 1)
        self.assertEqual(status['pending_total'], 1)
        applied = self.studio.apply_character_recommendations({
            'job_id': started['id'], 'all_pending': True,
        })
        self.assertEqual(applied['assigned'], 1)
        self.assertEqual(
            self.studio.character_discovery({'job_id': started['id']})['pending_total'],
            0,
        )

    def test_duplicate_location_can_be_quarantined_and_restored(self):
        preset = self.studio.save_preset({
            'name': 'Alice', 'kind': 'character', 'references': [], 'loras': []
        })
        character = next(
            item for item in self.studio.character_catalog.list_characters()
            if item['preset_id'] == preset['id']
        )
        first = self.runtime / 'first.png'
        second = self.runtime / 'copy.png'
        first.write_bytes(b'exact')
        second.write_bytes(b'exact')
        registered = self.studio.character_catalog.register_file(first)
        self.studio.character_catalog.register_file(second)
        self.studio.character_catalog.assign_asset(
            character['id'], registered['asset_id'], assignment_type='manual'
        )

        groups = self.studio.character_duplicates({'character_id': character['id']})
        remove = next(
            row for row in groups[0]['locations'] if Path(row['path']) == second.resolve()
        )
        operation = self.studio.quarantine_character_duplicate({'location_id': remove['id']})
        self.assertFalse(second.exists())
        restored = self.studio.restore_character_duplicate({'operation_id': operation['id']})

        self.assertEqual(restored['state'], 'restored')
        self.assertTrue(second.exists())

    def test_family_api_keeps_source_choice_separate_from_resolution_recommendation(self):
        preset = self.studio.save_preset({
            'name': 'Alice', 'kind': 'character', 'references': [], 'loras': []
        })
        character = next(
            item for item in self.studio.character_catalog.list_characters()
            if item['preset_id'] == preset['id']
        )
        low = self.runtime / 'low.png'
        high = self.runtime / 'high.png'
        Image.new('RGB', (32, 32), 'red').save(low)
        Image.new('RGB', (128, 64), 'blue').save(high)
        self.studio.assign_character_folder({
            'character_id': character['id'], 'path': str(self.runtime), 'recursive': False,
        })
        image_page = self.studio.character_images({
            'character_id': character['id'], 'limit': 1, 'offset': 0,
        })
        self.assertEqual(image_page['total'], 2)
        self.assertEqual(len(image_page['items']), 1)
        assets = self.studio.character_images({
            'character_id': character['id'], 'limit': 2, 'offset': 0,
        })['items']
        by_name = {item['original_name']: item for item in assets}

        family = self.studio.create_character_family({
            'character_id': character['id'], 'name': 'Outfit A',
            'asset_ids': [by_name['low.png']['id'], by_name['high.png']['id']],
        })
        self.studio.set_character_family_source({
            'family_id': family['id'], 'asset_id': by_name['low.png']['id'],
        })
        listed = self.studio.character_families({'character_id': character['id']})[0]

        self.assertEqual(listed['designated_source_id'], by_name['low.png']['id'])
        self.assertEqual(listed['recommended_source_id'], by_name['high.png']['id'])

    def test_completed_studio_output_records_authoritative_source_lineage(self):
        source = self.runtime / 'source.png'
        Image.new('RGB', (32, 32), 'red').save(source)
        reference_id = self.studio.register_reference(source)
        preset = self.studio.save_preset({
            'name': 'Alice', 'kind': 'character', 'references': [reference_id], 'loras': []
        })
        character = self.studio.character_catalog.character_for_preset(preset['id'])
        source_asset = self.studio.character_catalog.asset_id_for_path(
            self.studio.reference_path(reference_id)
        )
        output = self.runtime / 'output' / 'alice-result.png'
        output.parent.mkdir()
        Image.new('RGB', (64, 64), 'blue').save(output)
        run = {
            'id': 'run-lineage',
            'lineage_sources': [{
                'character_id': character['id'],
                'source_asset_id': source_asset,
                'reference_id': reference_id,
            }],
            'outputs': [{
                'filename': output.name, 'subfolder': '', 'type': 'output', 'kind': 'images',
            }],
        }

        self.studio.record_run_lineage(run)
        self.studio.record_run_lineage(run)

        lineage = self.studio.character_catalog.list_generated_from(source_asset)
        self.assertEqual(len(lineage), 1)
        self.assertEqual(lineage[0]['run_id'], 'run-lineage')

    def test_catalog_image_can_be_promoted_directly_into_compose_references(self):
        preset = self.studio.save_preset({
            'name': 'Alice', 'kind': 'character', 'references': [], 'loras': []
        })
        character = self.studio.character_catalog.character_for_preset(preset['id'])
        image = self.runtime / 'alice.png'
        Image.new('RGB', (48, 48), 'purple').save(image)
        registered = self.studio.character_catalog.register_file(image)
        self.studio.character_catalog.assign_asset(
            character['id'], registered['asset_id'], assignment_type='manual'
        )

        promoted = self.studio.use_character_image_in_compose({
            'character_id': character['id'], 'asset_id': registered['asset_id'],
        })

        saved = next(item for item in self.studio.state['presets'] if item['id'] == preset['id'])
        self.assertEqual(saved['references'], [promoted['reference_id']])
        managed = self.studio.reference_path(promoted['reference_id'])
        self.assertNotEqual(managed, image.resolve())
        self.assertEqual(managed.read_bytes(), image.read_bytes())

    def test_state_is_persisted_without_source_mutation(self):
        preset = self.studio.save_preset({'name': 'Test character', 'kind': 'character', 'positive': 'person', 'references': [], 'loras': []})
        restored = self.service.Studio(self.runtime)
        self.addCleanup(restored.close)
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
