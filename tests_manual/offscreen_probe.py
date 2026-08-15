"""Offscreen paint probe: stand the correction window up over a stubbed
graph stack (no capability loads, no real SpineView) and walk the cheap
gestures — boot ladder, pickers, spine open, walk paint, lane cycle, editor,
one commit gesture through the real loop thread — the paint-path
verification layer pytest cannot give (67335f7d), Qt edition. Run from a
NEUTRAL cwd:

    QT_QPA_PLATFORM=offscreen python offscreen_probe.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import cjm_transcript_correction_qt.app as app_mod  # noqa: E402
import cjm_transcript_correction_qt.session as sess_mod  # noqa: E402
from cjm_transcript_correction_qt.session import CorrectionShellSession  # noqa: E402


def seg(i, text, start, end):
    return SimpleNamespace(id=f"s{i}", index=i, text=text, start_time=start,
                           end_time=end, text_from=None)


class FakeQueue:
    async def stop(self):
        pass


def make_fake_view():
    segs = [seg(0, "hello there", 0.0, 1.5),
            seg(1, "second segment words", 1.5, 3.0),
            seg(2, "third one", 3.0, 4.5)]

    async def close():
        pass

    return SimpleNamespace(
        segments=segs, size=3, queue=FakeQueue(), graph_id="g",
        source_id="src-1", source_title="Probe Talk", source_path=None,
        inserted_ids=set(), pruned_ids=set(), marked_ids=set(),
        overlay_ids=set(), insert_labels={}, insert_ranks={},
        speakers={}, turn_proposals={}, event_proposals={},
        proposals_meta={}, turns_meta={}, cluster_entities={},
        show_tier2=False, overlay_count=0, gate=None, skeleton_hash="sha:1",
        seen_mark_classes=[], seen_insert_labels=[], seen_overlay_labels=[],
        aseg_index=lambda pos: 0, chunk=lambda i: None,
        seam=lambda i, d, context_s=2.0: None,
        marks_for=lambda sid: [], overlays_for=lambda sid: [],
        prune_correction_for=lambda sid: None,
        refresh_turn_proposal=lambda sid: None,
        refresh_event_proposals=lambda: None,
        add_mark_local=lambda m: None,
        close=close)


def install_stubs(tmp: Path):
    async def stack_opener(path, *, manifests_dir, graph_capability):
        return object(), FakeQueue(), str(tmp / "graph.db")

    async def view_opener(mgr, q, cap, source_id, title, *, rendition,
                          skeleton):
        return make_fake_view()

    class ProbeSession(CorrectionShellSession):
        def __init__(self, manifests_dir, **kw):
            super().__init__(manifests_dir, stack_opener=stack_opener,
                             view_opener=view_opener,
                             **{k: v for k, v in kw.items()
                                if k != "graph_capability"})

    async def fake_list_sources(queue, cap):
        return [("src-1", "Probe Talk"), ("src-2", "Other Talk")]

    async def fake_status(queue, cap, sid):
        return {"segments": 3, "corrections": 1, "marks": 0}

    async def fake_purposes(queue, cap):
        return {"src-1": {"genuine": 2}}

    async def fake_spines(queue, cap, sid, *, rendition_selector=None):
        return [{"skeleton_hash": None, "segments": 3},
                {"skeleton_hash": "sha256:abc", "split_policy": "sentence-split/v1",
                 "segments": 5}]

    async def fake_start_session(queue, graph_id, sources, *, journal_path,
                                 purpose):
        return SimpleNamespace(id="sess-probe")

    async def fake_entities(queue, graph_id):
        return []

    async def fake_commit_mark(queue, graph_id, source_id, anchor, mark_class,
                               session_id, *, actor, note, journal_path):
        return "mark-1"

    app_mod.CorrectionShellSession = ProbeSession
    sess_mod.list_sources = fake_list_sources
    sess_mod.source_status = fake_status
    sess_mod.session_purposes_by_source = fake_purposes
    sess_mod.list_source_spines = fake_spines
    sess_mod.start_session = fake_start_session
    sess_mod.list_speaker_entities = fake_entities
    app_mod.commit_mark_correction = fake_commit_mark


def pump(app, cond, what, timeout=8.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        app.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="correction-qt-probe-"))
    install_stubs(tmp)
    app = QApplication(sys.argv[:1])
    win = app_mod.CorrectionWindow(None, manifests_dir=str(tmp / "manifests"),
                                   autoplay=False)
    win.show()

    # boot ladder -> source picker with statuses painted
    pump(app, lambda: win._sources and win._status, "the source picker")
    assert win.stage == "select"
    assert "pick a source (2)" in win.status.text()
    assert "Probe Talk" in win.cards.toPlainText()
    assert "1 corrections" in win.cards.toPlainText()

    # walk the picker, open -> the spine picker (two skeletons coexist)
    win._move(1)
    win._move(-1)
    win.action_open_source()
    pump(app, lambda: win.stage == "spine", "the spine picker")
    assert "2 spines coexist" in win.cards.toPlainText()
    assert "vad-only (pre-split)" in win.cards.toPlainText()

    # open the spine -> the walk, center-pinned card canvas + WALK status
    win.action_open_source()
    pump(app, lambda: win.stage == "correct", "the walk")
    assert win.session_id == "sess-probe"
    assert "[WALK]" in win.status.text()
    assert "segment 1/3" in win.status.text()
    assert "hello there" in win.cards.toPlainText()

    # wheel/keys move the cursor; the status follows
    win._move(1)
    assert "segment 2/3" in win.status.text()

    # tab cycles the lane (assign next in rotation; no propset -> no propose)
    win.action_cycle_lane()
    assert win.lane == "assign"
    win.action_cycle_lane()
    assert win.lane == "annotate"
    win.action_cycle_lane()
    assert win.lane == "walk"

    # the inline editor opens with the segment text and escape closes it
    win.action_edit()
    assert win.editor.isVisible()
    assert win.editor.text() == "second segment words"
    win.action_cancel()
    assert not win.editor.isVisible()

    # one commit gesture through the REAL loop thread + gesture lock
    win._submit_gesture(win._do_mark_quick())
    pump(app, lambda: "⚑ #1 [suspect]" in win.status.text(), "the ⚑ echo")

    # gate: annotate-only keys are inert in the walk lane
    assert not win._allowed("word_select")
    assert win._allowed("edit")
    win.lane = "annotate"
    assert win._allowed("word_select") and not win._allowed("edit")
    win.lane = "walk"

    win.close()
    app.processEvents()
    print("offscreen probe: all assertions passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
