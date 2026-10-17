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
                                 purpose, actor="human"):
        assert sources == ["src-1"]
        assert journal_path == "/x/journal"
        assert purpose == "feature-test"
        assert actor == "agent:probe"   # the shell's actor reaches the session row (ac878d68)
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
                              purpose="feature-test", actor="agent:probe").result(5)
        assert res["session_id"] == "sess-42"
        assert res["entities"] == [{"id": "e1"}]
        assert sess.view is res["view"]
        assert sess.session_id == "sess-42"
    finally:
        sess.close()


def _seat_on(sess, tmp_path):  # The session over an in-memory store, as an opened stack leaves it
    from cjm_context_graph_layer.testing import MemGraph
    sess.queue, sess.db = MemGraph(), str(tmp_path / "graph.db")
    return sess.queue


def test_submitted_coroutines_serialize_in_order(tmp_path):
    sess, _ = make_session()
    sess.start()
    _seat_on(sess, tmp_path)
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
                                 purpose, actor="human"):
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


def test_a_gesture_is_one_atomic_unit_on_the_journal(tmp_path):
    """Ruling 3de795e4: a gesture's commits land at its close as ONE unit -- appended whole, then
    applied -- each core commit's own window joined; a failing gesture lands nothing."""
    from cjm_context_graph_layer.journal import sidecar_journal_path
    from cjm_context_graph_primitives.journal import read_journal
    from cjm_transcript_correction_core.graph import commit_speaker_entity, start_session

    sess, _ = make_session()
    sess.start()
    store = _seat_on(sess, tmp_path)
    j = sidecar_journal_path(sess.db)
    try:
        async def two_commits():
            s = await start_session(store, sess.graph_capability, ["src-1"], journal_path=j)
            await commit_speaker_entity(store, sess.graph_capability, "Ada", s.id, journal_path=j)
            assert read_journal(j) == []  # buffered until the gesture closes
            return s.id

        sid = sess.run_serial(two_commits()).result(5)
        recs = read_journal(j)
        assert [r["verb"] for r in recs] == ["session-start", "speaker-entity"]
        assert len({r["unit"] for r in recs}) == 1 and sid in store.nodes

        async def failing():
            await start_session(store, sess.graph_capability, ["src-1"], journal_path=j)
            raise RuntimeError("the gesture failed after its commit")

        with pytest.raises(RuntimeError):
            sess.run_serial(failing()).result(5)
        assert len(read_journal(j)) == 2  # the failed gesture landed nothing
    finally:
        sess.close()
