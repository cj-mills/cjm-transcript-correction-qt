"""Finetune-launch slice contract (DECs 48eff28b + 99280f79): the adapter-
manifest schema reader, training-run discovery, flywheel cursor + launch
gating, and the Qt-free halves of the launch flow. SimpleNamespace fakes +
unbound-method calls (the test_navigation strategy); the offscreen probe
drives the dialog itself."""

import json
from concurrent.futures import Future
from types import SimpleNamespace

from cjm_transcript_correction_qt import panes
from cjm_transcript_correction_qt.app import CorrectionWindow
from cjm_transcript_correction_qt.session import adapter_config_schema


def test_adapter_config_schema_routes_by_task(tmp_path):
    (tmp_path / "cap.json").write_text(json.dumps(
        {"name": "cjm-capability-pyannote",
         "config_schema": {"properties": {"wrong": {}}}}))
    (tmp_path / "adapter-a.json").write_text(json.dumps(
        {"unit": "adapter", "task_name": "audio_event_detection_finetune",
         "config_schema": {"properties": {"max_epochs": {
             "type": "integer", "default": 20}}}}))
    (tmp_path / "adapter-b.json").write_text(json.dumps(
        {"unit": "adapter", "task_name": "other_task"}))   # pre-upgrade: no key
    s = adapter_config_schema(str(tmp_path), "audio_event_detection_finetune")
    assert list(s["properties"]) == ["max_epochs"]
    assert adapter_config_schema(str(tmp_path), "other_task") == {}
    assert adapter_config_schema(str(tmp_path), "missing") == {}
    assert adapter_config_schema(str(tmp_path / "absent"), "x") == {}


def test_load_runs_filters_and_sorts(tmp_path, monkeypatch):
    from cjm_transcript_correction_qt import app as app_mod
    monkeypatch.setattr(app_mod, "resolve_workspace",
                        lambda: SimpleNamespace(root=tmp_path))
    good, newer = tmp_path / "training-runs/run_a", tmp_path / "training-runs/run_b"
    for d, (rid, ts) in ((good, ("run_a", 1.0)), (newer, ("run_b", 2.0))):
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps(
            {"format": "cjm-capability-pyannote/training-run-manifest",
             "run_id": rid, "created_at": ts}))
    stray = tmp_path / "training-runs/junk"
    stray.mkdir()
    (stray / "manifest.json").write_text(json.dumps({"format": "other"}))
    s = SimpleNamespace(_runs=[])
    CorrectionWindow._load_runs(s)
    assert [m["run_id"] for m in s._runs] == ["run_b", "run_a"]  # newest first
    assert all("_path" in m for m in s._runs)


def test_train_gating_and_flywheel_cursor():
    allowed = CorrectionWindow._allowed
    fly = SimpleNamespace(stage="flywheel", lane="walk")
    for a in ("train_dataset", "next", "prev", "extract_dataset"):
        assert allowed(fly, a)
    assert not allowed(SimpleNamespace(stage="select", lane="walk"),
                       "train_dataset")
    s = SimpleNamespace(stage="flywheel", _datasets=[1, 2, 3], _runs=[4, 5],
                        _fly_cursor=0, _render=lambda: None)
    CorrectionWindow._move(s, 1)
    CorrectionWindow._move(s, 1)
    CorrectionWindow._move(s, 9)
    assert s._fly_cursor == 4   # clamped over datasets + runs (df0b72c2)
    CorrectionWindow._move(s, -9)
    assert s._fly_cursor == 0


def test_action_train_dataset_paths(monkeypatch):
    from cjm_transcript_correction_qt import app as app_mod
    notes = []
    s = SimpleNamespace(stage="spine", _finetune_busy=False, _datasets=[],
                        _paint_status=notes.append)
    CorrectionWindow.action_train_dataset(s)     # wrong stage: silent
    assert notes == []
    s.stage = "flywheel"
    CorrectionWindow.action_train_dataset(s)     # no datasets: a note
    assert "no datasets" in notes[-1]
    opened = []
    monkeypatch.setattr(app_mod, "adapter_config_schema",
                        lambda d, t: {"properties": {}})
    ds = {"dataset_id": "d1", "_path": "/x/manifest.json"}
    run = {"run_id": "run_r", "dataset_id": "d1",
           "classes": ["speech", "inhale"],
           "config": {"exclude_labels": ["empty", "click"]}}
    stray = {"run_id": "run_s", "dataset_id": "gone"}

    def state(**kw):
        d = dict(stage="flywheel", _finetune_busy=False, _datasets=[ds],
                 _runs=[run, stray], _fly_cursor=0,
                 _paint_status=notes.append,
                 sess=SimpleNamespace(manifests_dir="/m"),
                 finetune_form=SimpleNamespace(
                     open_for=lambda d, sch, adopt=None, adopt_label="",
                     datasets=None, adopt_classes=None:
                     opened.append((d, adopt, adopt_label, datasets,
                                    adopt_classes))))
        d.update(kw)
        return SimpleNamespace(**d)

    CorrectionWindow.action_train_dataset(state())
    assert opened[-1] == (ds, None, "", [ds], None)  # dataset row: defaults
    CorrectionWindow.action_train_dataset(state(_fly_cursor=1))
    assert opened[-1] == (ds, {"exclude_labels": ["empty", "click"]},
                          "run_r", [ds], ["speech", "inhale"])
    #                    run row: recipe adopted + its TRAINED class set
    #                    (1275eb52); the ring passes either way
    CorrectionWindow.action_train_dataset(state(_fly_cursor=2))
    assert "not in the list" in notes[-1]        # consumed dataset missing


def test_launch_and_done_flow():
    calls = {}
    fut = Future()

    def fake_run(cap, path, config, progress=None):
        calls["args"] = (cap, path, config)
        return fut

    emitted = []
    s = SimpleNamespace(
        finetune_form=SimpleNamespace(
            dataset={"_path": "/ds/manifest.json"}, close=lambda: None),
        _finetune_busy=False, _render=lambda: None,
        event_capability="cjm-capability-pyannote",
        sess=SimpleNamespace(finetune_run=fake_run),
        progress_note=SimpleNamespace(emit=lambda t: None),
        finetune_done=SimpleNamespace(emit=lambda f: emitted.append(f)))
    CorrectionWindow._launch_finetune(s, {"max_epochs": 5})
    assert s._finetune_busy
    assert calls["args"] == ("cjm-capability-pyannote", "/ds/manifest.json",
                             {"max_epochs": 5})
    fut.set_result({"manifest": {"run_id": "run_x"}, "error": None})
    assert emitted == [fut]
    notes = []
    s2 = SimpleNamespace(_finetune_busy=True, _load_runs=lambda: None,
                         _render=lambda: None, _paint_status=notes.append)
    CorrectionWindow._on_finetune_done(s2, fut)
    assert not s2._finetune_busy and "run_x" in notes[-1]
    bad = Future()
    bad.set_result({"manifest": None, "error": "boom"})
    CorrectionWindow._on_finetune_done(s2, bad)
    assert "boom" in notes[-1]


def fly_state(**kw):
    d = dict(stage="flywheel", lane="walk", _purpose_vocab=["feature-test"],
             _include_purposes={"genuine"}, _datasets=[], _runs=[],
             _fly_cursor=0, _finetune_busy=False, _flywheel_log=[],
             _extract_busy=False)
    d.update(kw)
    return SimpleNamespace(**d)


def flat(lines):
    return "\n".join("".join(t for t, _ in ln) for ln in lines)


def test_flywheel_lines_sections_and_detail():
    ds = {"dataset_id": "dataset_a", "counts": {"examples": 9},
          "class_vocabulary": {"inhale": 488, "click": 15},
          "spines": [{"eligible": True}, {"eligible": False}]}
    run = {"run_id": "run_z", "base_model": {"model_id": "pyannote/seg"},
           "dataset_id": "dataset_a", "classes": ["speech", "inhale"],
           "config": {"exclude_labels": ["empty", "click"], "max_epochs": 20},
           "counts": {"totals": {"train": {"speech": 7, "inhale": 2}}},
           "eval": {"metrics": {"f1": 0.91}}}
    text = flat(panes.flywheel_lines(fly_state(_datasets=[ds], _runs=[run]),
                                     width=100))
    assert "DATASETS" in text and "TRAINING RUNS" in text
    assert "> dataset_a" in text          # cursor band
    assert "inhalex488" in text           # detail block: vocab survives
    assert "run_z" in text and "f1 0.91" in text and "9 train ex" in text
    # the cursor walks past the datasets into the runs; the recipe paints
    on_run = flat(panes.flywheel_lines(
        fly_state(_datasets=[ds], _runs=[run], _fly_cursor=1), width=100))
    assert "> run_z" in on_run
    assert "classes: speech inhale" in on_run
    assert "exclude: empty click" in on_run
    assert "T re-runs this recipe" in on_run
    busy = flat(panes.flywheel_lines(fly_state(_finetune_busy=True),
                                     width=100))
    assert "training…" in busy
    narrow = panes.flywheel_lines(fly_state(_datasets=[ds]), width=40)
    assert all(len("".join(t for t, _ in ln)) <= 40 for ln in narrow)


def test_flywheel_hints_and_chip():
    verbs = {e["verb"] for e in panes.hint_entries(fly_state())}
    assert {"train_dataset", "next", "extract_dataset"} <= verbs
    chip = panes.flywheel_status_chip(fly_state(_datasets=[1], _runs=[1, 2]))
    assert chip == "flywheel (1 datasets · 2 runs)"
    assert "training…" in panes.flywheel_status_chip(
        fly_state(_finetune_busy=True))


def test_form_dataset_row_cycles_ring():
    """Adopt-recipe onto a DIFFERENT dataset (2026-08-26, the second half of
    the a1326d5b trap): row 0 is the dataset row; space cycles the discovered
    ring while the recipe rows stay; the window reads form.dataset at launch;
    a single-dataset ring refuses the cycle with a note."""
    import sys
    from PySide6.QtCore import Qt, QEvent
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    from cjm_transcript_correction_qt.finetune_form import FinetuneFormDialog
    QApplication.instance() or QApplication(sys.argv[:1])
    dlg = FinetuneFormDialog(None, on_launch=lambda o: None)
    schema = {"properties": {"seed": {"type": "integer", "default": 42}}}
    old = {"dataset_id": "old", "counts": {"examples": 10}}
    new = {"dataset_id": "new", "counts": {"examples": 20}}
    dlg.open_for(old, schema, adopt={"seed": 7}, adopt_label="run_r",
                 datasets=[new, old])
    space = QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ")
    assert dlg.row == 0 and dlg.dataset["dataset_id"] == "old"
    assert "Dataset" in dlg.view.toPlainText()
    dlg.keyPressEvent(space)
    assert dlg.dataset["dataset_id"] == "new"            # ring stepped
    assert dlg.overrides() == {"seed": 7}                # recipe stays
    dlg.keyPressEvent(space)
    assert dlg.dataset["dataset_id"] == "old"            # wraps
    dlg.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_J, Qt.NoModifier, "j"))
    assert dlg.row == 1 and dlg._cur_field() is not None
    dlg.open_for(old, schema, datasets=[old])
    dlg.keyPressEvent(space)
    assert "only one dataset" in dlg._error
    dlg.close()


def test_form_excluded_labels_surfaces_classes_new_vs_recipe():
    """Excluded-Labels new-class guard (1275eb52; the e6694c0c stray): with
    a recipe adopted, classes the chosen dataset has that the recipe never
    TRAINED are auto-added to Excluded Labels (count-ordered) and flagged
    on the row; cycling the ring re-diffs against the new census; a hand
    edit that keeps a class stands; no recipe = no diff; the header
    carries the kit's mouse close and the anchor route rejects."""
    import sys
    from PySide6.QtCore import Qt, QEvent, QUrl
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    from cjm_transcript_correction_qt.finetune_form import FinetuneFormDialog
    QApplication.instance() or QApplication(sys.argv[:1])
    dlg = FinetuneFormDialog(None, on_launch=lambda o: None)
    schema = {"properties": {
        "exclude_labels": {"type": "array", "items": {"type": "string"},
                           "default": ["empty"], "title": "Excluded Labels"},
        "seed": {"type": "integer", "default": 42}}}
    trained = {"dataset_id": "old", "counts": {"examples": 10},
               "class_vocabulary": {"speech": 400, "inhale": 90, "empty": 30,
                                    "click": 4}}
    grown = {"dataset_id": "new", "counts": {"examples": 20},
             "class_vocabulary": {"speech": 500, "inhale": 120, "empty": 40,
                                  "click": 5, "chuckle": 6,
                                  "background-music": 3}}
    recipe = {"exclude_labels": ["empty", "click"], "seed": 7}
    # the run's own dataset: nothing new -> the recipe's list, untouched
    dlg.open_for(trained, schema, adopt=recipe, adopt_label="run_r",
                 datasets=[grown, trained], adopt_classes=["speech", "inhale"])
    assert dlg._new_classes == []
    assert dlg.overrides()["exclude_labels"] == ["empty", "click"]
    assert "new vs recipe" not in dlg.view.toPlainText()
    assert 'href="close:"' in dlg.view.toHtml() or "✕" in dlg.view.toPlainText()
    # cycle onto the grown dataset: the two unseen classes are auto-excluded
    space = QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ")
    dlg.keyPressEvent(space)
    assert dlg.dataset["dataset_id"] == "new"
    assert dlg._new_classes == ["chuckle", "background-music"]   # count order
    assert dlg.overrides()["exclude_labels"] == ["empty", "click", "chuckle",
                                                 "background-music"]
    text = dlg.view.toPlainText()
    assert "new vs recipe: chuckle×6, background-music×3" in text
    # back to the trained set: the auto-adds go, the recipe's list returns
    dlg.keyPressEvent(space)
    assert dlg._new_classes == []
    assert dlg.overrides()["exclude_labels"] == ["empty", "click"]
    # a hand edit keeps chuckle as a class: the guard's add is dropped
    dlg.keyPressEvent(space)
    dlg.row = 1
    dlg.editor.setText("empty, click, background-music")
    dlg._commit_editor()
    assert dlg.overrides()["exclude_labels"] == ["empty", "click",
                                                 "background-music"]
    assert dlg._new_classes == ["background-music"]
    # opened straight from a dataset row (no recipe): nothing to diff
    dlg.open_for(grown, schema, datasets=[grown])
    assert dlg._new_classes == [] and dlg.overrides() == {}
    # the header's close anchor rejects the dialog (140a7b3c)
    assert dlg.isVisible()
    dlg._on_anchor(QUrl("close:"))
    assert not dlg.isVisible()
    dlg._on_anchor(QUrl("pin:x"))        # any other anchor is ignored
    dlg.close()


def test_ctrl_c_copies_the_cards_selection():
    """Selectable text (04519af8): the cards pane never takes focus, so the
    window forwards Ctrl+C to it — only when a selection exists; otherwise
    the key falls through to the table / super() as before (on the fake,
    reaching super() raises TypeError — the fall-through signal)."""
    import pytest
    from PySide6.QtCore import Qt
    copied = []
    cursor = SimpleNamespace(hasSelection=lambda: True)
    s = SimpleNamespace(
        cards=SimpleNamespace(textCursor=lambda: cursor,
                              copy=lambda: copied.append(1)),
        hints_overlay=SimpleNamespace(toggle=lambda: None),
        _key_table={}, _allowed=lambda a: True)
    ctrl_c = SimpleNamespace(key=lambda: Qt.Key_C, text=lambda: "\x03",
                             modifiers=lambda: Qt.ControlModifier)
    CorrectionWindow.keyPressEvent(s, ctrl_c)
    assert copied == [1]
    cursor.hasSelection = lambda: False
    with pytest.raises(TypeError):          # reached super(): not copied
        CorrectionWindow.keyPressEvent(s, ctrl_c)
    assert copied == [1]
