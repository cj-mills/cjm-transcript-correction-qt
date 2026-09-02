"""The FILTER lane (55bcc3c5, the filtering payload of the kit HITL confirm):
the lane state's derivations over SimpleNamespace spines — pending worklist
items with the spine-index coordinate, run resolution BY TIME with the drift
flag, the payload card lines, the derived verdicts, the local echoes — plus
the shell's lane gate / key table / cards chips / status chips for the lane
(the test_gestures strategy: pure functions and unbound methods, no window)."""

from types import SimpleNamespace

from cjm_transcript_correction_core.models import FILTER_LANE_ACTIONS, FILTER_ONLY_ACTIONS
from cjm_transcript_correction_qt import panes
from cjm_transcript_correction_qt.app import CorrectionWindow
from cjm_transcript_correction_qt.filtering import FilterLane

from test_panes import make_state, make_view, seg


def _prop(pid, cat, start, end, ids, tier=1, conf=0.9, quote="q", rationale="why"):
    return {"proposal_id": pid, "category": cat, "start_time": start, "end_time": end,
            "segment_ids": ids, "tier": tier, "confidence": conf, "rationale": rationale,
            "evidence": {"quote": quote, "from_i": 0, "to_i": 0}}


def _stratum(sid, cat, ids, start, end, proposal_id=None):
    return {"id": sid, "correction_type": "stratum", "status": "applied", "actor": "human",
            "created_at": 1.0,
            "payload": {"operation": "classify", "source_id": "src-1", "category": cat,
                        "segment_ids": ids, "start_time": start, "end_time": end,
                        "proposal_id": proposal_id}}


def spine():
    # #0 header (now EMPTY after a boundary shift), #1 "Lesson 1." #2 "Confusion",
    # #3 body, #4 quote start, #5 quote body, #6 restored "End quote.", #7 author resumes
    return make_view([
        seg(0, text="", start=127.8, end=128.6),
        seg(1, text="Lesson 1.", start=128.7, end=129.6),
        seg(2, text="Confusion", start=130.5, end=131.3),
        seg(3, text="The sequence of school curricula", start=132.5, end=137.2),
        seg(4, text="Gatto wrote, quote", start=249.8, end=251.0),
        seg(5, text="I teach that students must stay", start=251.2, end=278.2),
        seg(6, text="End quote.", start=278.95, end=279.8),
        seg(7, text="Kids learn to stay where they're put.", start=280.95, end=282.9),
    ], skeleton_hash="sha256:skel", source_id="src-1")


def lane(**kw):
    manifest = {"proposal_set_id": "propset_20260901_202934_d38dd68c",
                "model": {"kind": "claude-code-subagent", "name": "reader-lg04", "model": "m"},
                "pack": {"pack_id": "pack_x", "digest": "sha256:abc", "segments": 8},
                "window": {"start": 2.1, "end": 935.0}}
    proposals = [
        _prop("p-header", "apparatus", 127.8, 128.6, ["s0"], quote="Lesson 1. Confusion"),
        _prop("p-quote", "quotation", 249.8, 278.2, ["s4", "s5"], tier=2, conf=0.8,
              quote="I teach that students"),
        _prop("p-body", "research-mark", 132.5, 137.2, ["s3"], conf=0.6, quote="sequence"),
    ]
    d = dict(sets=[{"manifest": manifest, "path": "/x/manifest.json", "proposals": proposals}])
    d.update(kw)
    return FilterLane(**d)


def test_pending_items_carry_the_spine_index_and_tier_gate():
    f, view = lane(), spine()
    items = f.items(view)
    assert [it["key"] for it in items] == ["p-header", "p-body"]   # tier 2 hidden by default
    assert items[1]["index"] == 3 and items[1]["category"] == "research-mark"
    f.show_tier2 = True
    items = f.items(view)
    assert [it["key"] for it in items] == ["p-header", "p-body", "p-quote"]  # time order
    assert items[0]["index"] is None                         # the packed segment went empty
    assert items[2]["index"] == 4 and items[2]["tier"] == 2


def test_run_resolves_by_time_and_flags_drift():
    f, view = lane(show_tier2=True), spine()
    header, quote, body = f.proposals
    assert f.covering_positions(view, header) == []          # nothing text-bearing under 127.8-128.6
    assert f.drifted(view, header)
    assert f.covering_positions(view, body) == [3] and not f.drifted(view, body)
    assert f.covering_positions(view, quote) == [4, 5]       # the restored bookend is OUTSIDE the span
    assert not f.drifted(view, quote)                        # frozen ids still name the run
    f.refresh_index(view)
    assert [p["proposal_id"] for p in f.pending_index["s4"]] == ["p-quote"]
    assert "s0" not in f.pending_index


def test_payload_lines_show_rationale_quote_run_and_span_anchor():
    f, view = lane(show_tier2=True), spine()
    f.cursor = 2
    p = f.current()
    assert p["proposal_id"] == "p-quote"
    lines = f.payload_lines(view, p, width=80)
    flat = ["".join(t for t, _ in ln) for ln in lines]
    assert flat[0].startswith("?? quotation · 04:09.8–04:38.2 · spine 4–5")
    assert any(l.startswith("Why: why") for l in flat)
    assert any("Quote: “I teach that students”" in l for l in flat)
    assert any("#4 04:09.8  Gatto wrote, quote" in l for l in flat)
    assert any("#6 04:38.9  End quote." in l for l in flat)   # one context line after
    assert not any("drifted" in l for l in flat)
    f.span = (249.8, 279.8)
    flat = ["".join(t for t, _ in ln) for ln in f.payload_lines(view, p, width=80)]
    assert flat[-1].startswith("  span edit: 04:09.8–04:39.8")
    f.cursor = 0
    flat = ["".join(t for t, _ in ln) for ln in f.payload_lines(view, f.current(), width=80)]
    assert any("no text segment of the current spine overlaps" in l for l in flat)
    assert f.payload_lines(view, None) == []


def test_echoes_move_rows_out_of_the_worklist_and_into_the_bench():
    f, view = lane(show_tier2=True), spine()
    assert len(f.pending()) == 3
    f.echo_stratum(_stratum("st1", "quotation", ["s4", "s5", "s6"], 249.8, 279.8,
                            proposal_id="p-quote"))
    assert [p["proposal_id"] for p in f.pending()] == ["p-header", "p-body"]
    assert f.span is None and f.strata_at("s6")[0]["id"] == "st1"
    f.echo_mark("p-body")
    assert [p["proposal_id"] for p in f.pending()] == ["p-header"]
    f.echo_gate({"annotated_through": 935.0, "extraction_status": "in_progress"})
    t1, t2, wm, extra = f.verdicts()
    assert wm == "935.0s" and extra.startswith("1 live strata")
    assert t1["accepted"] == 1 and t1["rejected"] == 1      # the mark counts; the header is below the watermark
    assert t2["accepted"] == 1                               # the quotation: IoU 0.95 vs the 1.0-tolerance? edited otherwise
    f.echo_retract("st1")
    assert [p["proposal_id"] for p in f.pending()] == ["p-header", "p-quote"]
    prov = dict(f.provenance("human", "sess-12345678"))
    assert prov["proposer"] == "claude-code-subagent:reader-lg04 (m)"
    assert prov["session"] == "sess-123 · actor human" and prov["window"] == "00:02.1–15:35.0"


def test_lane_gate_and_key_table():
    ok = SimpleNamespace(stage="correct", lane="filter", view=None)
    assert CorrectionWindow._allowed(ok, "filter_accept")
    assert CorrectionWindow._allowed(ok, "next") and CorrectionWindow._allowed(ok, "back")
    assert not CorrectionWindow._allowed(ok, "edit")         # the lane never edits text
    assert not CorrectionWindow._allowed(ok, "nudge_end_earlier")
    walk = SimpleNamespace(stage="correct", lane="walk", view=None)
    assert not CorrectionWindow._allowed(walk, "filter_accept")   # inert outside the lane
    assert FILTER_ONLY_ACTIONS <= FILTER_LANE_ACTIONS

    class Host:
        def __getattr__(self, name):
            return lambda *a, **k: None

    host = Host()
    CorrectionWindow._build_key_table(host)
    table = host._key_table
    bound = {a for acts in table.values() for a, _ in acts}
    assert FILTER_ONLY_ACTIONS <= bound
    assert [a for a, _ in table["E"]] == ["filter_accept_span"]
    assert "filter_span_start" in [a for a, _ in table[","]]
    assert "filter_jump" in [a for a, _ in table["enter"]]


def test_cards_and_status_paint_the_lane():
    f, view = lane(show_tier2=True), spine()
    f.echo_stratum(_stratum("st1", "apparatus", ["s1", "s2"], 128.7, 131.3, proposal_id="p-header"))
    f.span = (249.8, None)
    f.refresh_index(view)
    s = make_state(view, lane="filter", cursor=4, _filter=f, stage="correct")
    lines, _ = panes.card_lines(s, 4, 80)
    flat = "".join("".join(t for t, _ in ln) for ln in lines)
    assert "??quotation 0.80 ▏" in flat and "⟦" in flat        # pending chip + span-start anchor
    lines, _ = panes.card_lines(s, 1, 80)
    flat = "".join("".join(t for t, _ in ln) for ln in lines)
    assert "▣apparatus ▏" in flat                              # live stratum chip
    chips = dict(panes.status_chips(s))
    assert chips["lane"].startswith("[FILTER]")
    assert chips["proposals"] == "proposals 2 pending · tier2 1 shown"
    assert chips["strata"] == "▣ 1" and chips["watermark"] == "watermark none"
    verbs = {e["verb"] for e in panes.hint_entries(s)}
    assert {"filter_accept", "filter_accept_span", "filter_mark", "filter_watermark"} <= verbs
    assert panes.default_pins(s)[0] == "filter_accept"


# ---- cursor-anchored selection (the off-cursor accept, 2026-09-02) -------------

def two_on_one_segment():
    """ch05's #38: a research-mark AND a quotation both cover the same
    segment; the quotation runs on over the next two."""
    view = make_view([
        seg(0, text="Prussia built schools", start=100.0, end=105.0),
        seg(1, text="As the philosopher Fichte put it,", start=113.8, end=116.5),
        seg(2, text="the citizens should be made able", start=117.1, end=121.1),
        seg(3, text="and willing to use their own minds", start=121.5, end=126.6),
        seg(4, text="Lego used to come in all colors", start=363.6, end=369.4),
    ], skeleton_hash="sha256:skel", source_id="src-1")
    proposals = [
        _prop("p-rm", "research-mark", 113.8, 116.5, ["s1"], quote="Fichte"),
        _prop("p-q", "quotation", 113.8, 126.6, ["s1", "s2", "s3"], quote="the citizens"),
        _prop("p-lego", "research-mark", 363.6, 369.4, ["s4"], tier=2, quote="Lego"),
    ]
    manifest = {"proposal_set_id": "propset_x", "model": {"name": "r"},
                "pack": {"pack_id": "pack_x", "digest": "d", "segments": 5},
                "window": {"start": 0.0, "end": 400.0}}
    return view, FilterLane(sets=[{"manifest": manifest, "path": "/x/m.json",
                                   "proposals": proposals}], show_tier2=True)


def test_current_is_the_cursor_segments_pending_proposal_never_the_next_row():
    view, f = two_on_one_segment()
    f.cursor = 2   # a stale worklist index (pointing at the Lego row) must not win
    assert f.current(view, 1)["proposal_id"] == "p-rm"     # first in time order at #1
    assert f.cursor == 0                                    # worklist cursor follows
    assert f.current(view, 0) is None                       # nothing pending at #0
    assert f.current(view, 2)["proposal_id"] == "p-q"       # only the quotation covers #2


def test_after_accepting_one_class_the_other_still_pending_on_that_segment():
    view, f = two_on_one_segment()
    f.selected_id = "p-rm"
    assert f.current(view, 1)["proposal_id"] == "p-rm"
    f.echo_stratum(_stratum("c1", "research-mark", ["s1"], 113.8, 116.5, proposal_id="p-rm"))
    p = f.current(view, 1)                                  # the cursor did not move
    assert p is not None and p["proposal_id"] == "p-q", "the quotation is still pending at #1"
    assert f.cursor == f.pending().index(p)


def test_selected_id_tie_breaks_among_proposals_on_one_segment():
    view, f = two_on_one_segment()
    f.selected_id = "p-q"
    assert f.current(view, 1)["proposal_id"] == "p-q"
    f.selected_id = "p-nope"                                # a stale selection falls back
    assert f.current(view, 1)["proposal_id"] == "p-rm"


def test_step_reaches_the_second_class_on_the_same_segment_then_moves_on():
    view, f = two_on_one_segment()
    assert f.step(view, 1, +1)["proposal_id"] == "p-q"      # from p-rm at #1: next in list order
    assert f.selected_id == "p-q"
    assert f.step(view, 1, +1)["proposal_id"] == "p-lego"   # then the next segment's row
    assert f.step(view, 4, +1) is None                      # end of the list
    assert f.step(view, 4, -1)["proposal_id"] == "p-q"      # back: previous in list order
    assert f.step(view, 0, +1)["proposal_id"] == "p-rm"     # no proposal at #0: first after it
    assert f.step(view, 0, -1) is None


def test_focus_row_looks_ahead_when_the_cursor_has_nothing_pending():
    view, f = two_on_one_segment()
    assert f.focus_row(view, 0)["proposal_id"] == "p-rm"    # next pending at/after #0
    assert f.focus_row(view, 3)["proposal_id"] == "p-q"     # covers #3
    f.selected_id = "p-lego"
    assert f.focus_row(view, 0)["proposal_id"] == "p-lego"  # a live selection wins the card
    for p in list(f.pending()):
        f.echo_stratum(_stratum("c" + p["proposal_id"], p["category"], p["segment_ids"],
                                p["start_time"], p["end_time"], proposal_id=p["proposal_id"]))
    assert f.focus_row(view, 0) is None


def test_run_span_sounds_the_current_run_not_the_frozen_proposal_times():
    """R audition sighting (2026-09-02): a walk-lane nudge moved #129's
    start earlier; r replayed the nudged span, R the frozen one."""
    view, f = two_on_one_segment()
    view.segments[1].start_time = 113.3          # nudged 0.5 s earlier after the pack
    p = f.pending()[0]                            # p-rm over #1
    assert f.run_span(view, p) == (113.3, 116.5)
    q = next(x for x in f.pending() if x["proposal_id"] == "p-q")
    assert f.run_span(view, q) == (113.3, 126.6)  # the run's first start, last end
    orphan = _prop("p-none", "tangent", 900.0, 901.0, ["s9"])
    assert f.run_span(view, orphan) == (900.0, 901.0)   # nothing covers: frozen times
