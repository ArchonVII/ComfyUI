"""Confined local review reads and classification; no image deletion endpoint."""
import asyncio
import json
import re
import sys
from aiohttp import web

from . import review

ROOT = '/arch-reference-workbench/reviews'


def guarded(handler):
    async def call(request):
        try:
            return await handler(request)
        except FileNotFoundError:
            return web.json_response({'error': 'Review not found'}, status=404)
        except (ValueError, TypeError, KeyError) as error:
            return web.json_response({'error': str(error)}, status=400)
        except OSError:
            return web.json_response({'error': 'Local review storage unavailable'}, status=500)
    return call


async def get_review(request):
    value = await asyncio.to_thread(review.load_review, request.match_info['identifier'])
    return web.json_response(value, headers={'Cache-Control': 'no-store'})


async def post_classification(request):
    # Stream with an explicit limit, including requests lacking Content-Length.
    data = bytearray()
    async for chunk in request.content.iter_chunked(1024):
        data.extend(chunk)
        if len(data) > 4096:
            return web.json_response({'error': 'Request exceeds 4 KiB'}, status=413)
    payload = json.loads(data)
    if not isinstance(payload, dict) or set(payload) != {'classification'}:
        raise ValueError('Expected classification only')
    value = await asyncio.to_thread(review.classify, request.match_info['identifier'], payload['classification'])
    return web.json_response(value)


async def get_image(request):
    directory = review.review_directory(request.match_info['identifier'])
    filename = request.match_info['filename']
    if not re.fullmatch(r'(reference|result)_[0-9]{4,}\.png', filename):
        raise ValueError('Invalid image filename')
    path = (directory / filename).resolve()
    if path.parent != directory:
        raise ValueError('Image path escapes review storage')
    if not path.is_file():
        raise FileNotFoundError(path)
    return web.FileResponse(path, headers={'Cache-Control': 'private, no-store'})


def register_routes():
    server = getattr(getattr(sys.modules.get('server'), 'PromptServer', None), 'instance', None)
    if server is None:
        return
    if getattr(server, '_arch_workbench_review_routes', False):
        return
    routes = server.routes
    routes.get(ROOT + '/{identifier}')(guarded(get_review))
    routes.post(ROOT + '/{identifier}/classification')(guarded(post_classification))
    routes.get(ROOT + '/{identifier}/images/{filename}')(guarded(get_image))
    server._arch_workbench_review_routes = True
