"""The EVENT-SPAN payload of the kit HITL confirm component (55bcc3c5, the
propose lane re-homed onto the shared chrome): pure builders over the
SpineView's pending event proposals — worklist items (label / tier / span /
score / the anchor's text as the find-it-fast quote / the anchor's spine
index), the payload card (the proposed span against its anchor and the
next segment, and the accept SHAPE the a-gesture will take — gap, straddle
or mid-chunk split), the strip counts and the set provenance.

The propose lane's gestures are untouched (a accepts at the walk cursor,
n/N jump, R auditions, t toggles the audition tier); the panel adds the
listing, the card and enter-to-jump. Qt-free like panes.py."""

from typing import Any, Dict, List, Optional, Tuple

from cjm_substrate_qt_kit.hitl import fmt_ts

from . import panes

Line = List[Tuple[str, str]]

_EPS = 0.05


def _anchor_index(view: Any, anchor_id: str) -> Optional[int]:
    for i, seg in enumerate(view.segments):
        if seg.id == anchor_id:
            return i
    return None


def event_rows(view: Any) -> List[Tuple[int, Dict[str, Any]]]:
    """(anchor position, proposal) pairs for every pending event proposal,
    time order — the flattening of view.event_proposals (anchor id -> list)."""
    out: List[Tuple[int, Dict[str, Any]]] = []
    for anchor_id, props in (getattr(view, "event_proposals", None) or {}).items():
        pos = _anchor_index(view, anchor_id)
        if pos is None:
            continue
        for p in props or []:
            out.append((pos, p))
    out.sort(key=lambda t: (float(t[1].get("start_time") or 0.0), t[0]))
    return out


def event_key(pos: int, p: Dict[str, Any]) -> str:
    """The worklist key: the proposal id when the set carries one, else the
    anchor + span (older sets)."""
    return str(p.get("proposal_id") or f"{pos}:{p.get('start_time')}-{p.get('end_time')}")


def event_items(view: Any) -> List[Dict[str, Any]]:
    """Kit worklist items for the pending event proposals."""
    items: List[Dict[str, Any]] = []
    for pos, p in event_rows(view):
        seg = view.segments[pos]
        tail = (seg.text or "").strip()
        quote = ("…" + tail[-40:]) if len(tail) > 40 else tail
        items.append({"key": event_key(pos, p), "tier": int(p.get("tier", 1)),
                      "category": p.get("label"), "start": p.get("start_time"),
                      "end": p.get("end_time"), "confidence": p.get("score"),
                      "quote": quote or "(empty anchor)", "index": seg.index})
    return items


def accept_shape(view: Any, pos: int, p: Dict[str, Any]) -> str:
    """The shape the a-gesture takes on this row (the propose lane's own
    classification): mid-chunk split, mid-chunk overlay, gap, or straddle."""
    seg = view.segments[pos]
    ps, pe = float(p.get("start_time") or 0.0), float(p.get("end_time") or 0.0)
    a0 = float(seg.start_time) if seg.start_time is not None else None
    a1 = float(seg.end_time) if seg.end_time is not None else None
    interior = (a0 is not None and a1 is not None and ps > a0 + _EPS and pe < a1 - _EPS)
    if interior:
        return ("mid-chunk: a opens the caret editor and splits the text around it"
                if len((seg.text or "").split()) >= 2
                else "mid-chunk, one word: a inserts an overlay only")
    nxt = view.segments[pos + 1] if pos + 1 < len(view.segments) else None
    pulls = []
    if a1 is not None and ps < a1 - _EPS:
        pulls.append("anchor end pulled")
    if nxt is not None and nxt.start_time is not None and pe > float(nxt.start_time) + _EPS:
        pulls.append("next start pulled")
    return "gap: a inserts after the anchor" + (" · " + " · ".join(pulls) if pulls else "")


def event_payload_lines(view: Any, pos: int, p: Dict[str, Any], width: int = 96) -> List[Line]:
    """The event PayloadCard: label / tier / span / duration / anchor index /
    score, the anchor and next segment with their times (the seam the span
    sits in), and the accept shape."""
    seg = view.segments[pos]
    nxt = view.segments[pos + 1] if pos + 1 < len(view.segments) else None
    tier = int(p.get("tier", 1))
    ps, pe = float(p.get("start_time") or 0.0), float(p.get("end_time") or 0.0)
    score = p.get("score")
    head: Line = [("?? " if tier == 2 else "? ", "dim" if tier == 2 else "bold"),
                  (str(p.get("label") or "?"), "magenta" if tier == 2 else "cyan"),
                  (f" · {fmt_ts(ps)}–{fmt_ts(pe)} ({pe - ps:.2f}s) · after spine {seg.index}", "dim"),
                  ((f" · score {float(score):.2f}" if isinstance(score, (int, float)) else ""), "dim")]
    lines: List[Line] = [head]
    lines.extend(panes.wrap_spans(
        [(f"  #{seg.index} {fmt_ts(seg.start_time)}–{fmt_ts(seg.end_time)}  ", "dim"),
         (seg.text or "(empty)", "" if seg.text else "dim")], width))
    lines.append([("  ⊕ proposed span ", "cyan"), (f"{fmt_ts(ps)}–{fmt_ts(pe)}", "cyan")])
    if nxt is not None:
        lines.extend(panes.wrap_spans(
            [(f"  #{nxt.index} {fmt_ts(nxt.start_time)}–{fmt_ts(nxt.end_time)}  ", "dim"),
             (nxt.text or "(empty)", "dim")], width))
    lines.append([("  " + accept_shape(view, pos, p), "yellow")])
    return lines


def event_verdicts(view: Any) -> Tuple[Dict[str, int], Dict[str, int], Optional[str], str]:
    """The strip's arguments for the propose lane: pending per tier (the
    bench for event sets is a flywheel verb, not a lane paint), the gate
    watermark, and the inserts already on the spine."""
    rows = event_rows(view)
    t1 = sum(1 for _, p in rows if int(p.get("tier", 1)) != 2)
    t2 = sum(1 for _, p in rows if int(p.get("tier", 1)) == 2)
    meta = getattr(view, "proposals_meta", None) or {}
    gate = getattr(view, "gate", None) or {}
    wm = gate.get("annotated_through")
    hidden = int(meta.get("tier2_total") or 0) if not getattr(view, "show_tier2", False) else 0
    extra = (f"⊕ {len(getattr(view, 'inserted_ids', ()) or ())} inserts on the spine"
             + (f" · {hidden} tier-2 hidden (t)" if hidden else ""))
    return ({"pending": t1}, {"pending": t2},
            (f"{float(wm):.1f}s" if wm is not None else "none"), extra)


def event_provenance(view: Any, actor: str, session_id: Optional[str]) -> List[Tuple[str, str]]:
    meta = getattr(view, "proposals_meta", None) or {}
    win = meta.get("window") or {}
    w0 = win.get("start")
    w1 = win.get("end")
    return [("set", str(meta.get("proposal_set_id") or "?")),
            ("model", f"training run {str(meta.get('training_run_id') or '?')}"),
            ("classes", " · ".join(str(c) for c in (meta.get("classes") or [])) or "?"),
            ("window", f"{fmt_ts(w0) if w0 is not None else '00:00.0'}–"
                       f"{fmt_ts(w1) if w1 is not None else 'end'}"),
            ("session", f"{str(session_id or '')[:8]} · actor {actor}")]
