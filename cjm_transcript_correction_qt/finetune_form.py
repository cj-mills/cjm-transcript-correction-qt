"""Modal finetune-launch form (DECs 48eff28b + 99280f79): the tui-kit
ConfigForm model painted in a frameless modal dialog over the flywheel page
— the model owns semantics (cycle/parse/overrides), this dialog owns the
widgets (the KeyHintsOverlay chrome). Keys: j/k field cursor · space/o
cycle closed sets · enter typed input (the transient escape hatch, list
fields comma-split) · T launch · esc cancel. Launch reports overrides()
through on_launch — the CALLER submits the task and closes the dialog."""

import html as _html
from typing import Any, Callable, Dict, Optional

from cjm_substrate_qt_kit.keyhints import keycaps
from cjm_substrate_qt_kit.theme import current_theme, make_font
from cjm_substrate_tui_kit.form import ConfigForm
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QTextBrowser, QVBoxLayout


class FinetuneFormDialog(QDialog):
    """The finetune run-config form: schema-driven rows over a chosen
    dataset. State is (form, dataset, row); the caller opens with open_for
    and receives the non-default overrides dict through on_launch."""

    def __init__(self, parent, *,
                 on_launch: Callable[[Dict[str, Any]], None]):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self._on_launch = on_launch
        self.form: Optional[ConfigForm] = None
        self.dataset: Dict[str, Any] = {}
        self.adopt_label = ""
        self.row = 0
        self._error = ""
        self.view = QTextBrowser(self)
        self.view.setFocusPolicy(Qt.NoFocus)
        self.view.setFont(make_font(kind="mono"))
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
                 adopt_label: str = "") -> None:
        """(Re)build the form from the adapter's config schema and open
        centered over the owner — the keyhints sizing recipe: size to the
        RENDERED document (drive verdict e37afc63). `adopt` applies a prior
        run's config snapshot over the schema defaults (df0b72c2: re-run
        the recipe — the modified dots then paint the recipe's diff);
        `adopt_label` names the provenance in the header."""
        self.form = ConfigForm.from_schema(schema)
        if adopt:
            self.form.apply(adopt)
        self.adopt_label = adopt_label if adopt else ""
        self.dataset = dict(dataset)
        self.row = 0
        self._error = ""
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
        out = ["<b>FINETUNE</b> — %s<span style='color:%s'> · %s examples"
               "</span>" % (e(str(self.dataset.get("dataset_id") or "?")),
                            theme["content-dim"], counts.get("examples", 0))]
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
        for i, f in enumerate(fields):
            mark = "●" if f.modified else "&nbsp;"
            row = ("%s %s: <b>%s</b>" % (mark, e(f.title),
                                         e(self._render_value(f))))
            if i == self.row:
                desc = ("<br><span style='color:%s'>&nbsp;&nbsp;%s</span>"
                        % (theme["content-dim"], e(f.description))
                        if f.description else "")
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
                   "%s launch · %s cancel</span>"
                   % (theme["content-dim"], keycaps("j/k", theme),
                      keycaps("space", theme), keycaps("enter", theme),
                      keycaps("T", theme), keycaps("esc", theme)))
        self.view.setHtml("<div style='color:%s'>%s</div>"
                          % (theme["content"], "<br>".join(out)))

    # ---- keys ------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if self.editor.isVisible():   # the QLineEdit owns typing; esc lands
            super().keyPressEvent(event)   # in reject() below
            return
        key = event.text()
        fields = self._fields()
        if key in ("j",) or event.key() == Qt.Key_Down:
            self.row = min(len(fields) - 1, self.row + 1) if fields else 0
            self._error = ""
            self._render()
        elif key in ("k",) or event.key() == Qt.Key_Up:
            self.row = max(0, self.row - 1)
            self._error = ""
            self._render()
        elif key in (" ", "o") and fields:
            f = fields[self.row]
            if f.cycle(1):
                self._error = ""
                self._render()
            else:
                self._open_editor()
        elif key == "O" and fields:
            if fields[self.row].cycle(-1):
                self._error = ""
                self._render()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter) and fields:
            self._open_editor()
        elif key == "T":
            self._on_launch(self.overrides())
        else:
            super().keyPressEvent(event)

    def overrides(self) -> Dict[str, Any]:
        """The launch payload: the form's diff from schema defaults."""
        return self.form.overrides() if self.form is not None else {}

    def _open_editor(self) -> None:
        f = self._fields()[self.row]
        self.editor.setText(self._render_value(f)
                            if not isinstance(f.value, list)
                            else ", ".join(str(x) for x in f.value))
        self.editor.setVisible(True)
        self.editor.setFocus()

    def _commit_editor(self) -> None:
        text = self.editor.text()
        f = self._fields()[self.row]
        try:
            if isinstance(f.default, list):
                # the list dual of _render_value: comma-split, blanks dropped
                f.value = [t for t in (x.strip() for x in text.split(","))
                           if t]
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
