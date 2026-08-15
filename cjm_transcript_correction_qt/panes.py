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
from typing import Any, Dict, List, Optional, Tuple

from cjm_transcript_correction_tui.spine import segment_word_tokens

Span = Tuple[str, str]
Line = List[Span]

# Copied from CorrectionApp.WORDLESS_INSERT_LABELS (stranded as a Textual App
# class attribute — importing it would drag Textual into the Qt process; the
# duplication is a captured roadmap item, DEC 0f11683d).
WORDLESS_INSERT_LABELS = {"inhale", "empty", "throat-clear", "background-noise",
                          "click", "background-music", "background-voices", "echo",
                          "wheeze", "chuckle"}

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


def picker_lines(s: Any, width: int) -> List[Line]:
    """The 2ce81638 discovery stage: the graph's Sources with correction
    status at a glance."""
    lines: List[Line] = [[]]
    if not s._sources:
        lines.append([("  no Source nodes on this graph", "dim")])
    for i, (sid, title) in enumerate(s._sources):
        st = s._status.get(sid) or {}
        focused = (i == s.cursor)
        row: Line = [("  > " if focused else "    ", "")]
        row.append((title or sid[:12], "bold" if focused else ""))
        row.append((f"   {st.get('segments', 0)} segs", "dim"))
        row.append((f" · {st.get('corrections', 0)} corrections", "dim"))
        marks = st.get("marks", 0)
        if marks:
            row.append((f" · {marks} ⚑", "yellow"))
        mix = s._purposes.get(sid) or {}
        genuine = mix.get("genuine", 0)
        tests = sum(n for p, n in mix.items() if p != "genuine")
        if genuine:
            row.append((f" · genuine: {genuine}", "green"))
            if tests:
                row.append((f" (+{tests} test)", "dim"))
        elif tests:
            row.append((" · all test", "yellow"))
        lines.append(_truncate(row, width))
    return lines


def picker_status(s: Any) -> str:
    tail = str(s._graph_db_path or "")
    tail = tail if len(tail) <= 40 else "…" + tail[-39:]
    return (f"pick a source ({len(s._sources)})  ·  @{tail}"
            f"  ·  j/k walk · enter open · q quit")


def spine_picker_lines(s: Any, width: int) -> List[Line]:
    """The spine picker (DEC f1024568): one row per coexisting SKELETON."""
    from cjm_transcript_correction_tui.state import spine_label
    _, title = s._spine_source or ("", "")
    lines: List[Line] = [[]]
    header: Line = [("  ", ""), (title or "source", "bold"),
                    (f"  ·  {len(s._spines)} spines coexist — pick one", "dim")]
    lines.append(header)
    lines.append([])
    for i, sp in enumerate(s._spines):
        focused = (i == s.cursor)
        row: Line = [("  > " if focused else "    ", "")]
        row.append((spine_label(sp), "bold" if focused else ""))
        row.append((f"   {sp.get('segments', 0)} segs", "dim"))
        lines.append(_truncate(row, width))
    return lines


SPINE_PICKER_STATUS = "pick a spine  ·  j/k walk · enter open (choice persists) · q quit"


# ---- the flywheel page (port of _render_flywheel) ------------------------


def flywheel_lines(s: Any, width: int) -> List[Line]:
    """The cross-source flywheel page paint (DEC 82c463fe): dataset manifests
    + the last extract fold's own log lines."""
    lines: List[Line] = [[]]
    lines.append([("  FLYWHEEL — cross-source operations", "bold")])
    lines.append([])
    purposes: Line = [("  feedstock purposes:  ", ""), ("genuine ✓", "green")]
    for i, p in enumerate(s._purpose_vocab, 1):
        on = p in s._include_purposes
        purposes.append((f"   [{i}] ", ""))
        purposes.append((f"{p} {'✓' if on else '✗'}", "green" if on else "dim"))
    lines.append(_truncate(purposes, width))
    lines.append([])
    if not s._datasets:
        lines.append([("  no datasets yet — X extracts the gated overlay", "dim")])
    for i, m in enumerate(s._datasets):
        row: Line = [("    ", ""),
                     (str(m.get("dataset_id") or "?"), "bold" if i == 0 else "")]
        counts = m.get("counts") or {}
        row.append((f"   {counts.get('examples', 0)} examples", "dim"))
        vocab = m.get("class_vocabulary") or {}
        if vocab:
            row.append(("  ·  " + " ".join(f"{k}x{v}"
                                           for k, v in sorted(vocab.items())), "dim"))
        spines = m.get("spines") or []
        row.append((f"  ·  {sum(1 for sp in spines if sp.get('eligible'))}"
                    f"/{len(spines)} spines", "dim"))
        lines.append(_truncate(row, width))
    if s._flywheel_log:
        lines.append([])
        lines.append([("  last extract:", "bold")])
        for ln in s._flywheel_log[-14:]:
            lines.append(_truncate([("    " + ln, "dim")], width))
    return lines


def flywheel_status(s: Any) -> str:
    busy = "extracting…  ·  " if s._extract_busy else ""
    return (f"flywheel ({len(s._datasets)} datasets)  ·  {busy}"
            "1-9 purposes · X extract · F back · q quit")


def _truncate(line: Line, width: int) -> Line:
    out: Line = []
    used = 0
    for t, st in line:
        if used + len(t) <= width:
            out.append((t, st))
            used += len(t)
        else:
            out.append((t[:max(0, width - used)], st))
            break
    return out


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
