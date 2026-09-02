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
