"""Tests for the jobs-namespace cancel endpoints.

Covers both layers:

* the pure cancel helpers in ``comfy_execution.jobs``
  (``classify_job_for_cancel`` / ``cancel_job``), which hold the business
  logic of mapping a cancel onto interrupt-vs-dequeue, and

* the HTTP contract of ``POST /api/jobs/{job_id}/cancel`` and
  ``POST /api/jobs/cancel`` (status codes, single-cancel idempotency, and
  batch fail-fast on an unknown id with no partial side effects).

The HTTP layer is exercised against a small aiohttp app whose handlers are a
faithful copy of the wiring in ``server.py`` driven by a fake queue that
mirrors ``execution.PromptQueue`` (``get_current_queue`` / ``get_history`` /
``delete_queue_item``). This keeps the test free of the heavy ComfyUI runtime
(torch, nodes, ...) while still testing the real cancel logic.
"""

import json

import pytest
from aiohttp import web

from comfy_execution.jobs import (
    CANCEL_PENDING,
    CANCEL_RUNNING,
    CANCEL_TERMINAL,
    CANCEL_UNKNOWN,
    cancel_job,
    classify_job_for_cancel,
    validate_job_id,
)

# Classifications for which a cancel was actually dispatched (vs a no-op).
_CANCELLED = (CANCEL_RUNNING, CANCEL_PENDING)

# Canonical UUID ids for HTTP-layer tests (the batch endpoint validates UUID format).
_UUID_A = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
_UUID_B = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
_UUID_C = "cccccccc-cccc-4ccc-cccc-cccccccccccc"
_UUID_D = "dddddddd-dddd-4ddd-dddd-dddddddddddd"
_UUID_MISSING = "ffffffff-ffff-4fff-ffff-ffffffffffff"


def make_queue_item(prompt_id, number=0):
    """Build a queue tuple shaped like the real ones: index 1 is the id."""
    return (number, prompt_id, {}, {}, [])


class FakePromptQueue:
    """Minimal stand-in for execution.PromptQueue for the cancel paths.

    Tracks interrupts and dequeues so tests can assert side effects.
    """

    def __init__(self, running=None, pending=None, history=None):
        self._running = list(running or [])
        self._pending = list(pending or [])
        self._history = dict(history or {})
        self.interrupt_count = 0

    def get_current_queue(self):
        return (list(self._running), list(self._pending))

    def get_history(self, prompt_id=None):
        if prompt_id is None:
            return dict(self._history)
        if prompt_id in self._history:
            return {prompt_id: self._history[prompt_id]}
        return {}

    def delete_queue_item(self, function):
        for i, item in enumerate(self._pending):
            if function(item):
                self._pending.pop(i)
                return True
        return False

    def interrupt_processing(self):
        self.interrupt_count += 1


def build_app(queue):
    """Build an aiohttp app exposing the cancel routes against ``queue``.

    Handler bodies mirror server.py exactly.
    """

    def _cancel_job_by_id(job_id):
        running, pending = queue.get_current_queue()
        history = queue.get_history()

        def interrupt():
            queue.interrupt_processing()

        def dequeue(prompt_id):
            return queue.delete_queue_item(lambda a: a[1] == prompt_id)

        classification = cancel_job(
            job_id, running, pending, history, interrupt, dequeue
        )
        return classification in _CANCELLED

    async def cancel_job_by_id(request):
        job_id = request.match_info.get("job_id", None)
        if not job_id:
            return web.json_response({"error": "job_id is required"}, status=400)
        cancelled = _cancel_job_by_id(job_id)
        return web.json_response({"cancelled": cancelled})

    async def cancel_jobs_batch(request):
        try:
            json_data = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                {"error": "Request body must be valid JSON"}, status=400
            )

        job_ids = json_data.get("job_ids") if isinstance(json_data, dict) else None
        if not isinstance(job_ids, list):
            return web.json_response({"error": "job_ids must be a list"}, status=400)

        invalid_ids = []
        for jid in job_ids:
            try:
                validate_job_id(jid)
            except (ValueError, AttributeError):
                invalid_ids.append(jid if isinstance(jid, str) else repr(jid))
        if invalid_ids:
            return web.json_response(
                {"error": "job_ids contains invalid id(s)", "invalid_ids": invalid_ids},
                status=400,
            )

        running, pending = queue.get_current_queue()
        history = queue.get_history()
        unknown_ids = [
            jid
            for jid in job_ids
            if classify_job_for_cancel(jid, running, pending, history) == CANCEL_UNKNOWN
        ]
        if unknown_ids:
            return web.json_response(
                {"error": "Job(s) not found", "unknown_ids": unknown_ids}, status=404
            )

        cancelled = False
        for jid in job_ids:
            if _cancel_job_by_id(jid):
                cancelled = True
        return web.json_response({"cancelled": cancelled})

    app = web.Application()
    app.router.add_post("/api/jobs/{job_id}/cancel", cancel_job_by_id)
    app.router.add_post("/api/jobs/cancel", cancel_jobs_batch)
    return app


# ---------------------------------------------------------------------------
# Pure helper tests: classification + cancel side effects
# ---------------------------------------------------------------------------


class TestClassifyJobForCancel:
    def test_running(self):
        running = [make_queue_item("a")]
        assert classify_job_for_cancel("a", running, [], {}) == CANCEL_RUNNING

    def test_pending(self):
        pending = [make_queue_item("b")]
        assert classify_job_for_cancel("b", [], pending, {}) == CANCEL_PENDING

    def test_terminal(self):
        history = {"c": {"prompt": make_queue_item("c"), "outputs": {}, "status": {}}}
        assert classify_job_for_cancel("c", [], [], history) == CANCEL_TERMINAL

    def test_unknown(self):
        assert classify_job_for_cancel("z", [], [], {}) == CANCEL_UNKNOWN


class TestCancelJobHelper:
    def test_running_is_interrupted_not_dequeued(self):
        running = [make_queue_item("a")]
        interrupts = []
        dequeues = []
        result = cancel_job(
            "a", running, [], {},
            interrupt=lambda: interrupts.append(True),
            dequeue=lambda pid: dequeues.append(pid) or True,
        )
        assert result == CANCEL_RUNNING
        assert interrupts == [True]
        assert dequeues == []

    def test_pending_is_dequeued_not_interrupted(self):
        pending = [make_queue_item("b")]
        interrupts = []
        dequeues = []
        result = cancel_job(
            "b", [], pending, {},
            interrupt=lambda: interrupts.append(True),
            dequeue=lambda pid: dequeues.append(pid) or True,
        )
        assert result == CANCEL_PENDING
        assert dequeues == ["b"]
        assert interrupts == []

    def test_terminal_is_noop(self):
        history = {"c": {"prompt": make_queue_item("c"), "outputs": {}, "status": {}}}
        interrupts = []
        dequeues = []
        result = cancel_job(
            "c", [], [], history,
            interrupt=lambda: interrupts.append(True),
            dequeue=lambda pid: dequeues.append(pid) or True,
        )
        assert result == CANCEL_TERMINAL
        assert interrupts == []
        assert dequeues == []

    def test_unknown_is_noop(self):
        interrupts = []
        dequeues = []
        result = cancel_job(
            "z", [], [], {},
            interrupt=lambda: interrupts.append(True),
            dequeue=lambda pid: dequeues.append(pid) or True,
        )
        assert result == CANCEL_UNKNOWN
        assert interrupts == []
        assert dequeues == []

    def test_pending_dequeue_miss_returns_unknown(self):
        """If dequeue returns False (job left queue between snapshot and delete),
        cancel_job must return CANCEL_UNKNOWN so callers never report cancelled=True
        for a cancel that did not actually happen (TOCTOU guard)."""
        pending = [make_queue_item("b")]
        interrupts = []
        dequeues = []
        # dequeue always returns False — simulates job already gone from queue
        result = cancel_job(
            "b", [], pending, {},
            interrupt=lambda: interrupts.append(True),
            dequeue=lambda pid: (dequeues.append(pid), False)[1],
        )
        assert result == CANCEL_UNKNOWN
        assert dequeues == ["b"]   # dequeue was attempted
        assert interrupts == []    # interrupt was not called


# ---------------------------------------------------------------------------
# HTTP contract tests: POST /api/jobs/{job_id}/cancel
# ---------------------------------------------------------------------------


class TestSingleCancelEndpoint:
    @pytest.mark.asyncio
    async def test_cancel_running_job_interrupts(self, aiohttp_client):
        queue = FakePromptQueue(running=[make_queue_item("a")])
        client = await aiohttp_client(build_app(queue))

        resp = await client.post("/api/jobs/a/cancel")

        assert resp.status == 200
        assert (await resp.json()) == {"cancelled": True}
        assert queue.interrupt_count == 1

    @pytest.mark.asyncio
    async def test_cancel_pending_job_dequeues(self, aiohttp_client):
        queue = FakePromptQueue(pending=[make_queue_item("b")])
        client = await aiohttp_client(build_app(queue))

        resp = await client.post("/api/jobs/b/cancel")

        assert resp.status == 200
        assert (await resp.json()) == {"cancelled": True}
        # Pending job removed from the queue; nothing interrupted.
        assert queue.get_current_queue()[1] == []
        assert queue.interrupt_count == 0

    @pytest.mark.asyncio
    async def test_cancel_terminal_job_is_idempotent_noop(self, aiohttp_client):
        history = {"c": {"prompt": make_queue_item("c"), "outputs": {}, "status": {}}}
        queue = FakePromptQueue(history=history)
        client = await aiohttp_client(build_app(queue))

        resp = await client.post("/api/jobs/c/cancel")

        # Already-finished job: 200 no-op (cancelled=false), not an error.
        assert resp.status == 200
        assert (await resp.json()) == {"cancelled": False}
        assert queue.interrupt_count == 0

    @pytest.mark.asyncio
    async def test_cancel_unknown_id_is_200_noop(self, aiohttp_client):
        queue = FakePromptQueue()
        client = await aiohttp_client(build_app(queue))

        resp = await client.post("/api/jobs/does-not-exist/cancel")

        # Single-cancel of an unknown id is treated as an idempotent no-op.
        assert resp.status == 200
        assert (await resp.json()) == {"cancelled": False}
        assert queue.interrupt_count == 0


# ---------------------------------------------------------------------------
# HTTP contract tests: POST /api/jobs/cancel (batch)
# ---------------------------------------------------------------------------


class TestBatchCancelEndpoint:
    @pytest.mark.asyncio
    async def test_batch_happy_path(self, aiohttp_client):
        queue = FakePromptQueue(
            running=[make_queue_item(_UUID_A)],
            pending=[make_queue_item(_UUID_B, number=1)],
        )
        client = await aiohttp_client(build_app(queue))

        resp = await client.post("/api/jobs/cancel", json={"job_ids": [_UUID_A, _UUID_B]})

        assert resp.status == 200
        assert (await resp.json()) == {"cancelled": True}
        assert queue.interrupt_count == 1            # running job interrupted
        assert queue.get_current_queue()[1] == []    # pending job dequeued

    @pytest.mark.asyncio
    async def test_batch_fail_fast_404_on_unknown_id_no_side_effects(
        self, aiohttp_client
    ):
        queue = FakePromptQueue(
            running=[make_queue_item(_UUID_A)],
            pending=[make_queue_item(_UUID_B, number=1)],
        )
        client = await aiohttp_client(build_app(queue))

        resp = await client.post(
            "/api/jobs/cancel", json={"job_ids": [_UUID_A, _UUID_MISSING, _UUID_B]}
        )

        assert resp.status == 404
        body = await resp.json()
        assert body["unknown_ids"] == [_UUID_MISSING]
        # Fail-fast: nothing was cancelled — no partial side effects.
        assert queue.interrupt_count == 0
        assert len(queue.get_current_queue()[1]) == 1

    @pytest.mark.asyncio
    async def test_batch_all_terminal_is_idempotent_noop(self, aiohttp_client):
        history = {
            _UUID_C: {"prompt": make_queue_item(_UUID_C), "outputs": {}, "status": {}},
            _UUID_D: {"prompt": make_queue_item(_UUID_D), "outputs": {}, "status": {}},
        }
        queue = FakePromptQueue(history=history)
        client = await aiohttp_client(build_app(queue))

        resp = await client.post("/api/jobs/cancel", json={"job_ids": [_UUID_C, _UUID_D]})

        # All known but terminal: 200 with cancelled=false, nothing dispatched.
        assert resp.status == 200
        assert (await resp.json()) == {"cancelled": False}
        assert queue.interrupt_count == 0

    @pytest.mark.asyncio
    async def test_batch_missing_job_ids_is_400(self, aiohttp_client):
        queue = FakePromptQueue()
        client = await aiohttp_client(build_app(queue))

        resp = await client.post("/api/jobs/cancel", json={})

        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_batch_unhashable_element_is_400_not_500(self, aiohttp_client):
        """An unhashable element such as a dict or list must yield 400, not 500.

        Previously, passing e.g. {"job_ids": [{}]} would reach the classify
        loop where ``prompt_id in history`` raises TypeError on an unhashable
        type, resulting in an unhandled 500.  The input-validation guard must
        catch this before any queue or history access.
        """
        queue = FakePromptQueue()
        client = await aiohttp_client(build_app(queue))

        resp = await client.post("/api/jobs/cancel", json={"job_ids": [{}]})

        assert resp.status == 400
        body = await resp.json()
        assert "invalid_ids" in body
        # No queue side effects.
        assert queue.interrupt_count == 0

    @pytest.mark.asyncio
    async def test_batch_non_uuid_string_element_is_400(self, aiohttp_client):
        """A string that is not a valid UUID must be rejected with 400."""
        queue = FakePromptQueue()
        client = await aiohttp_client(build_app(queue))

        resp = await client.post(
            "/api/jobs/cancel", json={"job_ids": ["not-a-uuid"]}
        )

        assert resp.status == 400
        body = await resp.json()
        assert "invalid_ids" in body
