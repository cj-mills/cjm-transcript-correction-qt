"""Console-script driver for the Qt shell: the SAME argument surface and
resolution ladder as cjm-transcript-correction-tui — build_parser and
resolve_settings imported from it (DEC 0f11683d), so the two shells cannot
drift on which stack a correction session opens. Only the window in the
middle differs; there is no hand-off tail on this lane (quit = sidecar save
+ teardown, the donor's exit contract)."""

import sys

from cjm_transcript_correction_tui.cli import build_parser, resolve_settings
from PySide6.QtWidgets import QApplication

from .app import CorrectionWindow


def main() -> int:  # Console-script entry point (cjm-transcript-correction-qt)
    """Resolve the shared launch surface, run the Qt correction window."""
    parser = build_parser()
    parser.prog = "cjm-transcript-correction-qt"
    args = parser.parse_args()
    s = resolve_settings(args)
    qapp = QApplication(sys.argv[:1])
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
