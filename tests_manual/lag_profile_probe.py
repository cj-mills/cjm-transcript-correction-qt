"""Offscreen per-gesture cost probe (user sighting 2026-09-02: ~0.87 s lag on
navigation / accept in the propose lane on the multi-hour Show 62 spine while
r/R stayed responsive). Opens the real spine headlessly, switches to the
propose lane, then times + profiles navigation frames. Reads only — no
gesture that commits is submitted.

Run from the transcription-core workspace:
  QT_QPA_PLATFORM=offscreen python tests_manual/lag_profile_probe.py "<source substring>" <skeleton-prefix> [lane]
"""
import cProfile
import os
import pstats
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
win = CorrectionWindow(DB, source=sys.argv[1], manifests_dir=os.path.join(WS, ".cjm", "manifests"),
                       skeleton=sys.argv[2], actor="agent:probe", autoplay=False,
                       purpose="feature-test")
lane = sys.argv[3] if len(sys.argv) > 3 else "propose"


def pump(cond, what, timeout=180.0):
    t0 = time.monotonic()
    while not cond():
        app.processEvents()
        time.sleep(0.02)
        if time.monotonic() - t0 > timeout:
            raise SystemExit(f"timeout waiting for {what}")


t0 = time.monotonic()
pump(lambda: win.stage == "correct" and win.view is not None, "spine open")
print(f"spine open in {time.monotonic() - t0:.1f}s:", win.view.source_title, "segments", win.view.size,
      "proposals", len(win.view.event_proposals or {}), "skeleton", (win.view.skeleton_hash or "")[-12:])
for _ in range(50): app.processEvents(); time.sleep(0.02)   # let the filter-lane read land (None when no set)
win.resize(1600, 900)
win.show()
app.processEvents()
win.lane = lane
win.cursor = min(200, win.view.size - 1)
win._render()
app.processEvents()
print("lane:", win.lane, "hitl visible:", win.hitl.isVisible())


def frame(fn, n=5):
    ts = []
    for _ in range(n):
        t = time.monotonic()
        fn()
        app.processEvents()
        ts.append(time.monotonic() - t)
    return ts


print("move(+1) x5 (s):", [f"{t:.3f}" for t in frame(lambda: win._move(1))])
print("render() x3 (s):", [f"{t:.3f}" for t in frame(lambda: win._render(), 3)])
if lane == "propose":
    print("render_event_hitl x3 (s):", [f"{t:.3f}" for t in frame(lambda: win._render_event_hitl(), 3)])
    print("paint_frame x3 (s):", [f"{t:.3f}" for t in frame(lambda: win._paint_frame(), 3)])

prof = cProfile.Profile()
prof.enable()
for _ in range(5):
    win._move(1)
    app.processEvents()
prof.disable()
st = pstats.Stats(prof)
st.sort_stats("cumulative")
print("\n=== top cumulative (5 moves) ===")
st.print_stats(28)
st.sort_stats("tottime")
print("\n=== top tottime ===")
st.print_stats(14)
win.close()
