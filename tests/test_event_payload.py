"""The event-span payload of the kit HITL confirm (55bcc3c5): the propose
lane's pending proposals flatten into worklist items in time order with the
anchor's spine index, the payload card shows the seam and the accept shape
the a-gesture takes, and the strip / provenance derive from the view's
proposal metadata."""

from cjm_transcript_correction_qt.event_payload import (accept_shape, event_items,
                                                        event_payload_lines,
                                                        event_provenance, event_rows,
                                                        event_verdicts)

from test_panes import make_view, seg


def _p(pid, label, start, end, score=0.7, tier=1):
    return {"proposal_id": pid, "label": label, "start_time": start, "end_time": end,
            "score": score, "tier": tier}


def view():
    v = make_view([
        seg(0, text="so that is the plan we settled on for the quarter", start=0.0, end=4.0),
        seg(1, text="and", start=4.6, end=4.9),
        seg(2, text="then we shipped it", start=6.0, end=8.0),
    ], proposals_meta={"proposal_set_id": "propset_x", "training_run_id": "run_y",
                       "window": {"start": 0.0, "end": 8.0}, "classes": ["inhale", "click"],
                       "tier2_total": 3, "pending": 3},
        gate={"annotated_through": 6.0}, inserted_ids={"ins-1"})
    v.event_proposals = {
        "s1": [_p("e-gap", "inhale", 4.95, 5.6)],                 # gap after #1
        "s0": [_p("e-mid", "click", 1.0, 1.5, score=0.4, tier=2),  # mid-chunk in #0 (splittable)
               _p("e-straddle", "inhale", 3.8, 4.7)],               # straddles #0 -> #1
    }
    return v


def test_items_flatten_in_time_order_with_anchor_index():
    v = view()
    rows = event_rows(v)
    assert [(pos, p["proposal_id"]) for pos, p in rows] == [(0, "e-mid"), (0, "e-straddle"), (1, "e-gap")]
    items = event_items(v)
    assert [it["key"] for it in items] == ["e-mid", "e-straddle", "e-gap"]
    assert items[0]["tier"] == 2 and items[0]["category"] == "click" and items[0]["confidence"] == 0.4
    assert items[0]["quote"] == "…s the plan we settled on for the quarter" and items[0]["index"] == 0
    assert items[2]["quote"] == "and" and items[2]["index"] == 1


def test_accept_shape_and_payload_card():
    v = view()
    assert accept_shape(v, 0, _p("x", "click", 1.0, 1.5)).startswith("mid-chunk: a opens the caret")
    assert accept_shape(v, 1, _p("x", "click", 4.7, 4.8)) == "mid-chunk, one word: a inserts an overlay only"
    assert accept_shape(v, 1, _p("x", "inhale", 4.95, 5.6)) == "gap: a inserts after the anchor"
    assert accept_shape(v, 0, _p("x", "inhale", 3.8, 4.7)) == \
        "gap: a inserts after the anchor · anchor end pulled · next start pulled"
    lines = event_payload_lines(v, 1, _p("e-gap", "inhale", 4.95, 5.6), width=80)
    flat = ["".join(t for t, _ in ln) for ln in lines]
    assert flat[0] == "? inhale · 00:05.0–00:05.6 (0.65s) · after spine 1 · score 0.70"
    assert flat[1].startswith("#1 00:04.6–00:04.9  and")   # wrap_spans strips the lead indent
    assert flat[2] == "  ⊕ proposed span 00:05.0–00:05.6"
    assert flat[3].startswith("#2 00:06.0–00:08.0  then we shipped it")
    assert flat[4] == "  gap: a inserts after the anchor"


def test_verdicts_and_provenance_derive_from_view_meta():
    v = view()
    t1, t2, wm, extra = event_verdicts(v)
    assert t1 == {"pending": 2} and t2 == {"pending": 1} and wm == "6.0s"
    assert extra == "⊕ 1 inserts on the spine · 3 tier-2 hidden (t)"
    v.show_tier2 = True
    assert event_verdicts(v)[3] == "⊕ 1 inserts on the spine"
    prov = dict(event_provenance(v, "human", "sess-abcdefgh"))
    assert prov["set"] == "propset_x" and prov["model"] == "training run run_y"
    assert prov["classes"] == "inhale · click" and prov["window"] == "00:00.0–00:08.0"
    assert prov["session"] == "sess-abc · actor human"
