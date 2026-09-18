"""Live offscreen probe of the ANNOTATE lane's proposal mode (DEC d52d105f): open
the real correction window on a spine that carries a SPAN proposal set
(feature-test purpose, explicit db path), wait for the span lane to load, tab
order, dump what the panel paints, arm a few proposals (n / enter) and time the
per-gesture frame on the full set. Reads only — NO commit gesture is submitted
(the walk is the human's). Run from anywhere:
QT_QPA_PLATFORM=offscreen python tests_manual/live_span_probe.py ["<source>" <skeleton-prefix>]"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
WS = "/mnt/SN850X_8TB_EXT4/Projects/GitHub/cj-mills/cjm-transcription-core"
os.environ["CJM_WORKSPACE"] = WS
os.chdir(WS)

from PySide6.QtWidgets import QApplication  # noqa: E402

from cjm_transcript_correction_qt import panes  # noqa: E402
from cjm_transcript_correction_qt.app import CorrectionWindow  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])
DB = os.path.join(WS, ".cjm", "data", "cjm-capability-graph-sqlite", "context_graph.db")
win = CorrectionWindow(DB, source=sys.argv[1] if len(sys.argv) > 1 else "0b877597-bc3a-5bb9-8e58-0c73255118a6",
                       manifests_dir=os.path.join(WS, ".cjm", "manifests"),
                       skeleton=sys.argv[2] if len(sys.argv) > 2 else "ffe13ba4",
                       actor="agent:probe", autoplay=False, purpose="feature-test")


def pump(cond, what, timeout=90.0):
    t0 = time.monotonic()
    while not cond():
        app.processEvents()
        time.sleep(0.02)
        if time.monotonic() - t0 > timeout:
            print("stage:", win.stage, "sources:", len(win._sources), "spines:", len(win._spines))
            raise SystemExit(f"timeout waiting for {what}")


def settle(seconds=0.4):
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        app.processEvents()
        time.sleep(0.01)


pump(lambda: win.stage == "correct" and win.view is not None, "spine open")
view = win.view
print("spine open:", view.source_title, "· segments", view.size, "· skeleton",
      (view.skeleton_hash or "")[-12:], "· overlays", view.overlay_count)
pump(lambda: win._span is not None, "span lane load", timeout=30.0)
f = win._span
print("span sets:", len(f.sets), "· chosen", f.set_id, "· rows", len(f.proposals),
      "· pending", len(f.pending(view)), "· tier-2 hidden", f.hidden_tier2(view),
      "· watermark", f.watermark)

order = []
win.lane = "walk"
for _ in range(5):
    win._cycle_lane(1)
    order.append(win.lane)
print("tab order from walk:", " -> ".join(order))

win.lane = "annotate"
t0 = time.perf_counter()
win._render()
app.processEvents()
print(f"first annotate frame: {(time.perf_counter() - t0) * 1000:.0f} ms · hitl lane {win._hitl_lane()}"
      f" · hitl visible {win.hitl.isVisible()}")
print("--- worklist (head) ---")
print("\n".join(win.hitl.worklist.plain_text().splitlines()[:8]))
print("--- verdicts ---")
print(win.hitl.verdicts.plain_text())
print("--- provenance ---")
print(win.hitl.provenance.plain_text())
print("--- chips ---")
print(" | ".join(f"{k}: {v}" for k, v in panes.status_chips(win)))

win.cursor = 0   # the saved walk bookmark may sit anywhere; the worklist walk starts at the top
for step in range(3):
    t0 = time.perf_counter()
    win._jump_span(1)
    app.processEvents()
    ms = (time.perf_counter() - t0) * 1000
    settle()
    p = f.armed(view, win.cursor)
    seg = view.segments[win.cursor]
    print(f"--- n #{step + 1}: {ms:.0f} ms · cursor #{seg.index} · armed "
          f"{(p or {}).get('label')} “{((p or {}).get('anchor') or {}).get('text_snapshot')}” · "
          f"selection anchor/cursor {win._word_anchor}/{win._word_cursor}")
    for ln in f.payload_lines(view, p, width=100):
        print("   ", "".join(t for t, _ in ln))

print("--- cards around the cursor ---")
for ln in panes.render_rows(win, 110, 9):
    print("".join(t for t, _ in ln))

t0 = time.perf_counter()
for _ in range(10):
    win._move(1)
    app.processEvents()
print(f"10 walk steps on the annotate lane: {(time.perf_counter() - t0) * 100:.0f} ms/step")

win.action_span_tier2()
app.processEvents()
print("after t:", len(f.pending(view)), "pending (tier 2 shown)")
win.action_span_jump()
app.processEvents()
settle()
p = f.armed(view, win.cursor)
print("enter armed:", (p or {}).get("label"), ((p or {}).get("anchor") or {}).get("text_snapshot"),
      "· tier", (p or {}).get("tier"))
win.action_cancel()
print("esc: armed ->", f.armed(view, win.cursor), "· anchor", win._word_anchor)
print("overlays unchanged:", view.overlay_count)
win._leave_lane()
win.close()
app.processEvents()
print("PROBE OK")
