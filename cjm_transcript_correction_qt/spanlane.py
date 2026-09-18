"""The ANNOTATE lane's proposal-driven MODE (DEC d52d105f, design bbf8bafd (h)):
one SPAN proposal set over the open spine as the kit HITL worklist, beside the
hand path that stays load-bearing for measurement (the bench derives MISSED
from overlays no proposal matched — they exist only if the human can still
annotate by hand). One lane, two sources: with a span set bound the lane walks
it; with none bound, or off the worklist, it is the hand lane unchanged.

The mode adds NO second commit path. A jump ARMS a proposal: its words become
the lane's ordinary word selection on the CURRENT line (re-anchored through
core's locate_span_tokens), so the hand gestures are the refinement gestures —
accept commits the selection under the proposal's label, a digit commits it
under another (derived verdict: relabeled), a re-selection before the commit
moves the edges (edited). Every commit made while armed carries the proposal
id + set id; pending and the verdicts are DERIVED from the view's live
overlays (nothing stored), so a removal re-opens its proposal by itself.

Qt-free on purpose, like filtering.py: the overlays live on the SpineView (the
hand lane's own local echoes), the lane holds only the sets, the gate and the
shell-side cursor state. Derivations are cached on the overlay-id tuple — a
span set runs to hundreds of rows and the shell repaints per keypress."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from cjm_substrate_qt_kit.hitl import fmt_ts
from cjm_transcript_correction_core.graph import load_extraction_gates
from cjm_transcript_correction_core.spans import (bench_span_proposals, load_span_proposal_sets,
                                                  locate_span_tokens, pending_span_proposals,
                                                  SPAN_LANE)

from . import panes

Line = List[Tuple[str, str]]


@dataclass
class SpanLane:
    """The mode's state for ONE open spine: the span sets found for it (newest
    first; the chosen one by set_index), the span lane's own gate (the
    watermark below which an unmatched proposal derives as rejected), and
    the shell-side cursor / tier / ARMED proposal."""

    sets: List[Dict[str, Any]]
    set_index: int = 0
    gate: Dict[str, Any] = field(default_factory=dict)
    show_tier2: bool = False
    cursor: int = 0
    armed_id: Optional[str] = None   # the proposal the next commit carries (set by a jump, cleared by a walk step)
    pending_index: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    pos_by_id: Dict[str, int] = field(default_factory=dict)
    _cache: Dict[str, Any] = field(default_factory=dict)

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
            self.armed_id = None

    # ---- derivations (cached on the live overlay ids) --------------------

    def _key(self, view: Any) -> Tuple[Any, ...]:
        return (self.set_index, self.show_tier2, self.watermark,
                tuple(o.get("id") for o in view.overlays), len(view.segments))

    def _derived(self, view: Any) -> Dict[str, Any]:
        key = self._key(view)
        if self._cache.get("key") != key:
            self._cache = {"key": key}
        return self._cache

    def pending(self, view: Any) -> List[Dict[str, Any]]:
        """The worklist: proposals no active overlay carries and no same-label
        overlay overlaps on their segment (time order; tier 2 behind
        show_tier2) — core's pending_span_proposals over the view's overlays."""
        d = self._derived(view)
        if "pending" not in d:
            d["pending"] = pending_span_proposals(self.proposals, view.overlays,
                                                  show_tier2=self.show_tier2)
        return d["pending"]

    def hidden_tier2(self, view: Any) -> int:
        if self.show_tier2:
            return 0
        d = self._derived(view)
        if "hidden" not in d:
            d["hidden"] = sum(1 for p in pending_span_proposals(self.proposals, view.overlays,
                                                                show_tier2=True)
                              if int(p.get("tier", 1)) == 2)
        return d["hidden"]

    def refresh_index(self, view: Any) -> None:
        """Rebuild the per-segment maps the cards paint from (once per frame)."""
        d = self._derived(view)
        if "index" not in d:
            idx: Dict[str, List[Dict[str, Any]]] = {}
            for p in self.pending(view):
                idx.setdefault(str((p.get("anchor") or {}).get("segment_id")), []).append(p)
            for rows in idx.values():
                rows.sort(key=lambda q: int((q.get("anchor") or {}).get("char_start") or 0))
            d["index"] = idx
            d["pos"] = {seg.id: i for i, seg in enumerate(view.segments)}
        self.pending_index, self.pos_by_id = d["index"], d["pos"]

    def position(self, view: Any, p: Dict[str, Any]) -> Optional[int]:
        """The proposal's position on the CURRENT spine (None = its segment left it)."""
        self.refresh_index(view)
        return self.pos_by_id.get(str((p.get("anchor") or {}).get("segment_id")))

    def at_segment(self, view: Any, pos: int) -> List[Dict[str, Any]]:
        """The pending proposals on the segment at `pos`, in line order."""
        self.refresh_index(view)
        return list(self.pending_index.get(view.segments[pos].id) or [])

    def armed(self, view: Any, pos: int) -> Optional[Dict[str, Any]]:
        """THE proposal the next commit carries: the armed one, while it is
        still pending AND the walk stands on its segment — a gesture never
        carries a row the cursor is not on."""
        if not self.armed_id:
            return None
        return next((p for p in self.at_segment(view, pos)
                     if p.get("proposal_id") == self.armed_id), None)

    def focus_row(self, view: Any, pos: int) -> Optional[Dict[str, Any]]:
        """The worklist row to highlight + card: the armed proposal, else the
        first pending on the cursor segment, else the next pending at or after
        the cursor (the walk's lookahead)."""
        rows = self.pending(view)
        if not rows:
            return None
        p = self.armed(view, pos)
        if p is None:
            here = self.at_segment(view, pos)
            p = here[0] if here else None
        if p is None:
            placed = ((self.position(view, q), q) for q in rows)
            p = next((q for fp, q in placed if fp is not None and fp >= pos), rows[-1])
        self.cursor = rows.index(p)
        return p

    def step(self, view: Any, pos: int, direction: int) -> Optional[Dict[str, Any]]:
        """n/N: from the armed proposal, its worklist neighbour (the second
        span on one line is one step away); unarmed, the first pending on or
        after the cursor segment going forward, the last before it going back."""
        rows = self.pending(view)
        if not rows:
            return None
        cur = self.armed(view, pos)
        if cur is not None:
            i = rows.index(cur) + (1 if direction > 0 else -1)
            return rows[i] if 0 <= i < len(rows) else None
        placed = [(self.position(view, q), q) for q in rows]
        if direction > 0:
            return next((q for fp, q in placed if fp is not None and fp >= pos), None)
        back = [q for fp, q in placed if fp is not None and fp < pos]
        return back[-1] if back else None

    def token_range(self, view: Any, p: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        """The proposal's whole-token range on the CURRENT line (None = the
        words drifted off it — the hand selection is then the repair)."""
        pos = self.position(view, p)
        if pos is None:
            return None
        try:
            _cs, _ce, a, b = locate_span_tokens(p, view.segments[pos].text or "")
        except ValueError:
            return None
        return a, b

    def items(self, view: Any) -> List[Dict[str, Any]]:
        """The kit worklist items for the pending rows (index = the spine
        index of the proposal's segment, the app's navigation coordinate)."""
        d = self._derived(view)
        if "items" not in d:
            out: List[Dict[str, Any]] = []
            for p in self.pending(view):
                pos = self.position(view, p)
                out.append({"key": p.get("proposal_id"), "tier": int(p.get("tier", 1)),
                            "category": p.get("label"),
                            "start": p.get("start_time"), "end": p.get("end_time"),
                            "confidence": p.get("confidence"),
                            "quote": (p.get("anchor") or {}).get("text_snapshot") or "",
                            "index": (view.segments[pos].index if pos is not None else None)})
            d["items"] = out
        return d["items"]

    def bench(self, view: Any) -> Dict[str, Any]:
        d = self._derived(view)
        if "bench" not in d:
            d["bench"] = bench_span_proposals(self.proposals, view.overlays, self.window,
                                              watermark=self.watermark)
        return d["bench"]

    def verdicts(self, view: Any) -> Tuple[Dict[str, int], Dict[str, int], str, str]:
        """(tier-1 counts, tier-2 counts, watermark text, extra) — the strip's arguments."""
        b = self.bench(view)
        wm = self.watermark
        wm_txt = f"{wm:.1f}s" if wm is not None else "none"
        extra = (f"{view.overlay_count} live ◈"
                 + (f" · {len(b['missed'])} by hand (missed)" if b.get("missed") else ""))
        return b["counts"]["tier1"], b["counts"]["tier2"], wm_txt, extra

    def provenance(self, actor: str, session_id: Optional[str]) -> List[Tuple[str, str]]:
        m = self.manifest
        model = m.get("model") or {}
        pack = m.get("pack") or {}
        w0, w1 = self.window
        merged = m.get("merged_from") or []
        return [("set", self.set_id + (f"  ({self.set_index + 1}/{len(self.sets)} · S cycles)"
                                       if len(self.sets) > 1 else "")),
                ("proposer", f"{model.get('kind') or '?'}:{model.get('name') or '?'}"
                             + (f" ({model.get('model')})" if model.get("model") else "")
                             + (f" · merged from {len(merged)} sets" if merged else "")),
                ("pack", f"{pack.get('pack_id') or '?'} · {str(pack.get('digest') or '')[:19]}"
                         f" · {pack.get('segments', '?')} lines"),
                ("window", f"{fmt_ts(w0)}–{fmt_ts(w1) if w1 is not None else 'end'}"),
                ("session", f"{str(session_id or '')[:8]} · actor {actor}")]

    def payload_lines(self, view: Any, p: Optional[Dict[str, Any]],
                      width: int = 96, context: int = 1) -> List[Line]:
        """The PayloadCard: label / tier / time / spine index / confidence, the
        rationale, the origins (a merged row names every proposer that raised
        it), then the CURRENT line with the span marked ⟦…⟧ (one context line
        either side) and the drift flag when the words left the line."""
        if p is None:
            return []
        tier = int(p.get("tier", 1))
        conf = p.get("confidence")
        a = p.get("anchor") or {}
        pos = self.position(view, p)
        segs = view.segments
        where = f"#{segs[pos].index}" if pos is not None else "#?"
        head: Line = [("?? " if tier == 2 else "? ", "dim" if tier == 2 else "bold"),
                      (str(p.get("label") or "?"), "magenta" if tier == 2 else "cyan"),
                      (f" · {fmt_ts(p.get('start_time'))} · {where}", "dim"),
                      ((f" · c={float(conf):.2f}" if isinstance(conf, (int, float)) else ""), "dim"),
                      (f" · id …{str(p.get('proposal_id') or '')[-8:]}", "dim")]
        lines: List[Line] = [head]
        if p.get("rationale"):
            lines.extend(panes.wrap_spans([("Why: ", "dim"), (str(p["rationale"]), "")], width))
        origins = p.get("origins") or []
        if origins:
            names = [f"{o.get('proposer') or '?'}"
                     + (f" t{int(o['tier'])}" if o.get("tier") is not None else "")
                     + (f" c={float(o['confidence']):.2f}"
                        if isinstance(o.get("confidence"), (int, float)) else "")
                     for o in origins]
            lines.extend(panes.wrap_spans([("Origins: ", "dim"), (" · ".join(names), "dim")], width))
        if pos is None:
            lines.append([("  (the proposal's segment is no longer on the current spine)", "yellow")])
            return lines
        lo, hi = max(0, pos - context), min(len(segs), pos + 1 + context)
        for i in range(lo, hi):
            seg = segs[i]
            text = str(seg.text or "")
            if not text.strip():
                continue
            lead: Line = [(f"  #{seg.index} {fmt_ts(seg.start_time)}  ", "dim")]
            if i != pos:
                lines.extend(panes.wrap_spans(lead + [(text, "dim")], width))
                continue
            try:
                cs, ce, _a, _b = locate_span_tokens(p, text)
            except ValueError:
                lines.extend(panes.wrap_spans(lead + [(text, "")], width))
                lines.append([(f"  ⚠ “{a.get('text_snapshot')}” is no longer on this line — "
                               "select the words by hand (h/l · v), a accepts as edited", "yellow")])
                continue
            lines.extend(panes.wrap_spans(
                lead + [(text[:cs], ""), ("⟦", "yellow"), (text[cs:ce], "bold yellow"),
                        ("⟧", "yellow"), (text[ce:], "")], width))
        return lines

    # ---- local echoes ----------------------------------------------------

    def echo_gate(self, gate: Dict[str, Any]) -> None:
        self.gate = dict(gate)


def gate_echo(gate_id: str, view: Any, status: str, watermark: Optional[float],
              actor: str) -> Dict[str, Any]:
    """The local echo of a span-lane watermark assertion."""
    return {"id": gate_id, "source_id": view.source_id, "skeleton_hash": view.skeleton_hash,
            "extraction_status": status, "annotated_through": watermark, "lane": SPAN_LANE,
            "actor": actor, "created_at": time.time()}


async def load_span_lane(view: Any, ws_root: str) -> Optional[SpanLane]:
    """Loop-side loader (the filter lane's mirror, format-gated to SPAN sets):
    the sets for this source + spine newest first and the span lane's gate.
    None when the workspace holds no span set for the spine — the
    annotate lane is then the hand lane alone."""
    sets = load_span_proposal_sets(ws_root, view.source_id, skeleton_hash=view.skeleton_hash)
    if not sets:
        return None
    gates = await load_extraction_gates(view.queue, view.graph_id, view.source_id,
                                        lane=SPAN_LANE)
    return SpanLane(sets=sets, gate=dict(gates.get(view.skeleton_hash) or {}))
