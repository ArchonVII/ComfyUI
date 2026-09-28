import tempfile
import sys
import unittest
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from builder import (
    BuilderStore, build_prompt_catalog, compile_builder_option,
    create_basic_image_workflow, import_workflow_document, render_prompt_board,
)


class BuilderDocumentTests(unittest.TestCase):
    def test_basic_image_recipe_creates_a_connected_editable_graph(self):
        document = create_basic_image_workflow()
        graph = document['source_graph']

        self.assertEqual(graph['sampler']['inputs']['model'], ['model', 0])
        self.assertEqual(graph['decode']['inputs']['samples'], ['sampler', 0])
        self.assertEqual(graph['output']['inputs']['images'], ['decode', 0])
        self.assertEqual(document['advanced_nodes'], {})
        self.assertIn('positive.text', document['adapter']['positive'])

    def test_basic_recipe_compiles_selected_model_and_lora_stack(self):
        option = {
            'prompt_board': {'blocks': []},
            'workflow_graph': create_basic_image_workflow(),
            'resources': {
                'model': 'portrait.safetensors', 'references': [],
                'loras': [{'name': 'detail.safetensors', 'model': .8, 'clip': .6}],
            },
            'settings': {'seed': 7},
        }

        compiled = compile_builder_option(option)

        self.assertEqual(compiled['model']['inputs']['ckpt_name'], 'portrait.safetensors')
        lora = next(node for node in compiled.values() if node['class_type'] == 'LoraLoader')
        self.assertEqual(lora['inputs']['lora_name'], 'detail.safetensors')
        self.assertEqual(compiled['sampler']['inputs']['model'], ['1', 0])

    def test_import_preserves_unknown_nodes_and_compiler_applies_builder_prompt(self):
        graph = {
            '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': 'old.safetensors'}},
            '2': {'class_type': 'CLIPTextEncode', '_meta': {'title': 'Positive Prompt'}, 'inputs': {'text': 'old', 'clip': ['1', 1]}},
            '3': {'class_type': 'MysteryCustomNode', 'inputs': {'source': ['2', 0], 'strength': 4}},
        }
        document = import_workflow_document(graph)
        option = {
            'prompt_board': {'blocks': [{'id': 'a', 'lane': 'positive', 'text': 'new prompt', 'weight': 1, 'enabled': True}]},
            'workflow_graph': document,
            'resources': {'model': 'new.safetensors', 'loras': [], 'references': []},
            'settings': {'seed': 42},
        }

        compiled = compile_builder_option(option)

        self.assertIn('3', document['advanced_nodes'])
        self.assertEqual(compiled['3'], graph['3'])
        self.assertEqual(compiled['2']['inputs']['text'], 'new prompt')
        self.assertEqual(compiled['1']['inputs']['ckpt_name'], 'new.safetensors')

    def test_prompt_catalog_combines_builtins_presets_and_linked_wildcards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            builtin = root / 'builtin.json'
            builtin.write_text('{"options":[{"id":"pose.wave","label":"Wave","node":"pose","field":"base","phrases":{"flux":"waving"}}]}', encoding='utf-8')
            wildcards = root / 'wildcards'
            wildcards.mkdir()
            file = wildcards / 'moods.txt'
            file.write_text('happy\n# comment\ncalm\n', encoding='utf-8')

            first = build_prompt_catalog(
                builtin, [{'id': 'p1', 'name': 'Cinematic', 'positive': 'cinematic light'}],
                [wildcards], query=''
            )
            file.write_text('dramatic\n', encoding='utf-8')
            refreshed = build_prompt_catalog(builtin, [], [wildcards], query='dramatic')

            self.assertEqual({item['source'] for item in first}, {'builtin', 'preset', 'wildcard'})
            self.assertEqual([item['text'] for item in refreshed], ['dramatic'])

    def test_prompt_board_renders_ordered_weighted_enabled_lanes(self):
        board = {
            'blocks': [
                {'id': 'a', 'lane': 'positive', 'text': 'portrait', 'weight': 1, 'enabled': True},
                {'id': 'b', 'lane': 'negative', 'text': 'blurry', 'weight': 1.25, 'enabled': True},
                {'id': 'c', 'lane': 'positive', 'text': 'studio light', 'weight': 0.8, 'enabled': True},
                {'id': 'd', 'lane': 'positive', 'text': 'disabled', 'weight': 1, 'enabled': False},
            ]
        }

        rendered = render_prompt_board(board)

        self.assertEqual(rendered['positive'], 'portrait, (studio light:0.8)')
        self.assertEqual(rendered['negative'], '(blurry:1.25)')

    def test_experiment_branches_and_revisions_are_independent_after_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = BuilderStore(root)
            experiment = store.create_experiment('Portrait study')
            original = experiment['options'][0]
            store.update_option(original['id'], {
                'prompt_board': {'blocks': [
                    {'id': 'a', 'lane': 'positive', 'text': 'red dress', 'weight': 1, 'enabled': True}
                ]},
                'resources': {'model': 'base.safetensors', 'loras': []},
            })
            branch = store.branch_option(original['id'], 'Blue dress')
            store.update_option(branch['id'], {
                'prompt_board': {'blocks': [
                    {'id': 'a', 'lane': 'positive', 'text': 'blue dress', 'weight': 1, 'enabled': True}
                ]}
            })
            revision = store.create_revision(branch['id'], {'1': {'class_type': 'Test', 'inputs': {}}})

            reopened = BuilderStore(root)
            saved_original = reopened.get_option(original['id'])
            saved_branch = reopened.get_option(branch['id'])
            saved_revision = reopened.get_revision(revision['id'])

            self.assertEqual(saved_original['prompt_board']['blocks'][0]['text'], 'red dress')
            self.assertEqual(saved_branch['prompt_board']['blocks'][0]['text'], 'blue dress')
            self.assertEqual(saved_revision['option_snapshot']['prompt_board']['blocks'][0]['text'], 'blue dress')
            saved_branch['prompt_board']['blocks'][0]['text'] = 'mutated outside store'
            self.assertEqual(reopened.get_revision(revision['id'])['option_snapshot']['prompt_board']['blocks'][0]['text'], 'blue dress')

    def test_favorites_and_prompt_bundles_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = BuilderStore(root)
            store.toggle_favorite('builtin:pose.wave')
            bundle = store.save_bundle('Portrait base', {'blocks': [{
                'id': 'a', 'lane': 'positive', 'text': 'portrait',
                'weight': 1, 'enabled': True,
            }]})

            reopened = BuilderStore(root).snapshot()

            self.assertEqual(reopened['favorites'], ['builtin:pose.wave'])
            self.assertEqual(reopened['bundles'][0]['id'], bundle['id'])
            self.assertEqual(reopened['bundles'][0]['prompt_board']['blocks'][0]['text'], 'portrait')

    def test_scrapping_an_option_keeps_revisions_and_removes_empty_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BuilderStore(Path(directory))
            experiment = store.create_experiment('Disposable study')
            original = experiment['options'][0]
            branch = store.branch_option(original['id'], 'Keep me')
            revision = store.create_revision(original['id'], {
                '1': {'class_type': 'Test', 'inputs': {}}
            })

            store.delete_option(original['id'])
            self.assertEqual(store.snapshot()['experiments'][0]['options'][0]['id'], branch['id'])
            self.assertEqual(store.get_revision(revision['id'])['option_id'], original['id'])

            result = store.delete_option(branch['id'])
            self.assertEqual(result, {
                'deleted_option_id': branch['id'],
                'deleted_experiment_id': experiment['id'],
            })
            self.assertEqual(store.snapshot()['experiments'], [])

    def test_invalid_builder_resources_do_not_corrupt_the_durable_option(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BuilderStore(Path(directory))
            option = store.create_experiment('Safe study')['options'][0]

            with self.assertRaisesRegex(ValueError, 'LoRA strengths'):
                store.update_option(option['id'], {'resources': {
                    'model': None, 'references': [],
                    'loras': [{'name': 'bad.safetensors', 'model': math.nan, 'clip': 1}],
                }})

            reopened = BuilderStore(Path(directory)).get_option(option['id'])
            self.assertEqual(reopened['resources']['loras'], [])


if __name__ == '__main__':
    unittest.main()
