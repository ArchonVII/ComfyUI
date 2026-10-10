import importlib.util
import json
from pathlib import Path
import sys

import pytest
import torch

SOURCE = Path(__file__).resolve().parents[1] / 'review.py'
spec = importlib.util.spec_from_file_location('workbench_review_test', SOURCE)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(review, 'review_root', lambda: tmp_path / 'reviews')
    monkeypatch.setattr(review.folder_paths, 'get_output_directory', lambda: str(tmp_path / 'output'))
    return tmp_path

def test_review_preserves_batch_and_classification_only(roots):
    result = review.ArchResultReview().save(torch.zeros(1, 8, 10, 3), torch.ones(3, 6, 7, 3), '{"score":0.5}', 'plain settings')
    record = json.loads(result['result'][0])
    assert len(record['results']) == 3
    before = [Path(p['path']).read_bytes() for p in record['results']]
    updated = review.classify(record['id'], 'reject')
    assert updated['classification'] == 'reject'
    assert before == [Path(p['path']).read_bytes() for p in updated['results']]
    assert updated['run_settings'] == 'plain settings'

@pytest.mark.parametrize('identifier', ['../escape', 'not-uuid', '00000000-0000-0000-0000-000000000000/../'])
def test_rejects_unsafe_ids(roots, identifier):
    with pytest.raises(ValueError): review.review_directory(identifier)

def test_run_record_is_unique_and_honest(roots):
    node = review.ArchRunRecord()
    args = dict(images=torch.ones(2, 5, 6, 3), filename_prefix='example', reference_metadata_json='{"subject":{"path":"selected.png"}}', seed=123, model='supplied-name')
    one = json.loads(node.save(**args)['result'][0])
    two = json.loads(node.save(**args)['result'][0])
    assert one['id'] != two['id']
    assert len(one['images']) == 2
    assert one['supplied_settings']['seed'] == 123
    assert one['reference_metadata']['subject']['path'] == 'selected.png'
    assert Path(one['record_path']).is_file()
    assert all(Path(x['path']).is_file() for x in one['images'])
    with pytest.raises(ValueError): node.save(images=args['images'], filename_prefix='../escape')

def test_metadata_limits_and_symlink_confinement(roots):
    with pytest.raises(ValueError): review.parse_metadata('x' * (review.MAX_JSON_BYTES + 1))
    with pytest.raises(ValueError): review.classify('00000000-0000-0000-0000-000000000000', 'delete')

def test_routes_classification_size_and_image_confinement(roots, monkeypatch):
    import asyncio
    import types
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    package = types.ModuleType('review_route_test_package')
    package.__path__ = [str(SOURCE.parent)]
    package.review = review
    sys.modules[package.__name__] = package
    route_spec = importlib.util.spec_from_file_location(package.__name__ + '.routes', SOURCE.parent / 'routes.py')
    routes = importlib.util.module_from_spec(route_spec)
    route_spec.loader.exec_module(routes)
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, 'server', types.SimpleNamespace(PromptServer=type('PromptServer', (), {})))
        routes.register_routes()
        registered = web.RouteTableDef()
        server = types.SimpleNamespace(routes=registered)
        patch.setitem(sys.modules, 'server', types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=server)))
        routes.register_routes()
        routes.register_routes()
        assert len(registered) == 3

    async def scenario():
        record = json.loads(review.ArchResultReview().save(torch.zeros(1, 3, 4, 3), torch.ones(2, 3, 4, 3))['result'][0])
        app = web.Application()
        app.router.add_get('/{identifier}', routes.guarded(routes.get_review))
        app.router.add_post('/{identifier}/classification', routes.guarded(routes.post_classification))
        app.router.add_get('/{identifier}/images/{filename}', routes.guarded(routes.get_image))
        async with TestClient(TestServer(app)) as client:
            identifier = record['id']
            assert (await client.get('/bad-id')).status == 400
            assert (await client.get('/' + str(__import__('uuid').uuid4()))).status == 404
            assert (await client.get(f'/{identifier}/images/result_0001.png')).status == 200
            assert (await client.get(f'/{identifier}/images/review.json')).status == 400
            response = await client.post(f'/{identifier}/classification', json={'classification': 'keep'})
            assert response.status == 200
            assert (await response.json())['classification'] == 'keep'
            assert (await client.post(f'/{identifier}/classification', json={'classification': 'delete'})).status == 400
            assert (await client.post(f'/{identifier}/classification', data='x' * 5000)).status == 413
            assert (await client.post(f'/{identifier}/classification', data='not json')).status == 400
            assert len(list(review.review_directory(identifier).glob('*.png'))) == 3
    asyncio.run(scenario())


def test_run_record_handles_comfy_nonfinite_cache_metadata_without_mutating_graph(roots):
    prompt = {'12': {'class_type': 'ArchReferenceCast', 'inputs': {}, 'is_changed': float('nan')}}
    extra = {'workflow': {'nodes': [{'id': 12, 'properties': {'cached': float('inf')}}]}}
    result = review.ArchRunRecord().save(torch.zeros(1, 3, 4, 3), prompt=prompt, extra_pnginfo=extra)
    value = json.loads(result['result'][0])
    assert value['api_prompt']['12']['is_changed'] == {'nonfinite_number': 'NaN'}
    assert value['extra_pnginfo']['workflow']['nodes'][0]['properties']['cached'] == {'nonfinite_number': 'Infinity'}
    assert 'nonfinite_number' in value['hidden_metadata_note']
    assert __import__('math').isnan(prompt['12']['is_changed'])
    json.dumps(value, allow_nan=False)
    with pytest.raises(ValueError):
        review.ArchRunRecord().save(torch.zeros(1, 3, 4, 3), reference_metadata_json='{"score": NaN}')
    assert review.ArchRunRecord.INPUT_TYPES()['optional']['seed'][1]['control_after_generate'] is False
