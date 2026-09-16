"""The correction app's chunk-escalation gesture (7a5e9c84; 0b4d5cfa (6)): the pure
helpers (argv, refusal classes, the two-phase pending record, the reload cursor), the
E key binding + lane gating, and the walk-lane hint row — over SimpleNamespace fakes
(the test_navigation strategy), no live QWidget."""

from types import SimpleNamespace

from cjm_transcript_correction_qt import panes
from cjm_transcript_correction_qt.app import CorrectionWindow
from cjm_transcript_correction_qt.escalation import (classify_refusal, cursor_for_time, pending_matches,
                                                     readout_from, refusal_line, resolve_decomp_core,
                                                     respine_argv)


class KeyTableHost:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _seg(i, s):
    return SimpleNamespace(id=f"s{i}", index=i, start_time=s)


def test_respine_argv_pins_the_spine_and_db():
    a = respine_argv("src", 655.812, "sha256:ffe1", "/tmp/p.txt", "gemini-3.8-flash", "sha256:tpl",
                     "/g.db", ".cjm/manifests")
    assert a[:5] == ["respine-chunk", "--source", "src", "--at-time", "655.812"]
    assert a[a.index("--skeleton") + 1] == "sha256:ffe1" and a[a.index("--graph-db-path") + 1] == "/g.db"
    assert a[a.index("--manifests-dir") + 1] == ".cjm/manifests" and "--strand" not in a
    b = respine_argv("src", 1.0, None, "/p", "m", "h", None, "m", strand=True)
    assert "--skeleton" not in b and "--graph-db-path" not in b and b[-1] == "--strand"


def test_refusals_pending_and_cursor_helpers(tmp_path, monkeypatch):
    dep = "REFUSED: the chunk's old segments carry dependents — 2 event insert(s) …; 5 would STRAND (…)\n"
    assert classify_refusal(dep) == "dependents" and refusal_line(dep).startswith("the chunk")
    assert classify_refusal("REFUSED: no decomp manifest records …\n") == "other"
    assert classify_refusal("respined chunk 3 of X: …\n") is None
    assert readout_from("[INFO] x\nrespined chunk 3 of X: 84 old -> 80 new\ntranscript: t\n") == "respined chunk 3 of X: 84 old -> 80 new"
    assert readout_from("chunk 3: already respined — no-op (transcript t)\n").startswith("chunk 3:")
    assert readout_from("") == "done"
    p = {"chunk": 3, "chunk_range": (655.75, 873.4)}
    assert pending_matches(p, 700.0) and pending_matches(p, 655.4) and not pending_matches(p, 900.0)
    assert not pending_matches(None, 700.0) and not pending_matches(p, None) and not pending_matches({}, 1.0)
    segs = [_seg(0, 0.0), _seg(1, 10.0), SimpleNamespace(id="ins", index=1, start_time=None), _seg(2, 20.0)]
    assert cursor_for_time(segs, 10.0) == 1 and cursor_for_time(segs, 9.5) == 1 and cursor_for_time(segs, 15.0) == 3
    assert cursor_for_time(segs, 99.0) == 3 and cursor_for_time(segs, None) == 0 and cursor_for_time([], 5.0) == 0
    # the ladder: this env's bin, then PATH, then the sibling env
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    monkeypatch.setattr("sys.executable", str(tmp_path / "own" / "bin" / "python"))
    assert resolve_decomp_core(envs_root=str(tmp_path / "envs")) is None
    own = tmp_path / "own" / "bin" / "cjm-transcript-decomp-core"
    own.parent.mkdir(parents=True)
    own.write_text("#!/bin/sh\n")
    assert resolve_decomp_core(envs_root=str(tmp_path / "envs")) == str(own)


def test_key_table_binds_E_and_lane_gating():
    host = KeyTableHost()
    CorrectionWindow._build_key_table(host)
    actions = [a for a, _ in host._key_table["E"]]
    assert actions == ["escalate_chunk", "filter_accept_span"], "E = escalate in the walk lane; the filter lane's span accept keeps its key"
    assert [a for a, _ in host._key_table["I"]] == ["insert_labeled"], "I stays insert_labeled (the ratified key collides)"
    st = SimpleNamespace(stage="correct", lane="walk", view=object())
    assert CorrectionWindow._allowed(st, "escalate_chunk")
    for lane in ("assign", "propose", "annotate", "filter"):
        st.lane = lane
        assert not CorrectionWindow._allowed(st, "escalate_chunk"), lane


def test_walk_hint_row_names_the_gesture():
    walk = {r["verb"]: r for r in panes.hint_entries(SimpleNamespace(stage="correct", lane="walk"))}
    assert walk["escalate_chunk"]["key"] == "E" and walk["escalate_chunk"]["group"] == "Respine"
    assign = {r["verb"] for r in panes.hint_entries(SimpleNamespace(stage="correct", lane="assign"))}
    assert "escalate_chunk" not in assign
