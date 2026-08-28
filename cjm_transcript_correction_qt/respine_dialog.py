"""Modal transfer dialog for the spine picker (work item 9af9793a — the
in-app respine with carried approvals): the correction shell's driver over
the transfer-wordless engine. Two phases in one frameless kit modal
(modal_header mouse close, 140a7b3c): PICK a donor spine from a native
QListWidget (the TrainingRunPicker recipe — the dialog owns the keys, the
list is NoFocus), then the engine's DRY-RUN PLAN renders in-dialog before
anything commits — counts by label, the skip classes (dup · word-bearing ·
unanchored), the speaker-split half (54aac7d3) and the first rows. T or
enter commits, esc cancels at either phase. The dialog holds no engine
call: on_plan(donor) asks the window to plan (a loop-thread Future), the
window hands the result back through show_plan / show_error, and
on_commit(plan) hands the rendered plan to the window's commit verb."""

import html as _html
from typing import Any, Callable, Dict, List, Optional

from cjm_substrate_qt_kit.keyhints import is_close_anchor, keycaps, modal_header
from cjm_substrate_qt_kit.style import apply_row_style
from cjm_substrate_qt_kit.theme import current_theme, make_font
from cjm_transcript_correction_core.state import spine_label
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QLabel, QListWidget, QListWidgetItem, QTextBrowser,
                               QVBoxLayout)


def plan_lines(plan: Dict[str, Any],   # A plan_wordless_transfer result
               donor: str,             # Donor spine label
               target: str,            # Destination spine label
               limit: int = 8,         # Rows of each kind to list before eliding
               ) -> List[str]:  # Plain text lines (the dialog escapes + paints them)
    """The plan render (pure): what the CLI's --dry-run prints, shaped for
    a modal — the header pair, the event half with its skip classes, the
    speaker-split half when the donor has any, the first rows of each, and
    the stays-behind reminder. An empty plan says so instead of listing."""
    rows = plan.get("plan") or []
    splits = plan.get("splits") or []
    out = [f"{donor}  ({plan.get('from_segments', 0)} segs)   →   "
           f"{target}  ({plan.get('to_segments', 0)} segs)", ""]
    out.append(f"wordless events: {plan.get('donors', 0)} donors → transfer {len(rows)}"
               f"   (dup-skip {plan.get('dups', 0)} · word-bearing-skip "
               f"{plan.get('word_bearing', 0)} · unanchored {plan.get('unanchored', 0)})")
    by = plan.get("by_label") or {}
    out.append("  by label: " + (" · ".join(f"{k}×{v}" for k, v in sorted(by.items()))
                                 or "none"))
    if plan.get("split_donors"):
        out.append(f"speaker splits: {plan['split_donors']} donors → transfer {len(splits)}"
                   f"   (dup-skip {plan.get('split_dups', 0)} · unanchored "
                   f"{plan.get('split_unanchored', 0)} · same-segment conflicts "
                   f"{plan.get('split_conflicts', 0)})")
    out.append("")
    for p in rows[:limit]:
        out.append(f"  {p['label']:>16} {p['start']:9.3f}–{p['end']:9.3f}s   "
                   f"after {str(p['after_id'])[:8]}")
    if len(rows) > limit:
        out.append(f"  … {len(rows) - limit} more events")
    for s in splits[:limit]:
        out.append(f"  {'split':>16} {s['time']:9.3f}s   "
                   f"{s['left_text'][-20:]!r} | {s['right_text'][:20]!r}")
    if len(splits) > limit:
        out.append(f"  … {len(splits) - limit} more splits")
    if not rows and not splits:
        out.append("  nothing to transfer — every donor is already on the target, "
                   "or unanchored")
    out.append("")
    out.append("stays behind by design: boundary shifts · text edits · labeled "
               "inserts that gained text")
    return out


class TransferDialog(QDialog):
    """The spine picker's transfer verb: phase `pick` (donor list) →
    `planning` (the window's Future in flight) → `plan` (rendered, T/enter
    commits) or `error` (the engine's refusal, esc closes). open_for paints
    the donors and parks the cursor on the head; show_plan / show_error land
    the Future's outcome — on a dialog the user already cancelled they are
    dropped. The CALLER owns what a pick and a commit mean."""

    def __init__(self, parent, *,
                 on_plan: Callable[[Dict[str, Any]], None],
                 on_commit: Callable[[Dict[str, Any]], None]):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self._on_plan = on_plan
        self._on_commit = on_commit
        self.phase = "pick"
        self.target: Dict[str, Any] = {}
        self.donors: List[Dict[str, Any]] = []
        self.donor: Optional[Dict[str, Any]] = None
        self.plan: Optional[Dict[str, Any]] = None
        self.error = ""
        self._note = ""
        self.head = QTextBrowser(self)
        self.head.setFocusPolicy(Qt.NoFocus)
        self.head.setOpenLinks(False)
        self.head.anchorClicked.connect(self._on_anchor)
        self.head.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # The DIALOG owns the keys: a focused QListWidget keyboard-searches
        # on letter presses, which would eat j/k.
        self.list = QListWidget(self)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setFont(make_font(kind="mono"))
        self.list.itemDoubleClicked.connect(lambda _item: self._request_plan())
        self.body = QTextBrowser(self)
        self.body.setFocusPolicy(Qt.NoFocus)
        self.body.setFont(make_font(kind="mono"))
        self.body.setOpenLinks(False)
        self.foot = QLabel(self)
        self.foot.setTextFormat(Qt.RichText)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        lay.addWidget(self.head)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.body, 1)
        lay.addWidget(self.foot)

    def open_for(self, target: Dict[str, Any],
                 donors: List[Dict[str, Any]]) -> None:
        """Open the donor pick over the owner: `target` is the picker's
        cursor spine (the destination), `donors` its siblings (list order —
        the picker's own, legacy first)."""
        self.target = dict(target)
        self.donors = [dict(d) for d in donors]
        self.donor, self.plan, self.error, self._note = None, None, "", ""
        self.phase = "pick"
        self._render()
        self._resize()
        self.open()
        self.setFocus()

    def show_plan(self, plan: Dict[str, Any]) -> None:
        """The window's plan Future landed: render it for the commit
        decision. Dropped when the dialog is no longer open (esc raced the
        Future)."""
        if not self.isVisible():
            return
        self.plan = dict(plan)
        self.phase = "plan"
        self._note = ""
        self._render()
        self._resize()

    def show_error(self, message: str) -> None:
        """The engine refused (empty spine, the same spine twice, …): paint
        the refusal; esc closes. Dropped on a cancelled dialog."""
        if not self.isVisible():
            return
        self.error = message
        self.phase = "error"
        self._render()
        self._resize()

    # ---- paint -----------------------------------------------------------

    def _labels(self):
        return (spine_label(self.donor) if self.donor else "?",
                spine_label(self.target) if self.target else "?")

    def _render(self) -> None:
        theme = current_theme()
        chrome = ("background: %s; border: 1px solid %s; padding: 6px;"
                  % (theme["surface"], theme["border"]))
        self.head.setStyleSheet("QTextBrowser { %s }" % chrome)
        self.list.setStyleSheet("QListWidget { %s }" % chrome)
        self.body.setStyleSheet("QTextBrowser { %s }" % chrome)
        self.foot.setStyleSheet("QLabel { %s color: %s; }"
                                % (chrome, theme["content-dim"]))
        e = _html.escape
        dim = theme["content-dim"]
        donor, target = self._labels()
        pick = self.phase == "pick"
        self.list.setVisible(pick)
        self.body.setVisible(not pick)
        if pick:
            title = ("TRANSFER → %s<span style='color:%s'> · pick the DONOR spine "
                     "whose approvals carry over · %d sibling(s)</span>"
                     % (e(target), dim, len(self.donors)))
            self.list.clear()
            for d in self.donors:
                item = QListWidgetItem("  %s   %s segs" % (spine_label(d),
                                                          d.get("segments", 0)))
                apply_row_style(item, None)
                self.list.addItem(item)
            if not self.donors:
                item = QListWidgetItem("  (no sibling spine — nothing to transfer from)")
                apply_row_style(item, "dim")
                self.list.addItem(item)
            self.list.setCurrentRow(0)
            foot = ("%s move · %s plan · %s or ✕ cancel"
                    % (keycaps("j/k", theme), keycaps("enter", theme),
                       keycaps("esc", theme)))
        elif self.phase == "planning":
            title = ("TRANSFER %s → %s<span style='color:%s'> · planning…</span>"
                     % (e(donor), e(target), dim))
            self.body.setPlainText("reading both spines and the source's "
                                   "corrections — the plan lands here")
            foot = "%s or ✕ cancel" % keycaps("esc", theme)
        elif self.phase == "error":
            title = ("TRANSFER %s → %s<span style='color:%s'> · refused</span>"
                     % (e(donor), e(target), dim))
            self.body.setPlainText("⚠ " + self.error)
            foot = "%s or ✕ close" % keycaps("esc", theme)
        else:
            title = ("TRANSFER %s → %s<span style='color:%s'> · dry-run plan — "
                     "nothing committed yet</span>" % (e(donor), e(target), dim))
            self.body.setPlainText("\n".join(plan_lines(self.plan or {}, donor, target)))
            foot = ("%s commit · %s or ✕ cancel"
                    % (keycaps("T/enter", theme), keycaps("esc", theme)))
        if self._note:
            foot = "<span style='color:%s'>%s</span> · %s" % (theme["accent"],
                                                              e(self._note), foot)
        self.head.setHtml("<div style='color:%s'>%s</div>"
                          % (theme["content"], modal_header(title, theme)))
        self.foot.setText(foot)

    def _resize(self) -> None:
        """The keyhints sizing recipe: size to the rendered content, capped
        by the owner, centered over it."""
        owner = self.parentWidget()
        avail_w = (owner.width() - 64) if owner is not None else 960
        avail_h = (owner.height() - 64) if owner is not None else 640
        if self.phase == "pick":
            width = min(avail_w, max(self.list.sizeHintForColumn(0) + 48, 640))
        else:
            doc = self.body.document()
            doc.setTextWidth(-1)
            width = min(avail_w, max(int(doc.idealWidth()) + 44, 640))
        doc = self.head.document()
        doc.setTextWidth(width - 24)
        head_h = int(doc.size().height()) + 12
        self.head.setFixedHeight(head_h)
        if self.phase == "pick":
            row_h = max(self.list.sizeHintForRow(0), 18)
            mid_h = row_h * (self.list.count() + 1)
        else:
            bdoc = self.body.document()
            bdoc.setTextWidth(width - 30)
            mid_h = int(bdoc.size().height()) + 24
        height = min(avail_h, head_h + mid_h + self.foot.sizeHint().height() + 24)
        self.resize(width, height)
        if owner is not None:
            center = owner.mapToGlobal(owner.rect().center())
            self.move(center.x() - self.width() // 2,
                      center.y() - self.height() // 2)

    # ---- selection -------------------------------------------------------

    def current_donor(self) -> Optional[Dict[str, Any]]:
        """The donor under the cursor (None on the empty placeholder)."""
        i = self.list.currentRow()
        return self.donors[i] if 0 <= i < len(self.donors) else None

    def _move(self, delta: int) -> None:
        n = self.list.count()
        if n:
            self.list.setCurrentRow(max(0, min(n - 1,
                                               self.list.currentRow() + delta)))

    def _request_plan(self) -> None:
        donor = self.current_donor()
        if self.phase != "pick" or donor is None:
            return
        self.donor = donor
        self.phase = "planning"
        self._render()
        self._resize()
        self._on_plan(donor)

    def _commit(self) -> None:
        if self.phase != "plan" or self.plan is None:
            return
        if not (self.plan.get("plan") or self.plan.get("splits")):
            self._note = "nothing to transfer"
            self._render()
            return
        self.accept()
        self._on_commit(self.plan)

    def _on_anchor(self, url) -> None:
        """The header's mouse close (140a7b3c) — the one link painted."""
        if is_close_anchor(url):
            self.reject()

    # ---- keys ------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        key = event.text()
        if self.phase == "pick":
            if key == "j" or event.key() == Qt.Key_Down:
                self._move(1)
            elif key == "k" or event.key() == Qt.Key_Up:
                self._move(-1)
            elif key == " " or event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._request_plan()
            else:
                super().keyPressEvent(event)
        elif self.phase == "plan" and (key == "T" or event.key() in (Qt.Key_Return,
                                                                     Qt.Key_Enter)):
            self._commit()
        else:
            super().keyPressEvent(event)
