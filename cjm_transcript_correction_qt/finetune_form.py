"""Modal finetune-launch form (DECs 48eff28b + 99280f79) on the kit
FormShell (d55292f9): the tui-kit ConfigForm model owns semantics
(cycle/parse/overrides); the shell owns the chrome — a FIXED header (title
+ mouse close, 140a7b3c) and FIXED footer (hints + errors) around NATIVE
clickable rows (kit PickerList) with ensure-visible keyboard follow, and
the focused row's description in the always-visible detail pane — the
scrolled-away header/hints defect dies here. Keys: j/k or click = row
cursor · space/o cycle closed sets (dataset row: cycle the discovered
ring) · enter typed input (the transient escape hatch, list fields
comma-split) · T launch · esc cancel. Launch reports overrides() through
on_launch — the CALLER submits the task and closes the dialog."""

import html as _html
from typing import Any, Callable, Dict, List, Optional

from cjm_substrate_qt_kit.formdialog import FormShell
from cjm_substrate_qt_kit.keyhints import keycaps
from cjm_substrate_qt_kit.theme import current_theme
from cjm_substrate_tui_kit.form import ConfigForm
from PySide6.QtCore import Qt


class FinetuneFormDialog(FormShell):
    """The finetune run-config form: schema-driven rows over a chosen
    dataset. State is (form, dataset, row = the body cursor); the caller
    opens with open_for and receives the non-default overrides dict
    through on_launch. Row 0 is the dataset row — space cycles the
    discovered ring while the recipe rows stay (the a1326d5b trap's second
    half) — and an adopted recipe's Excluded-Labels row surfaces the
    classes the chosen dataset has that the recipe never trained
    (1275eb52)."""

    def __init__(self, parent, *,
                 on_launch: Callable[[Dict[str, Any]], None]):
        super().__init__(parent, on_cursor=self._on_row)
        self._on_launch = on_launch
        self.form: Optional[ConfigForm] = None
        self.dataset: Dict[str, Any] = {}
        self.datasets: List[Dict[str, Any]] = []   # the selectable ring
        self._opened_id = ""                       # the dataset opened with
        self.adopt_label = ""
        self._recipe_classes: Optional[List[str]] = None  # adopted run's trained set
        self._new_classes: List[str] = []          # census − recipe, this dataset
        self._auto_excluded: List[str] = []        # what the guard added last
        self._error = ""
        self.editor.returnPressed.connect(self._commit_editor)

    @property
    def row(self) -> int:
        """0 = dataset row, 1.. = schema fields (the body cursor)."""
        return self.body.cursor

    @row.setter
    def row(self, i: int) -> None:
        self.body.set_cursor(int(i))

    def open_for(self, dataset: Dict[str, Any],
                 schema: Dict[str, Any],
                 adopt: Optional[Dict[str, Any]] = None,
                 adopt_label: str = "",
                 datasets: Optional[List[Dict[str, Any]]] = None,
                 adopt_classes: Optional[List[str]] = None) -> None:
        """(Re)build the form from the adapter's config schema and open
        centered over the owner, sized to the rendered rows (the shell's
        keyhints recipe). `adopt` applies a prior run's config snapshot
        over the schema defaults (df0b72c2: re-run the recipe — the
        modified dots then paint the recipe's diff); `adopt_label` names
        the provenance in the header. `datasets` is the selectable ring
        (newest first): an adopted run's consumed dataset is only the
        STARTING point — space on the dataset row cycles to any discovered
        dataset, so a recipe re-runs on NEW data without retyping its
        config. `adopt_classes` is the adopted run's TRAINED class set —
        with it the Excluded-Labels row guards against silent class growth
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
        self._error = ""
        self._guard_new_classes()
        self._render(cursor=0)
        self.open_sized(min_width=520)

    # ---- state -----------------------------------------------------------

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
            self._paint_context()
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

    # ---- paint -----------------------------------------------------------

    def _render(self, cursor: Optional[int] = None) -> None:
        """Rebuild header + rows (open, ring cycle, editor commit); plain
        cursor moves repaint only the detail/footer (_on_row)."""
        theme = current_theme()
        e = _html.escape
        counts = self.dataset.get("counts") or {}
        title = ("FINETUNE — %s<span style='color:%s'> · %s examples</span>"
                 % (e(str(self.dataset.get("dataset_id") or "?")),
                    theme["content-dim"], counts.get("examples", 0)))
        if self.adopt_label:
            title += ("<span style='color:%s'> · recipe from %s — ● rows "
                      "are its diff from defaults</span>"
                      % (theme["content-dim"], e(self.adopt_label)))
        self.set_header(title)
        rows: List[Dict[str, Any]] = []
        fields = self._fields()
        if not fields:
            rows.append({"kind": "note", "spans": [
                ("  no config schema — regenerate the adapter manifest "
                 "(cjm-ctl generate-adapter-manifest); launch uses worker "
                 "defaults", "dim")]})
        did = str(self.dataset.get("dataset_id") or "")
        rows.append({"kind": "item", "key": "dataset", "spans": [
            ("● " if did != self._opened_id else "  ", ""),
            ("Dataset: ", ""),
            ("%s · %s examples" % (did or "?", counts.get("examples", 0)),
             "bold")]})
        vocab = self.dataset.get("class_vocabulary") or {}
        for f in fields:
            spans = [("● " if f.modified else "  ", ""),
                     (f.title + ": ", ""), (self._render_value(f), "bold")]
            if f.key == "exclude_labels" and self._new_classes:
                spans.append(("  ◆ new vs recipe: %s (auto-excluded)"
                              % ", ".join("%s×%s" % (c, vocab.get(c, "?"))
                                          for c in self._new_classes),
                              "yellow"))
            rows.append({"kind": "item", "key": f.key, "spans": spans})
        self.body.set_rows(rows, cursor=self.row if cursor is None else cursor)
        self._paint_context()

    def _paint_context(self) -> None:
        """The focused row's description (detail pane) + the fixed footer
        (error, then hints) — the halves a cursor move repaints alone."""
        theme = current_theme()
        if self.row == 0:
            desc = ("The dataset this run trains on — space cycles the %d "
                    "discovered dataset(s), newest first; the recipe rows "
                    "stay." % len(self.datasets))
        else:
            f = self._cur_field()
            desc = (f.description or "") if f is not None else ""
            if (f is not None and f.key == "exclude_labels"
                    and self._new_classes):
                desc += (" ◆ Classes in this dataset the adopted recipe "
                         "never trained were auto-excluded so the class set "
                         "cannot grow silently — enter edits the list to "
                         "keep one.")
        self.body.set_detail([[(desc, "dim")]] if desc else None)
        err = ("<span style='color:%s'>⚠ %s</span><br>"
               % (theme["accent"], _html.escape(self._error))
               if self._error else "")
        self.set_footer(err + "%s move · %s cycle · %s edit · %s launch · "
                        "%s or ✕ cancel"
                        % (keycaps("j/k", theme), keycaps("space", theme),
                           keycaps("enter", theme), keycaps("T", theme),
                           keycaps("esc", theme)))

    def _on_row(self, i: int) -> None:
        """Cursor landing (keyboard or click): the error clears and only
        the detail/footer repaint — never the rows."""
        self._error = ""
        self._paint_context()

    # ---- keys ------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if self.editor.isVisible():   # the QLineEdit owns typing; esc lands
            super().keyPressEvent(event)   # in the shell's reject ladder
            return
        key = event.text()
        f = self._cur_field()
        if key in ("j",) or event.key() == Qt.Key_Down:
            self.body.move(1)
        elif key in ("k",) or event.key() == Qt.Key_Up:
            self.body.move(-1)
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
        self.open_editor(self._render_value(f)
                         if not isinstance(f.value, list)
                         else ", ".join(str(x) for x in f.value))

    def _commit_editor(self) -> None:
        text = self.editor.text()
        f = self._cur_field()
        if f is None:
            self.close_editor()
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
        self.close_editor()
        self._render()
