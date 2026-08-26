"""Offscreen paint probe: stand the correction window up over a stubbed
graph stack (no capability loads, no real SpineView) and walk the cheap
gestures — boot ladder, pickers, spine open, walk paint, lane cycle, editor,
one commit gesture through the real loop thread — the paint-path
verification layer pytest cannot give (67335f7d), Qt edition. Run from a
NEUTRAL cwd:

    QT_QPA_PLATFORM=offscreen python offscreen_probe.py
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import cjm_transcript_correction_qt.app as app_mod  # noqa: E402
import cjm_transcript_correction_qt.session as sess_mod  # noqa: E402
from cjm_transcript_correction_qt.session import CorrectionShellSession  # noqa: E402


def seg(i, text, start, end):
    return SimpleNamespace(id=f"s{i}", index=i, text=text, start_time=start,
                           end_time=end, text_from=None)


class FakeQueue:
    async def stop(self):
        pass


def make_fake_view():
    segs = [seg(0, "hello there", 0.0, 1.5),
            seg(1, "second segment words", 1.5, 3.0),
            seg(2, "third one", 3.0, 4.5)]

    async def close():
        pass

    return SimpleNamespace(
        segments=segs, size=3, queue=FakeQueue(), graph_id="g",
        source_id="src-1", source_title="Probe Talk", source_path=None,
        inserted_ids=set(), pruned_ids=set(), marked_ids=set(),
        overlay_ids=set(), insert_labels={}, insert_ranks={},
        speakers={}, turn_proposals={}, event_proposals={},
        proposals_meta={}, turns_meta={}, cluster_entities={},
        show_tier2=False, overlay_count=0, gate=None, skeleton_hash="sha:1",
        seen_mark_classes=[], seen_insert_labels=[], seen_overlay_labels=[],
        aseg_index=lambda pos: 0, chunk=lambda i: None,
        seam=lambda i, d, context_s=2.0: None,
        marks_for=lambda sid: [], overlays_for=lambda sid: [],
        prune_correction_for=lambda sid: None,
        refresh_turn_proposal=lambda sid: None,
        refresh_event_proposals=lambda: None,
        add_mark_local=lambda m: None,
        close=close)


def install_stubs(tmp: Path):
    async def stack_opener(path, *, manifests_dir, graph_capability):
        return object(), FakeQueue(), str(tmp / "graph.db")

    async def view_opener(mgr, q, cap, source_id, title, *, rendition,
                          skeleton):
        return make_fake_view()

    class ProbeSession(CorrectionShellSession):
        def __init__(self, manifests_dir, **kw):
            super().__init__(manifests_dir, stack_opener=stack_opener,
                             view_opener=view_opener,
                             **{k: v for k, v in kw.items()
                                if k != "graph_capability"})

    async def fake_list_sources(queue, cap):
        return [("src-1", "Probe Talk"), ("src-2", "Other Talk")]

    async def fake_status(queue, cap, sid):
        return {"segments": 3, "corrections": 1, "marks": 0}

    async def fake_purposes(queue, cap):
        return {"src-1": {"genuine": 2}}

    async def fake_spines(queue, cap, sid, *, rendition_selector=None):
        return [{"skeleton_hash": None, "segments": 3},
                {"skeleton_hash": "sha256:abc", "split_policy": "sentence-split/v1",
                 "segments": 5}]

    async def fake_start_session(queue, graph_id, sources, *, journal_path,
                                 purpose):
        return SimpleNamespace(id="sess-probe")

    async def fake_entities(queue, graph_id):
        return []

    async def fake_commit_mark(queue, graph_id, source_id, anchor, mark_class,
                               session_id, *, actor, note, journal_path):
        return "mark-1"

    app_mod.CorrectionShellSession = ProbeSession
    sess_mod.list_sources = fake_list_sources
    sess_mod.source_status = fake_status
    sess_mod.session_purposes_by_source = fake_purposes
    sess_mod.list_source_spines = fake_spines
    sess_mod.start_session = fake_start_session
    sess_mod.list_speaker_entities = fake_entities
    app_mod.commit_mark_correction = fake_commit_mark


def pump(app, cond, what, timeout=8.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        app.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="correction-qt-probe-"))
    install_stubs(tmp)
    app = QApplication(sys.argv[:1])
    win = app_mod.CorrectionWindow(None, manifests_dir=str(tmp / "manifests"),
                                   autoplay=False)
    win.show()

    # boot ladder -> source picker with statuses painted
    pump(app, lambda: win._sources and win._status, "the source picker")
    assert win.stage == "select"
    assert "pick a source (2)" in strip_text(win)
    assert "Probe Talk" in win.cards.toPlainText()
    assert "1 corrections" in win.cards.toPlainText()

    # walk the picker, open -> the spine picker (two skeletons coexist)
    win._move(1)
    win._move(-1)
    win.action_open_source()
    pump(app, lambda: win.stage == "spine", "the spine picker")
    assert "2 spines coexist" in win.cards.toPlainText()
    assert "vad-only (pre-split)" in win.cards.toPlainText()

    # open the spine -> the walk, center-pinned card canvas + WALK status
    win.action_open_source()
    pump(app, lambda: win.stage == "correct", "the walk")
    assert win.session_id == "sess-probe"
    assert "[WALK]" in strip_text(win)
    assert "segment 1/3" in strip_text(win)
    assert "hello there" in win.cards.toPlainText()
    assert win.strip.hints.text().endswith("? keys")

    # wheel/keys move the cursor; the chips follow (readout untouched)
    win._move(1)
    assert "segment 2/3" in strip_text(win)

    # tab cycles the lane (assign next in rotation; no propset -> no propose)
    win.action_cycle_lane()
    assert win.lane == "assign"
    win.action_cycle_lane()
    assert win.lane == "annotate"
    win.action_cycle_lane()
    assert win.lane == "walk"

    # the inline editor opens with the segment text and escape closes it
    win.action_edit()
    assert win.editor.isVisible()
    assert win.editor.text() == "second segment words"
    win.action_cancel()
    assert not win.editor.isVisible()

    # the M prompt (variable-length vocabulary) rides the full-width CONTEXT
    # slot, not the readout — and leaves with the editor
    win.action_mark_editor()
    assert win.editor.isVisible()
    assert "suspect" in win.strip.context.text()
    assert not win.strip.context.isHidden()
    assert "suspect" not in win.strip.readout.text()
    win.action_cancel()
    assert win.strip.context.isHidden()

    # one commit gesture through the REAL loop thread + gesture lock — the
    # echo lands in the persistent-readout slot and STAYS across a move
    win._submit_gesture(win._do_mark_quick())
    pump(app, lambda: "⚑ #1 [suspect]" in win.strip.readout.text(), "the ⚑ echo")
    win._move(1)
    assert "⚑ #1 [suspect]" in win.strip.readout.text()

    # the ?-overlay opens with the lane model; pinning re-projects the line
    win.hints_overlay.toggle()
    assert win.hints_overlay.isVisible()
    assert "Keyboard hints" in win.hints_overlay.view.toPlainText()
    win.hints_overlay._toggle_pin("next")   # unpin a default…
    win.hints_overlay._toggle_pin("yank")   # …pin y copy in its place
    assert "y copy" in win.strip.hints.text()
    win.hints_overlay.toggle()
    assert not win.hints_overlay.isVisible()

    # gate: annotate-only keys are inert in the walk lane
    assert not win._allowed("word_select")
    assert win._allowed("edit")
    win.lane = "annotate"
    assert win._allowed("word_select") and not win._allowed("edit")
    win.lane = "walk"

    # ---- navigation slice (f27f2b99): no more dead ends ------------------
    # the menubar exists and mirrors the shell verbs (keys stay on the walk)
    assert [a.text() for a in win.menuBar().actions()] == \
        ["&File", "&Navigate", "&View"]
    win._refresh_nav_menu()
    assert win._nav_actions["back"].isEnabled()
    assert win._nav_actions["spines"].isEnabled()

    # stale-readout fix: a lane readout dies on the flywheel doorstep
    win._paint_status("opening Probe Talk…")
    win.action_flywheel_page()
    pump(app, lambda: "FLYWHEEL" in win.cards.toPlainText(),
         "the flywheel page")
    assert win.stage == "flywheel"
    assert win.strip.readout.text() == ""

    # F returns to the INTACT lane (the seat survived the page swap)
    win.action_flywheel_page()
    assert win.stage == "correct" and win.view is not None
    assert "segment" in strip_text(win)

    # B unwinds the lane to the spine picker (browse mode: picker always
    # shows), then further back to the sources with statuses re-read
    win.action_back()
    pump(app, lambda: win.stage == "spine", "the spine picker (back)")
    assert win.view is None and win._nav_browsing
    assert win.strip.readout.text() == ""
    win.action_back()
    pump(app, lambda: win.stage == "select" and win._discovered,
         "the source picker (back)")
    assert win._open_kwargs["source"] is None   # pre-pick consumed

    # forward re-descends; reopening mints a fresh session on the seat
    win.action_forward()
    pump(app, lambda: win.stage == "spine", "the spine picker (forward)")
    win.action_open_source()
    pump(app, lambda: win.stage == "correct", "the walk (again)")
    assert win.session_id == "sess-probe" and win.view is not None

    # ---- finetune launch (48eff28b + 99280f79): form -> seat -> runs -----
    win.action_flywheel_page()
    pump(app, lambda: "FLYWHEEL" in win.cards.toPlainText(),
         "the flywheel page (finetune walk)")
    assert "TRAINING RUNS" in win.cards.toPlainText()
    win.action_train_dataset()
    assert "no datasets" in win.strip.readout.text()

    ds = {"dataset_id": "dataset_probe", "_path": "/probe/ds/manifest.json",
          "counts": {"examples": 42},
          "class_vocabulary": {"inhale": 40, "click": 2},
          "spines": [{"eligible": True}]}
    win._datasets = [ds]
    win._move(1)   # the flywheel cursor clamps on one dataset
    assert win._fly_cursor == 0
    schema = {"properties": {
        "max_epochs": {"type": "integer", "default": 20,
                       "title": "Max Epochs"},
        "prepare_wav": {"type": "boolean", "default": True,
                        "title": "Prepare WAV"}}}
    orig_schema_read = app_mod.adapter_config_schema
    app_mod.adapter_config_schema = lambda d, t: schema
    win.action_train_dataset()
    app_mod.adapter_config_schema = orig_schema_read
    dlg = win.finetune_form
    assert dlg.isVisible() and len(dlg._fields()) == 2
    assert "dataset_probe" in dlg.view.toPlainText()

    # space cycles the bool row; the transient editor commits a typed int
    dlg.row = 1
    assert dlg._fields()[1].cycle(1)
    dlg.row = 0
    dlg._open_editor()
    dlg.editor.setText("5")
    dlg._commit_editor()
    assert dlg.overrides() == {"max_epochs": 5, "prepare_wav": False}

    # launch through a STUBBED seat: the Future resolves with a manifest and
    # the Qt-side flow lands it in the readout + refreshes the runs section
    from concurrent.futures import Future as _Future
    seat_calls = {}

    def fake_finetune_run(cap, path, config, progress=None):
        seat_calls["args"] = (cap, path, config)
        f = _Future()
        f.set_result({"manifest": {"run_id": "run_probe"}, "error": None})
        return f

    win.sess.finetune_run = fake_finetune_run
    dlg._on_launch(dlg.overrides())   # the T gesture's effect
    pump(app, lambda: not win._finetune_busy and
         "run_probe" in win.strip.readout.text(), "the finetune result")
    assert seat_calls["args"] == ("cjm-capability-pyannote",
                                  "/probe/ds/manifest.json",
                                  {"max_epochs": 5, "prepare_wav": False})
    assert not dlg.isVisible()

    # T on a RUN row re-runs its recipe (df0b72c2): the form opens for the
    # run's consumed dataset with its config adopted + provenance named
    win._runs = [{"run_id": "run_adopt", "dataset_id": "dataset_probe",
                  "classes": ["speech", "inhale"],
                  "config": {"max_epochs": 7},
                  "counts": {"totals": {"train": {"speech": 3}}}}]
    win._fly_cursor = 1   # past the one dataset, onto the run row
    win._render()
    assert "T re-runs this recipe" in win.cards.toPlainText()
    app_mod.adapter_config_schema = lambda d, t: schema
    win.action_train_dataset()
    app_mod.adapter_config_schema = orig_schema_read
    assert dlg.isVisible()
    assert dlg.overrides() == {"max_epochs": 7}   # the recipe's diff
    assert "recipe from run_adopt" in dlg.view.toPlainText()
    dlg.reject()
    assert not dlg.isVisible()

    win.close()
    app.processEvents()
    print("offscreen probe: all assertions passed")
    return 0


def strip_text(win):
    """All visible StatusStrip text — chips + readout + transient — the
    probe's one-line view of the decomposed footer (DEC 2a42c028)."""
    parts = [c.text() for c in win.strip._chips.values()]
    parts += [win.strip.readout.text(), win.strip.transient.text()]
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
