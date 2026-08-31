"""Pure paint builders for the correction Qt shell — the Textual paint logic,
Qt-free (DEC 0f11683d). Unlike the transcription/decomp ports, the donor had
NO pure panes (every region was a self-bound method returning rich.Text), so
this module is the net-new extraction: each function is a line-for-line port
of a `CorrectionApp` paint method, re-expressed over "span lines" — a line is
`[(text, style), ...]` with Rich-ish style words ("dim", "cyan", "bold
yellow", "reverse", …) — plus `lines_to_html` to materialize the canvas for a
monospace QTextBrowser. Functions take `s`, the shell state, duck-typed with
the SAME attribute names the Textual app used (view/cursor/lane/_marks/…), so
the port stays diffable against the donor and tests drive plain
SimpleNamespace stand-ins.

Layout stays CHARACTER-CELL: the fixed gutter, the wrap width, and the
center-pin row math are all in cells, exactly the Textual geometry — the
shell measures its font once (QFontMetrics) and asks for (width, height) in
cells. The pin never moves; the spine flows past it."""

import html as _html
import re as _re
import time as _time
from typing import Any, Dict, List, Optional, Tuple

from cjm_transcript_correction_core.models import WORDLESS_INSERT_LABELS
from cjm_transcript_correction_core.spine import segment_word_tokens

Span = Tuple[str, str]
Line = List[Span]

_COLORS = {"red": "#c74a3c", "yellow": "#b9770e", "cyan": "#2b8a9d",
           "magenta": "#9b59b6", "green": "#3f9d55", "blue": "#4a6fb5",
           "bright_magenta": "#c06fd6", "bright_red": "#e0604f",
           "dim": "#8a9299"}
_REVERSE_BG = "#3a5a78"   # the focused card's full-width band


# ---- shared state predicates (ports of App helpers) ----------------------


def wordless_insert(view: Any, pos: int) -> bool:
    """A certified-wordless inserted chunk: wordless CLASS and empty text
    (label AND text must both agree, DEC a5754fa4)."""
    seg = view.segments[pos]
    return (seg.id in view.inserted_ids
            and not (seg.text or "").strip()
            and str(view.insert_labels.get(seg.id) or "") in WORDLESS_INSERT_LABELS)


def folded(s: Any, pos: int) -> bool:
    """Is this position folded away right now? (z toggle; never in the
    propose lane — pending proposals may anchor to inserted segments)."""
    return (s.fold_wordless and s.lane != "propose"
            and wordless_insert(s.view, pos))


def entity_name(entities: List[Dict[str, Any]], entity_id: Optional[str]) -> str:
    """Display name for an entity id; provisional handles read with a leading
    ? (a DESCRIPTION, not an identification — DEC 484e2d74)."""
    for d in entities:
        if d.get("id") == entity_id:
            p = d.get("properties") or {}
            nm = str(p.get("canonical_name") or str(entity_id)[:8])
            return f"?{nm}" if p.get("provisional") else nm
    return str(entity_id or "")[:8]


_CLUSTER_TINTS = ("cyan", "green", "yellow", "blue", "bright_magenta", "bright_red")


def cluster_style(view: Any, cluster: str) -> str:
    """Stable per-cluster tint (dim — a proposal reads quieter than an
    assignment's magenta)."""
    clusters = sorted({str(p.get("cluster")) for p in view.turn_proposals.values()})
    idx = clusters.index(cluster) if cluster in clusters else 0
    return f"dim {_CLUSTER_TINTS[idx % len(_CLUSTER_TINTS)]}"


def selection_range(word_cursor: int, word_anchor: Optional[int],
                    n_tokens: int) -> Optional[Tuple[int, int]]:
    """The selected token range (inclusive), clamped: the v-anchor..cursor
    span when a range is anchored, else the word under the cursor."""
    if n_tokens <= 0:
        return None
    c = max(0, min(n_tokens - 1, word_cursor))
    if word_anchor is None:
        return c, c
    a = max(0, min(n_tokens - 1, word_anchor))
    return (min(a, c), max(a, c))


def gate_chip(view: Any) -> str:
    """The status-strip gate chip: empty when never asserted (the quiet
    in_progress default), else status glyph + watermark seconds."""
    gate = view.gate if view is not None else None
    if not gate:
        return ""
    glyph = {"in_progress": "▶", "signed_off": "✔", "excluded": "✘"}.get(
        str(gate.get("extraction_status")), "?")
    wm = gate.get("annotated_through")
    return f"gate {glyph}{f'{float(wm):.1f}s' if wm is not None else ''}"


# ---- span plumbing -------------------------------------------------------


def _cells(line: Line) -> int:
    return sum(len(t) for t, _ in line)


def _pad(line: Line, width: int, style: str = "") -> None:
    gap = width - _cells(line)
    if gap > 0:
        line.append((" " * gap, style))


def _stylize(line: Line, extra: str) -> Line:
    return [(t, (st + " " + extra).strip()) for t, st in line]


def wrap_spans(spans: Line, width: int) -> List[Line]:
    """Word-wrap styled spans at a cell width (the Textual Text.wrap stand-in):
    breaks land only at whitespace, adjacent spans WITHOUT a space between
    them stay glued (the lane chip's `▏` hugs the first word, the donor's
    append_text seam), internal space runs are preserved, and the space at a
    fold point is dropped."""
    groups: List[Tuple[Line, bool]] = []   # (styled fragment run, is_space)
    for text, style in spans:
        for part in _re.findall(r"\S+|\s+", text):
            if part.isspace():
                groups.append(([(part, style)], True))
            elif groups and not groups[-1][1]:
                groups[-1][0].append((part, style))   # glue across the span seam
            else:
                groups.append(([(part, style)], False))
    if not groups:
        return [[]]
    lines: List[Line] = []
    cur: Line = []
    cur_w = 0
    for frag, is_space in groups:
        w = sum(len(t) for t, _ in frag)
        if not is_space and cur and cur_w + w > width:
            while cur and cur[-1][0].isspace():   # the fold eats the separator
                cur_w -= len(cur.pop()[0])
            lines.append(cur)
            cur, cur_w = [], 0
        if is_space and not cur:
            continue   # no leading space on a folded line
        cur.extend(frag)
        cur_w += w
    while cur and cur[-1][0].isspace():
        cur_w -= len(cur.pop()[0])
    lines.append(cur)
    return lines


# ---- the segment card (port of _card_lines / _gutter_w) ------------------


def gutter_w(view: Any) -> int:
    """The source-wide gutter width: sized ONCE from the last segment (the
    widest index + time span), so the text lane's indent never wobbles."""
    last = view.segments[-1]
    t_w = (len(f"{last.end_time:.1f}–{last.end_time:.1f}s")
           if last.end_time is not None else 0)
    return max(t_w, len("(no audio)"), len(f"#{last.index}") + 6) + 2


def annotate_body(s: Any, seg: Any) -> Line:
    """The focused card's word-level paint in the annotate lane: the word
    cursor underlined, the v-selection yellow, committed overlay spans cyan."""
    toks = segment_word_tokens(seg.text)
    committed = []
    for o in s.view.overlays_for(seg.id):
        a = (o.get("payload") or {}).get("anchor") or {}
        if a.get("char_start") is not None and a.get("char_end") is not None:
            committed.append((int(a["char_start"]), int(a["char_end"])))
    sel = selection_range(s._word_cursor, s._word_anchor, len(toks))
    body: Line = []
    for i, (cs, ce, w) in enumerate(toks):
        if i:
            body.append((" ", ""))
        style = ""
        if any(cs >= a and ce <= b for a, b in committed):
            style = "cyan"
        if sel is not None and sel[0] <= i <= sel[1]:
            style = "bold yellow"
        if i == s._word_cursor:
            style = (style + " underline").strip()
        body.append((w, style))
    return body


def card_lines(s: Any, pos: int, width: int) -> Tuple[List[Line], int]:
    """One segment card as styled span lines + the offset of its first body
    line — the fixed-gutter/one-text-lane layout, cursor reverse band,
    lane chips, folded one-liner, and aseg banner, ported verbatim."""
    view = s.view
    seg = view.segments[pos]
    gut_w = gutter_w(view)
    if pos != s.cursor and folded(s, pos):
        lab = view.insert_labels.get(seg.id) or "wordless"
        row: Line = [(f"⊕{seg.index}".ljust(gut_w), "dim cyan")]
        row.append(((f"({lab} · {seg.start_time:.1f}–{seg.end_time:.1f}s)"
                     if seg.start_time is not None else f"({lab})"), "dim"))
        return [row], 0
    lane_w = max(10, width - gut_w)
    mark = "✎" if s._marks.get(pos) == "corrected" else "·"
    g1: Line = []
    if seg.id in view.inserted_ids:
        g1.append((f"⊕{seg.index} {mark}", "cyan"))
    else:
        g1.append((f"#{seg.index} {mark}", "dim"))
    if seg.id in view.pruned_ids:
        g1.append((" ✂", "red"))
    if seg.id in view.marked_ids:
        g1.append((" ⚑", "yellow"))
    if seg.id in view.overlay_ids:
        g1.append((" ◈", "cyan"))
    g2: Line = [((f"{seg.start_time:.1f}–{seg.end_time:.1f}s"
                  if seg.start_time is not None else "(no audio)"), "dim")]
    if seg.text:
        body: Line = [(seg.text, "")]
    elif seg.id in view.inserted_ids:
        lab = view.insert_labels.get(seg.id)
        body = [(f"(inserted{': ' + lab if lab else ''})", "cyan")]
    else:
        body = [("(empty)", "dim")]
    if s.lane == "assign":
        sp = view.speakers.get(seg.id)
        prop = view.turn_proposals.get(seg.id)
        if sp:
            chip: Line = [(f"{entity_name(s._entities, sp['entity_id'])[:14]} ▏",
                           "magenta")]
        elif prop:
            chip = [(f"?{str(prop['cluster']).replace('SPEAKER_', 'S')} ▏",
                     cluster_style(view, str(prop["cluster"])))]
        else:
            chip = [("∅ ▏", "dim")]
        body = chip + body
    elif s.lane == "propose":
        props = view.event_proposals.get(seg.id)
        if props:
            p = props[0]
            extra = f"×{len(props)}" if len(props) > 1 else ""
            q = "??" if int(p.get("tier", 1)) == 2 else "?"
            chip = [(f"{q}{p.get('label')} {float(p.get('score') or 0):.2f}{extra} ▏",
                     "dim magenta" if q == "??" else "dim cyan")]
            body = chip + body
    elif s.lane == "annotate" and pos == s.cursor and seg.text:
        body = annotate_body(s, seg)
    if abs(pos - s.cursor) > 1 and seg.text:
        body = _stylize(body, "dim")
    lane = wrap_spans(body, lane_w)
    lines: List[Line] = []
    a = view.aseg_index(pos)
    if a is not None and (pos == 0 or view.aseg_index(pos - 1) != a):
        lines.append([(f"━━━ audio segment {a} ━━━", "yellow")])
    body_offset = len(lines)
    gutter = [g1, g2]
    for i in range(max(len(gutter), len(lane))):
        row = list(gutter[i]) if i < len(gutter) else []
        _pad(row, gut_w)
        if i < len(lane):
            row.extend(lane[i])
        lines.append(row)
    if pos == s.cursor:
        banded: List[Line] = []
        for ln in lines:
            _pad(ln, width)
            banded.append(_stylize(ln, "reverse"))
        lines = banded
    return lines, body_offset


# ---- the center-pinned canvas (port of _render's walk branch) ------------


def render_rows(s: Any, width: int, height: int) -> List[Line]:
    """Center-pinned paint: the focused card's first body line pinned to the
    vertical center; neighbor cards stack outward (one blank separator) and
    absorb the height variance, clipping at the canvas edges."""
    rows: List[Optional[Line]] = [None] * max(1, height)

    def place(lines: List[Line], top: int) -> None:
        for i, ln in enumerate(lines):
            if 0 <= top + i < height:
                rows[top + i] = ln

    f_lines, f_off = card_lines(s, s.cursor, width)
    top_f = height // 2 - f_off
    place(f_lines, top_f)
    pos, bottom = s.cursor - 1, top_f - 2
    while pos >= 0 and bottom >= 0:
        lines, _ = card_lines(s, pos, width)
        place(lines, bottom - len(lines) + 1)
        bottom -= len(lines) + 1
        pos -= 1
    pos, top = s.cursor + 1, top_f + len(f_lines) + 1
    while pos < s.view.size and top < height:
        lines, _ = card_lines(s, pos, width)
        place(lines, top)
        top += len(lines) + 1
        pos += 1
    return [r if r is not None else [] for r in rows]


# ---- the status strip (port of _status_line) -----------------------------


def status_line(s: Any) -> str:
    """The unified status strip (DEC cc55a7b5): lane badge + purpose badge +
    position + lane-scoped counters + the ACTIVE LANE's keybar only."""
    view = s.view
    badges = {"assign": "[ASSIGN]", "propose": "[PROPOSE]",
              "annotate": "[ANNOTATE]"}.get(s.lane, "[WALK]")
    if s.purpose:
        badges += (" [TEST PASS]" if s.purpose == "feature-test"
                   else f" [{s.purpose.upper()}]")
    head = (f"{badges}  {view.source_title}"
            f"  ·  segment {s.cursor + 1}/{view.size}")
    chip = gate_chip(view)
    if chip:
        head += f"  ·  {chip}"
    tail = f"  ·  ×{s.speed:g}  ·  session {str(s.session_id or '')[:8]}"
    if s.lane == "assign":
        assigned = sum(1 for seg in view.segments if seg.id in view.speakers)
        active = (entity_name(s._entities, s._active_entity)
                  if s._active_entity else "none")
        meta = view.turns_meta.get("metadata") or {}
        turns = (f"  ·  turns {len(view.turn_proposals)}/{view.size}"
                 f" · {meta.get('speaker_count', '?')}spk"
                 if view.turn_proposals else "  ·  no turns")
        return (f"{head}  ·  assigned {assigned}/{view.size}{turns}"
                f"  ·  speaker: {active}{tail}"
                f"  ·  a accept · 1-9 pick · space same · A new · j/k walk · r replay"
                f" · g/G seam · [/] speed · y copy · tab walk-lane · q quit")
    if s.lane == "propose":
        meta = view.proposals_meta or {}
        pending = meta.get("pending", 0)
        t2 = meta.get("tier2_total", 0)
        tier2 = (f" · tier2 {t2} {'shown' if view.show_tier2 else 'hidden'}"
                 if t2 else "")
        return (f"{head}  ·  proposals {pending} pending{tier2}"
                f" · set {str(meta.get('proposal_set_id') or '')[-8:]}"
                f" · model {str(meta.get('training_run_id') or '')[-8:]}{tail}"
                f"  ·  a accept · n/N jump · R proposal{' · t tier2' if t2 else ''}"
                f" · r chunk · ,./<> nudge"
                f" · i/I manual · L relabel · x remove · e edit · j/k walk"
                f" · g/G seam · tab lane · q quit")
    if s.lane == "annotate":
        seg = view.segments[s.cursor]
        toks = segment_word_tokens(seg.text)
        sel = selection_range(s._word_cursor, s._word_anchor, len(toks))
        if toks and sel is not None:
            a, b = sel
            readout = " ".join(t for _, _, t in toks[a:b + 1])
            readout = readout if len(readout) <= 30 else readout[:29] + "…"
            sel_txt = f"  ·  sel “{readout}”"
        else:
            sel_txt = "  ·  (no words here)" if not toks else ""
        return (f"{head}  ·  ◈ {view.overlay_count}{sel_txt}"
                f"  ·  label: {s._overlay_label}{tail}"
                f"  ·  h/l·←→ word · v range · space ◈commit · 1-9 class"
                f" · A class+ · R audition · ,./<> ◈nudge · x remove · n/N ◈ jump"
                f" · j/k walk · r replay · tab lane · q quit")
    edited = sum(1 for v in s._marks.values() if v == "corrected")
    return (f"{head}  ·  edited {edited}{tail}"
            f"  ·  j/k·w/s walk · ←→/a/d shift · r replay · g/G seam · ,./<> nudge"
            f" · {{}} step · [/] speed · e edit · y copy · i/I ⊕insert · x ⊖remove"
            f" · m/b/M ⚑mark · n/N⚑ p/P✂ jump · z fold⊕ · F gate · tab assign-lane · q quit")


# ---- the pickers (ports of _render_picker / _render_spine_picker) --------


def _source_row(s: Any, sid: str, title: str) -> Dict[str, Any]:
    """One source picker item row (key = (source_id, title) — what a pick
    means to the app): correction status at a glance, the purpose-mix chips."""
    st = s._status.get(sid) or {}
    spans: Line = [("  ", ""), (title or sid[:12], "")]
    spans.append((f"   {st.get('segments', 0)} segs", "dim"))
    spans.append((f" · {st.get('corrections', 0)} corrections", "dim"))
    marks = st.get("marks", 0)
    if marks:
        spans.append((f" · {marks} ⚑", "yellow"))
    mix = s._purposes.get(sid) or {}
    genuine = mix.get("genuine", 0)
    tests = sum(n for p, n in mix.items() if p != "genuine")
    if genuine:
        spans.append((f" · genuine: {genuine}", "green"))
        if tests:
            spans.append((f" (+{tests} test)", "dim"))
    elif tests:
        spans.append((" · all test", "yellow"))
    return {"kind": "item", "spans": spans, "key": (sid, title)}


def picker_rows(s: Any) -> List[Dict[str, Any]]:
    """The 2ce81638 discovery stage as kit PickerList rows (8d29f0f0):
    sources grouped under Collection headers — the hub build_rows grouping
    (chain order first, unordered tail alphabetical, an Unfiled tail for
    sources no collection holds); a graph with no Collections lists flat.
    The app derives its open order from the item keys."""
    if not s._sources:
        return [{"kind": "note",
                 "spans": [("  no Source nodes on this graph", "dim")]}]
    rows: List[Dict[str, Any]] = []
    cols = list(getattr(s, "_collections", []) or [])
    if not cols:
        for sid, title in s._sources:
            rows.append(_source_row(s, sid, title))
        return rows
    members = dict(getattr(s, "_coll_members", {}) or {})
    order = dict(getattr(s, "_coll_order", {}) or {})
    titles = dict(s._sources)
    filed: set = set()
    for c in sorted(cols, key=lambda c: (c.get("title") or "").lower()):
        ms = members.get(c["id"], [])
        flag = "  ⚑ proposed" if c.get("status") == "proposed" else ""
        rows.append({"kind": "header",
                     "spans": [("  " + (c.get("title") or c["id"][:12]), "bold"),
                               (f"   {len(ms)} source(s){flag}", "dim")]})
        member_ids = {i for i, _ in ms}
        ordered = [i for i in order.get(c["id"], []) if i in member_ids]
        tail = sorted((i for i in member_ids if i not in set(ordered)),
                      key=lambda i: (titles.get(i) or "").lower())
        for sid in ordered + tail:
            rows.append(_source_row(s, sid,
                                    titles.get(sid) or dict(ms).get(sid) or sid))
            filed.add(sid)
    unfiled = [(i, t) for i, t in s._sources if i not in filed]
    if unfiled:
        rows.append({"kind": "header",
                     "spans": [("  Unfiled", "bold"),
                               (f"   {len(unfiled)} source(s)", "dim")]})
        for sid, title in sorted(unfiled, key=lambda p: (p[1] or "").lower()):
            rows.append(_source_row(s, sid, title))
    return rows


def picker_detail(s: Any) -> List[Line]:
    """The focused source's identity block (2e0928f2 propagated to the
    correction discovery surface): id + status counts + session-purpose mix
    + the collections holding it — the kit detail pane repaints this alone
    on cursor moves."""
    items = list(getattr(s, "_picker_items", []) or [])
    if not items or not (0 <= s.cursor < len(items)):
        return []
    sid, title = items[s.cursor]
    st = s._status.get(sid) or {}
    lines: List[Line] = [[(title or sid[:12], "bold"), ("  ·  " + sid, "dim")]]
    row: Line = [(f"{st.get('segments', 0)} segments · "
                  f"{st.get('corrections', 0)} corrections", "dim")]
    marks = st.get("marks", 0)
    if marks:
        row.append((f" · {marks} ⚑ open marks", "yellow"))
    lines.append(row)
    mix = s._purposes.get(sid) or {}
    if mix:
        lines.append([("sessions: " + " · ".join(
            f"{p} {n}" for p, n in sorted(mix.items())), "dim")])
    holding = [str(c.get("title") or "")
               for c in getattr(s, "_collections", []) or []
               if any(m == sid for m, _ in
                      (getattr(s, "_coll_members", {}) or {}).get(c["id"], []))]
    if holding:
        lines.append([("collections: " + ", ".join(holding), "dim")])
    return lines


def spine_picker_rows(s: Any) -> List[Dict[str, Any]]:
    """The spine picker (DEC f1024568) as kit rows: one item per coexisting
    SKELETON, keyed by its index into s._spines. Created-at rides each row
    (65cdd573 (a)) so respined skeletons are tellable apart; retire/archive
    filtering (65cdd573 (b)) stays discussion-first."""
    from cjm_transcript_correction_core.state import spine_label
    _, title = s._spine_source or ("", "")
    rows: List[Dict[str, Any]] = [
        {"kind": "note",
         "spans": [("  ", ""), (title or "source", "bold"),
                   (f"  ·  {len(s._spines)} spines coexist — pick one", "dim")]},
        {"kind": "note", "spans": []},
    ]
    for i, sp in enumerate(s._spines):
        spans: Line = [("  ", ""), (spine_label(sp), ""),
                       (f"   {sp.get('segments', 0)} segs", "dim")]
        created = float(sp.get("created_at") or 0.0)
        if created:
            spans.append(("  ·  " + _time.strftime(
                "%Y-%m-%d %H:%M", _time.localtime(created)), "dim"))
        rows.append({"kind": "item", "spans": spans, "key": i})
    return rows


# ---- the flywheel page (port of _render_flywheel) ------------------------


def flywheel_rows(s: Any) -> List[Dict[str, Any]]:
    """The cross-source flywheel page (DEC 82c463fe; restructured per
    48eff28b) as kit rows: purpose toggles, then DATASETS and TRAINING RUNS
    as native grouped items — keys ("dataset", manifest) / ("run", manifest)
    are the app's _fly_items map. Archived artifacts ride the sections
    dimmed + chipped ⌂ when shown (h — the b20cb911 lifecycle surface,
    the decomp trainrun-picker grammar); the last extract fold's log trails
    as notes. The focused row's vocabulary/recipe detail lives in
    flywheel_detail (the kit detail pane)."""
    rows: List[Dict[str, Any]] = []
    purposes: Line = [("  feedstock purposes:  ", ""), ("genuine ✓", "green")]
    for i, p in enumerate(s._purpose_vocab, 1):
        on = p in s._include_purposes
        purposes.append((f"   [{i}] ", ""))
        purposes.append((f"{p} {'✓' if on else '✗'}", "green" if on else "dim"))
    rows.append({"kind": "note", "spans": purposes})
    rows.append({"kind": "note", "spans": []})
    show_arch = bool(getattr(s, "_fly_show_archived", False))
    ds_arch = list(getattr(s, "_datasets_archived", []) or [])

    def arch_note(n: int) -> str:
        return (f" · {n} archived ({'shown' if show_arch else 'h shows'})"
                if n else "")

    rows.append({"kind": "header",
                 "spans": [("  DATASETS", "bold"),
                           (f"  {len(s._datasets)}"
                            f"{arch_note(len(ds_arch))}", "dim")]})
    if not s._datasets and not (show_arch and ds_arch):
        rows.append({"kind": "note", "spans": [
            ("    no datasets yet — X extracts the gated overlay", "dim")]})
    for m in list(s._datasets) + (ds_arch if show_arch else []):
        archived = m.get("_lifecycle") == "archived"
        counts = m.get("counts") or {}
        spines = m.get("spines") or []
        spans: Line = [("  ", ""),
                       (str(m.get("dataset_id") or "?"),
                        "dim" if archived else ""),
                       (f"   {counts.get('examples', 0)} examples", "dim"),
                       (f"  ·  {sum(1 for sp in spines if sp.get('eligible'))}"
                        f"/{len(spines)} spines", "dim")]
        if archived:
            spans.append(("  ⌂ archived", "dim"))
        rows.append({"kind": "item", "spans": spans, "key": ("dataset", m)})
    rows.append({"kind": "note", "spans": []})
    runs = list(getattr(s, "_runs", []) or [])
    run_arch = list(getattr(s, "_runs_archived", []) or [])
    rows.append({"kind": "header",
                 "spans": [("  TRAINING RUNS", "bold"),
                           (f"  {len(runs)}{arch_note(len(run_arch))}",
                            "dim")]})
    if getattr(s, "_finetune_busy", False):
        rows.append({"kind": "note", "spans": [
            ("    ⚙ training… the manifest lands when the run finishes",
             "yellow")]})
    elif not runs and not (show_arch and run_arch):
        rows.append({"kind": "note", "spans": [
            ("    none yet — T finetunes the selected dataset", "dim")]})
    for m in runs + (run_arch if show_arch else []):
        archived = m.get("_lifecycle") == "archived"
        base = str((m.get("base_model") or {}).get("model_id") or "?")
        spans = [("  ", ""),
                 (str(m.get("run_id") or "?"), "dim" if archived else ""),
                 (f"   {base}", "dim"),
                 (f"  ·  ds …{str(m.get('dataset_id') or '?')[-12:]}", "dim")]
        totals = ((m.get("counts") or {}).get("totals") or {}).get("train") or {}
        n = sum(v for v in totals.values() if isinstance(v, (int, float)))
        if n:
            spans.append((f"  ·  {n} train ex", "dim"))
        metrics = (m.get("eval") or {}).get("metrics") or {}
        for k, v in list(metrics.items())[:2]:
            spans.append((f"  ·  {k} {v:.3f}" if isinstance(v, float)
                          else f"  ·  {k} {v}", "green"))
        if archived:
            spans.append(("  ⌂ archived", "dim"))
        rows.append({"kind": "item", "spans": spans, "key": ("run", m)})
    if s._flywheel_log:
        rows.append({"kind": "note", "spans": []})
        rows.append({"kind": "note", "spans": [("  last extract:", "bold")]})
        for ln in s._flywheel_log[-14:]:
            rows.append({"kind": "note", "spans": [("    " + ln, "dim")]})
    return rows


def flywheel_detail(s: Any) -> List[Line]:
    """The focused flywheel row's drill block: a dataset's full class
    vocabulary (wrapped — the off-screen truncation this pattern replaced),
    a run's RECIPE (df0b72c2: what T re-runs). Repainted alone on cursor
    moves through the kit detail pane."""
    items = list(getattr(s, "_fly_items", []) or [])
    cur = int(getattr(s, "_fly_cursor", 0))
    if not items or not (0 <= cur < len(items)):
        return []
    kind, m = items[cur]
    lines: List[Line] = []
    if kind == "dataset":
        vocab = m.get("class_vocabulary") or {}
        if not vocab:
            return []
        lines.append([("class vocabulary:", "bold")])
        words = [f"{k}x{v}" for k, v in sorted(vocab.items())]
        for chunk in _wrap_tokens(words, 96):
            lines.append([("  " + chunk, "dim")])
        return lines
    classes = m.get("classes") or []
    if classes:
        lines.append([("classes: " + " ".join(str(c) for c in classes),
                       "green")])
    cfg = m.get("config") or {}
    excl = cfg.get("exclude_labels") or []
    if excl:
        for w_i, chunk in enumerate(_wrap_tokens([str(x) for x in excl], 90)):
            lines.append([(("exclude: " if w_i == 0 else "         ") + chunk,
                           "dim")])
    lines.append([(f"epochs {cfg.get('max_epochs', '?')}"
                   f" · lr {cfg.get('learning_rate', '?')}"
                   f" · batch {cfg.get('batch_size', '?')}"
                   f" · seed {cfg.get('seed', '?')}"
                   f"  ·  T re-runs this recipe", "dim")])
    return lines


# ---- HTML materialization ------------------------------------------------


def _span_css(style: str) -> str:
    parts = style.split()
    css: List[str] = []
    color = next((w for w in parts if w in _COLORS and w != "dim"), None)
    if color:
        css.append(f"color:{_COLORS[color]}")
        if "dim" in parts:
            css.append("opacity:0.65")
    elif "dim" in parts:
        css.append(f"color:{_COLORS['dim']}")
    if "bold" in parts:
        css.append("font-weight:bold")
    if "underline" in parts:
        css.append("text-decoration:underline")
    return ";".join(css)


def lines_to_html(lines: List[Line]) -> str:
    """Materialize span lines as one <pre> block for a monospace
    QTextBrowser. A line carrying "reverse" paints as the full-width focus
    band (background swap — the Textual reverse's stand-in)."""
    out: List[str] = []
    for line in lines:
        reverse = any("reverse" in st.split() for _, st in line)
        parts: List[str] = []
        for text, st in line:
            esc = _html.escape(text)
            css = _span_css(st.replace("reverse", "").strip())
            parts.append(f"<span style='{css}'>{esc}</span>" if css else esc)
        body = "".join(parts)
        if reverse:
            body = (f"<span style='background-color:{_REVERSE_BG};"
                    f"color:#e8e8e8'>{body}</span>")
        out.append(body)
    return ("<pre style='margin:0;font-family:inherit'>"
            + "\n".join(out) + "</pre>")


def status_chips(s: Any) -> List[Tuple[str, str]]:
    """The strip's permanent chips (DEC 2a42c028): status_line's identity/
    position half as named slots — the keybar half now lives in
    hint_entries + the ?-overlay, and action results ride the readout slot."""
    view = s.view
    badges = {"assign": "[ASSIGN]", "propose": "[PROPOSE]",
              "annotate": "[ANNOTATE]"}.get(s.lane, "[WALK]")
    if s.purpose:
        badges += (" [TEST PASS]" if s.purpose == "feature-test"
                   else f" [{s.purpose.upper()}]")
    chips: List[Tuple[str, str]] = [
        ("lane", badges), ("source", str(view.source_title)),
        ("segment", f"segment {s.cursor + 1}/{view.size}")]
    chip = gate_chip(view)
    if chip:
        chips.append(("gate", chip))
    if s.lane == "assign":
        assigned = sum(1 for seg in view.segments if seg.id in view.speakers)
        meta = view.turns_meta.get("metadata") or {}
        turns = (f"turns {len(view.turn_proposals)}/{view.size}"
                 f" · {meta.get('speaker_count', '?')}spk"
                 if view.turn_proposals else "no turns")
        active = (entity_name(s._entities, s._active_entity)
                  if s._active_entity else "none")
        chips += [("assigned", f"assigned {assigned}/{view.size}"),
                  ("turns", turns), ("speaker", f"speaker: {active}")]
    elif s.lane == "propose":
        meta = view.proposals_meta or {}
        t2 = meta.get("tier2_total", 0)
        tier2 = (f" · tier2 {t2} {'shown' if view.show_tier2 else 'hidden'}"
                 if t2 else "")
        chips += [("proposals",
                   f"proposals {meta.get('pending', 0)} pending{tier2}"),
                  ("set", f"set {str(meta.get('proposal_set_id') or '')[-8:]}"),
                  ("model",
                   f"model {str(meta.get('training_run_id') or '')[-8:]}")]
    elif s.lane == "annotate":
        seg = view.segments[s.cursor]
        toks = segment_word_tokens(seg.text)
        sel = selection_range(s._word_cursor, s._word_anchor, len(toks))
        chips.append(("overlays", f"◈ {view.overlay_count}"))
        if toks and sel is not None:
            a, b = sel
            readout = " ".join(t for _, _, t in toks[a:b + 1])
            readout = readout if len(readout) <= 30 else readout[:29] + "…"
            chips.append(("sel", f"sel “{readout}”"))
        elif not toks:
            chips.append(("sel", "(no words here)"))
        chips.append(("label", f"label: {s._overlay_label}"))
    else:
        edited = sum(1 for v in s._marks.values() if v == "corrected")
        chips.append(("edited", f"edited {edited}"))
    chips += [("speed", f"×{s.speed:g}"),
              ("session", f"session {str(s.session_id or '')[:8]}")]
    return chips


def hint_entries(s: Any) -> List[Dict[str, str]]:
    """The declarative hint model (DEC 2a42c028): the active stage/lane's
    vocabulary as [{verb, label, key, group}] — the ?-overlay's sections and
    the hint line's pin identities. Verbs track the key-table ACTION names
    where a row maps to one action (the remapping-UI alignment); combined
    rows (j/k) carry the forward action's name."""
    def e(verb: str, key: str, label: str, group: str) -> Dict[str, str]:
        return {"verb": verb, "key": key, "label": label, "group": group}
    if s.stage in ("select", "spine"):
        rows = [e("next", "j/k", "walk", "Picker"),
                e("open_source", "enter", "open", "Picker"),
                e("flywheel_page", "F", "flywheel", "Picker")]
        if s.stage == "spine":
            rows.append(e("export_wordless", "x", "export wordless propset", "Respine"))
            rows.append(e("transfer_wordless", "t", "transfer events from a sibling",
                          "Respine"))
            rows.append(e("back", "B/esc", "back to sources", "Picker"))
        rows.append(e("quit_app", "q", "quit", "Picker"))
        return rows
    if s.stage == "flywheel":
        return [e("next", "j/k", "walk rows", "Flywheel"),
                e("purpose_pick", "1-9", "toggle purpose", "Flywheel"),
                e("extract_dataset", "X", "extract dataset", "Flywheel"),
                e("train_dataset", "T", "finetune (run row: re-run recipe)",
                  "Flywheel"),
                e("lifecycle_toggle", "a", "archive/unarchive row", "Lifecycle"),
                e("lifecycle_archived", "h", "show archived", "Lifecycle"),
                e("lifecycle_delete", "x", "delete (archived, twice)", "Lifecycle"),
                e("flywheel_page", "F/esc", "back", "Flywheel"),
                e("quit_app", "q", "quit", "Flywheel")]
    if s.lane == "assign":
        return [e("assign_accept", "a", "accept turn", "Assign"),
                e("assign_pick", "1-9", "pick speaker", "Assign"),
                e("assign_same", "space", "same speaker", "Assign"),
                e("assign_new", "A", "new speaker", "Assign"),
                e("next", "j/k", "walk", "Walk"),
                e("seam_next", "g/G", "seam", "Walk"),
                e("replay", "r", "replay", "Audio"),
                e("speed_up", "[/]", "speed", "Audio"),
                e("yank", "y", "copy", "App"),
                e("cycle_lane", "tab", "walk lane", "App"),
                e("back", "B", "spine picker", "App"),
                e("flywheel_page", "F", "flywheel", "App"),
                e("quit_app", "q", "quit", "App")]
    if s.lane == "propose":
        return [e("propose_accept", "a", "accept proposal", "Proposals"),
                e("propose_next", "n/N", "jump proposal", "Proposals"),
                e("propose_audition", "R", "audition proposal", "Proposals"),
                e("toggle_tier2", "t", "tier2 show/hide", "Proposals"),
                e("nudge_end_earlier", ",./<>", "nudge", "Edit"),
                e("insert_chunk", "i/I", "manual insert", "Edit"),
                e("relabel_insert", "L", "relabel", "Edit"),
                e("remove_insert", "x", "remove", "Edit"),
                e("edit", "e", "edit text", "Edit"),
                e("replay", "r", "replay chunk", "Audio"),
                e("next", "j/k", "walk", "Walk"),
                e("seam_next", "g/G", "seam", "Walk"),
                e("cycle_lane", "tab", "lane", "App"),
                e("back", "B", "spine picker", "App"),
                e("flywheel_page", "F", "flywheel", "App"),
                e("quit_app", "q", "quit", "App")]
    if s.lane == "annotate":
        return [e("word_right", "h/l·←→", "word", "Words"),
                e("word_select", "v", "range", "Words"),
                e("annotate_quick", "space", "◈ commit", "Words"),
                e("annotate_pick", "1-9", "class", "Words"),
                e("annotate_editor", "A", "class+", "Words"),
                e("overlay_cycle", "o/O", "◈ pick", "Overlays"),
                e("overlay_nudge", ",./<>", "◈ nudge", "Overlays"),
                e("overlay_remove", "x", "◈ remove", "Overlays"),
                e("next_overlay", "n/N", "◈ jump", "Overlays"),
                e("annotate_audition", "R", "audition", "Audio"),
                e("replay", "r", "replay", "Audio"),
                e("next", "j/k", "walk", "Walk"),
                e("cycle_lane", "tab", "lane", "App"),
                e("back", "B", "spine picker", "App"),
                e("flywheel_page", "F", "flywheel", "App"),
                e("quit_app", "q", "quit", "App")]
    return [e("next", "j/k·w/s", "walk", "Walk"),
            e("shift_push", "←→/a/d", "shift boundary", "Walk"),
            e("seam_next", "g/G", "seam", "Walk"),
            e("next_mark", "n/N", "⚑ jump", "Walk"),
            e("next_prune", "p/P", "✂ jump", "Walk"),
            e("toggle_wordless_fold", "z", "fold ⊕", "Walk"),
            e("replay", "r", "replay", "Audio"),
            e("nudge_end_earlier", ",./<>", "nudge", "Audio"),
            e("nudge_step_up", "{}", "nudge step", "Audio"),
            e("speed_up", "[/]", "speed", "Audio"),
            e("gate_editor", "W", "gate", "Audio"),
            e("edit", "e", "edit text", "Edit"),
            e("yank", "y", "copy", "Edit"),
            e("insert_chunk", "i/I", "⊕ insert", "Edit"),
            e("remove_insert", "x", "⊖ remove", "Edit"),
            e("split_chunk", "S", "split", "Edit"),
            e("mark_quick", "m/b", "⚑ mark", "Marks"),
            e("mark_editor", "M", "⚑ class", "Marks"),
            e("cycle_lane", "tab", "assign lane", "App"),
            e("cancel", "esc", "stop audio", "App"),
            e("back", "B", "spine picker", "App"),
            e("flywheel_page", "F", "flywheel", "App"),
            e("quit_app", "q", "quit", "App")]


def default_pins(s: Any) -> List[str]:
    """The hint line's default 3-5 verbs per stage/lane — what shows before
    the user pins their own set through the ?-overlay (DEC 2a42c028)."""
    if s.stage in ("select", "spine"):
        return ["next", "open_source", "quit_app"]
    if s.stage == "flywheel":
        return ["purpose_pick", "extract_dataset", "train_dataset"]
    return {"assign": ["assign_accept", "assign_pick", "assign_same",
                       "next", "cycle_lane"],
            "propose": ["propose_accept", "propose_next",
                        "propose_audition", "next", "cycle_lane"],
            "annotate": ["word_right", "annotate_quick", "annotate_pick",
                         "next", "cycle_lane"],
            }.get(s.lane, ["next", "replay", "nudge_end_earlier", "edit",
                           "cycle_lane"])


def picker_status_chip(s: Any) -> str:
    """picker_status minus the keybar tail — the chips half only
    (DEC 2a42c028: gesture hints live in the hint line/overlay now)."""
    tail = str(s._graph_db_path or "")
    tail = tail if len(tail) <= 40 else "…" + tail[-39:]
    return f"pick a source ({len(s._sources)})  ·  @{tail}"


def flywheel_status_chip(s: Any) -> str:
    """flywheel_status minus the keybar tail — the chips half only
    (DEC 2a42c028)."""
    busy = ("  ·  extracting…" if s._extract_busy
            else "  ·  ⚙ training…" if getattr(s, "_finetune_busy", False)
            else "")
    runs = len(getattr(s, "_runs", []) or [])
    tail = f" · {runs} runs" if runs else ""
    return f"flywheel ({len(s._datasets)} datasets{tail}){busy}"


def _wrap_tokens(tokens: List[str],  # Words to flow (kept whole)
                 width: int,         # Line budget in cells
                 ) -> List[str]:  # Space-joined lines, each <= width
    """Greedy token wrap for detail blocks (the flywheel selected-dataset
    class vocabulary) — tokens never split, an over-wide token stands
    alone on its line."""
    out: List[str] = []
    line = ""
    for t in tokens:
        cand = f"{line} {t}" if line else t
        if line and len(cand) > width:
            out.append(line)
            line = t
        else:
            line = cand
    if line:
        out.append(line)
    return out
