"""Footer decomposition contract (DEC 2a42c028): chips carry identity/
position only (no keybar text), the hint model is lane-scoped declarative
data, and default pins project a compact hint line."""

from types import SimpleNamespace

from cjm_substrate_qt_kit.keyhints import hint_line

from cjm_transcript_correction_qt import panes

from test_panes import make_state, make_view, seg


def walk_state(**kw):
    view = make_view([seg(0, start=1.0, end=2.5), seg(1, start=2.5, end=4.0)])
    kw.setdefault("stage", "correct")
    return make_state(view, **kw)


def test_status_chips_walk_identity_only():
    s = walk_state()
    chips = dict(panes.status_chips(s))
    assert chips["lane"] == "[WALK]"
    assert chips["source"] == "Talk"
    assert chips["segment"] == "segment 1/2"
    assert chips["speed"] == "×1"
    assert chips["session"] == "session abcdef12"
    text = " ".join(chips.values())
    assert "j/k" not in text and "quit" not in text  # keybar left the strip


def test_status_chips_lane_extras_swap():
    walk = [n for n, _ in panes.status_chips(walk_state())]
    assign = [n for n, _ in panes.status_chips(walk_state(lane="assign"))]
    assert "edited" in walk and "assigned" not in walk
    assert "assigned" in assign and "edited" not in assign
    assert walk[-2:] == assign[-2:] == ["speed", "session"]


def test_hint_entries_lane_and_stage_scoping():
    verbs = {e["verb"] for e in panes.hint_entries(walk_state())}
    assert "edit" in verbs and "assign_accept" not in verbs
    a_verbs = {e["verb"] for e in panes.hint_entries(walk_state(lane="assign"))}
    assert "assign_accept" in a_verbs and "mark_quick" not in a_verbs
    picker = panes.hint_entries(walk_state(stage="select"))
    assert {e["group"] for e in picker} == {"Picker"}
    groups = [e["group"] for e in panes.hint_entries(walk_state())]
    assert groups.index("Walk") < groups.index("App")  # grouped, ordered


def test_default_pins_project_hint_line():
    s = walk_state()
    pins = panes.default_pins(s)
    assert 3 <= len(pins) <= 5
    line = hint_line(panes.hint_entries(s), pins)
    assert line.endswith("? keys")
    assert "replay" in line
    assert panes.default_pins(walk_state(lane="assign"))[0] == "assign_accept"


def test_picker_and_flywheel_chips_drop_keybar():
    s = SimpleNamespace(_graph_db_path="/tmp/g.db", _sources=[("a", "A")],
                        _datasets=[1, 2], _extract_busy=False)
    assert "j/k" not in panes.picker_status_chip(s)
    assert panes.flywheel_status_chip(s) == "flywheel (2 datasets)"
    s._extract_busy = True
    assert "extracting…" in panes.flywheel_status_chip(s)
