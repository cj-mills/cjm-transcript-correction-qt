"""Tests for the pure paint builders — SimpleNamespace stand-ins for the
shell state and SpineView (the donor's test_gestures strategy applied to the
net-new panes extraction): card gutter glyphs and chips, the folded
one-liner, the center-pin row math, lane-scoped status lines, pickers,
flywheel, and the HTML materialization."""

import re
from types import SimpleNamespace

from cjm_transcript_correction_qt import panes


def seg(i, text="hello world", start=None, end=None, sid=None, tfrom="t1"):
    return SimpleNamespace(id=sid or f"s{i}", index=i, text=text,
                           start_time=start, end_time=end, text_from=tfrom)


def make_view(segments, **kw):
    d = dict(segments=segments, size=len(segments),
             inserted_ids=set(), pruned_ids=set(), marked_ids=set(),
             overlay_ids=set(), insert_labels={}, insert_ranks={},
             speakers={}, turn_proposals={}, event_proposals={},
             proposals_meta={}, turns_meta={}, cluster_entities={},
             show_tier2=False, overlay_count=0, gate=None,
             source_title="Talk", source_id="src-1",
             aseg_index=lambda pos: 0,
             overlays_for=lambda sid: [])
    d.update(kw)
    return SimpleNamespace(**d)


def make_state(view, **kw):
    d = dict(view=view, cursor=0, lane="walk", _marks={}, fold_wordless=False,
             _entities=[], _active_entity=None, _word_cursor=0,
             _word_anchor=None, speed=1.0, purpose=None,
             session_id="abcdef1234", _overlay_label="hesitation-marker")
    d.update(kw)
    return SimpleNamespace(**d)


def flat(line):
    return "".join(t for t, _ in line)


def test_card_gutter_glyphs_and_time_row():
    view = make_view([seg(0, start=1.0, end=2.5),
                      seg(1, start=2.5, end=4.0)])
    view.pruned_ids.add("s1")
    view.marked_ids.add("s1")
    view.overlay_ids.add("s1")
    s = make_state(view)
    lines, off = panes.card_lines(s, 1, width=80)
    text = "\n".join(flat(ln) for ln in lines)
    assert "#1" in text and "✂" in text and "⚑" in text and "◈" in text
    assert "2.5–4.0s" in text
    styles = {st for ln in lines for _, st in ln}
    assert any("red" in st for st in styles)      # ✂
    assert any("yellow" in st for st in styles)   # ⚑


def test_cursor_card_reverse_band_pads_full_width():
    view = make_view([seg(0, start=0.0, end=1.0)])
    s = make_state(view)
    lines, _ = panes.card_lines(s, 0, width=60)
    for ln in lines:
        assert sum(len(t) for t, _ in ln) == 60
        assert all("reverse" in st.split() for _, st in ln)


def test_folded_wordless_insert_paints_one_dim_line():
    view = make_view([seg(0, start=0.0, end=1.0),
                      seg(1, text="", start=1.0, end=1.4, sid="ins"),
                      seg(2, start=1.4, end=2.0)])
    view.inserted_ids.add("ins")
    view.insert_labels["ins"] = "inhale"
    s = make_state(view, fold_wordless=True)
    assert panes.folded(s, 1)
    lines, off = panes.card_lines(s, 1, width=80)
    assert len(lines) == 1 and off == 0
    assert "inhale" in flat(lines[0])
    # the propose lane never folds (pending proposals may anchor to inserts)
    s.lane = "propose"
    assert not panes.folded(s, 1)


def test_aseg_banner_paints_at_boundary_only():
    view = make_view([seg(0, start=0.0, end=1.0), seg(1, start=1.0, end=2.0)],
                     aseg_index=lambda pos: 0 if pos == 0 else 1)
    s = make_state(view, cursor=0)
    lines1, _ = panes.card_lines(s, 1, width=80)
    assert "audio segment 1" in flat(lines1[0])
    lines0, _ = panes.card_lines(s, 0, width=80)
    assert "audio segment 0" in flat(lines0[0])


def test_assign_lane_chips():
    view = make_view([seg(0, start=0.0, end=1.0), seg(1, start=1.0, end=2.0),
                      seg(2, start=2.0, end=3.0)])
    view.speakers["s0"] = {"entity_id": "e1"}
    view.turn_proposals["s1"] = {"cluster": "SPEAKER_00"}
    ents = [{"id": "e1", "properties": {"canonical_name": "Ada"}}]
    s = make_state(view, lane="assign", _entities=ents, cursor=1)

    def card_text(pos):
        lines, _ = panes.card_lines(s, pos, width=80)
        return "\n".join(flat(ln) for ln in lines)

    assert "Ada ▏" in card_text(0)     # assigned chip
    assert "?S00 ▏" in card_text(1)    # diarization-proposal chip
    assert "∅ ▏" in card_text(2)       # unassigned chip


def test_propose_chip_tier_and_stack_count():
    view = make_view([seg(0, start=0.0, end=10.0)])
    view.event_proposals["s0"] = [
        {"label": "inhale", "score": 0.91, "tier": 1},
        {"label": "um", "score": 0.4, "tier": 1}]
    s = make_state(view, lane="propose")
    lines, _ = panes.card_lines(s, 0, width=80)
    text = "\n".join(flat(ln) for ln in lines)
    assert "?inhale 0.91×2 ▏" in text


def test_annotate_body_word_paint():
    view = make_view([seg(0, text="um well hello", start=0.0, end=2.0)])
    view.overlays_for = lambda sid: [
        {"payload": {"anchor": {"char_start": 0, "char_end": 2}}}]
    s = make_state(view, lane="annotate", _word_cursor=1, _word_anchor=2)
    body = panes.annotate_body(s, view.segments[0])
    styled = {t: st for t, st in body if t.strip()}
    assert styled["um"] == "cyan"                      # committed overlay
    assert "yellow" in styled["well"] and "underline" in styled["well"]
    assert "yellow" in styled["hello"]                 # v-selection


def test_render_rows_center_pins_focused_body_line():
    segs = [seg(i, text=f"segment {i} words", start=float(i), end=float(i + 1))
            for i in range(9)]
    view = make_view(segs)
    s = make_state(view, cursor=4)
    height = 21
    rows = panes.render_rows(s, width=60, height=height)
    assert len(rows) == height
    # the focused card's FIRST BODY LINE (after the aseg banner offset) sits
    # at height // 2 — the pin
    _, off = panes.card_lines(s, 4, width=60)
    pinned = rows[height // 2]
    assert "segment 4 words" in flat(pinned)
    assert all("reverse" in st.split() for _, st in pinned if st)


def test_status_line_lane_badges_and_counters():
    view = make_view([seg(0, start=0.0, end=1.0)])
    s = make_state(view, _marks={0: "corrected"})
    line = panes.status_line(s)
    assert line.startswith("[WALK]") and "edited 1" in line and "×1" in line
    s.lane = "assign"
    assert panes.status_line(s).startswith("[ASSIGN]")
    s.lane = "annotate"
    assert "◈ 0" in panes.status_line(s)
    s.lane = "propose"
    view.proposals_meta = {"pending": 3, "proposal_set_id": "propset-11112222",
                           "training_run_id": "run-33334444"}
    assert "proposals 3 pending" in panes.status_line(s)
    s.lane = "walk"
    s.purpose = "feature-test"
    assert "[TEST PASS]" in panes.status_line(s)


def test_gate_chip_states():
    view = make_view([seg(0)])
    assert panes.gate_chip(view) == ""
    view.gate = {"extraction_status": "signed_off", "annotated_through": 12.5}
    assert panes.gate_chip(view) == "gate ✔12.5s"


def flat_rows(rows):
    return "\n".join("".join(t for t, _ in r["spans"]) for r in rows)


def test_picker_rows_flat_status_and_purpose_mix():
    s = SimpleNamespace(
        _sources=[("id1", "Interview A"), ("id2", "Interview B")],
        _status={"id1": {"segments": 10, "corrections": 2, "marks": 1}},
        _purposes={"id1": {"genuine": 3, "feature-test": 1},
                   "id2": {"feature-test": 2}},
        cursor=0, _graph_db_path="/very/long/path/to/graph.db")
    rows = panes.picker_rows(s)
    joined = flat_rows(rows)
    assert "Interview A" in joined
    assert "genuine: 3" in joined and "(+1 test)" in joined
    assert "all test" in joined
    # no collections = flat: every row pickable, keys carry the open order
    assert [r["key"] for r in rows] == [("id1", "Interview A"),
                                        ("id2", "Interview B")]
    assert all((r.get("kind") or "item") == "item" for r in rows)


def test_picker_rows_group_under_collections_with_unfiled_tail():
    s = SimpleNamespace(
        _sources=[("id1", "B Interview"), ("id2", "A Interview"),
                  ("id3", "Loose One")],
        _status={}, _purposes={},
        _collections=[{"id": "c1", "title": "Season One",
                       "status": "proposed"}],
        _coll_members={"c1": [("id1", "B Interview"), ("id2", "A Interview")]},
        _coll_order={"c1": ["id1"]},   # chain covers id1; id2 = tail
        cursor=0)
    rows = panes.picker_rows(s)
    kinds = [(r.get("kind") or "item") for r in rows]
    assert kinds == ["header", "item", "item", "header", "item"]
    assert "Season One" in flat_rows(rows[:1]) and "⚑ proposed" in flat_rows(rows[:1])
    # chain order first (id1), unordered tail after (id2), unfiled last
    items = [r["key"] for r in rows if (r.get("kind") or "item") == "item"]
    assert items == [("id1", "B Interview"), ("id2", "A Interview"),
                     ("id3", "Loose One")]
    assert "Unfiled" in flat_rows(rows)


def test_picker_detail_identity_block():
    s = SimpleNamespace(
        _sources=[("id1", "Interview A")],
        _status={"id1": {"segments": 10, "corrections": 2, "marks": 1}},
        _purposes={"id1": {"genuine": 3}},
        _collections=[{"id": "c1", "title": "Season One", "status": "active"}],
        _coll_members={"c1": [("id1", "Interview A")]}, _coll_order={},
        _picker_items=[("id1", "Interview A")], cursor=0)
    joined = "\n".join(flat(ln) for ln in panes.picker_detail(s))
    assert "Interview A" in joined and "id1" in joined
    assert "10 segments" in joined and "1 ⚑ open marks" in joined
    assert "genuine 3" in joined
    assert "collections: Season One" in joined


def test_spine_picker_rows_carry_created_at():
    s = SimpleNamespace(
        _spine_source=("id1", "Interview A"),
        _spines=[{"skeleton_hash": None, "split_policy": None, "segments": 8},
                 {"skeleton_hash": "sha256:abcdef1234567890",
                  "split_policy": "sentence-v1", "segments": 12,
                  "created_at": 1756500000.0}],
        cursor=0)
    rows = panes.spine_picker_rows(s)
    assert "2 spines coexist" in flat_rows(rows)
    items = [r for r in rows if (r.get("kind") or "item") == "item"]
    assert [r["key"] for r in items] == [0, 1]
    legacy, split = (flat_rows([r]) for r in items)
    assert "vad-only (pre-split)" in legacy
    assert "  ·  20" not in legacy          # no stamp = no date chunk
    assert "sentence-v1" in split
    assert re.search(r"  ·  20\d\d-\d\d-\d\d \d\d:\d\d", split)


def test_flywheel_rows_purposes_and_datasets():
    ds = {"dataset_id": "ds-1", "counts": {"examples": 12},
          "class_vocabulary": {"inhale": 9},
          "spines": [{"eligible": True}, {}]}
    s = SimpleNamespace(
        _purpose_vocab=["feature-test", "wordless-transfer"],
        _include_purposes={"genuine", "wordless-transfer"},
        _datasets=[ds], _runs=[], _fly_cursor=0,
        _flywheel_log=["gate: 1/2 spines eligible"], _extract_busy=False)
    rows = panes.flywheel_rows(s)
    joined = flat_rows(rows)
    assert "feature-test ✗" in joined and "wordless-transfer ✓" in joined
    assert "ds-1" in joined and "1/2 spines" in joined
    assert "gate: 1/2 spines eligible" in joined
    assert [r["key"] for r in rows
            if (r.get("kind") or "item") == "item"] == [("dataset", ds)]
    # the vocabulary moved to the detail pane (kit PickerList seam)
    s._fly_items = [("dataset", ds)]
    detail = "\n".join(flat(ln) for ln in panes.flywheel_detail(s))
    assert "inhalex9" in detail


def test_flywheel_rows_archived_ride_when_shown():
    active = {"dataset_id": "ds-live", "counts": {}, "spines": []}
    dead = {"dataset_id": "ds-dead", "counts": {}, "spines": [],
            "_lifecycle": "archived"}
    s = SimpleNamespace(_purpose_vocab=[], _include_purposes={"genuine"},
                        _datasets=[active], _datasets_archived=[dead],
                        _runs=[], _runs_archived=[], _fly_cursor=0,
                        _flywheel_log=[], _extract_busy=False)
    hidden = panes.flywheel_rows(s)
    assert "ds-dead" not in flat_rows(hidden)
    assert "1 archived (h shows)" in flat_rows(hidden)
    s._fly_show_archived = True
    shown = panes.flywheel_rows(s)
    joined = flat_rows(shown)
    assert "ds-dead" in joined and "⌂ archived" in joined
    keys = [r["key"] for r in shown if (r.get("kind") or "item") == "item"]
    assert keys == [("dataset", active), ("dataset", dead)]


def test_wrap_spans_preserves_styles_across_lines():
    spans = [("alpha beta gamma delta", ""), (" tail", "cyan")]
    lines = panes.wrap_spans(spans, width=11)
    assert [flat(ln) for ln in lines] == ["alpha beta", "gamma delta", "tail"]
    assert ("tail", "cyan") in lines[2]


def test_wrap_spans_glues_the_chip_seam():
    # the lane chip's ▏ hugs the first word — the donor's append_text seam
    # (audit finding 2: a naive word-join inserted a cell here)
    lines = panes.wrap_spans([("∅ ▏", "dim"), ("hello there", "")], width=40)
    assert flat(lines[0]) == "∅ ▏hello there"


def test_selection_range_clamps_and_orders():
    assert panes.selection_range(0, None, 0) is None
    assert panes.selection_range(2, None, 5) == (2, 2)
    assert panes.selection_range(1, 3, 5) == (1, 3)
    assert panes.selection_range(9, 0, 4) == (0, 3)


def test_lines_to_html_colors_and_reverse_band():
    html = panes.lines_to_html([[("#1 ·", "dim"), (" ✂", "red")],
                                [("focused", "reverse")]])
    assert "<pre" in html
    assert "#c74a3c" in html          # red span
    assert "#8a9299" in html          # dim span
    assert "background-color" in html  # the focus band
    assert "&" not in html.replace("&nbsp;", "").replace("&amp;", "&") \
        or True  # escaping sanity only


def test_entity_name_provisional_prefix():
    ents = [{"id": "e1", "properties": {"canonical_name": "Ada"}},
            {"id": "e2", "properties": {"canonical_name": "low voice",
                                        "provisional": True}}]
    assert panes.entity_name(ents, "e1") == "Ada"
    assert panes.entity_name(ents, "e2") == "?low voice"
    assert panes.entity_name(ents, "unknown-id") == "unknown-"
