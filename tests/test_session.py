"""Contract tests for CorrectionShellSession — injected fakes, no Qt, no
graph stack (the decomp-qt test_session pattern): the open ladder resolves in
order, gesture coroutines serialize on the loop, library exits resolve as
Future exceptions instead of killing the loop, and teardown follows the
donor's quit contract (seat owns the stack once a spine opened; picker-stage
quit stops the bare queue)."""

import asyncio
from types import SimpleNamespace

import pytest

from cjm_transcript_correction_qt.session import CorrectionShellSession


class FakeQueue:
    def __init__(self):
        self.stopped = False

    async def stop(self):
        self.stopped = True


class FakeView:
    def __init__(self, queue):
        self.queue = queue
        self.graph_id = "cjm-capability-graph-sqlite"
        self.source_id = "src-1"
        self.closed = False

    async def close(self):
        self.closed = True


def make_session(db="/tmp/g.db", stack_exc=None):
    queue = FakeQueue()
    manager = object()

    async def stack_opener(path, *, manifests_dir, graph_capability):
        if stack_exc is not None:
            raise stack_exc
        return manager, queue, path or db

    async def view_opener(mgr, q, cap, source_id, title, *, rendition, skeleton):
        return FakeView(q)

    sess = CorrectionShellSession("/tmp/manifests",
                                  stack_opener=stack_opener,
                                  view_opener=view_opener)
    return sess, queue


def test_open_stack_resolves_db_and_seats():
    sess, queue = make_session()
    sess.start()
    try:
        res = sess.open_stack("/x/graph.db").result(5)
        assert res == {"db": "/x/graph.db"}
        assert sess.db == "/x/graph.db"
        assert sess.queue is queue
        assert sess.manager is not None
    finally:
        sess.close()


def test_open_stack_systemexit_resolves_as_error_and_loop_survives():
    sess, _ = make_session(stack_exc=SystemExit("no such capability"))
    sess.start()
    try:
        with pytest.raises(RuntimeError, match="no such capability"):
            sess.open_stack(None).result(5)

        # the loop thread survived the library exit — later verbs still run
        async def ping():
            return "alive"
        assert sess.submit(ping()).result(5) == "alive"
    finally:
        sess.close()


def test_open_spine_mints_session_and_registry(monkeypatch):
    import cjm_transcript_correction_qt.session as mod

    async def fake_start_session(queue, graph_id, sources, *, journal_path,
                                 purpose):
        assert sources == ["src-1"]
        assert journal_path == "/x/journal"
        assert purpose == "feature-test"
        return SimpleNamespace(id="sess-42")

    async def fake_entities(queue, graph_id):
        return [{"id": "e1"}]

    monkeypatch.setattr(mod, "start_session", fake_start_session)
    monkeypatch.setattr(mod, "list_speaker_entities", fake_entities)
    sess, _ = make_session()
    sess.start()
    try:
        sess.open_stack(None).result(5)
        res = sess.open_spine("src-1", "Talk", rendition=None, skeleton=None,
                              journal_path="/x/journal",
                              purpose="feature-test").result(5)
        assert res["session_id"] == "sess-42"
        assert res["entities"] == [{"id": "e1"}]
        assert sess.view is res["view"]
        assert sess.session_id == "sess-42"
    finally:
        sess.close()


def test_submitted_coroutines_serialize_in_order():
    sess, _ = make_session()
    sess.start()
    try:
        order = []

        async def slow():
            order.append("slow-start")
            await asyncio.sleep(0.05)
            order.append("slow-end")

        async def fast():
            order.append("fast")

        f1 = sess.run_serial(slow())
        f2 = sess.run_serial(fast())
        f1.result(5)
        f2.result(5)
        # gestures run TO COMPLETION in submission order (the gesture lock —
        # the Textual message-queue semantics the echo consistency rides on);
        # bare submit() would interleave at the await point
        assert order == ["slow-start", "slow-end", "fast"]
    finally:
        sess.close()


def test_close_with_open_spine_closes_view(monkeypatch):
    import cjm_transcript_correction_qt.session as mod

    async def fake_start_session(queue, graph_id, sources, *, journal_path,
                                 purpose):
        return SimpleNamespace(id="s")

    async def fake_entities(queue, graph_id):
        return []

    monkeypatch.setattr(mod, "start_session", fake_start_session)
    monkeypatch.setattr(mod, "list_speaker_entities", fake_entities)
    sess, queue = make_session()
    sess.start()
    sess.open_stack(None).result(5)
    res = sess.open_spine("s", "t", rendition=None, skeleton=None,
                          journal_path=None, purpose=None).result(5)
    view = res["view"]
    sess.close()
    assert view.closed
    assert not queue.stopped   # the seat owned teardown, not the bare queue


def test_close_picker_stage_stops_queue():
    sess, queue = make_session()
    sess.start()
    sess.open_stack(None).result(5)
    sess.close()
    assert queue.stopped


def test_statuses_batches_status_and_purposes(monkeypatch):
    import cjm_transcript_correction_qt.session as mod

    async def fake_status(queue, cap, sid):
        return {"segments": 3, "corrections": 1, "marks": 0}

    async def fake_purposes(queue, cap):
        return {"src-1": {"genuine": 2}}

    monkeypatch.setattr(mod, "source_status", fake_status)
    monkeypatch.setattr(mod, "session_purposes_by_source", fake_purposes)
    sess, _ = make_session()
    sess.start()
    try:
        sess.open_stack(None).result(5)
        res = sess.statuses(["src-1", "src-2"]).result(5)
        assert res["status"]["src-2"]["segments"] == 3
        assert res["purposes"]["src-1"]["genuine"] == 2
    finally:
        sess.close()
