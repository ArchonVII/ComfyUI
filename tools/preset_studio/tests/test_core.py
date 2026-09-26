import copy
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'core.py').exists(), 'Preset Studio composition engine is not implemented')
        import core
        self.core = core

    def graph(self):
        return {
            '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': 'base.safetensors'}},
            '2': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'old', 'clip': ['1', 1]}},
            '3': {'class_type': 'KSampler', 'inputs': {'model': ['1', 0], 'seed': 4}},
            '4': {'class_type': 'LoadImage', 'inputs': {'image': 'old.png'}},
        }

    def test_selection_order_and_extra_text(self):
        result = self.core.compose([
            {'name': 'Character', 'positive': 'identity', 'negative': 'different person', 'references': ['a.png']},
            {'name': 'Phone', 'positive': 'candid phone photo', 'loras': [{'name': 'phone.safetensors', 'model': .6, 'clip': .7}]},
        ], 'at the beach', 'blur')
        self.assertEqual(result['positive'], 'identity, candid phone photo, at the beach')
        self.assertEqual(result['negative'], 'different person, blur')
        self.assertEqual(result['references'], ['a.png'])
        self.assertEqual(result['loras'][0]['model'], .6)

    def test_conflicting_lora_strengths_are_not_silently_overwritten(self):
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            self.core.compose([{'loras': [{'name': 'same', 'model': 1}]}, {'loras': [{'name': 'same', 'model': .5}]}])

    def test_patch_is_nonmutating_and_chains_loras(self):
        graph = self.graph()
        original = copy.deepcopy(graph)
        adapter = {'positive': ['2.text'], 'seed': ['3.seed'], 'references': ['4.image'], 'model': ['1', 0], 'clip': ['1', 1]}
        composition = self.core.compose([{'positive': 'new', 'references': ['new.png'], 'loras': [{'name': 'one'}, {'name': 'two'}]}])
        patched = self.core.compile_graph(graph, adapter, composition, 123)
        self.assertEqual(graph, original)
        self.assertEqual(patched['2']['inputs']['text'], 'new')
        self.assertEqual(patched['3']['inputs']['seed'], 123)
        self.assertEqual(patched['4']['inputs']['image'], 'new.png')
        loaders = [n for n in patched.values() if n['class_type'] == 'LoraLoader']
        self.assertEqual(len(loaders), 2)
        self.assertEqual(loaders[0]['inputs']['model'], ['1', 0])
        self.assertNotEqual(patched['3']['inputs']['model'], ['1', 0])

    def test_missing_reference_and_binding_fail_before_queue(self):
        with self.assertRaisesRegex(ValueError, 'reference'):
            self.core.compile_graph(self.graph(), {'references': ['4.image']}, self.core.compose([]), 1)
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.core.compile_graph(self.graph(), {'positive': ['99.text']}, self.core.compose([]), 1)

    def test_lora_requires_explicit_insertion_point(self):
        with self.assertRaisesRegex(ValueError, 'LoRA'):
            self.core.compile_graph(self.graph(), {}, self.core.compose([{'loras': [{'name': 'one'}]}]), 1)

    def test_editor_workflow_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'API'):
            self.core.validate_graph({'nodes': [], 'links': []})


if __name__ == '__main__':
    unittest.main()
