"""Modal finetune-launch form (DECs 48eff28b + 99280f79): the tui-kit
ConfigForm model painted in a frameless modal dialog over the flywheel page
— the model owns semantics (cycle/parse/overrides), this dialog owns the
widgets (the KeyHintsOverlay chrome). Keys: j/k field cursor · space/o
cycle closed sets · enter typed input (the transient escape hatch, list
fields comma-split) · T launch · esc cancel. Launch reports overrides()
through on_launch — the CALLER submits the task and closes the dialog."""

import html as _html
from typing import Any, Callable, Dict, List, Optional

from cjm_substrate_qt_kit.keyhints import is_close_anchor, keycaps, modal_header
from cjm_substrate_qt_kit.theme import current_theme, make_font
from cjm_substrate_tui_kit.form import ConfigForm
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QTextBrowser, QVBoxLayout


class FinetuneFormDialog(QDialog):
    """The finetune run-config form: schema-driven rows over a chosen
    dataset. State is (form, dataset, row); the caller opens with open_for
    and receives the non-default overrides dict through on_launch. The
    header row carries the kit's mouse close (modal_header, 140a7b3c), and
    an adopted recipe's Excluded-Labels row surfaces the classes the chosen
    dataset has that the recipe never trained (1275eb52)."""

    def __init__(self, parent, *,
                 on_launch: Callable[[Dict[str, Any]], None]):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self._on_launch = on_launch
        self.form: Optional[ConfigForm] = None
        self.dataset: Dict[str, Any] = {}
        self.datasets: List[Dict[str, Any]] = []   # the selectable ring
        self._opened_id = ""                       # the dataset opened with
        self.adopt_label = ""
        self._recipe_classes: Optional[List[str]] = None  # adopted run's trained set
        self._new_classes: List[str] = []          # census − recipe, this dataset
        self._auto_excluded: List[str] = []        # what the guard added last
        self.row = 0                               # 0 = dataset row, 1.. = fields
        self._error = ""
        self.view = QTextBrowser(self)
        self.view.setFocusPolicy(Qt.NoFocus)
        self.view.setFont(make_font(kind="mono"))
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._on_anchor)
        self.editor = QLineEdit(self)
        self.editor.setVisible(False)
        self.editor.returnPressed.connect(self._commit_editor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        lay.addWidget(self.view)
        lay.addWidget(self.editor)

    def open_for(self, dataset: Dict[str, Any],
                 schema: Dict[str, Any],
                 adopt: Optional[Dict[str, Any]] = None,
                 adopt_label: str = "",
                 datasets: Optional[List[Dict[str, Any]]] = None,
                 adopt_classes: Optional[List[str]] = None) -> None:
        """(Re)build the form from the adapter's config schema and open
        centered over the owner — the keyhints sizing recipe: size to the
        RENDERED document (drive verdict e37afc63). `adopt` applies a prior
        run's config snapshot over the schema defaults (df0b72c2: re-run
        the recipe — the modified dots then paint the recipe's diff);
        `adopt_label` names the provenance in the header. `datasets` is
        the selectable ring (newest first): an adopted run's consumed
        dataset is only the STARTING point — space on the dataset row
        cycles to any discovered dataset, so a recipe re-runs on NEW data
        without retyping its config (the second half of the a1326d5b trap:
        adopt-recipe alone re-trained the run's own set, 2026-08-26).
        `adopt_classes` is the adopted run's TRAINED class set — with it
        the Excluded-Labels row guards against silent class growth
        (_guard_new_classes)."""
        self.form = ConfigForm.from_schema(schema)
        if adopt:
            self.form.apply(adopt)
        self.adopt_label = adopt_label if adopt else ""
        self._recipe_classes = (list(adopt_classes)
                                if adopt and adopt_classes is not None
                                else None)
        self._auto_excluded = []
        self.dataset = dict(dataset)
        self.datasets = ([dict(d) for d in datasets] if datasets
                         else [dict(dataset)])
        self._opened_id = str(dataset.get("dataset_id") or "")
        self.row = 0
        self._error = ""
        self._guard_new_classes()
        owner = self.parentWidget()
        avail_w = (owner.width() - 64) if owner is not None else 900
        avail_h = (owner.height() - 64) if owner is not None else 640
        self._render()
        doc = self.view.document()
        doc.setTextWidth(-1)
        width = min(avail_w, max(int(doc.idealWidth()) + 44, 520))
        doc.setTextWidth(width - 30)
        height = min(avail_h, int(doc.size().height()) + 40)
        self.resize(width, height)
        if owner is not None:
            center = owner.mapToGlobal(owner.rect().center())
            self.move(center.x() - self.width() // 2,
                      center.y() - self.height() // 2)
        self.open()
        self.setFocus()

    # ---- paint -----------------------------------------------------------

    def _fields(self):
        return self.form.fields if self.form is not None else []

    def _cur_field(self):
        """The schema field under the cursor — None on the dataset row (0)."""
        fields = self._fields()
        return fields[self.row - 1] if 0 < self.row <= len(fields) else None

    def _exclude_field(self):
        """The Excluded-Labels row (the adapter's exclude_labels axis), or
        None when the schema lacks it."""
        return next((f for f in self._fields() if f.key == "exclude_labels"),
                    None)

    def _guard_new_classes(self) -> None:
        """Excluded-Labels new-class surfacing (call-out 1275eb52): with a
        recipe adopted, the chosen dataset's class census is diffed against
        the recipe's TRAINED class set; classes the recipe never saw are
        auto-added to Excluded Labels and flagged on the row, so a re-run's
        class set never grows silently (the e6694c0c stray: chuckle ×6
        cleared min_class_count and became a head nobody asked for).
        Editing the row keeps a class; cycling the dataset ring re-diffs
        against the new census — this pass's auto-adds are replaced, hand
        edits kept. No recipe (a dataset row's schema defaults) = nothing
        to diff against."""
        self._new_classes = []
        f = self._exclude_field()
        if f is None or self._recipe_classes is None:
            self._auto_excluded = []
            return
        current = [x for x in (f.value if isinstance(f.value, list) else [])
                   if x not in self._auto_excluded]
        vocab = self.dataset.get("class_vocabulary") or {}
        known = set(self._recipe_classes) | set(current)
        new = sorted((c for c in vocab if c not in known),
                     key=lambda c: (-int(vocab.get(c) or 0), c))
        f.value = current + new
        self._auto_excluded = list(new)
        self._new_classes = list(new)

    def _cycle_dataset(self, step: int) -> None:
        """space/O on the dataset row: step through the discovered ring."""
        if len(self.datasets) < 2:
            self._error = "only one dataset discovered — X extracts more"
            self._render()
            return
        did = str(self.dataset.get("dataset_id") or "")
        idx = next((i for i, d in enumerate(self.datasets)
                    if str(d.get("dataset_id") or "") == did), 0)
        self.dataset = dict(self.datasets[(idx + step) % len(self.datasets)])
        self._error = ""
        self._guard_new_classes()
        self._render()

    def _render_value(self, f) -> str:
        """List-typed fields render comma-joined (parse's dual below);
        everything else uses the form model's spec-grammar render."""
        if isinstance(f.value, list):
            return ", ".join(str(x) for x in f.value) or "(none)"
        return f.render()

    def _render(self) -> None:
        theme = current_theme()
        self.view.setStyleSheet(
            "QTextBrowser { background: %s; border: 1px solid %s; "
            "padding: 10px; }" % (theme["surface"], theme["border"]))
        e = _html.escape
        counts = self.dataset.get("counts") or {}
        out = [modal_header(
            "FINETUNE — %s<span style='color:%s'> · %s examples</span>"
            % (e(str(self.dataset.get("dataset_id") or "?")),
               theme["content-dim"], counts.get("examples", 0)), theme)]
        if self.adopt_label:
            out.append("<span style='color:%s'>recipe from %s — ● rows are "
                       "its diff from defaults</span>"
                       % (theme["content-dim"], e(self.adopt_label)))
        out.append("")
        fields = self._fields()
        if not fields:
            out.append("<span style='color:%s'>no config schema — "
                       "regenerate the adapter manifest (cjm-ctl "
                       "generate-adapter-manifest); launch uses worker "
                       "defaults</span>" % theme["content-dim"])
        did = str(self.dataset.get("dataset_id") or "")
        rows = [("●" if did != self._opened_id else "&nbsp;", "Dataset",
                 "%s · %s examples" % (did or "?", counts.get("examples", 0)),
                 "The dataset this run trains on — space cycles the %d "
                 "discovered dataset(s), newest first; the recipe rows stay."
                 % len(self.datasets))]
        vocab = self.dataset.get("class_vocabulary") or {}
        for f in fields:
            value, description = self._render_value(f), f.description or ""
            if f.key == "exclude_labels" and self._new_classes:
                value += "  ◆ new vs recipe: %s (auto-excluded)" % ", ".join(
                    "%s×%s" % (c, vocab.get(c, "?")) for c in self._new_classes)
                description += (" ◆ Classes in this dataset the adopted recipe "
                                "never trained were auto-excluded so the class "
                                "set cannot grow silently — enter edits the "
                                "list to keep one.")
            rows.append(("●" if f.modified else "&nbsp;", f.title, value,
                         description))
        for i, (mark, title, value, description) in enumerate(rows):
            row = "%s %s: <b>%s</b>" % (mark, e(title), e(value))
            if i == self.row:
                desc = ("<br><span style='color:%s'>&nbsp;&nbsp;%s</span>"
                        % (theme["content-dim"], e(description))
                        if description else "")
                out.append("<div style='background:%s;color:%s;padding:1px "
                           "4px'>▸ %s%s</div>"
                           % (theme["raised"], theme["content"], row, desc))
            else:
                out.append("<div style='padding:1px 4px 1px 14px'>%s</div>"
                           % row)
        out.append("")
        if self._error:
            out.append("<span style='color:%s'>⚠ %s</span>"
                       % (theme["accent"], e(self._error)))
        out.append("<span style='color:%s'>%s move · %s cycle · %s edit · "
                   "%s launch · %s or ✕ cancel</span>"
                   % (theme["content-dim"], keycaps("j/k", theme),
                      keycaps("space", theme), keycaps("enter", theme),
                      keycaps("T", theme), keycaps("esc", theme)))
        self.view.setHtml("<div style='color:%s'>%s</div>"
                          % (theme["content"], "<br>".join(out)))

    def _on_anchor(self, url) -> None:
        """The header's mouse close (140a7b3c) — the one link the form
        paints; esc's reject ladder applies (an open editor closes first)."""
        if is_close_anchor(url):
            self.reject()

    # ---- keys ------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if self.editor.isVisible():   # the QLineEdit owns typing; esc lands
            super().keyPressEvent(event)   # in reject() below
            return
        key = event.text()
        last = len(self._fields())            # row 0 = dataset, 1.. = fields
        f = self._cur_field()
        if key in ("j",) or event.key() == Qt.Key_Down:
            self.row = min(last, self.row + 1)
            self._error = ""
            self._render()
        elif key in ("k",) or event.key() == Qt.Key_Up:
            self.row = max(0, self.row - 1)
            self._error = ""
            self._render()
        elif key in (" ", "o") and self.row == 0:
            self._cycle_dataset(1)
        elif key == "O" and self.row == 0:
            self._cycle_dataset(-1)
        elif key in (" ", "o") and f is not None:
            if f.cycle(1):
                self._error = ""
                self._render()
            else:
                self._open_editor()
        elif key == "O" and f is not None:
            if f.cycle(-1):
                self._error = ""
                self._render()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter) and f is not None:
            self._open_editor()
        elif key == "T":
            self._on_launch(self.overrides())
        else:
            super().keyPressEvent(event)

    def overrides(self) -> Dict[str, Any]:
        """The launch payload: the form's diff from schema defaults."""
        return self.form.overrides() if self.form is not None else {}

    def _open_editor(self) -> None:
        f = self._cur_field()
        if f is None:                 # the dataset row has no typed editor
            return
        self.editor.setText(self._render_value(f)
                            if not isinstance(f.value, list)
                            else ", ".join(str(x) for x in f.value))
        self.editor.setVisible(True)
        self.editor.setFocus()

    def _commit_editor(self) -> None:
        text = self.editor.text()
        f = self._cur_field()
        if f is None:
            self.editor.setVisible(False)
            self.setFocus()
            return
        try:
            if isinstance(f.default, list):
                # the list dual of _render_value: comma-split, blanks dropped
                f.value = [t for t in (x.strip() for x in text.split(","))
                           if t]
                if f is self._exclude_field():
                    # A hand edit settles the row: whatever the guard added
                    # and the user kept stays as THEIR choice, and a class
                    # they dropped is not re-added until the census changes.
                    self._auto_excluded = [c for c in self._auto_excluded
                                           if c in f.value]
                    self._new_classes = [c for c in self._new_classes
                                         if c in f.value]
            else:
                f.parse(text)
            self._error = ""
        except ValueError as err:
            self._error = f"{f.title}: {err}"
        self.editor.setVisible(False)
        self.setFocus()
        self._render()

    def reject(self) -> None:
        """Esc: an open editor closes first (a modal IS a step — the
        action_back ladder's rule, applied inward)."""
        if self.editor.isVisible():
            self.editor.setVisible(False)
            self.setFocus()
            self._render()
            return
        super().reject()
