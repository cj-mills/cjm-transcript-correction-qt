"""The inline editor's Return must be CONSUMED, never bubbled to the window's
key table (user-surfaced 2026-09-02, propose-lane relabel).

QLineEdit emits returnPressed and then ignore()s the key event so it propagates
to the parent — dialog default-button semantics. In this app the parent is the
QMainWindow whose keyPressEvent dispatches the lane key table, and the propose
lane carries an `enter` binding (propose_jump). The bubbled Return therefore
moved the cursor off the just-inserted chunk BEFORE the relabel submit ran, and
`_do_submit_relabel` refused itself ("cursor moved off the insert").

The fix routes Return through CorrectionWindow.eventFilter on the editor
(submit + return True). These tests drive a real QLineEdit under a real parent
offscreen and delegate the Return/Enter branch to the app's unbound
eventFilter, so the guarded behaviour is the app's, not a copy. (Only that
branch is delegated: the app filter's fall-through is the QMainWindow super
call, which a stub host cannot satisfy.)"""
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from cjm_transcript_correction_qt.app import CorrectionWindow


class _Parent(QWidget):
    """Stands in for the QMainWindow: counts the key presses that reach it."""

    def __init__(self):
        super().__init__()
        self.seen = []

    def keyPressEvent(self, event) -> None:
        self.seen.append(event.key())
        super().keyPressEvent(event)


class _ReturnDelegate(QObject):
    """Installs on the editor; hands Return/Enter presses to the APP's
    eventFilter over a stub host and lets everything else through."""

    def __init__(self, host):
        super().__init__()
        self.host = host

    def eventFilter(self, obj, event) -> bool:
        if (event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)):
            return CorrectionWindow.eventFilter(self.host, obj, event)
        return False


def _app():
    return QApplication.instance() or QApplication(sys.argv[:1])


def _press(widget, key, text="") -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text))


def _rig():
    _app()
    parent = _Parent()
    editor = QLineEdit(parent)
    submitted = []
    host = SimpleNamespace(editor=editor,
                           cards=SimpleNamespace(viewport=lambda: None),
                           _on_editor_submitted=lambda: submitted.append(1))
    delegate = _ReturnDelegate(host)
    editor.installEventFilter(delegate)
    return parent, editor, submitted, delegate


def test_qt_bubbles_return_from_a_bare_line_edit():
    """The behaviour the fix guards against: without the filter, Return reaches
    the parent's keyPressEvent (QLineEdit ignore()s it after returnPressed)."""
    _app()
    parent = _Parent()
    editor = QLineEdit(parent)
    fired = []
    editor.returnPressed.connect(lambda: fired.append(1))
    _press(editor, Qt.Key_Return)
    assert fired == [1]
    assert parent.seen == [Qt.Key_Return]


def test_editor_return_is_submitted_and_swallowed():
    parent, editor, submitted, _keep = _rig()
    _press(editor, Qt.Key_Return)
    assert submitted == [1], "the editor's Return must submit exactly once"
    assert parent.seen == [], "and must NOT bubble to the window's key table"
    _press(editor, Qt.Key_Enter)   # keypad Enter is the same gesture
    assert submitted == [1, 1]
    assert parent.seen == []


def test_editor_other_keys_still_type():
    """Only Return/Enter are intercepted — printable keys reach the field."""
    parent, editor, submitted, _keep = _rig()
    _press(editor, Qt.Key_X, "x")
    assert editor.text() == "x"
    assert submitted == []
    assert parent.seen == []
