"""Live offscreen probe of the kit HITL panel on BOTH payloads (55bcc3c5): open the
real correction window on a Learning Game spine (feature-test purpose, explicit db
path), wait for the filter lane to load, dump what the panel paints on the filter
lane and the propose lane, jump once on each. Reads only — no gesture is submitted.
Run from the transcription-core workspace: QT_QPA_PLATFORM=offscreen python
tests_manual/live_hitl_probe.py ["<source substring>" <skeleton-prefix>]"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
WS = "/mnt/SN850X_8TB_EXT4/Projects/GitHub/cj-mills/cjm-transcription-core"
os.environ["CJM_WORKSPACE"] = WS
os.chdir(WS)

from PySide6.QtWidgets import QApplication  # noqa: E402

from cjm_transcript_correction_qt.app import CorrectionWindow  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])
DB = os.path.join(WS, ".cjm", "data", "cjm-capability-graph-sqlite", "context_graph.db")
win = CorrectionWindow(DB, source=sys.argv[1] if len(sys.argv) > 1 else "Foreword by David Perell",
                       manifests_dir=os.path.join(WS, ".cjm", "manifests"),
                       skeleton=sys.argv[2] if len(sys.argv) > 2 else "2a00e49e",
                       actor="agent:probe", autoplay=False, purpose="feature-test")


def pump(cond, what, timeout=60.0):
    t0 = time.monotonic()
    while not cond():
        app.processEvents()
        time.sleep(0.02)
        if time.monotonic() - t0 > timeout:
            from PySide6.QtWidgets import QLabel
            print("stage:", win.stage, "sources:", len(win._sources), "spines:", len(win._spines))
            print("labels:", [w.text()[:120] for w in win.strip.findChildren(QLabel) if w.text().strip()])
            raise SystemExit(f"timeout waiting for {what}")


pump(lambda: win.stage == "correct" and win.view is not None, "spine open")
print("spine open:", win.view.source_title, "segments", win.view.size, "skeleton", (win.view.skeleton_hash or "")[-12:])
pump(lambda: win._filter is not None, "filter lane load", timeout=30.0)
f = win._filter
print("sets:", len(f.sets), "chosen", f.set_id, "strata", len(f.strata), "marks", len(f.mark_ids), "watermark", f.watermark)
print("readout:", win.strip.chip_text("context") if hasattr(win.strip, "chip_text") else "")
win.lane = "filter"
win._render()
app.processEvents()
print("hitl visible:", win.hitl.isVisible(), "| cards visible:", win.cards.isVisible())
print("--- worklist ---")
print(win.hitl.worklist.plain_text())
print("--- verdicts ---")
print(win.hitl.verdicts.plain_text())
print("--- provenance ---")
print(win.hitl.provenance.plain_text())
print("--- chips ---")
for row in (win.strip.chip_rows() if hasattr(win.strip, "chip_rows") else []):
    print("  ", row)
# tier 2 on, jump to the first pending, dump the payload card
win.action_filter_tier2()
win._render()
app.processEvents()
print("--- after t (tier 2) ---")
print(win.hitl.worklist.plain_text())
p = f.current()
if p is not None:
    print("--- payload for", p.get("proposal_id")[-8:], "---")
    for ln in f.payload_lines(win.view, p, width=90):
        print("".join(t for t, _ in ln))
    win._jump_filter(1)
    app.processEvents()
    print("walk cursor after n:", win.cursor, "seg #", win.view.segments[win.cursor].index,
          win.view.segments[win.cursor].text[:40])
print("--- cards (filter lane) ---")
from cjm_transcript_correction_qt import panes  # noqa: E402
for ln in panes.render_rows(win, 100, 12):
    print("".join(t for t, _ in ln))
print("=== PROPOSE LANE ===")
win.lane = "propose"
win._render()
app.processEvents()
print("hitl lane:", win._hitl_lane(), "| proposals_meta:", {k: v for k, v in (win.view.proposals_meta or {}).items() if k != "classes"})
print(win.hitl.worklist.plain_text()[:1200])
print("--- verdicts ---")
print(win.hitl.verdicts.plain_text())
print("--- provenance ---")
print(win.hitl.provenance.plain_text())
print("--- payload (cursor 0) ---")
for ln in win._event_payload():
    print("".join(t for t, _ in ln))
win.action_propose_jump()
app.processEvents()
print("walk cursor after enter:", win.cursor, "#", win.view.segments[win.cursor].index)
win._leave_lane()
win.close()
app.processEvents()
print("PROBE OK")
