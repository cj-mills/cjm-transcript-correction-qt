"""Console-script driver for the Qt shell: the SAME argument surface and
resolution ladder as every correction shell — build_parser and
resolve_settings imported from cjm_transcript_correction_core.launch (DEC
0f11683d; absorbed there by spine absorption 12f342f1), so the shells cannot
drift on which stack a correction session opens. Only the window in the
middle differs; there is no hand-off tail on this lane (quit = sidecar save
+ teardown, the donor's exit contract)."""

import sys

from cjm_substrate_qt_kit.theme import apply_theme
from cjm_transcript_correction_core.launch import build_parser, resolve_settings
from PySide6.QtWidgets import QApplication

from .app import CorrectionWindow


def main() -> int:  # Console-script entry point (cjm-transcript-correction-qt)
    """Resolve the shared launch surface, run the Qt correction window."""
    parser = build_parser()
    parser.prog = "cjm-transcript-correction-qt"
    args = parser.parse_args()
    s = resolve_settings(args)
    qapp = QApplication(sys.argv[:1])
    apply_theme(qapp)
    win = CorrectionWindow(args.graph_db_path, source=args.source,
                           manifests_dir=s["manifests_dir"],
                           rendition=args.rendition,
                           skeleton=args.skeleton,
                           actor=args.actor, autoplay=not args.no_autoplay,
                           audio_device=s["audio_device"],
                           resume=not args.no_resume,
                           shift_floor_s=s["shift_floor_s"],
                           nudge_step_ms=args.nudge_step_ms, lane=args.lane,
                           purpose=s["purpose"],
                           fa_cache_db=args.fa_cache_db)
    win.show()
    qapp.exec()
    return 0
