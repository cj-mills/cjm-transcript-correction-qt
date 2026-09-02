"""The FILTER lane's state + pure builders (work item 55bcc3c5, the filtering
payload of the kit HITL confirm component): one filtering proposal set over
the open spine, the live strata, the mark-family accepts, the lane's own
watermark, and the derivations the shell paints — the pending worklist (kit
items), the payload card (rationale + quote + the verbatim run from the
CURRENT effective spine with spine indices), the derived verdicts and the
provenance pairs.

Qt-free on purpose: every gesture the window submits ends in a local ECHO
here (echo_stratum / echo_retract / echo_mark / echo_gate), exactly like
SpineView's *_local echoes — the graph is written first, the lane re-derives
from its own state, no reload.

Drift is a first-class fact of this lane (user ruling 2026-09-01): a
proposal's segment ids froze at pack time while the walk lane keeps moving
text between neighbours, so the card shows the run BY TIME over the current
spine and flags when the frozen ids no longer match it; the span-edit
gesture (mark start / end at the cursor, accept over the marked span) is the
repair, and it resolves through the same select_span_segments the headless
verb uses."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cjm_substrate_qt_kit.hitl import fmt_ts
from cjm_transcript_correction_core.graph import load_extraction_gates, load_source_corrections
from cjm_transcript_correction_core.strata import (active_strata, bench_filter_proposals,
                                                   FILTER_LANE, load_filter_proposal_sets,
                                                   materialized_mark_ids, pending_filter_proposals,
                                                   strata_index)

from . import panes

Line = List[Tuple[str, str]]

_EPS = 0.01


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


@dataclass
class FilterLane:
    """The lane's state for ONE open spine: the sets found for it (newest
    first; the chosen one by set_index), the live strata + materialized
    mark-family accepts, the lane gate, the packs the sets cite, and the
    shell-side cursor / tier / span-edit anchors."""

    sets: List[Dict[str, Any]]
    set_index: int = 0
    strata: List[Dict[str, Any]] = field(default_factory=list)
    mark_ids: set = field(default_factory=set)
    gate: Dict[str, Any] = field(default_factory=dict)
    packs: Dict[str, Optional[Dict[str, Any]]] = field(default_factory=dict)
    show_tier2: bool = False
    span: Optional[Tuple[Optional[float], Optional[float]]] = None
    cursor: int = 0
    selected_id: Optional[str] = None   # the worklist's chosen proposal (tie-break among several at one segment)
    pending_index: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    strata_map: Dict[str, List[str]] = field(default_factory=dict)

    # ---- the chosen set --------------------------------------------------

    @property
    def manifest(self) -> Dict[str, Any]:
        return (self.sets[self.set_index]["manifest"] if self.sets else {})

    @property
    def proposals(self) -> List[Dict[str, Any]]:
        return (self.sets[self.set_index]["proposals"] if self.sets else [])

    @property
    def set_id(self) -> str:
        return str(self.manifest.get("proposal_set_id") or "")

    @property
    def watermark(self) -> Optional[float]:
        wm = (self.gate or {}).get("annotated_through")
        return float(wm) if wm is not None else None

    @property
    def window(self) -> Tuple[float, Optional[float]]:
        w = self.manifest.get("window") or {}
        return (float(w.get("start") or 0.0), w.get("end"))

    def cycle_set(self, delta: int = 1) -> None:
        if self.sets:
            self.set_index = (self.set_index + delta) % len(self.sets)
            self.cursor = 0
            self.span = None

    # ---- derivations -----------------------------------------------------

    def pending(self) -> List[Dict[str, Any]]:
        """The worklist: proposals with no live stratum or mark carrying
        them and no same-class stratum overlapping them (time order; tier 2
        behind show_tier2)."""
        return pending_filter_proposals(self.proposals, self.strata,
                                        show_tier2=self.show_tier2,
                                        materialized=self.mark_ids)

    def at_cursor(self, view: Any, pos: int) -> List[Dict[str, Any]]:
        """The pending proposals whose span covers spine position `pos`
        (time order) — several when classes overlap on one segment."""
        return [p for p in self.pending() if pos in self.covering_positions(view, p)]

    def current(self, view: Any = None, pos: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """THE proposal a gesture acts on. Cursor-anchored (the fix for the
        off-cursor accept, 2026-09-02): the pending proposal covering the
        SPINE cursor — `selected_id` tie-breaks when several cover it, else
        the first in time order — and None when nothing pending covers the
        cursor. A gesture never acts on a row the walk is not standing on.
        The worklist cursor follows the resolution. The legacy no-argument
        form keeps the worklist-index semantics for callers without a spine."""
        rows = self.pending()
        if not rows:
            return None
        if view is None or pos is None:
            self.cursor = max(0, min(len(rows) - 1, self.cursor))
            return rows[self.cursor]
        here = self.at_cursor(view, pos)
        if not here:
            return None
        p = next((q for q in here if q.get("proposal_id") == self.selected_id), here[0])
        self.cursor = rows.index(p)
        return p

    def focus_row(self, view: Any, pos: int) -> Optional[Dict[str, Any]]:
        """The worklist row to highlight + card: the cursor's proposal when
        one is pending there, else the selected row if still pending, else
        the next pending row at or after the cursor (the walk's lookahead)."""
        rows = self.pending()
        if not rows:
            return None
        p = self.current(view, pos)
        if p is None:
            p = next((q for q in rows if q.get("proposal_id") == self.selected_id), None)
        if p is None:
            firsts = [(self.covering_positions(view, q)[:1] or [None])[0] for q in rows]
            p = next((q for q, fp in zip(rows, firsts) if fp is not None and fp >= pos), rows[-1])
        self.cursor = rows.index(p)
        return p

    def step(self, view: Any, pos: int, direction: int) -> Optional[Dict[str, Any]]:
        """n/N: the next/previous pending proposal in worklist (time) order
        from the cursor's own proposal when one is pending there — so the
        second class on the same segment is one step away — else the first
        pending row strictly after/before the cursor. Selects it."""
        rows = self.pending()
        if not rows:
            return None
        cur = self.current(view, pos)
        if cur is not None:
            i = rows.index(cur) + (1 if direction > 0 else -1)
            p = rows[i] if 0 <= i < len(rows) else None
        else:
            firsts = [(self.covering_positions(view, q)[:1] or [None])[0] for q in rows]
            cands = [q for q, fp in zip(rows, firsts)
                     if fp is not None and (fp > pos if direction > 0 else fp < pos)]
            p = (cands[0] if direction > 0 else cands[-1]) if cands else None
        if p is not None:
            self.selected_id = p.get("proposal_id")
            self.cursor = rows.index(p)
        return p

    def covering_positions(self, view: Any, p: Dict[str, Any]) -> List[int]:
        """Positions in the CURRENT effective spine whose text-bearing
        segment overlaps the proposal's span — the card's run and the jump
        target (never the frozen segment ids)."""
        ps, pe = float(p.get("start_time") or 0.0), float(p.get("end_time") or 0.0)
        out: List[int] = []
        for i, seg in enumerate(view.segments):
            if not (seg.text or "").strip() or seg.start_time is None or seg.end_time is None:
                continue
            if _overlap(float(seg.start_time), float(seg.end_time), ps, pe) > _EPS:
                out.append(i)
        return out

    def run_span(self, view: Any, p: Dict[str, Any]) -> Tuple[float, float]:
        """The span a gesture SOUNDS for a proposal: the covering run's
        current times on the effective spine (walk-lane nudges and shifts
        included — what an accept would mint), falling back to the frozen
        proposal times when nothing covers it. User sighting 2026-09-02:
        R auditioned the frozen span while r replayed the nudged one."""
        pos = self.covering_positions(view, p)
        times = [(view.segments[i].start_time, view.segments[i].end_time) for i in pos]
        times = [(float(s), float(e)) for s, e in times if s is not None and e is not None]
        if not times:
            return (float(p.get("start_time") or 0.0), float(p.get("end_time") or 0.0))
        return (min(s for s, _ in times), max(e for _, e in times))

    def drifted(self, view: Any, p: Dict[str, Any]) -> bool:
        """The frozen segment ids no longer name the run the span covers."""
        want = [view.segments[i].id for i in self.covering_positions(view, p)]
        return want != list(p.get("segment_ids") or [])

    def refresh_index(self, view: Any) -> None:
        """Rebuild the per-segment maps the cards paint from (once per
        frame, not once per card)."""
        idx: Dict[str, List[Dict[str, Any]]] = {}
        for p in self.pending():
            for i in self.covering_positions(view, p):
                idx.setdefault(view.segments[i].id, []).append(p)
        self.pending_index = idx
        self.strata_map = strata_index(self.strata)

    def strata_at(self, segment_id: str) -> List[Dict[str, Any]]:
        return [c for c in self.strata
                if segment_id in ((c.get("payload") or {}).get("segment_ids") or [])]

    def items(self, view: Any) -> List[Dict[str, Any]]:
        """The kit worklist items for the pending rows (index = the first
        covering spine index, the app's navigation coordinate)."""
        out: List[Dict[str, Any]] = []
        for p in self.pending():
            ev = p.get("evidence") or {}
            pos = self.covering_positions(view, p)
            out.append({"key": p.get("proposal_id"), "tier": int(p.get("tier", 1)),
                        "category": p.get("category"),
                        "start": p.get("start_time"), "end": p.get("end_time"),
                        "confidence": p.get("confidence"), "quote": ev.get("quote") or "",
                        "index": (view.segments[pos[0]].index if pos else None)})
        return out

    def bench(self) -> Dict[str, Any]:
        return bench_filter_proposals(self.proposals, self.strata, self.window,
                                      watermark=self.watermark, mark_ids=self.mark_ids)

    def verdicts(self) -> Tuple[Dict[str, int], Dict[str, int], str, str]:
        """(tier-1 counts, tier-2 counts, watermark text, extra) — the strip's
        arguments."""
        b = self.bench()
        wm = self.watermark
        wm_txt = f"{wm:.1f}s" if wm is not None else "none"
        extra = (f"{len(self.strata)} live strata"
                 + (f" · {len(b['missed'])} missed" if b.get("missed") else ""))
        return b["counts"]["tier1"], b["counts"]["tier2"], wm_txt, extra

    def provenance(self, actor: str, session_id: Optional[str]) -> List[Tuple[str, str]]:
        m = self.manifest
        model = m.get("model") or {}
        pack = m.get("pack") or {}
        w0, w1 = self.window
        return [("set", self.set_id + (f"  ({self.set_index + 1}/{len(self.sets)} · S cycles)"
                                       if len(self.sets) > 1 else "")),
                ("proposer", f"{model.get('kind') or '?'}:{model.get('name') or '?'}"
                             + (f" ({model.get('model')})" if model.get("model") else "")),
                ("pack", f"{pack.get('pack_id') or '?'} · {str(pack.get('digest') or '')[:19]}"
                         f" · {pack.get('segments', '?')} lines"),
                ("window", f"{fmt_ts(w0)}–{fmt_ts(w1) if w1 is not None else 'end'}"),
                ("session", f"{str(session_id or '')[:8]} · actor {actor}")]

    def payload_lines(self, view: Any, p: Optional[Dict[str, Any]],
                      width: int = 96, context: int = 1) -> List[Line]:
        """The PayloadCard: class / tier / times / spine range / confidence,
        the full rationale, the quote, then the verbatim run from the CURRENT
        spine (one context line either side), the drift flag, and the marked
        span-edit anchors when set."""
        if p is None:
            return []
        ev = p.get("evidence") or {}
        tier = int(p.get("tier", 1))
        conf = p.get("confidence")
        pos = self.covering_positions(view, p)
        segs = view.segments
        rng = (f"spine {segs[pos[0]].index}–{segs[pos[-1]].index}" if pos else "spine ?")
        head: Line = [("?? " if tier == 2 else "? ", "dim" if tier == 2 else "bold"),
                      (str(p.get("category") or "?"), "magenta" if tier == 2 else "cyan"),
                      (f" · {fmt_ts(p.get('start_time'))}–{fmt_ts(p.get('end_time'))} · {rng}", "dim"),
                      ((f" · c={float(conf):.2f}" if isinstance(conf, (int, float)) else ""), "dim"),
                      (f" · id …{str(p.get('proposal_id') or '')[-8:]}", "dim")]
        lines: List[Line] = [head]
        if p.get("rationale"):
            lines.extend(panes.wrap_spans([("Why: ", "dim"), (str(p["rationale"]), "")], width))
        if ev.get("quote"):
            lines.append([("Quote: ", "dim"), (f"“{ev['quote']}”", "")])
        if pos:
            lo, hi = max(0, pos[0] - context), min(len(segs), pos[-1] + 1 + context)
            for i in range(lo, hi):
                seg = segs[i]
                if not (seg.text or "").strip():
                    continue
                inside = pos[0] <= i <= pos[-1]
                lines.append([(f"  #{seg.index} {fmt_ts(seg.start_time)}  ", "dim"),
                              (str(seg.text), "" if inside else "dim")])
            if self.drifted(view, p):
                lines.append([("  ⚠ run drifted since the pack — , . mark the run at the cursor, "
                               "E accepts over it", "yellow")])
        else:
            lines.append([("  (no text segment of the current spine overlaps this span)", "yellow")])
        if self.span is not None:
            a, b = self.span
            lines.append([("  span edit: ", "dim"),
                          (f"{fmt_ts(a) if a is not None else '…'}–{fmt_ts(b) if b is not None else '…'}",
                           "yellow"),
                          ("  · E accepts over it · esc clears", "dim")])
        return lines

    # ---- local echoes ----------------------------------------------------

    def echo_stratum(self, correction: Dict[str, Any]) -> None:
        self.strata.append(correction)
        self.strata.sort(key=lambda c: float((c.get("payload") or {}).get("start_time") or 0.0))
        self.span = None

    def echo_retract(self, stratum_id: str) -> None:
        self.strata = [c for c in self.strata if c.get("id") != stratum_id]

    def echo_mark(self, proposal_id: str) -> None:
        self.mark_ids.add(proposal_id)

    def echo_gate(self, gate: Dict[str, Any]) -> None:
        self.gate = dict(gate)


def load_pack(ws_root: str, manifest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The pack a set cites, when the workspace still holds it (None = quote-only)."""
    pid = (manifest.get("pack") or {}).get("pack_id")
    if not pid:
        return None
    path = Path(ws_root) / "packs" / f"{pid}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


async def load_filter_lane(view: Any, ws_root: str) -> Optional[FilterLane]:
    """Loop-side loader: the sets for this source + spine, the live strata
    and mark-family accepts (one corrections read), the lane gate, the packs.
    None when the workspace holds no filtering set for the spine — the lane
    then stays out of the tab rotation."""
    sets = load_filter_proposal_sets(ws_root, view.source_id, skeleton_hash=view.skeleton_hash)
    if not sets:
        return None
    corrections, superseded = await load_source_corrections(view.queue, view.graph_id,
                                                            view.source_id)
    gates = await load_extraction_gates(view.queue, view.graph_id, view.source_id,
                                        lane=FILTER_LANE)
    lane = FilterLane(sets=sets,
                      strata=active_strata(corrections, superseded),
                      mark_ids=materialized_mark_ids(corrections, superseded),
                      gate=dict(gates.get(view.skeleton_hash) or {}))
    for s in sets:
        pid = ((s["manifest"].get("pack") or {}).get("pack_id"))
        if pid and pid not in lane.packs:
            lane.packs[pid] = load_pack(ws_root, s["manifest"])
    return lane
