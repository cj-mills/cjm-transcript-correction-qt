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
           "config": {"exclude_labels": ["empty", "click"]}}
    stray = {"run_id": "run_s", "dataset_id": "gone"}

    def state(**kw):
        d = dict(stage="flywheel", _finetune_busy=False, _datasets=[ds],
                 _runs=[run, stray], _fly_cursor=0,
                 _paint_status=notes.append,
                 sess=SimpleNamespace(manifests_dir="/m"),
                 finetune_form=SimpleNamespace(
                     open_for=lambda d, sch, adopt=None, adopt_label="":
                     opened.append((d, adopt, adopt_label))))
        d.update(kw)
        return SimpleNamespace(**d)

    CorrectionWindow.action_train_dataset(state())
    assert opened[-1] == (ds, None, "")          # dataset row: schema defaults
    CorrectionWindow.action_train_dataset(state(_fly_cursor=1))
    assert opened[-1] == (ds, {"exclude_labels": ["empty", "click"]},
                          "run_r")               # run row: recipe adopted
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
