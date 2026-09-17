"""The E gesture's LIVE slot text (finding c63cd2e3): the corrected spine over a
chunk's span, by segment START time — inserts with a time ride along, timeless ones
and pruned segments stay out — and the readout names which slots came from it."""
from types import SimpleNamespace

from cjm_transcript_correction_qt.app import CorrectionWindow
from cjm_transcript_correction_qt.escalation import spine_text_between


def seg(sid, start, text):
    return SimpleNamespace(id=sid, start_time=start, text=text)


def test_spine_text_between_reads_the_corrected_span():
    segs = [seg("a", 0.0, "before"), seg("b", 100.0, "CORRECTED one"), seg("ins", 150.5, "[laughs]"),
            seg("tl", None, "timeless insert"), seg("p", 160.0, "pruned junk"),
            seg("empty", 170.0, "   "), seg("c", 200.0, "after")]
    assert spine_text_between(segs, 100.0, 200.0, pruned_ids={"p"}) == "CORRECTED one [laughs]"
    assert spine_text_between(segs, 0.0, 100.0) == "before"
    assert spine_text_between(segs, 300.0, 400.0) == ""
    assert spine_text_between([], 0.0, 100.0) == ""


def test_prompt_ready_readout_names_the_spine_sourced_slots(monkeypatch):
    import cjm_transcript_correction_qt.app as mod
    painted = []
    monkeypatch.setattr(mod.QGuiApplication, "clipboard",
                        staticmethod(lambda: SimpleNamespace(setText=lambda t: None)))
    h = SimpleNamespace(_respine_busy=True, _escalation=None,
                        _paint_status=lambda s: painted.append(s))
    r = {"prompt": "p", "chunk": 3, "chunk_range": (300.0, 400.0), "prompt_hash": "h" * 20,
         "audio": "/nope/x.wav", "at_time": 310.0, "live_segments": 12,
         "slot_sources": {"prev_text": "spine", "next_text": "manifest", "draft_text": "spine"}}
    fut = SimpleNamespace(result=lambda: r)
    CorrectionWindow._on_prompt_ready(h, fut)
    assert "prev/draft from the corrected spine" in painted[-1]
    assert h._escalation["chunk"] == 3 and h._respine_busy is False
    r["slot_sources"] = {"prev_text": "manifest", "next_text": "manifest", "draft_text": "manifest"}
    CorrectionWindow._on_prompt_ready(h, fut)
    assert "slots from the manifest" in painted[-1]
