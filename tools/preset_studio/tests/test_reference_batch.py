import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Studio


class ReferenceBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.studio = Studio(self.temp.name)
        self.addCleanup(self.studio.close)
        self.refs = []
        for name in ('face-a', 'face-b', 'room'):
            path = Path(self.temp.name) / (name + '.png')
            path.write_bytes(b'\x89PNG\r\n\x1a\n' + name.encode())
            self.refs.append(self.studio.register_reference(path))
        self.character = self.studio.save_preset({'name': 'Character', 'kind': 'character', 'positive': 'person', 'references': self.refs[:2]})
        self.workflow = self.studio.save_workflow({'name': 'Two references', 'graph': {
            '1': {'class_type': 'LoadImage', 'inputs': {'image': 'subject.png'}},
            '2': {'class_type': 'LoadImage', 'inputs': {'image': 'room.png'}},
            '3': {'class_type': 'Sample', 'inputs': {'seed': 1, 'text': ''}},
        }, 'adapter': {'references': ['1.image', '2.image'], 'positive': ['3.text'], 'seed': ['3.seed']}})
        self.data = {'preset_ids': [self.character['id']], 'reference_ids': [self.refs[0], self.refs[2]], 'workflow_id': self.workflow['id'],
                     'seed': 42, 'count': 1, 'reference_batch': {'preset_id': self.character['id'], 'image_ids': self.refs[:2], 'slot': 0}}
        self.submissions = []
        self.uploads = []
        def upload(key):
            self.uploads.append(key)
            return key + '.png'
        self.studio.upload_to_comfy = upload
        self.studio.comfy = self.backend

    def backend(self, path, data=None):
        if path == '/object_info':
            return {'LoadImage': {'input': {'required': {'image': [[key + '.png' for key in self.refs]]}}, 'output': ['IMAGE']},
                    'Sample': {'input': {'required': {'seed': ['INT'], 'text': ['STRING']}}, 'output': []}}
        self.submissions.append(copy.deepcopy(data['prompt']))
        return {'prompt_id': f'p{len(self.submissions)}'}

    def test_each_selected_character_image_runs_once_with_environment_and_seed_fixed(self):
        preview = self.studio.preview(self.data)
        self.assertEqual(preview.get('run_count'), 2)
        runs = self.studio.submit(self.data)['runs']
        self.assertEqual(len(runs), 2)
        self.assertEqual([g['1']['inputs']['image'] for g in self.submissions], [r + '.png' for r in self.refs[:2]])
        self.assertTrue(all(g['2']['inputs']['image'] == self.refs[2] + '.png' for g in self.submissions))
        self.assertEqual([r['seed'] for r in runs], [42, 42])
        self.assertEqual([r['composition']['references'][0] for r in runs], self.refs[:2])
        self.assertEqual(self.uploads.count(self.refs[2]), 1)
        self.assertTrue(all(len(run['lineage_sources']) == 1 for run in runs))
        self.assertEqual(
            [source['reference_id'] for run in runs for source in run['lineage_sources']],
            self.refs[:2],
        )

    def test_restoring_one_batch_result_does_not_repeat_the_group(self):
        runs = self.studio.submit(self.data)['runs']
        self.assertEqual(len(runs), 2)
        restored = self.studio.restore({'id': runs[1]['id']})
        self.assertNotIn('reference_batch', restored)
        self.assertEqual(restored['reference_ids'], [self.refs[1], self.refs[2]])
        self.assertEqual(self.studio.preview(restored)['run_count'], 1)

    def test_batch_rejects_noncharacter_images_duplicate_images_and_seed_multiplication(self):
        for changes in ({'image_ids': [self.refs[2]]}, {'image_ids': [self.refs[0], self.refs[0]]}, {'slot': 1}, {'image_ids': []}):
            with self.subTest(changes=changes):
                data = copy.deepcopy(self.data)
                data['reference_batch'].update(changes)
                with self.assertRaises(ValueError):
                    self.studio.submit(data)
        with self.assertRaisesRegex(ValueError, 'once'):
            self.studio.submit({**self.data, 'count': 4})
        self.assertEqual(self.submissions, [])

    def test_single_specific_reference_still_uses_exact_selection(self):
        data = {**self.data, 'reference_ids': [self.refs[1], self.refs[2]]}
        del data['reference_batch']
        runs = self.studio.submit(data)['runs']
        self.assertEqual(len(runs), 1)
        self.assertEqual(self.submissions[0]['1']['inputs']['image'], self.refs[1] + '.png')


if __name__ == '__main__':
    unittest.main()
