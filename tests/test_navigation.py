"""Navigation slice contract (work item f27f2b99): the pickers/flywheel
stop being a dead end — the back ladder, shell-universal nav gating, browse
mode, the W gate remap, lane teardown-lite, and the nav hint rows. Unbound-
method calls over SimpleNamespace fakes (the test_gestures strategy) — no
live QWidget; the offscreen probe covers the menubar."""

from types import SimpleNamespace

from cjm_transcript_correction_qt import panes
from cjm_transcript_correction_qt.app import CorrectionWindow


class KeyTableHost:
    """Attribute sink for _build_key_table: every referenced handler exists."""

    def __getattr__(self, name):
        return lambda *a, **k: None


def build_table():
    host = KeyTableHost()
    CorrectionWindow._build_key_table(host)
    return host._key_table


def test_key_table_nav_bindings():
    t = build_table()
    assert [a for a, _ in t["W"]] == ["gate_editor"]      # gate left F
    assert [a for a, _ in t["F"]] == ["flywheel_page"]    # F is nav-only now
    assert [a for a, _ in t["B"]] == ["back"]
    assert [a for a, _ in t["escape"]] == ["cancel", "back"]  # lanes cancel first


def nav_state(**kw):
    d = dict(stage="correct", lane="walk", view=object())
    d.update(kw)
    return SimpleNamespace(**d)


def test_allowed_nav_gating():
    allowed = CorrectionWindow._allowed
    for stage in ("select", "spine", "flywheel"):
        assert allowed(nav_state(stage=stage), "back")
    for lane in ("walk", "assign", "propose", "annotate"):
        s = nav_state(lane=lane)
        assert allowed(s, "back") and allowed(s, "flywheel_page")
    assert allowed(nav_state(lane="walk"), "gate_editor")
    assert not allowed(nav_state(lane="assign"), "gate_editor")
    assert not allowed(nav_state(stage="select"), "gate_editor")


def recorder(calls, name):
    return lambda *a, **k: calls.append(name)


def back_state(**kw):
    calls = []
    d = dict(stage="correct", view=object(),
             editor=SimpleNamespace(isVisible=lambda: False),
             _word_anchor=None, _overlay_pick=None,
             action_cancel=recorder(calls, "cancel"),
             action_flywheel_page=recorder(calls, "flywheel"),
             action_nav_spines=recorder(calls, "spines"),
             action_nav_sources=recorder(calls, "sources"),
             _paint_status=recorder(calls, "status"))
    d.update(kw)
    return SimpleNamespace(**d), calls


def test_back_ladder():
    s, calls = back_state()
    CorrectionWindow.action_back(s)
    assert calls == ["spines"]            # lane unwinds to the spine picker
    s, calls = back_state(stage="flywheel")
    CorrectionWindow.action_back(s)
    assert calls == ["flywheel"]          # flywheel returns where it came from
    s, calls = back_state(stage="spine", view=None)
    CorrectionWindow.action_back(s)
    assert calls == ["sources"]
    s, calls = back_state(stage="select", view=None)
    CorrectionWindow.action_back(s)
    assert calls == ["status"]            # front door: a note, never a teardown
    s, calls = back_state(editor=SimpleNamespace(isVisible=lambda: True))
    CorrectionWindow.action_back(s)
    assert calls == ["cancel"]            # a modal IS a step


def test_forward_redescends():
    calls = []
    s = SimpleNamespace(stage="select", _spine_source=("src-1", "Talk"),
                        action_nav_spines=recorder(calls, "spines"))
    CorrectionWindow.action_forward(s)
    assert calls == ["spines"]
    opened = []
    s = SimpleNamespace(stage="spine", _last_spine=("src-1", "Talk", None),
                        _open_spine=lambda *a: opened.append(a))
    CorrectionWindow.action_forward(s)
    assert opened == [("src-1", "Talk", None)]
    CorrectionWindow.action_forward(
        SimpleNamespace(stage="spine", _last_spine=None))   # nothing to redo


class FakeFuture:
    def __init__(self):
        self.cb = None

    def add_done_callback(self, cb):
        self.cb = cb


def test_nav_sources_enters_browse_and_relists():
    fut = FakeFuture()
    emitted = []
    s = SimpleNamespace(
        view=None, _nav_browsing=False, stage="flywheel",
        _open_kwargs={"source": "pre-pick", "rendition": None,
                      "skeleton": None},
        _discovered=True, cursor=3, _paint_status=lambda text: None,
        sess=SimpleNamespace(list_sources=lambda: fut),
        sources_listed=SimpleNamespace(emit=lambda f: emitted.append(f)))
    CorrectionWindow.action_nav_sources(s)
    assert s._nav_browsing and s.stage == "select" and not s._discovered
    assert s._open_kwargs["source"] is None   # pre-pick consumed: no bounce
    assert s.cursor == 0
    fut.cb("payload")
    assert emitted == ["payload"]


def test_nav_spines_requires_source_and_relists():
    CorrectionWindow.action_nav_spines(
        SimpleNamespace(_spine_source=None))   # no source chosen: refuses
    fut = FakeFuture()
    s = SimpleNamespace(
        _spine_source=("src-1", "Talk"), view=None, _nav_browsing=False,
        _open_kwargs={"rendition": None}, _paint_status=lambda text: None,
        sess=SimpleNamespace(list_spines=lambda sid, r: fut),
        spines_listed=SimpleNamespace(emit=lambda f: None))
    CorrectionWindow.action_nav_spines(s)
    assert s._nav_browsing and fut.cb is not None


def test_leave_lane_bookmarks_and_resets(monkeypatch):
    saved = []
    from cjm_transcript_correction_qt import app as app_mod
    monkeypatch.setattr(
        app_mod, "save_tui_state",
        lambda db, sid, cursor, **kw: saved.append((sid, cursor, kw)))
    s = SimpleNamespace(
        _autoplay_timer=SimpleNamespace(stop=lambda: None),
        player=None, _stop_ticker=lambda: None,
        editor=SimpleNamespace(isVisible=lambda: False),
        view=SimpleNamespace(source_id="src-1"),
        _graph_db_path="/tmp/g.db", cursor=7, speed=1.5,
        session_id="sess", _marks={1: "corrected"},
        _pending_proposal=object(), _accept_cluster="c",
        _active_entity="e", _word_anchor=2, _overlay_pick="o")
    CorrectionWindow._leave_lane(s)
    assert saved == [("src-1", 7, {"speed": 1.5})]   # the closeEvent half
    assert s.view is None and s.session_id is None and s._marks == {}
    assert s.cursor == 0 and s._word_anchor is None and s._overlay_pick is None


def test_hint_entries_nav_rows():
    walk = {e["verb"]: e for e in panes.hint_entries(
        SimpleNamespace(stage="correct", lane="walk"))}
    assert walk["gate_editor"]["key"] == "W"
    assert walk["back"]["key"] == "B"
    assert "flywheel_page" in walk
    for lane in ("assign", "propose", "annotate"):
        verbs = {e["verb"] for e in panes.hint_entries(
            SimpleNamespace(stage="correct", lane=lane))}
        assert {"back", "flywheel_page"} <= verbs
    spine = panes.hint_entries(SimpleNamespace(stage="spine", lane="walk"))
    assert any(e["verb"] == "back" for e in spine)
    select = panes.hint_entries(SimpleNamespace(stage="select", lane="walk"))
    assert all(e["verb"] != "back" for e in select)   # front door has no back
    fly = {e["verb"]: e for e in panes.hint_entries(
        SimpleNamespace(stage="flywheel", lane="walk"))}
    assert fly["flywheel_page"]["key"] == "F/esc"
