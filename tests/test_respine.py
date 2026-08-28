"""Respine surface contract (work item 9af9793a + DoD rider 54aac7d3): the
spine picker's x / t verbs — key table + stage gating + hint rows, the
window handlers over SimpleNamespace fakes (the test_navigation strategy),
the session verbs over injected engine fakes, and the TransferDialog's
phases offscreen (pick a donor -> on_plan; show_plan renders the engine's
counts; T commits through on_commit; an empty plan refuses; esc and the
header's close anchor cancel; a late Future result on a cancelled dialog is
dropped)."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from cjm_transcript_correction_qt import app as app_mod
from cjm_transcript_correction_qt import panes
from cjm_transcript_correction_qt import session as session_mod
from cjm_transcript_correction_qt.app import CorrectionWindow
from cjm_transcript_correction_qt.respine_dialog import plan_lines, TransferDialog
from cjm_transcript_correction_qt.session import CorrectionShellSession


class KeyTableHost:
    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeFuture:
    def __init__(self, result=None, exc=None):
        self._result, self._exc, self.cb = result, exc, None

    def add_done_callback(self, cb):
        self.cb = cb

    def result(self, timeout=None):
        if self._exc is not None:
            raise self._exc
        return self._result


def _key(key, text=""):
    return QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text)


def sample_plan():
    return {"from_segments": 1161, "to_segments": 1156, "donors": 3,
            "plan": [{"label": "inhale", "start": 1.0, "end": 1.2, "rank": 0.0,
                      "after_id": "seg-aaaaaaaa", "before_id": "seg-b"},
                     {"label": "inhale", "start": 2.0, "end": 2.3, "rank": 1.0,
                      "after_id": "seg-b", "before_id": None}],
            "by_label": {"inhale": 2}, "dups": 1, "word_bearing": 0, "unanchored": 0,
            "split_donors": 1,
            "splits": [{"time": 5.5, "left_text": "one two", "right_text": "three four",
                        "segment_id": "x"}],
            "split_dups": 0, "split_unanchored": 0, "split_conflicts": 0}


SPINES = [{"skeleton_hash": None, "split_policy": None, "segments": 900},
          {"skeleton_hash": "sha256:4b8818ee0000", "split_policy": "event-carve/v1",
           "segments": 1161},
          {"skeleton_hash": "sha256:825e1e2a0000", "split_policy": "event-carve/v1",
           "segments": 1156}]


def test_key_table_gating_and_hints():
    host = KeyTableHost()
    CorrectionWindow._build_key_table(host)
    t = host._key_table
    assert "export_wordless" in [a for a, _ in t["x"]]
    assert "transfer_wordless" in [a for a, _ in t["t"]]
    allowed = CorrectionWindow._allowed
    spine = SimpleNamespace(stage="spine", lane="walk", view=None)
    assert allowed(spine, "export_wordless") and allowed(spine, "transfer_wordless")
    for stage in ("select", "flywheel"):
        s = SimpleNamespace(stage=stage, lane="walk", view=None)
        assert not allowed(s, "export_wordless") and not allowed(s, "transfer_wordless")
    lane = SimpleNamespace(stage="correct", lane="propose", view=object())
    assert not allowed(lane, "export_wordless")     # shell verb, never lane vocabulary
    assert allowed(lane, "toggle_tier2")             # t keeps its propose-lane meaning
    rows = panes.hint_entries(SimpleNamespace(stage="spine", lane="walk"))
    keys = {r["verb"]: (r["key"], r["group"]) for r in rows}
    assert keys["export_wordless"] == ("x", "Respine")
    assert keys["transfer_wordless"] == ("t", "Respine")
    select = {r["verb"] for r in panes.hint_entries(SimpleNamespace(stage="select", lane="walk"))}
    assert "export_wordless" not in select and "transfer_wordless" not in select


def test_plan_lines_counts_rows_and_empty():
    lines = plan_lines(sample_plan(), "vad-only (pre-split)", "event-carve/v1 · 825e1e2a")
    text = "\n".join(lines)
    assert lines[0].startswith("vad-only (pre-split)  (1161 segs)")
    assert "event-carve/v1 · 825e1e2a  (1156 segs)" in lines[0]
    assert "3 donors → transfer 2" in text and "dup-skip 1" in text
    assert "inhale×2" in text and "after seg-aaaa" in text
    assert "speaker splits: 1 donors → transfer 1" in text
    assert "'one two' | 'three four'" in text
    assert "stays behind by design" in lines[-1]
    empty = "\n".join(plan_lines({"plan": [], "splits": []}, "a", "b"))
    assert "nothing to transfer" in empty and "speaker splits" not in empty
    many = dict(sample_plan(), plan=[sample_plan()["plan"][0]] * 12)
    assert "… 4 more events" in "\n".join(plan_lines(many, "a", "b"))


def test_transfer_dialog_phases():
    QApplication.instance() or QApplication(sys.argv[:1])
    planned, committed = [], []
    dlg = TransferDialog(None, on_plan=planned.append, on_commit=committed.append)
    target, donors = SPINES[2], SPINES[:2]
    dlg.open_for(target, donors)
    assert dlg.phase == "pick" and dlg.list.count() == 2 and dlg.list.currentRow() == 0
    assert dlg.list.isVisible() and not dlg.body.isVisible()
    assert "vad-only (pre-split)" in dlg.list.item(0).text()
    dlg.keyPressEvent(_key(Qt.Key_J, "j"))
    assert dlg.list.currentRow() == 1
    dlg.keyPressEvent(_key(Qt.Key_Return))
    assert planned == [donors[1]] and dlg.phase == "planning" and dlg.isVisible()
    assert dlg.body.isVisible() and "planning" in dlg.head.toPlainText()
    dlg.keyPressEvent(_key(Qt.Key_T, "T"))      # nothing to commit while planning
    assert committed == []
    plan = sample_plan()
    dlg.show_plan(plan)
    assert dlg.phase == "plan" and "transfer 2" in dlg.body.toPlainText()
    assert "4b8818ee" in dlg.head.toPlainText() and "825e1e2a" in dlg.head.toPlainText()
    dlg.keyPressEvent(_key(Qt.Key_T, "T"))
    assert committed == [plan] and not dlg.isVisible()
    # an empty plan refuses the commit and stays open with a note
    dlg.open_for(target, donors)
    dlg.keyPressEvent(_key(Qt.Key_Return))
    dlg.show_plan({"plan": [], "splits": [], "donors": 0})
    dlg.keyPressEvent(_key(Qt.Key_Return))
    assert len(committed) == 1 and dlg.isVisible() and "nothing to transfer" in dlg.foot.text()
    # the engine's refusal paints as the error phase; esc closes it
    dlg.show_error("empty spine (from=0 to=1 segments)")
    assert dlg.phase == "error" and "empty spine" in dlg.body.toPlainText()
    dlg.keyPressEvent(_key(Qt.Key_Escape))
    assert not dlg.isVisible()
    # a Future landing after cancel is dropped — the dialog stays closed
    dlg.show_plan(plan)
    dlg.show_error("late")
    assert not dlg.isVisible() and dlg.phase == "error"
    # the header's close anchor cancels; an empty sibling list is a placeholder
    dlg.open_for(target, donors)
    dlg._on_anchor(QUrl("close:"))
    assert not dlg.isVisible()
    dlg.open_for(target, [])
    assert dlg.current_donor() is None and dlg.list.count() == 1
    dlg.keyPressEvent(_key(Qt.Key_Return))
    assert len(planned) == 2 and dlg.phase == "pick"
    dlg.reject()


def test_action_transfer_requires_sibling_and_opens_dialog():
    calls, opened = [], []
    s = SimpleNamespace(stage="spine", _respine_busy=False, _spines=SPINES[:1], cursor=0,
                        _paint_status=calls.append,
                        transfer_dialog=SimpleNamespace(
                            open_for=lambda t, d: opened.append((t, d))))
    CorrectionWindow.action_transfer_wordless(s)
    assert opened == [] and "sibling" in calls[-1]
    s._spines, s.cursor = SPINES, 2
    CorrectionWindow.action_transfer_wordless(s)
    assert opened == [(SPINES[2], SPINES[:2])]
    s.stage = "select"
    CorrectionWindow.action_transfer_wordless(s)
    assert len(opened) == 1


def test_plan_commit_and_done_handlers():
    calls, submitted = [], []
    dialog = SimpleNamespace(shown=[], errors=[])
    dialog.show_plan = dialog.shown.append
    dialog.show_error = dialog.errors.append
    fut = FakeFuture()
    s = SimpleNamespace(
        stage="spine", _respine_busy=False, _spines=SPINES, cursor=2,
        _spine_source=("src-1", "Title"), _open_kwargs={"rendition": None},
        _journal_path="/j", actor="human", _paint_status=calls.append,
        transfer_dialog=dialog,
        transfer_planned=SimpleNamespace(emit=lambda f: None),
        transfer_done=SimpleNamespace(emit=lambda f: None),
        sess=SimpleNamespace(
            transfer_plan=lambda sid, **kw: (submitted.append(("plan", sid, kw)), fut)[1],
            transfer_commit=lambda sid, plan, **kw: (submitted.append(("commit", sid, kw)), fut)[1]))
    CorrectionWindow._plan_transfer(s, SPINES[0])
    assert s._respine_busy and submitted[0][:2] == ("plan", "src-1")
    assert submitted[0][2] == {"rendition": None, "from_skeleton": "legacy",
                               "to_skeleton": "sha256:825e1e2a0000"}
    plan = sample_plan()
    CorrectionWindow._on_transfer_planned(s, FakeFuture(result=plan))
    assert not s._respine_busy and dialog.shown == [plan]
    CorrectionWindow._on_transfer_planned(s, FakeFuture(exc=RuntimeError("same spine")))
    assert dialog.errors == ["same spine"]
    CorrectionWindow._commit_transfer(s, plan)
    assert s._respine_busy and submitted[-1] == ("commit", "src-1",
                                                 {"journal_path": "/j", "actor": "human"})
    assert "2 events + 1 splits" in calls[-1]
    CorrectionWindow._on_transfer_done(
        s, FakeFuture(result={"session_id": "sess-12345678", "transferred": 2, "splits": 1}))
    assert not s._respine_busy and "✓ transferred 2 event inserts + 1 speaker splits" in calls[-1]
    assert "(session sess-123)" in calls[-1]
    CorrectionWindow._on_transfer_done(s, FakeFuture(exc=RuntimeError("boom")))
    assert calls[-1] == "⚠ transfer failed: boom"


def test_export_requires_workspace_and_reports(monkeypatch):
    calls, submitted = [], []
    s = SimpleNamespace(stage="spine", _respine_busy=False, _spines=SPINES[1:2], cursor=0,
                        _spine_source=("src-1", "Title"), _open_kwargs={"rendition": None},
                        _paint_status=calls.append,
                        export_done=SimpleNamespace(emit=lambda f: None),
                        sess=SimpleNamespace())
    monkeypatch.setattr(app_mod, "resolve_workspace", lambda *a, **k: None)
    CorrectionWindow.action_export_wordless(s)
    assert "workspace" in calls[-1] and s._respine_busy is False
    ws = SimpleNamespace(root=Path("/ws"))
    monkeypatch.setattr(app_mod, "resolve_workspace", lambda *a, **k: ws)
    s.sess = SimpleNamespace(
        export_wordless=lambda sid, **kw: (submitted.append((sid, kw)), FakeFuture())[1])
    CorrectionWindow.action_export_wordless(s)
    sid, kw = submitted[0]
    assert sid == "src-1" and kw["from_skeleton"] == "sha256:4b8818ee0000"
    assert kw["out_root"] == Path("/ws/proposals") and kw["ws"] is ws
    assert s._respine_busy and "exporting" in calls[-1]
    CorrectionWindow.action_export_wordless(s)          # busy: no second submit
    assert len(submitted) == 1
    CorrectionWindow._on_export_done(
        s, FakeFuture(result={"set_id": "propset_x", "donors": 521,
                              "classes": ["click", "inhale"]}))
    assert not s._respine_busy
    assert "propset_x" in calls[-1] and "521 spans" in calls[-1] and "Shift+E" in calls[-1]
    CorrectionWindow._on_export_done(s, FakeFuture(exc=RuntimeError("no wordless donors")))
    assert calls[-1] == "⚠ export failed: no wordless donors"


def test_session_respine_verbs(monkeypatch):
    seen = []

    async def fake_plan(queue, graph_id, sid, **kw):
        seen.append(("plan", sid, kw))
        return {"plan": [1], "splits": []}

    async def fake_commit(queue, graph_id, sid, plan, **kw):
        seen.append(("commit", sid, kw))
        return {"session_id": "s", "transferred": 1, "splits": 0}

    async def fake_resolve(queue, graph_id, source):
        return (source, "Title", "/media/a.wav")

    async def fake_export_plan(queue, graph_id, sid, **kw):
        seen.append(("export", sid, kw))
        return {"donors": [1, 2], "word_bearing": 3, "counts": {"inhale": 2},
                "from_hash": "h", "window_end": 9.0}

    def fake_write(plan, **kw):
        seen.append(("write", kw))
        return {"set_id": "propset_x", "set_dir": str(kw["out_root"]),
                "manifest_path": "m", "classes": ["inhale"], "counts": {"inhale": 2}}

    monkeypatch.setattr(session_mod, "plan_wordless_transfer", fake_plan)
    monkeypatch.setattr(session_mod, "commit_wordless_transfer", fake_commit)
    monkeypatch.setattr(session_mod, "resolve_source_node", fake_resolve)
    monkeypatch.setattr(session_mod, "plan_wordless_export", fake_export_plan)
    monkeypatch.setattr(session_mod, "write_wordless_propset", fake_write)
    sess = CorrectionShellSession("/tmp/manifests")
    sess.start()
    try:
        res = sess.transfer_plan("src-1", rendition=None, from_skeleton="legacy",
                                 to_skeleton="sha256:a").result(5)
        assert res == {"plan": [1], "splits": []}
        assert seen[0] == ("plan", "src-1", {"from_skeleton": "legacy",
                                             "to_skeleton": "sha256:a",
                                             "rendition": None, "tolerance": 0.05})
        out = sess.transfer_commit("src-1", res, journal_path="/j", actor="human").result(5)
        assert out["transferred"] == 1
        assert seen[1] == ("commit", "src-1", {"journal_path": "/j", "actor": "human"})
        exp = sess.export_wordless("src-1", rendition=None, from_skeleton="legacy",
                                   out_root=Path("/ws/proposals"), ws=None).result(5)
        assert exp["set_id"] == "propset_x" and exp["donors"] == 2 and exp["word_bearing"] == 3
        assert seen[3][1]["media_path"] == "/media/a.wav"
        assert seen[3][1]["out_root"] == Path("/ws/proposals")

        async def refuse(*a, **k):
            raise SystemExit("no wordless donors on this spine — nothing to export")

        monkeypatch.setattr(session_mod, "plan_wordless_export", refuse)
        with pytest.raises(RuntimeError, match="no wordless donors"):
            sess.export_wordless("src-1", rendition=None, from_skeleton="legacy",
                                 out_root=Path("/ws/proposals"), ws=None).result(5)
        monkeypatch.setattr(session_mod, "plan_wordless_transfer", refuse)
        with pytest.raises(RuntimeError):
            sess.transfer_plan("src-1", rendition=None, from_skeleton="a",
                               to_skeleton="b").result(5)
    finally:
        sess.close()
