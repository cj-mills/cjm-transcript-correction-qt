"""The ANNOTATE lane's proposal-driven mode (DEC d52d105f): the span lane's
derivations over SimpleNamespace spines — the pending worklist derived from
the view's LIVE overlays, arm / step / token ranges on the current line, the
payload card's ⟦…⟧ mark and drift flag, the derived verdicts — plus the
shell's lane gate / key table / lane order / armed-commit provenance (the
test_gestures strategy: pure functions and unbound methods, no window)."""

import asyncio
from types import SimpleNamespace

from cjm_transcript_correction_core.models import ANNOTATE_LANE_ACTIONS, ANNOTATE_ONLY_ACTIONS
from cjm_transcript_correction_qt import app as app_module
from cjm_transcript_correction_qt import panes
from cjm_transcript_correction_qt.app import CorrectionWindow
from cjm_transcript_correction_qt.spanlane import label_consequence, SpanLane

from test_panes import flat, make_state, make_view, seg


def _prop(pid, label, sid, cs, ce, snap, start, tier=1, conf=0.9, index=0, origins=None):
    return {"proposal_id": pid, "label": label, "category": label, "segment_id": sid,
            "index": index, "tier": tier, "confidence": conf, "rationale": f"why {pid}",
            "anchor": {"kind": "span", "segment_id": sid, "char_start": cs, "char_end": ce,
                       "text_snapshot": snap},
            "start_time": start, "end_time": start + 0.3, "snap": "estimated",
            "origins": origins or []}


def _overlay(oid, label, sid, cs, ce, text, start, proposal_id=None):
    return {"id": oid, "correction_type": "annotation", "actor": "human",
            "payload": {"operation": "speech_overlay", "label": label, "text": text,
                        "anchor": {"kind": "span", "segment_id": sid, "char_start": cs,
                                   "char_end": ce, "text_snapshot": text},
                        "start_time": start, "end_time": start + 0.3, "snap": "fa",
                        "proposal_id": proposal_id}}


def spine(overlays=None):
    #        0         1         2         3
    #        0123456789012345678901234567890123456
    # s1: "So, um, the the kernel is, like, fast"
    view = make_view([
        seg(0, text="Welcome back.", start=0.0, end=1.0),
        seg(1, text="So, um, the the kernel is, like, fast", start=1.0, end=5.0),
        seg(2, text="", start=5.0, end=5.5),
        seg(3, text="and, uh, it works", start=5.5, end=8.0),
    ], skeleton_hash="sha256:skel", source_id="src-1")
    view.overlays = list(overlays or [])
    view.overlay_count = len(view.overlays)
    view.overlays_for = lambda sid: [
        o for o in view.overlays if o["payload"]["anchor"]["segment_id"] == sid]
    return view


def lane(**kw):
    manifest = {"proposal_set_id": "propset_20260918_113855_ee2a7291",
                "model": {"kind": "merge", "name": "spans-w5+lexicon-merged"},
                "pack": {"pack_id": "pack_x", "digest": "sha256:abc", "segments": 4},
                "window": {"start": 0.0, "end": 8.0},
                "merged_from": [{"proposal_set_id": "a"}, {"proposal_set_id": "b"}]}
    proposals = [
        _prop("p-um", "hesitation-marker", "s1", 4, 7, "um,", 1.4, index=1,
              origins=[{"proposer": "capability:span-lexicon", "tier": 1},
                       {"proposer": "spans-w5-01", "tier": 1, "confidence": 0.95}]),
        _prop("p-the", "word-repeat", "s1", 8, 11, "the", 1.8, index=1),
        _prop("p-like", "discourse-marker", "s1", 27, 32, "like,", 3.9, tier=2, conf=0.5, index=1),
        _prop("p-uh", "hesitation-marker", "s3", 5, 8, "uh,", 6.0, index=3),
    ]
    d = dict(sets=[{"manifest": manifest, "path": "/x/manifest.json", "proposals": proposals}])
    d.update(kw)
    return SpanLane(**d)


def test_pending_derives_from_the_views_live_overlays():
    view, f = spine(), lane()
    assert [p["proposal_id"] for p in f.pending(view)] == ["p-um", "p-the", "p-uh"]
    assert f.hidden_tier2(view) == 1
    f.show_tier2 = True
    assert [p["proposal_id"] for p in f.pending(view)] == ["p-um", "p-the", "p-like", "p-uh"]
    # An accept lands on the VIEW (the hand lane's own echo) and the worklist follows;
    # a hand overlay of the same label over the same words closes its row too.
    view.overlays.append(_overlay("o1", "hesitation-marker", "s1", 4, 7, "um,", 1.4, "p-um"))
    view.overlays.append(_overlay("o2", "hesitation-marker", "s3", 5, 8, "uh,", 6.0))
    assert [p["proposal_id"] for p in f.pending(view)] == ["p-the", "p-like"]
    # A removal re-opens its proposal by itself — nothing is stored on the lane.
    view.overlays.pop(0)
    assert [p["proposal_id"] for p in f.pending(view)] == ["p-um", "p-the", "p-like"]


def test_items_index_and_per_segment_maps():
    view, f = spine(), lane()
    items = f.items(view)
    assert [(i["key"], i["category"], i["quote"], i["index"]) for i in items] == [
        ("p-um", "hesitation-marker", "um,", 1), ("p-the", "word-repeat", "the", 1),
        ("p-uh", "hesitation-marker", "uh,", 3)]
    assert f.items(view) is items            # cached until the overlays change
    assert [p["proposal_id"] for p in f.at_segment(view, 1)] == ["p-um", "p-the"]
    assert f.at_segment(view, 0) == []
    assert f.position(view, f.proposals[3]) == 3


def test_arm_step_and_focus_follow_the_cursor():
    view, f = spine(), lane()
    assert f.armed(view, 1) is None
    # Unarmed: forward = first pending on or after the cursor, back = last before it.
    assert f.step(view, 0, 1)["proposal_id"] == "p-um"
    assert f.step(view, 1, 1)["proposal_id"] == "p-um"
    assert f.step(view, 3, -1)["proposal_id"] == "p-the"
    assert f.step(view, 0, -1) is None
    # Armed: the worklist neighbour — the second span on one line is one step away.
    f.armed_id = "p-um"
    assert f.armed(view, 1)["proposal_id"] == "p-um"
    assert f.armed(view, 3) is None          # never a row the cursor is not on
    assert f.step(view, 1, 1)["proposal_id"] == "p-the"
    f.armed_id = "p-uh"
    assert f.step(view, 3, 1) is None
    assert f.step(view, 3, -1)["proposal_id"] == "p-the"
    # Focus: armed row, else the cursor segment's first, else the lookahead.
    assert f.focus_row(view, 3)["proposal_id"] == "p-uh"
    f.armed_id = None
    assert f.focus_row(view, 1)["proposal_id"] == "p-um"
    assert f.focus_row(view, 2)["proposal_id"] == "p-uh" and f.cursor == 2


def test_token_range_reanchors_on_the_current_line():
    view, f = spine(), lane()
    assert f.token_range(view, f.proposals[0]) == (1, 1)      # "um,"
    assert f.token_range(view, f.proposals[1]) == (2, 2)      # the first "the"
    view.segments[1].text = "Right. So, um, the the kernel is, like, fast"   # a walk-lane edit
    assert f.token_range(view, f.proposals[0]) == (2, 2)
    view.segments[1].text = "So the kernel is fast"
    assert f.token_range(view, f.proposals[0]) is None        # words gone: the hand path repairs


def test_payload_card_marks_the_span_and_flags_drift():
    view, f = spine(), lane()
    text = "\n".join(flat(ln) for ln in f.payload_lines(view, f.proposals[0], width=96))
    assert "hesitation-marker" in text and "#1" in text and "why p-um" in text
    assert "So, ⟦um,⟧ the the kernel" in text
    assert "capability:span-lexicon t1 · spans-w5-01 t1 c=0.95" in text
    assert "Welcome back." in text                           # one context line
    view.segments[1].text = "So the kernel is fast"
    text = "\n".join(flat(ln) for ln in f.payload_lines(view, f.proposals[0], width=96))
    assert "no longer on this line" in text and "⟦" not in text
    assert f.payload_lines(view, None) == []


def test_card_names_overlapping_rows_and_what_accepting_does():
    """Finding 67c4af17 + the user's keep-or-filter question: a same-label row
    nested with the armed one is closed UNSEEN when either lands, so the card
    names it; another label's overlapping row is named as staying pending (a
    hidden tier-2 one says so); the head states what accepting DOES, read from
    the clean read's own label tuples."""
    view, f = spine(), lane()
    f.proposals.append(_prop("p-so-um", "hesitation-marker", "s1", 0, 7, "So, um,", 1.0, index=1,
                             origins=[{"proposer": "spans-w5-01"}]))
    f.proposals.append(_prop("p-fs", "false-start", "s1", 4, 15, "um, the the", 1.4, tier=2, index=1))
    um = f.proposals[0]
    assert [q["proposal_id"] for q in f.overlapping(view, um)] == ["p-so-um", "p-fs"]
    text = "\n".join(flat(ln) for ln in f.payload_lines(view, um, width=200))
    assert "⚠ overlaps ?hesitation-marker “So, um,” (spans-w5-01) — SAME label" in text
    assert "overlaps ??false-start “um, the the” [tier 2 hidden · t shows] — another label" in text
    assert "accept → filtered from the clean read" in text
    # once one of the nested pair lands, the other is closed and the note goes with it
    view.overlays.append(_overlay("o1", "hesitation-marker", "s1", 4, 7, "um,", 1.4, "p-um"))
    assert [q["proposal_id"] for q in f.overlapping(view, f.proposals[1])] == ["p-fs"]
    # ... and a row of ANOTHER label over the accepted words names the overlay it would join
    fs_card = "\n".join(flat(ln) for ln in f.payload_lines(view, f.proposals[-1], width=200))
    assert "overlaps accepted ◈ hesitation-marker “um,” — both stand" in fs_card
    assert label_consequence("word-repeat") == (
        "→ filtered from the clean read, last unit survives", "yellow")
    assert label_consequence("emphasis-repeat")[0].startswith("→ KEPT")
    assert label_consequence("my-own-label")[1] == "green"    # only the filter labels subtract


def test_verdicts_and_provenance():
    view, f = spine([_overlay("o1", "hesitation-marker", "s1", 4, 7, "um,", 1.4, "p-um"),
                     _overlay("o2", "discourse-marker", "s1", 8, 11, "the", 1.8, "p-the"),
                     _overlay("o3", "emphasis-repeat", "s0", 0, 7, "Welcome", 0.1)]), lane()
    f.gate = {"annotated_through": 4.0}
    t1, t2, wm, extra = f.verdicts(view)
    assert t1["accepted"] == 1 and t1["relabeled"] == 1 and t1["unvisited"] == 1
    assert t2["unaccepted"] == 1                              # tier-2 'like' sits below the watermark
    assert wm == "4.0s" and "1 by hand (missed)" in extra
    prov = dict(f.provenance("human", "abcdef1234"))
    assert prov["set"] == "propset_20260918_113855_ee2a7291"
    assert "merged from 2 sets" in prov["proposer"]


def test_lane_gate_and_key_table():
    span_actions = {"span_accept", "span_next", "span_prev", "span_jump", "span_tier2",
                    "span_set", "span_watermark"}
    assert span_actions <= ANNOTATE_LANE_ACTIONS and span_actions <= ANNOTATE_ONLY_ACTIONS
    allowed = CorrectionWindow._allowed
    for lane_name in ("walk", "assign", "filter"):
        s = SimpleNamespace(stage="correct", lane=lane_name)
        assert not any(allowed(s, a) for a in span_actions)
    s = SimpleNamespace(stage="correct", lane="annotate")
    assert all(allowed(s, a) for a in span_actions)

    class Host:
        def __getattr__(self, name):
            return lambda *a, **k: None
    host = Host()
    CorrectionWindow._build_key_table(host)
    table = host._key_table

    def first_allowed(key):
        return next(a for a, _ in table[key] if allowed(s, a))
    assert first_allowed("a") == "span_accept"
    assert first_allowed("n") == "span_next" and first_allowed("N") == "span_prev"
    assert first_allowed("p") == "next_overlay" and first_allowed("P") == "prev_overlay"
    assert first_allowed("enter") == "span_jump"
    assert first_allowed("t") == "span_tier2" and first_allowed("S") == "span_set"
    assert first_allowed("W") == "span_watermark"
    walk = SimpleNamespace(stage="correct", lane="walk")
    assert next(a for a, _ in table["p"] if allowed(walk, a)) == "next_prune"


def test_lane_order_follows_the_workflow(monkeypatch):
    monkeypatch.setattr(app_module, "save_tui_state", lambda *a, **k: None)
    calls = []

    def state(lane_name, proposals_meta):
        return SimpleNamespace(
            lane=lane_name, view=SimpleNamespace(proposals_meta=proposals_meta, source_id="src"),
            _filter=SimpleNamespace(sets=[1]), _span=SimpleNamespace(sets=[1]),
            _word_anchor=None, _overlay_pick=None, _graph_db_path="db",
            _reload_filter_lane=lambda: calls.append("filter"),
            _reload_span_lane=lambda: calls.append("span"), _render=lambda: None)
    s, seen = state("propose", {"pending": 1}), []
    for _ in range(5):
        CorrectionWindow._cycle_lane(s, 1)
        seen.append(s.lane)
    assert seen == ["walk", "assign", "filter", "annotate", "propose"]
    s = state("annotate", {})
    CorrectionWindow._cycle_lane(s, 1)
    assert s.lane == "walk"                  # propose stays conditional on a set existing
    CorrectionWindow._cycle_lane(s, -1)
    assert s.lane == "annotate" and calls == []
    # Landing on annotate with no span set loaded re-reads the workspace.
    s = state("filter", {})
    s._span = None
    CorrectionWindow._cycle_lane(s, 1)
    assert s.lane == "annotate" and calls == ["span"]


def _commit_state(view, f, **kw):
    d = dict(view=view, cursor=1, lane="annotate", _span=f, actor="human", session_id="sess",
             _journal_path=None, _graph_db_path="db", _overlay_label="discourse-marker",
             _word_cursor=1, _word_anchor=1, _overlay_pick=None, stage="correct")
    d.update(kw)
    s = SimpleNamespace(**d)
    s._span_ready = lambda: CorrectionWindow._span_ready(s)

    async def snap(seg_):
        return ({"char_start": 4, "char_end": 7, "text": "um,", "start_time": 1.41,
                 "end_time": 1.72, "snap": "fa", "words": [{"s": 1.41, "e": 1.72, "text": "um,"}]},
                None)
    s._snap_selection = snap
    return s


def test_an_armed_commit_carries_the_proposal_and_leaves_the_sticky_label(monkeypatch):
    sent = {}

    async def fake_commit(queue, graph_id, source_id, anchor, label, start, end, text,
                          session_id, **kw):
        sent.update(anchor=anchor, label=label, **kw)
        return "overlay-1"
    monkeypatch.setattr(app_module, "commit_speech_overlay_correction", fake_commit)
    monkeypatch.setattr(app_module, "save_tui_state", lambda *a, **k: None)
    view, f = spine(), lane()
    view.queue = view.graph_id = None
    view.add_overlay_local = lambda o: view.overlays.append(o)
    f.armed_id = "p-um"
    s = _commit_state(view, f)
    out = asyncio.run(CorrectionWindow._do_commit_overlay(s, "hesitation-marker", None))
    assert sent["proposal_id"] == "p-um" and sent["proposal_set_id"] == f.set_id
    assert sent["note"] == "why p-um"
    assert s._overlay_label == "discourse-marker"            # the hand path's sticky label is untouched
    assert view.overlays[-1]["payload"]["proposal_id"] == "p-um"
    assert [p["proposal_id"] for p in f.pending(view)] == ["p-the", "p-uh"]
    assert "accepted" in out["play"][3]
    # Relabel: another label while armed carries the proposal with the relabel note.
    view2, f2 = spine(), lane()
    view2.queue = view2.graph_id = None
    view2.add_overlay_local = lambda o: view2.overlays.append(o)
    f2.armed_id = "p-um"
    out = asyncio.run(CorrectionWindow._do_commit_overlay(_commit_state(view2, f2),
                                                          "discourse-marker", None))
    assert sent["label"] == "discourse-marker" and sent["proposal_id"] == "p-um"
    assert sent["note"].startswith("relabeled from hesitation-marker by human")
    assert "relabeled" in out["play"][3]
    # Unarmed: the hand path, no provenance, the sticky label follows.
    view3, f3 = spine(), lane()
    view3.queue = view3.graph_id = None
    view3.add_overlay_local = lambda o: view3.overlays.append(o)
    s3 = _commit_state(view3, f3)
    asyncio.run(CorrectionWindow._do_commit_overlay(s3, "hesitation-marker", None))
    assert sent["proposal_id"] is None and sent["proposal_set_id"] is None
    assert s3._overlay_label == "hesitation-marker"


def test_a_walk_step_disarms(monkeypatch):
    """The armed proposal's words ARE the word selection; a walk step clears the
    selection, so it must clear the arm too — walking away and back never leaves
    a commit carrying the row over whatever word the cursor reset to."""
    monkeypatch.setattr(app_module, "save_tui_state", lambda *a, **k: None)
    view, f = spine(), lane()
    f.armed_id = "p-um"
    s = SimpleNamespace(stage="correct", view=view, cursor=1, lane="annotate", _span=f,
                        _word_cursor=1, _word_anchor=1, _overlay_pick=None, fold_wordless=False,
                        _state_saved=float("inf"), _graph_db_path="db", autoplay=False,
                        _render=lambda: None)
    assert f.armed(view, 1)["proposal_id"] == "p-um"
    CorrectionWindow._move(s, 1)
    CorrectionWindow._move(s, -1)
    assert s.cursor == 1 and s._word_anchor is None
    assert f.armed_id is None and f.armed(view, 1) is None


def test_cards_chips_and_hints_in_proposal_mode():
    view, f = spine(), lane()
    s = make_state(view, lane="annotate", cursor=0, _span=f, stage="correct")
    f.refresh_index(view)
    lines, _ = panes.card_lines(s, 1, width=100)
    assert "?2 ▏" in "\n".join(flat(ln) for ln in lines)     # two pending spans on the line
    s.cursor = 1
    body = panes.annotate_body(s, view.segments[1])
    words = [(w, st) for w, st in body if w.strip()]
    assert words[0] == ("So,", "bold yellow underline")      # the word cursor is the selection
    assert words[1] == ("um,", "magenta")                    # pending tier 1
    assert words[2] == ("the", "magenta") and words[3] == ("the", "")   # the FIRST 'the' only
    chips = dict(panes.status_chips(s))
    assert chips["proposals"].startswith("spans 3 pending") and "tier2 1 hidden" in chips["proposals"]
    verbs = [h["verb"] for h in panes.hint_entries(s)]
    assert "span_accept" in verbs and "span_next" in verbs and "span_watermark" in verbs
    assert panes.default_pins(s)[:2] == ["span_next", "span_accept"]
    # No set bound: the hand lane, unchanged.
    s2 = make_state(view, lane="annotate", cursor=1, _span=None, stage="correct")
    assert "span_accept" not in [h["verb"] for h in panes.hint_entries(s2)]
    assert panes.default_pins(s2)[0] == "word_right"
