"""The Qt correction workbench: the same center-pinned segment walk, lane
vocabulary, and commit-then-echo gestures as cjm-transcript-correction-tui,
repainted on a monospace QTextBrowser canvas and handed the same sidecar
view-state contract — a DIRECT PORT (DEC 0f11683d; warts carry as captures,
never mid-port design litigation).

Shell shape: every stateful decision lives in the imported spine (SpineView +
the pure planners), in correction-core's commit vocabulary, or in
CorrectionShellSession, whose loop thread owns the graph stack and the seat.
This module materializes panes.py span lines into HTML, forwards the VERBATIM
key vocabulary through ONE stage+lane dispatcher (the check_action gate as a
table walk — Qt has no per-binding gate, so keys bound 2-4× resolve here),
and rides the inline QLineEdit editor the Textual shell used (two input modes
read the CARET as the semantic text cut — a modal could not carry that).

Async discipline (the c4b0d6e5 seam): gesture coroutines compose core commits
+ the SpineView local echo and resolve as loop-thread Futures landing here
through QUEUED Signals; the loop serializes them in submission order — the
same serial semantics Textual's message queue gave the donor. Audio: BOTH
decode paths ride SpanPlayer (chunk = model-input WAV span; seams, synthetic
inserts, proposals, overlays = the ORIGINAL media at source coordinates —
the ffmpeg-pipe/WSOLA/sounddevice stack retires). The playback ticker keeps
the wall-clock×speed position readout, with an explicit paint-generation
counter replacing the Textual content-receipt trick."""

import html
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cjm_context_graph_layer.journal import sidecar_journal_path
from cjm_substrate.core.workspace import resolve_workspace
from cjm_substrate_qt_kit.keyhints import hint_line, keycaps, KeyHintsOverlay
from cjm_substrate_qt_kit.player import SpanPlayer
from cjm_substrate_qt_kit.statusstrip import StatusStrip
from cjm_substrate_qt_kit.theme import make_font
from cjm_transcript_correction_core.cli import run_extract
from cjm_transcript_correction_core.graph import (commit_boundary_shift_correction,
                                                  commit_chunk_insert_correction,
                                                  commit_chunk_insert_removal,
                                                  commit_chunk_split_correction,
                                                  commit_chunk_split_removal,
                                                  commit_extraction_gate, commit_mark_correction,
                                                  commit_mark_dismissal, commit_prune_amendment,
                                                  commit_speaker_assign_correction,
                                                  commit_speaker_entity,
                                                  commit_speech_overlay_correction,
                                                  commit_speech_overlay_removal,
                                                  commit_text_correction,
                                                  commit_time_nudge_correction,
                                                  fa_words_for_transcript)
from cjm_transcript_correction_core.models import (ANNOTATE_LANE_ACTIONS, ANNOTATE_ONLY_ACTIONS,
                                                   ASSIGN_LANE_ACTIONS, ASSIGN_ONLY_ACTIONS,
                                                   NUDGE_STEPS_MS, NUDGE_TAIL_S,
                                                   PROPOSE_LANE_ACTIONS, PROPOSE_ONLY_ACTIONS,
                                                   RECOMMENDED_INSERT_LABELS,
                                                   RECOMMENDED_MARK_CLASSES,
                                                   RECOMMENDED_OVERLAY_LABELS, SPEEDS)
from cjm_transcript_correction_core.spine import (match_sources, neighbor_word_bound,
                                                  parse_entity_input, parse_mark_input,
                                                  plan_boundary_shift, plan_chunk_insert,
                                                  plan_chunk_split, plan_gate, plan_time_nudge,
                                                  resolve_mark_class_token, segment_word_tokens,
                                                  snap_word_span)
from cjm_transcript_correction_core.state import load_tui_state, save_tui_state, selector_for_spine
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLineEdit, QMainWindow, QTextBrowser, QVBoxLayout, QWidget

from . import panes
from .finetune_form import FinetuneFormDialog
from .session import adapter_config_schema, CorrectionShellSession

_KEYNAMES = {Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left",
             Qt.Key_Right: "right", Qt.Key_Tab: "tab", Qt.Key_Backtab: "shift+tab",
             Qt.Key_Escape: "escape", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
             Qt.Key_Space: "space", Qt.Key_PageUp: "pgup", Qt.Key_PageDown: "pgdn",
             Qt.Key_Home: "home", Qt.Key_End: "end"}

# Long-range stride for PgUp/PgDn (792d3ac6: page + top/bottom jump as standard
# options — the thousands-of-segments spine needs fast distant moves; folded-run
# skipping stays a |delta|==1 concern, so a page stride never fights the folds).
PAGE_STRIDE = 10


class CorrectionWindow(QMainWindow):
    """The correction loop under Qt — one window, the donor's stages/lanes."""

    stack_opened = Signal(object)    # loop-thread Future -> Qt thread (queued)
    sources_listed = Signal(object)
    statuses_done = Signal(object)
    spines_listed = Signal(object)
    spine_opened = Signal(object)
    gesture_done = Signal(object)    # every commit gesture resolves through here
    progress_note = Signal(str)      # loop-thread narration (extract log)
    finetune_done = Signal(object)   # finetune seat Future -> Qt thread

    def __init__(self, graph_db_path: Optional[str] = None,
                 *, source: Optional[str] = None,
                 manifests_dir: str = ".cjm/manifests",
                 rendition: Optional[str] = None,
                 skeleton: Optional[str] = None,
                 actor: str = "human",
                 autoplay: bool = True,
                 audio_device: Optional[object] = None,  # accepted for CLI parity; QMediaPlayer uses the default sink (captured wart)
                 resume: bool = True,
                 shift_floor_s: float = 0.0,
                 nudge_step_ms: Optional[float] = None,
                 lane: Optional[str] = None,
                 purpose: Optional[str] = None,
                 fa_cache_db: Optional[str] = None,
                 event_capability: str = "cjm-capability-pyannote"):
        super().__init__()
        self.setWindowTitle("cjm transcript correction (qt)")
        self.resize(1080, 780)
        self._open_kwargs = dict(source=source, manifests_dir=manifests_dir,
                                 rendition=rendition, skeleton=skeleton)
        self._spines: List[Dict[str, Any]] = []
        self._spine_source: Optional[Tuple[str, str]] = None
        self._graph_db_path = graph_db_path
        self._journal_path: Optional[object] = None
        self.stage = "select"
        self._graph_cap = "cjm-capability-graph-sqlite"
        self._sources: List[Tuple[str, str]] = []
        self._discovered = False   # discovery landed — the picker may paint
        self._status: Dict[str, Dict[str, int]] = {}
        self._purposes: Dict[str, Dict[str, int]] = {}
        self._datasets: List[Dict[str, Any]] = []
        self._flywheel_log: List[str] = []
        self._flywheel_return = "select"
        self._nav_browsing = False   # navigation began — pickers always show
        self._last_spine: Optional[Tuple[str, str, Optional[str]]] = None
        self._runs: List[Dict[str, Any]] = []    # training-run manifests
        self._fly_cursor = 0                     # flywheel dataset cursor
        self._finetune_busy = False
        self.event_capability = event_capability
        self._extract_busy = False
        self._purpose_vocab: List[str] = []
        self._include_purposes: set = {"genuine", "wordless-transfer"}
        self.view: Optional[Any] = None
        self.player: Optional[SpanPlayer] = None
        self.cursor = 0
        self.actor = actor
        self.purpose = purpose
        self.autoplay = autoplay
        self.speed = 1.0
        self.audio_device = audio_device
        self.session_id: Optional[str] = None
        self._marks: Dict[int, str] = {}
        self._mark_class = "suspect"
        self._insert_label = "inhale"
        self._overlay_label = "hesitation-marker"
        self._word_cursor = 0
        self._overlay_pick: Optional[str] = None
        self._word_anchor: Optional[int] = None
        self._fa_cache_arg = fa_cache_db
        self._fa_cache_db: Optional[Path] = None
        self._fa_words_cache: Dict[str, Optional[List[Dict[str, Any]]]] = {}
        self._input_mode = "edit"
        self._pending_proposal = None
        self._tick_info = None
        self._tick_claim = -1        # the paint generation the ticker owns
        self._status_gen = 0         # bumped by every status paint (the explicit receipt)
        self._hint_pins: Dict[str, Any] = {}   # per-scope pinned hint verbs (db-wide sidecar pref)
        self._editor_helper = ""     # the open editor's prompt (context slot while visible)
        self.lane = lane or "walk"
        self._lane_arg = lane
        self._entities: List[Dict[str, Any]] = []
        self._active_entity: Optional[str] = None
        self._accept_cluster: Optional[str] = None
        self._shift_busy = False
        self._last_shift = 0.0
        self.fold_wordless = False
        self._shift_floor = float(shift_floor_s)
        self._nudge_step_arg = nudge_step_ms
        self._nudge_step = 0.1
        self._nudge_busy = False
        self.resume = resume
        self._state_saved = 0.0
        self._build_widgets()
        self._build_menubar()
        self._build_key_table()
        self._wheel_accum = 0
        self._ticker = QTimer(self)
        self._ticker.setInterval(100)
        self._ticker.timeout.connect(self._tick)
        # Autoplay DEBOUNCE (drive-1 field find, a named divergence from the
        # donor's immediate-play: that contract was priced against
        # ChunkPlayer's single persistent PortAudio stream, where churn was a
        # buffer swap. QMediaPlayer restarts the FFmpeg pipeline into the
        # sink per play, and a navigation-speed storm of stream starts
        # DISTORTS THE PIPEWIRE SINK DEVICE-WIDE until it reconnects. So
        # navigation stops audio at once and only the SETTLED segment plays;
        # r / speed steps / gesture replays stay immediate.)
        self._autoplay_timer = QTimer(self)
        self._autoplay_timer.setSingleShot(True)
        self._autoplay_timer.setInterval(150)
        self._autoplay_timer.timeout.connect(self._play_cursor)
        self.stack_opened.connect(self._on_stack_opened)
        self.sources_listed.connect(self._on_sources_listed)
        self.statuses_done.connect(self._on_statuses_done)
        self.spines_listed.connect(self._on_spines_listed)
        self.spine_opened.connect(self._on_spine_opened)
        self.gesture_done.connect(self._on_gesture_done)
        self.progress_note.connect(self._on_progress_note)
        self.finetune_done.connect(self._on_finetune_done)
        self.sess = CorrectionShellSession(manifests_dir,
                                           graph_capability=self._graph_cap)
        self.sess.start()
        self._paint_status("opening graph stack…")
        fut = self.sess.open_stack(graph_db_path)
        fut.add_done_callback(self.stack_opened.emit)

    # ---- widgets + geometry ---------------------------------------------

    def _build_widgets(self) -> None:
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self.cards = QTextBrowser()
        self.cards.setReadOnly(True)
        self.cards.setFocusPolicy(Qt.NoFocus)
        self.cards.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cards.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cards.setFont(make_font(kind="mono"))
        self.cards.viewport().installEventFilter(self)
        self.editor = QLineEdit()
        self.editor.setVisible(False)
        self.editor.returnPressed.connect(self._on_editor_submitted)
        self.strip = StatusStrip()
        self.strip.set_readout("loading spine…")
        self.hints_overlay = KeyHintsOverlay(
            self, on_pins_changed=self._on_pins_changed)
        self.finetune_form = FinetuneFormDialog(
            self, on_launch=self._launch_finetune)
        lay.addWidget(self.cards, 1)
        lay.addWidget(self.editor)
        lay.addWidget(self.strip)
        self.setCentralWidget(central)

    def _cells(self) -> Tuple[int, int]:
        fm = self.cards.fontMetrics()
        cw = max(1, fm.horizontalAdvance("M"))
        lh = max(1, fm.lineSpacing())
        vp = self.cards.viewport()
        return (max(20, vp.width() // cw), max(3, vp.height() // lh))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.view is not None or self.stage in ("select", "spine", "flywheel"):
            self._render()

    def focusNextPrevChild(self, next_: bool) -> bool:
        return False   # tab is a LANE key, never a focus move (priority=True port)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.cards.viewport() and event.type() == QEvent.Wheel:
            # One cursor move per 120-unit wheel NOTCH (drive-1 field find:
            # high-resolution wheels emit several sub-notch events per detent,
            # and a per-event move both broke the wheel-moves-1 contract
            # (2bc3bd6b) and amplified the autoplay churn storm).
            self._wheel_accum += event.angleDelta().y()
            while self._wheel_accum >= 120:
                self._wheel_accum -= 120
                self._move(-1)
            while self._wheel_accum <= -120:
                self._wheel_accum += 120
                self._move(1)
            return True
        if (obj is self.cards.viewport()
                and event.type() == QEvent.MouseButtonPress):
            if event.button() == Qt.BackButton:
                self.action_back()
                return True
            if event.button() == Qt.ForwardButton:
                self.action_forward()
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        # Window chrome (strip, margins): the same mouse nav as the cards
        # (the 5d9ca1f8 universal — back/forward buttons navigate).
        if event.button() == Qt.BackButton:
            self.action_back()
            return
        if event.button() == Qt.ForwardButton:
            self.action_forward()
            return
        super().mousePressEvent(event)

    # ---- painting --------------------------------------------------------

    def _paint_status(self, text: str) -> None:
        """Action results land in the strip's persistent-readout slot
        (DEC 2a42c028): they persist until superseded and never evict the
        chips or the hint line. The generation counter still arbitrates
        readout ownership (the ticker-yield contract)."""
        self._status_gen += 1
        self.strip.set_readout(text)

    def _pin_scope(self) -> str:
        """Pins are per stage on the pickers/flywheel, per lane on a spine."""
        return self.stage if self.stage in ("select", "spine",
                                            "flywheel") else self.lane

    def _lane_pins(self) -> List[str]:
        return list(self._hint_pins.get(self._pin_scope())
                    or panes.default_pins(self))

    def _on_pins_changed(self, pins: List[str]) -> None:
        """The overlay's pin gesture: persist the scope's pin set (db-wide
        sidecar pref) and refresh the hint line."""
        self._hint_pins[self._pin_scope()] = list(pins)
        if self.view is not None and self._graph_db_path:
            save_tui_state(self._graph_db_path, self.view.source_id, None,
                           hint_pins=self._hint_pins)
        self._paint_frame()

    def _paint_frame(self) -> None:
        """Chips + hint line + overlay model for the current stage/lane —
        the identity/position half of the old status line; the readout slot
        is deliberately untouched."""
        if self.stage == "select":
            chips = [("context", panes.picker_status_chip(self))]
        elif self.stage == "spine":
            chips = [("context", "pick a spine (choice persists)")]
        elif self.stage == "flywheel":
            chips = [("context", panes.flywheel_status_chip(self))]
        elif self.view is not None and self.view.size:
            chips = panes.status_chips(self)
        else:
            chips = []
        self.strip.set_chips(chips)
        entries = panes.hint_entries(self)
        self.strip.set_hints(hint_line(entries, self._lane_pins()))
        self.hints_overlay.set_entries(entries)
        self.hints_overlay.pins = self._lane_pins()
        # The CONTEXT slot derives like the chips (drive verdict 2026-08-25):
        # the editor's helper prompt while the editor is open, else the
        # active lane's pick menu — full-width and word-wrapped, so the
        # variable-length vocabularies never fight the readout for space.
        if self.editor.isVisible() and self._editor_helper:
            context = self._editor_helper
        elif self.stage == "correct" and self.view is not None \
                and self.view.size and self.lane == "assign":
            menu = self._assign_menu()
            context = ("speakers: "
                       + " · ".join(f"{i + 1}:{nm}"
                                    for i, (_, nm) in enumerate(menu[:9]))
                       + " · A new") if menu else "speakers: none yet · A new"
        elif self.stage == "correct" and self.view is not None \
                and self.view.size and self.lane == "annotate":
            menu = self._overlay_label_menu()
            context = ("◈ " + self._overlay_label + " · "
                       + " ".join(f"{i + 1}:{c}"
                                  for i, c in enumerate(menu[:9]))
                       + (" · …" if len(menu) > 9 else "") + " · A other")
        else:
            context = ""
        self.strip.set_context(self._context_rich(context) if context else "")

    def _context_rich(self, text: str) -> str:
        """Context-row rich text: pickable tokens wear the overlay's key-cap
        grammar (kit keycaps) — N:label picks and the bare -/A gesture
        tokens; everything else, user-minted names included, is escaped."""
        out = []
        for tok in html.escape(text, quote=False).split(" "):
            head, sep, rest = tok.partition(":")
            if sep and head.isdigit() and rest:
                out.append(keycaps(head) + " " + rest)
            elif tok in ("-", "A"):
                out.append(keycaps(tok))
            else:
                out.append(tok)
        return " ".join(out)

    def _render(self) -> None:
        width, height = self._cells()
        if self.stage == "select":
            if not self._discovered:
                return   # boot ladder still running — keep the loading status
            self.cards.setHtml(panes.lines_to_html(panes.picker_lines(self, width)))
            self._paint_frame()
            return
        if self.stage == "spine":
            self.cards.setHtml(panes.lines_to_html(
                panes.spine_picker_lines(self, width)))
            self._paint_frame()
            return
        if self.stage == "flywheel":
            self.cards.setHtml(panes.lines_to_html(
                panes.flywheel_lines(self, width)))
            self._paint_frame()
            return
        view = self.view
        if view is None:
            return
        if not view.size:
            self._paint_frame()
            self._paint_status(f"{view.source_title}  ·  empty spine")
            return
        self.cards.setHtml(panes.lines_to_html(
            panes.render_rows(self, width, height)))
        self._paint_frame()

    # ---- the boot ladder (the Textual on_mount, future-chained) ----------

    def _on_stack_opened(self, fut) -> None:
        try:
            res = fut.result()
        except Exception as e:
            self._paint_status(f"⚠ graph stack failed: {e}")
            return
        self._graph_db_path = res["db"]
        self._journal_path = sidecar_journal_path(res["db"])
        self.player = SpanPlayer(self)
        f = self.sess.list_sources()
        f.add_done_callback(self.sources_listed.emit)

    def _on_sources_listed(self, fut) -> None:
        try:
            sources = fut.result()
        except Exception as e:
            self._paint_status(f"⚠ source listing failed: {e}")
            return
        picked = match_sources(sources, self._open_kwargs["source"])
        if len(picked) == 1 and not self._nav_browsing:
            self._open_source(*picked[0])
            return
        # 2ce81638 discovery: no unique --source -> browse the graph's Sources.
        self._sources = picked if len(picked) > 1 else sources
        self._paint_status("reading correction status…")
        f = self.sess.statuses([sid for sid, _ in self._sources])
        f.add_done_callback(self.statuses_done.emit)

    def _on_statuses_done(self, fut) -> None:
        try:
            res = fut.result()
        except Exception as e:
            self._paint_status(f"⚠ status read failed: {e}")
            return
        self._status = res["status"]
        self._purposes = res["purposes"]
        self._discovered = True
        self.cursor = 0
        self._render()
        self._paint_status("")   # picker landing claims the readout (f27f2b99)

    def _open_source(self, source_id: str, title: str) -> None:
        """Resolve WHICH skeleton spine first (DEC f1024568): one spine (or an
        explicit --skeleton) opens directly; coexisting spines ALWAYS show the
        picker, sidecar choice pre-positioning the cursor."""
        self._paint_status(f"opening {title or source_id[:12]}…")
        self._spine_source = (source_id, title)
        f = self.sess.list_spines(source_id, self._open_kwargs["rendition"])
        f.add_done_callback(self.spines_listed.emit)

    def _on_spines_listed(self, fut) -> None:
        try:
            spines = fut.result()
        except Exception as e:
            self._paint_status(f"⚠ spine listing failed: {e}")
            return
        selector = self._open_kwargs["skeleton"]
        sid, title = self._spine_source
        if self._nav_browsing or (selector is None and len(spines) > 1):
            saved = load_tui_state(self._graph_db_path).get(sid) or {}
            last = str(saved.get("skeleton") or "")
            self._spines = spines
            self.stage = "spine"
            self.cursor = next((i for i, sp in enumerate(spines)
                                if selector_for_spine(sp) == last), 0)
            self._render()
            self._paint_status("")   # picker landing claims the readout
            return
        self._open_spine(sid, title, selector)

    def _open_spine(self, source_id: str, title: str,
                    skeleton: Optional[str]) -> None:
        self._last_spine = (source_id, title, skeleton)
        self._paint_status(f"opening spine · {title or source_id[:12]}…")
        f = self.sess.open_spine(source_id, title,
                                 rendition=self._open_kwargs["rendition"],
                                 skeleton=skeleton,
                                 journal_path=self._journal_path,
                                 purpose=self.purpose)
        f.add_done_callback(self.spine_opened.emit)

    def _on_spine_opened(self, fut) -> None:
        try:
            res = fut.result()
        except Exception as e:
            self._paint_status(f"⚠ spine open failed: {e}")
            return
        self.view = res["view"]
        self.session_id = res["session_id"]
        self._entities = res["entities"]
        self.stage = "correct"
        state = load_tui_state(self._graph_db_path)
        try:
            self.speed = float(state.get("_speed") or 1.0)
        except (TypeError, ValueError):
            self.speed = 1.0
        try:
            saved_ms = float(state.get("_nudge_step_ms") or 0.0)
        except (TypeError, ValueError):
            saved_ms = 0.0
        step_ms = (float(self._nudge_step_arg) if self._nudge_step_arg is not None
                   else (saved_ms if saved_ms > 0 else 100.0))
        self._nudge_step = step_ms / 1000.0
        mc = str(state.get("_mark_class") or "suspect")
        self._mark_class = mc if mc[:1].isalnum() else "suspect"
        il = str(state.get("_insert_label") or "inhale")
        self._insert_label = il if il[:1].isalnum() else "inhale"
        saved_lane = str(state.get("_lane") or "")
        self.lane = self._lane_arg or (saved_lane if saved_lane in
                                       ("walk", "assign", "annotate") else "walk")
        ol = str(state.get("_overlay_label") or "hesitation-marker")
        self._overlay_label = ol if ol[:1].isalnum() else "hesitation-marker"
        self._fa_cache_db = self._resolve_fa_cache()
        self._fa_words_cache = {}
        self._word_cursor, self._word_anchor = 0, None
        self.fold_wordless = bool(state.get("_fold_wordless") or False)
        pins = state.get("_hint_pins")
        self._hint_pins = dict(pins) if isinstance(pins, dict) else {}
        self._active_entity = None
        self.cursor = 0
        if self.resume:
            saved = state.get(self.view.source_id)
            if saved and self.view.size:
                self.cursor = max(0, min(self.view.size - 1,
                                         int(saved.get("cursor", 0))))
        self._paint_status("")   # lane landing claims the readout
        self._render()
        if self.autoplay:
            self._play_cursor()

    # ---- key dispatch (the check_action gate as a table walk) ------------

    def _build_key_table(self) -> None:
        t: Dict[str, List[Tuple[str, Any]]] = {}

        def add(key, action, fn):
            t.setdefault(key, []).append((action, fn))

        for k in ("j", "down", "s"):
            add(k, "next", lambda: self._move(1))
        for k in ("k", "up", "w"):
            add(k, "prev", lambda: self._move(-1))
        # Long-range nav (792d3ac6): page + top/bottom jump ride the next/prev
        # ACTION names, so lane legality is exactly the walk's — one gate, no
        # new core vocabulary. _move clamps on every stage.
        add("pgdn", "next", lambda: self._move(PAGE_STRIDE))
        add("pgup", "prev", lambda: self._move(-PAGE_STRIDE))
        add("end", "next", lambda: self._move(10**9))
        add("home", "prev", lambda: self._move(-10**9))
        add("r", "replay", self._play_cursor)
        add("g", "seam_next", lambda: self._audition_seam(1))
        add("G", "seam_prev", lambda: self._audition_seam(-1))
        add(",", "nudge_end_earlier", lambda: self._nudge("end", -1))
        add(".", "nudge_end_later", lambda: self._nudge("end", 1))
        add("<", "nudge_start_earlier", lambda: self._nudge("start", -1))
        add(">", "nudge_start_later", lambda: self._nudge("start", 1))
        add(",", "overlay_nudge", lambda: self._overlay_nudge("end", -1))
        add(".", "overlay_nudge", lambda: self._overlay_nudge("end", 1))
        add("<", "overlay_nudge", lambda: self._overlay_nudge("start", -1))
        add(">", "overlay_nudge", lambda: self._overlay_nudge("start", 1))
        add("{", "nudge_step_down", lambda: self._step_nudge(-1))
        add("}", "nudge_step_up", lambda: self._step_nudge(1))
        add("[", "speed_down", lambda: self._step_speed(-1))
        add("]", "speed_up", lambda: self._step_speed(1))
        add("i", "insert_chunk", lambda: self._submit_gesture(self._do_insert_chunk(None)))
        add("I", "insert_labeled", self.action_insert_labeled)
        add("L", "relabel_insert", self.action_relabel_insert)
        add("x", "remove_insert", lambda: self._submit_gesture(self._do_remove_insert()))
        add("x", "overlay_remove", lambda: self._submit_gesture(self._do_overlay_remove()))
        add("S", "split_chunk", self.action_split_chunk)
        add("e", "edit", self.action_edit)
        add("y", "yank", self.action_yank)
        add("right", "shift_push", lambda: self._shift("push"))
        add("d", "shift_push", lambda: self._shift("push"))
        add("left", "shift_pull", lambda: self._shift("pull"))
        add("a", "shift_pull", lambda: self._shift("pull"))
        add("right", "word_right", lambda: self._word_move(1))
        add("left", "word_left", lambda: self._word_move(-1))
        add("a", "assign_accept", lambda: self._submit_gesture(self._do_assign_accept()))
        add("a", "propose_accept", self.action_propose_accept)
        add("tab", "cycle_lane", self.action_cycle_lane)
        add("shift+tab", "cycle_lane_prev", self.action_cycle_lane_prev)
        add("space", "assign_same", lambda: self._submit_gesture(self._do_assign_same()))
        add("space", "annotate_quick", self.action_annotate_quick)
        add("A", "assign_new", self.action_assign_new)
        add("A", "annotate_editor", self.action_annotate_editor)
        for d in range(1, 10):
            add(str(d), "assign_pick",
                lambda n=d: self._submit_gesture(self._do_assign_pick(n)))
            add(str(d), "annotate_pick", lambda n=d: self.action_annotate_pick(n))
            add(str(d), "purpose_pick", lambda n=d: self.action_purpose_pick(n))
        add("n", "propose_next", lambda: self._jump_proposal(1))
        add("N", "propose_prev", lambda: self._jump_proposal(-1))
        add("n", "next_overlay",
            lambda: self._jump_glyph(1, self.view.overlay_ids, "◈ annotated"))
        add("N", "prev_overlay",
            lambda: self._jump_glyph(-1, self.view.overlay_ids, "◈ annotated"))
        add("n", "next_mark",
            lambda: self._jump_glyph(1, self.view.marked_ids, "⚑ marked"))
        add("N", "prev_mark",
            lambda: self._jump_glyph(-1, self.view.marked_ids, "⚑ marked"))
        add("R", "propose_audition", self.action_propose_audition)
        add("R", "annotate_audition",
            lambda: self._submit_gesture(self._do_annotate_audition()))
        add("t", "toggle_tier2", self.action_toggle_tier2)
        add("h", "word_left", lambda: self._word_move(-1))
        add("l", "word_right", lambda: self._word_move(1))
        add("v", "word_select", self.action_word_select)
        add("o", "overlay_cycle", lambda: self.action_overlay_cycle(1))
        add("O", "overlay_cycle", lambda: self.action_overlay_cycle(-1))
        add("m", "mark_quick",
            lambda: self._submit_gesture(self._do_mark_quick()))
        add("b", "mark_boundary",
            lambda: self._submit_gesture(self._do_mark_boundary()))
        add("M", "mark_editor", self.action_mark_editor)
        add("p", "next_prune",
            lambda: self._jump_glyph(1, self.view.pruned_ids, "✂ pruned"))
        add("P", "prev_prune",
            lambda: self._jump_glyph(-1, self.view.pruned_ids, "✂ pruned"))
        add("W", "gate_editor", self.action_gate_editor)
        add("F", "flywheel_page", self.action_flywheel_page)
        add("X", "extract_dataset", self.action_extract_dataset)
        add("T", "train_dataset", self.action_train_dataset)
        add("enter", "open_source", self.action_open_source)
        add("z", "toggle_wordless_fold", self.action_toggle_wordless_fold)
        add("escape", "cancel", self.action_cancel)
        add("escape", "back", self.action_back)
        add("B", "back", self.action_back)
        add("q", "quit_app", self.close)
        self._key_table = t

    def _allowed(self, action: str) -> bool:
        """The check_action gate, verbatim (one data table, one gate —
        DEC cc55a7b5): stage gates the pickers/flywheel, the ACTIVE LANE
        scopes the walk vocabulary."""
        if self.stage == "select":
            return action in ("next", "prev", "open_source", "flywheel_page",
                              "back", "quit_app")
        if self.stage == "spine":
            return action in ("next", "prev", "open_source", "flywheel_page",
                              "back", "quit_app")
        if self.stage == "flywheel":
            return action in ("flywheel_page", "extract_dataset", "purpose_pick",
                              "train_dataset", "next", "prev",
                              "back", "quit_app")
        if action in ("back", "flywheel_page"):
            return True   # shell navigation — lane-universal (f27f2b99),
                          # never core lane vocabulary
        if self.lane == "assign":
            return action in ASSIGN_LANE_ACTIONS
        if self.lane == "propose":
            return action in PROPOSE_LANE_ACTIONS
        if self.lane == "annotate":
            return action in ANNOTATE_LANE_ACTIONS
        return action not in (ASSIGN_ONLY_ACTIONS | PROPOSE_ONLY_ACTIONS
                              | ANNOTATE_ONLY_ACTIONS)

    def keyPressEvent(self, event) -> None:
        if event.text() == "?":
            # Universal, gate-free by design (DEC 2a42c028): the overlay is
            # available on every stage/lane; it re-points at the live model
            # in _paint_frame, so open is just a toggle.
            self.hints_overlay.toggle()
            return
        name = _KEYNAMES.get(event.key())
        if name is None:
            text = event.text()
            name = text if text and text.isprintable() and text != " " else None
        if name is None:
            super().keyPressEvent(event)
            return
        for action, fn in self._key_table.get(name, ()):
            if self._allowed(action):
                fn()
                return
        super().keyPressEvent(event)

    # ---- gesture submission ----------------------------------------------

    def _submit_gesture(self, coro) -> None:
        """One commit gesture: the coroutine runs core commits + the local
        echo on the loop, serialized TO COMPLETION in submission order (the
        session's gesture lock — the Textual message-queue semantics),
        resolves to {"status", "play", …}, and the done slot repaints +
        sounds the instruction."""
        fut = self.sess.run_serial(coro)
        fut.add_done_callback(self.gesture_done.emit)

    def _on_gesture_done(self, fut) -> None:
        try:
            res = fut.result() or {}
        except Exception as e:
            self._render()
            self._paint_status(f"⚠ {e}")
            return
        if res.get("advance"):
            self._move(int(res["advance"]))   # the assign-and-walk gesture
        self._render()
        if res.get("editor"):
            mode, value = res["editor"]       # the a-gesture's editor hop
            self._open_editor(mode, value, status=res.get("status"))
            return
        status = res.get("status")
        play = res.get("play")
        if status and res.get("status_first"):
            # The donor's insert ordering: status painted BEFORE the play, so
            # the ticker claims the fresh line and the ▶ readout stays live
            # (every other play-then-status gesture leaves its status the
            # winner — the nudge ⏱ contract).
            self._paint_status(status)
            status = None
        if play:
            kind = play[0]
            if kind == "cursor":
                self._play_cursor()
            elif kind == "span":
                _, start_s, end_s, note = play
                self._play_span_source(start_s, end_s, note=note)
            elif kind == "chunk_tail":
                c = self.view.chunk(play[1])   # the NUDGED segment, not the live cursor
                if c is None:
                    self.player.stop()
                else:
                    tail = max(c.start_s, c.end_s - NUDGE_TAIL_S)
                    self.player.play_span(c.wav_path, tail, c.end_s,
                                          rate=self.speed)
        if status:
            self._paint_status(status)

    def _on_progress_note(self, text: str) -> None:
        if self.stage == "flywheel":
            self._render()
        if text:
            self._paint_status(text)

    # ---- playback (SpanPlayer both paths) + the ticker -------------------

    def _start_ticker(self, start_s: float, end_s: float, note: str = "") -> None:
        """Live playback-position readout: position derives from wall-clock ×
        speed (identical on both decode paths — the donor's math). Ownership
        rides an explicit paint-generation counter: any other gesture's status
        paint bumps the generation and the ticker yields (the content-receipt
        trick, made explicit — DEC 0f11683d)."""
        self._tick_info = (time.monotonic(), start_s, end_s, note, self.speed)
        self._tick_claim = self._status_gen
        self._ticker.start()

    def _stop_ticker(self) -> None:
        self._ticker.stop()
        self._tick_info = None

    def _tick(self) -> None:
        if self._tick_info is None:
            self._stop_ticker()
            return
        if self._status_gen != self._tick_claim:
            self._stop_ticker()   # another gesture owns the line — yield
            return
        t0, start_s, end_s, note, speed = self._tick_info
        cur = start_s + (time.monotonic() - t0) * speed
        if cur >= end_s:
            self._stop_ticker()
            # Persistent-readout class (DEC 2a42c028): the played-span readout
            # stays until the next action supersedes it — that readout IS the
            # point of replay feedback.
            self._paint_status(f"■ played {start_s:.2f}–{end_s:.2f}s{note}")
            return
        self._paint_status(f"▶ {cur:.2f}s · span {start_s:.2f}–{end_s:.2f}s{note}"
                           " · esc stops")
        self._tick_claim = self._status_gen

    def _play_cursor(self) -> None:
        if self.view is None or not self.view.size:
            return
        seg = self.view.segments[self.cursor]
        note = ""
        if self.lane == "propose":
            props = self.view.event_proposals.get(seg.id)
            if props:
                p = props[0]
                note = (f" · ?{p.get('label')} {float(p['start_time']):.2f}"
                        f"–{float(p['end_time']):.2f}s")
        if seg.id in self.view.inserted_ids:
            # Synthetic chunk: its audio may exist ONLY in the original source.
            self.player.stop()
            self._stop_ticker()
            if seg.start_time is not None and seg.end_time is not None \
                    and float(seg.end_time) - float(seg.start_time) >= 0.02:
                self._play_span_source(float(seg.start_time),
                                       float(seg.end_time), note=note)
            return
        c = self.view.chunk(self.cursor)
        if c is None:
            self.player.stop()
            self._stop_ticker()
            return
        self.player.play_span(c.wav_path, c.start_s, c.end_s, rate=self.speed)
        if seg.start_time is not None and seg.end_time is not None:
            self._start_ticker(float(seg.start_time), float(seg.end_time), note)

    def _play_span_source(self, start_s: float, end_s: float,
                          note: str = "") -> None:
        """Play a source-coordinate span of the ORIGINAL media — direct
        QMediaPlayer file-span playback (the ffmpeg decode retires)."""
        path = self.view.source_path
        if not path or not Path(path).exists():
            self._paint_status(f"insert audio: source media not found "
                               f"({path or 'no path on Source'})")
            return
        self.player.play_span(path, start_s, end_s, rate=self.speed)
        err = self.player.error_text()
        if err:
            self._paint_status(f"playback unavailable: {err}")
            return
        self._start_ticker(start_s, end_s, note)

    def _audition_seam(self, direction: int) -> None:
        """g/G: play the SOURCE audio across the boundary after/before the
        cursor segment — context tail + the whole gap + context head. Under
        QMediaPlayer this is a direct span play of the original media."""
        ref = self.view.seam(self.cursor, direction)
        if ref is None:
            self._paint_status("seam audio: no neighbor segment in that direction")
            return
        path = self.view.source_path
        if not path or not Path(path).exists():
            self._paint_status(f"seam audio: source media not found "
                               f"({path or 'no path on Source'})")
            return
        self.player.stop()
        self.player.play_span(path, ref.start_s, ref.end_s, rate=self.speed)
        segs = self.view.segments
        self._paint_status(
            f"♪ seam #{segs[ref.left].index}|#{segs[ref.right].index}:"
            f" source {ref.start_s:.1f}–{ref.end_s:.1f}s"
            f" (gap {ref.gap_s:+.2f}s) · esc stops")

    # ---- movement + sidecar ---------------------------------------------

    def _move(self, delta: int) -> None:
        if self.stage == "select":
            if self._sources:
                self.cursor = max(0, min(len(self._sources) - 1,
                                         self.cursor + delta))
                self._render()
            return
        if self.stage == "spine":
            if self._spines:
                self.cursor = max(0, min(len(self._spines) - 1,
                                         self.cursor + delta))
                self._render()
            return
        if self.stage == "flywheel":
            total = len(self._datasets) + len(self._runs)
            if total:
                self._fly_cursor = max(0, min(total - 1,
                                              self._fly_cursor + delta))
                self._render()
            return
        if self.view is None:
            return
        new = max(0, min(self.view.size - 1, self.cursor + delta))
        if abs(delta) == 1 and panes.folded(self, new):
            probe = new
            while 0 <= probe < self.view.size and panes.folded(self, probe):
                probe += delta
            new = probe if 0 <= probe < self.view.size else self.cursor
        if new == self.cursor:
            return
        self.cursor = new
        self._word_cursor, self._word_anchor = 0, None
        self._overlay_pick = None
        now = time.monotonic()
        if now - self._state_saved > 1.0:
            save_tui_state(self._graph_db_path, self.view.source_id, new)
            self._state_saved = now
        self._render()
        if self.autoplay:
            # stale audio must not ride the new focus; the debounced timer
            # plays the segment the walk SETTLES on (see __init__)
            if self.player is not None:
                self.player.stop()
            self._stop_ticker()
            self._autoplay_timer.start()

    def _jump_glyph(self, direction: int, ids: set, what: str) -> None:
        view = self.view
        if not ids:
            self._paint_status(f"no {what} segments on this source")
            return
        for step in range(1, view.size + 1):
            j = (self.cursor + direction * step) % view.size
            if view.segments[j].id in ids:
                self._move(j - self.cursor)
                return

    # ---- nudges / speed / shift ------------------------------------------

    def _step_nudge(self, delta: int) -> None:
        cur = self._nudge_step * 1000.0
        i = min(range(len(NUDGE_STEPS_MS)),
                key=lambda j: abs(NUDGE_STEPS_MS[j] - cur))
        ms = NUDGE_STEPS_MS[max(0, min(len(NUDGE_STEPS_MS) - 1, i + delta))]
        self._nudge_step = ms / 1000.0
        save_tui_state(self._graph_db_path, self.view.source_id, self.cursor,
                       nudge_step_ms=ms)
        self._paint_status(f"nudge step: {ms:g} ms")

    def _step_speed(self, delta: int) -> None:
        i = min(range(len(SPEEDS)), key=lambda j: abs(SPEEDS[j] - self.speed))
        self.speed = SPEEDS[max(0, min(len(SPEEDS) - 1, i + delta))]
        save_tui_state(self._graph_db_path, self.view.source_id, self.cursor,
                       speed=self.speed)
        self._render()
        self._play_cursor()

    def _nudge(self, edge: str, sign: int) -> None:
        if self._nudge_busy:
            return
        self._nudge_busy = True
        try:
            self._submit_gesture(self._do_nudge(edge, sign))
        except Exception:
            self._nudge_busy = False   # a submit that never runs must not latch
            raise

    async def _do_nudge(self, edge: str, sign: int):
        """,/. (cursor END) and </> (cursor START): nudge a boundary TIME by
        ±the ladder step, then replay so the ear verifies at once (welded
        point cuts move both edges atomically via plan_time_nudge)."""
        try:
            view, i = self.view, self.cursor
            delta = sign * self._nudge_step
            plan = plan_time_nudge(view.segments, i, edge, delta)
            if plan is None:
                return {"status": f"nudge: refused ({edge} {delta:+.3f}s — "
                                  "missing times, or a segment would collapse)"}
            segs = view.segments
            if edge == "end":
                left_t = segs[i].text
                right_t = segs[i + 1].text if i + 1 < view.size else ""
            else:
                left_t = segs[i - 1].text if i > 0 else ""
                right_t = segs[i].text
            words = {"left": (left_t.split() or [None])[-1],
                     "right": (right_t.split() or [None])[0]}
            await commit_time_nudge_correction(
                view.queue, view.graph_id, view.source_id, plan,
                self.session_id, boundary_words=words, step_s=delta,
                actor=self.actor, journal_path=self._journal_path)
            by_id = {s.id: s for s in segs}
            for e in plan:
                s = by_id[e["segment_id"]]
                if e["edge"] == "start":
                    s.start_time = e["new_time"]
                else:
                    s.end_time = e["new_time"]
            e0 = plan[0]
            welded = " ⚭" if len(plan) > 1 else ""
            status = (f"⏱ #{segs[i].index} {e0['edge']} "
                      f"{e0['old_time']:.2f}→{e0['new_time']:.2f}s"
                      f" ({delta:+.3f}s){welded} · replaying segment")
            if segs[i].id in view.inserted_ids:
                play: Tuple = ("cursor",)
            elif edge == "end":
                play = ("chunk_tail", i)
            else:
                play = ("cursor",)
            return {"status": status, "play": play}
        finally:
            self._nudge_busy = False

    def _shift(self, direction: str) -> None:
        now = time.monotonic()
        if self._shift_busy or now - self._last_shift < self._shift_floor:
            return   # busy commit OR inside the paint-rate floor — drop the repeat
        self._shift_busy = True
        try:
            self._submit_gesture(self._do_shift(direction))
        except Exception:
            self._shift_busy = False   # a submit that never runs must not latch
            raise

    async def _do_shift(self, direction: str):
        """One ←/→ press: move ONE word across the boundary after the cursor
        (wordless inserts hopped, word-bearing inserts + aseg seams refuse)."""
        try:
            view, i = self.view, self.cursor
            if i + 1 >= view.size:
                return {"status": "boundary shift: no segment after the cursor"}
            if view.segments[i].id in view.inserted_ids:
                return {"status": "boundary shift: ✋ inserted chunk — its text "
                                  "lives on the overlay (e edits it)"}
            j = i + 1
            while j < view.size and panes.wordless_insert(view, j):
                j += 1
            if j >= view.size:
                return {"status": "boundary shift: no layer-0 segment after the cursor"}
            if view.segments[j].id in view.inserted_ids:
                return {"status": "boundary shift: ✋ word-bearing insert between — "
                                  "its text lives on the overlay (e edits it)"}
            if view.aseg_index(i) != view.aseg_index(j):
                return {"status": "boundary shift: ✋ audio-segment seam — text "
                                  "stays within its audio segment"}
            left, right = view.segments[i], view.segments[j]
            plan = plan_boundary_shift(left.text, right.text, direction)
            if plan is None:
                return {"status": f"boundary shift: nothing to {direction}"}
            moved, new_left, new_right = plan
            await commit_boundary_shift_correction(
                view.queue, view.graph_id, view.source_id, left.id, right.id,
                moved, direction, self.session_id, actor=self.actor,
                journal_path=self._journal_path)
            receiver = right if direction == "push" else left
            if receiver.id in view.pruned_ids:
                prior = view.prune_correction_for(receiver.id)
                if prior is not None:
                    amended = await commit_prune_amendment(
                        view.queue, view.graph_id, prior, [receiver.id],
                        self.session_id, actor=self.actor,
                        journal_path=self._journal_path)
                    view.unprune_local(prior["id"], amended)
            left.text, right.text = new_left, new_right
            self._marks[i] = "corrected"
            self._marks[j] = "corrected"
            return {}
        finally:
            self._last_shift = time.monotonic()
            self._shift_busy = False

    # ---- yank / edit / editor plumbing -----------------------------------

    def action_yank(self) -> None:
        seg = self.view.segments[self.cursor]
        QGuiApplication.clipboard().setText(seg.text)
        self._paint_status(f"copied segment #{seg.index} text "
                           f"({len(seg.text)} chars, clipboard)")

    def _open_editor(self, mode: str, value: str, caret: Optional[int] = None,
                     status: Optional[str] = None) -> None:
        self._input_mode = mode
        self.editor.setText(value)
        self.editor.setVisible(True)
        self.editor.setFocus()
        if caret is not None:
            self.editor.setCursorPosition(caret)
        # Editor prompts are mode-scoped context, not readout traffic — they
        # ride the full-width context slot until the editor closes.
        self._editor_helper = status or ""
        self._paint_frame()

    def _close_editor(self) -> None:
        self.editor.setVisible(False)
        self.editor.clearFocus()
        self.cards.setFocus(Qt.OtherFocusReason)  # keys land in keyPressEvent again
        self.setFocus(Qt.OtherFocusReason)
        self._input_mode = "edit"
        self._editor_helper = ""
        self._paint_frame()

    def action_edit(self) -> None:
        self._open_editor("edit", self.view.segments[self.cursor].text)

    def _on_editor_submitted(self) -> None:
        value = self.editor.text()
        caret = self.editor.cursorPosition()
        mode = self._input_mode
        self._close_editor()
        if mode == "mark":
            self._submit_gesture(self._do_submit_mark(value))
        elif mode == "insert":
            self._submit_gesture(self._do_submit_insert(value))
        elif mode == "assign":
            self._submit_gesture(self._do_submit_assign(value))
        elif mode == "split":
            self._submit_gesture(self._do_submit_split(value, caret))
        elif mode == "propose_split":
            self._submit_gesture(self._do_submit_propose_split(value, caret))
        elif mode == "relabel":
            self._submit_gesture(self._do_submit_relabel(value))
        elif mode == "gate":
            self._submit_gesture(self._do_submit_gate(value))
        elif mode == "annotate":
            self._submit_gesture(self._do_submit_annotate(value))
        else:
            self._submit_gesture(self._do_submit_edit(value))

    async def _do_submit_edit(self, new_text: str):
        seg = self.view.segments[self.cursor]
        if new_text != seg.text:
            await commit_text_correction(
                self.view.queue, self.view.graph_id, self.view.source_id,
                seg.id, new_text, self.session_id,
                old_text=seg.text, actor=self.actor,
                journal_path=self._journal_path)
            seg.text = new_text
            self._marks[self.cursor] = "corrected"
            self.view.refresh_turn_proposal(seg.id)
        # A text-bearing PRUNED position must leave the prune set (the rescue).
        if new_text.strip() and seg.id in self.view.pruned_ids:
            prior = self.view.prune_correction_for(seg.id)
            if prior is not None:
                amended = await commit_prune_amendment(
                    self.view.queue, self.view.graph_id, prior, [seg.id],
                    self.session_id, actor=self.actor,
                    journal_path=self._journal_path)
                self.view.unprune_local(prior["id"], amended)
                self._marks[self.cursor] = "corrected"
        return {}

    # ---- lanes -----------------------------------------------------------

    def action_cycle_lane(self) -> None:
        if self.editor.isVisible():
            return
        self._cycle_lane(1)

    def action_cycle_lane_prev(self) -> None:
        if self.editor.isVisible():
            return
        self._cycle_lane(-1)

    def _cycle_lane(self, delta: int) -> None:
        order = (["walk", "assign"]
                 + (["propose"] if self.view.proposals_meta else [])
                 + ["annotate"])
        self.lane = order[(order.index(self.lane) + delta) % len(order)] \
            if self.lane in order else "walk"
        self._word_anchor = None
        self._overlay_pick = None
        save_tui_state(self._graph_db_path, self.view.source_id, None,
                       lane=self.lane)
        self._render()
        # Lane pick menus now DERIVE into the context slot every frame
        # (_paint_frame) — no entry-time readout paints to go stale.

    # ---- assign lane -----------------------------------------------------

    def _assign_menu(self) -> List[Tuple[str, str]]:
        seen: List[str] = []
        for s in self.view.segments:
            sp = self.view.speakers.get(s.id)
            if sp and sp.get("entity_id") and sp["entity_id"] not in seen:
                seen.append(sp["entity_id"])
        rest = [d["id"] for d in self._entities if d["id"] not in seen]
        return [(eid, panes.entity_name(self._entities, eid))
                for eid in (seen + rest)[:9]]

    async def _do_assign_pick(self, n: int):
        menu = self._assign_menu()
        if not (1 <= n <= len(menu)):
            return {"status": f"assign: no speaker #{n} — A mints a new one"}
        self._active_entity = menu[n - 1][0]
        return await self._do_commit_assign(menu[n - 1][0])

    async def _do_assign_same(self):
        if self._active_entity is None:
            return {"status": "assign: no active speaker — pick 1-9 or A new"}
        return await self._do_commit_assign(self._active_entity)

    async def _do_assign_accept(self):
        seg = self.view.segments[self.cursor]
        prop = self.view.turn_proposals.get(seg.id)
        if not prop:
            return {"status": "accept: no diarization proposal on this segment"}
        cluster = str(prop["cluster"])
        entity = self.view.cluster_entities.get(cluster)
        if entity:
            return await self._do_commit_accept(cluster, entity)
        self._accept_cluster = cluster
        menu = self._assign_menu()
        listing = " · ".join(f"{i + 1}:{nm}" for i, (_, nm) in enumerate(menu))
        return {"editor": ("assign", ""),
                "status": f'accept {cluster}: #-or-Name · "? handle" = provisional'
                          + (f" · {listing}" if listing else "")}

    async def _do_commit_accept(self, cluster: str, entity_id: str):
        view = self.view
        targets = [s.id for s in view.segments
                   if s.id not in view.speakers
                   and str((view.turn_proposals.get(s.id) or {}).get("cluster"))
                   == cluster]
        if not targets:
            return {"status": f"accept: no unassigned segments under {cluster}"}
        merged = entity_id in {e for c, e in view.cluster_entities.items()
                               if c != cluster}
        verdict = "cluster-merge" if merged else "accept"
        cov = [float((view.turn_proposals.get(t) or {}).get("coverage") or 0.0)
               for t in targets]
        cap = view.turns_meta.get("capability") or {}
        meta = view.turns_meta.get("metadata") or {}
        proposal = {"cluster": cluster,
                    "model_id": meta.get("model_id"),
                    "config_hash": cap.get("config_hash"),
                    "segments": len(targets),
                    "mean_coverage": round(sum(cov) / len(cov), 3) if cov else None}
        corr_id = await commit_speaker_assign_correction(
            view.queue, view.graph_id, view.source_id,
            targets, entity_id, self.session_id, verdict=verdict,
            proposal=proposal, actor=self.actor,
            journal_path=self._journal_path)
        view.assign_local(targets, entity_id, verdict, corr_id, cluster=cluster)
        self._active_entity = entity_id
        return {"status": f"{verdict}: {cluster} → "
                          f"{panes.entity_name(self._entities, entity_id)}"
                          f" ({len(targets)} segments)"}

    def action_assign_new(self) -> None:
        menu = self._assign_menu()
        listing = " · ".join(f"{i + 1}:{nm}" for i, (_, nm) in enumerate(menu))
        self._open_editor("assign", "",
                          status='speaker: #-or-Name · "? handle" = provisional'
                                 + (f" · {listing}" if listing else ""))

    async def _do_submit_assign(self, raw: str):
        token = (raw or "").strip()
        if token.isdigit():
            menu = self._assign_menu()
            n = int(token)
            if not (1 <= n <= len(menu)):
                return {"status": f"assign: no speaker #{n} — menu has {len(menu)}"}
            self._active_entity = menu[n - 1][0]
            return await self._do_commit_assign(menu[n - 1][0])
        parsed = parse_entity_input(raw)
        if parsed is None:
            return {}
        name, provisional = parsed
        for d in self._entities:
            p = d.get("properties") or {}
            if str(p.get("canonical_name") or "").lower() == name.lower():
                self._active_entity = d["id"]
                return await self._do_commit_assign(d["id"])
        eid = await commit_speaker_entity(
            self.view.queue, self.view.graph_id, name, self.session_id,
            provisional=provisional, actor=self.actor,
            journal_path=self._journal_path)
        self._entities.append({"id": eid, "properties": {
            "canonical_name": name, "provisional": provisional,
            "kind": "person"}})
        self._active_entity = eid
        return await self._do_commit_assign(eid)

    async def _do_commit_assign(self, entity_id: str):
        if self._accept_cluster is not None:
            cluster, self._accept_cluster = self._accept_cluster, None
            return await self._do_commit_accept(cluster, entity_id)
        seg = self.view.segments[self.cursor]
        corr_id = await commit_speaker_assign_correction(
            self.view.queue, self.view.graph_id, self.view.source_id,
            [seg.id], entity_id, self.session_id, verdict="name",
            actor=self.actor, journal_path=self._journal_path)
        self.view.assign_local([seg.id], entity_id, "name", corr_id)
        idx = seg.index
        return {"advance": 1,
                "status": f"@ #{idx} → "
                          f"{panes.entity_name(self._entities, entity_id)}"}

    # ---- propose lane ----------------------------------------------------

    def action_toggle_tier2(self) -> None:
        view = self.view
        if not (view.proposals_meta or {}).get("tier2_total"):
            self._paint_status("single-tier proposal set — no audition tier to show")
            return
        view.show_tier2 = not view.show_tier2
        view.refresh_event_proposals()
        self._render()
        t2 = (view.proposals_meta or {}).get("tier2_total", 0)
        self._paint_status(
            f"audition tier shown ({t2} tier-2 spans join the walk) · t hides"
            if view.show_tier2 else "audition tier hidden · t shows")

    def action_propose_audition(self) -> None:
        props = self.view.event_proposals.get(
            self.view.segments[self.cursor].id)
        if not props:
            self._paint_status("no pending proposal at cursor — n/N jump to one")
            return
        p = props[0]
        self.player.stop()
        self._play_span_source(
            float(p["start_time"]), float(p["end_time"]),
            note=f" · ?{p.get('label')} score {float(p.get('score') or 0):.2f}"
                 " · a accepts")

    def _jump_proposal(self, direction: int) -> None:
        view = self.view
        rng = (range(self.cursor + 1, view.size) if direction > 0
               else range(self.cursor - 1, -1, -1))
        for i in rng:
            props = view.event_proposals.get(view.segments[i].id)
            if props:
                self.cursor = i
                self._render()
                p = props[0]
                self.player.stop()
                self._play_span_source(
                    float(p["start_time"]), float(p["end_time"]),
                    note=f" · ?{p.get('label')} score "
                         f"{float(p.get('score') or 0):.2f}"
                         " · a accepts · R replays")
                return
        self._paint_status("no more pending proposals this way")

    def action_propose_accept(self) -> None:
        """a (propose lane): the accept gesture IS the insert op — gap /
        straddle / split-chain / overlay shapes, ported verbatim. The
        splittable shape opens the caret editor FIRST (paint thread), so the
        guard walk happens here and only the commit rides the loop."""
        view = self.view
        i = self.cursor
        seg = view.segments[i]
        props = view.event_proposals.get(seg.id)
        if not props:
            self._paint_status("no pending proposal at cursor — n/N jump to one")
            return
        p = props[0]
        ps, pe = float(p["start_time"]), float(p["end_time"])
        eps = 0.05
        a_start = float(seg.start_time) if seg.start_time is not None else None
        a_end = float(seg.end_time) if seg.end_time is not None else None
        interior = (a_start is not None and a_end is not None
                    and ps > a_start + eps and pe < a_end - eps)
        splittable = interior and len((seg.text or "").split()) >= 2
        if splittable:
            self._pending_proposal = (i, p)
            frac = (ps - a_start) / max(a_end - a_start, 1e-6)
            caret = max(0, min(len(seg.text), round(len(seg.text) * frac)))
            self._open_editor("propose_split", seg.text, caret=caret,
                              status=f"accept: caret marks the text cut at {ps:.2f}s"
                                     " · enter = split + inhale between · esc cancels")
            return
        self._submit_gesture(self._do_propose_accept_flat(i, p, interior))

    async def _do_propose_accept_flat(self, i: int, p: Dict[str, Any],
                                      interior: bool):
        view = self.view
        seg = view.segments[i]
        ps, pe = float(p["start_time"]), float(p["end_time"])
        eps = 0.05
        a_end = float(seg.end_time) if seg.end_time is not None else None
        nxt = view.segments[i + 1] if i + 1 < view.size else None
        plan = plan_chunk_insert(view.segments, i, inserted_ids=view.inserted_ids,
                                 insert_ranks=view.insert_ranks)
        if plan is None:
            return {"status": "accept: refused (missing times, or an overlapping "
                              "boundary — nudge the overlap first)"}
        insert_id = await commit_chunk_insert_correction(
            view.queue, view.graph_id, view.source_id,
            plan["after_id"], ps, pe, self.session_id,
            before_segment_id=plan["before_id"], label=p.get("label"),
            rank=plan["rank"], actor=self.actor,
            journal_path=self._journal_path)
        pos = view.add_insert_local(
            {"id": insert_id,
             "payload": {"operation": "chunk_insert",
                         "after_segment_id": plan["after_id"],
                         "start_time": ps, "end_time": pe,
                         "label": p.get("label"), "text": "",
                         "rank": plan["rank"]}})
        note = ""
        if not interior:
            if a_end is not None and ps < a_end - eps:
                last = ((seg.text or "").split() or [None])[-1]
                await self._commit_span_nudge(seg.id, "end", a_end, ps,
                                              {"left": last, "right": None})
                note = " · anchor end pulled"
            if nxt is not None and nxt.start_time is not None \
                    and pe > float(nxt.start_time) + eps:
                first = ((nxt.text or "").split() or [None])[0]
                await self._commit_span_nudge(nxt.id, "start",
                                              float(nxt.start_time), pe,
                                              {"left": None, "right": first})
                note = note or " · next start pulled"
        else:
            note = " · mid-chunk, text not divisible — overlay insert only"
        if pos is not None:
            self._marks = {(k + 1 if k >= pos else k): v
                           for k, v in self._marks.items()}
            self.cursor = pos
        view.refresh_event_proposals()
        return {"play": ("span", ps, pe,
                         f" · ✓ {p.get('label')} accepted{note}")}

    async def _do_submit_propose_split(self, value: str, caret: int):
        view = self.view
        pending, self._pending_proposal = self._pending_proposal, None
        if pending is None:
            return {}
        i, p = pending
        seg = view.segments[i] if 0 <= i < view.size else None
        head = (view.event_proposals.get(seg.id) or [None])[0] if seg else None
        if head is None or head.get("proposal_id") != p.get("proposal_id"):
            return {"status": "accept: proposal state changed — n/N jump again"}
        ps, pe = float(p["start_time"]), float(p["end_time"])
        plan = plan_chunk_split(view.segments, i, caret, text=value,
                                inserted_ids=view.inserted_ids)
        if plan is None:
            left_words = value[:caret].split()
            right_words = value[caret:].split()
            if left_words and not right_words:
                return await self._do_accept_bookend(i, p, "end")
            if right_words and not left_words:
                return await self._do_accept_bookend(i, p, "start")
            return {"status": "accept: split refused (the caret must leave "
                              "words on both sides of the cut)"}
        plan["split_s"] = ps   # the MODEL's span start is the cut
        old_text = seg.text
        ids = await commit_chunk_split_correction(
            view.queue, view.graph_id, view.source_id, plan["segment_id"],
            plan["split_s"], plan["left_text"], plan["right_text"],
            plan["end_s"], self.session_id, plan["after_id"],
            before_segment_id=plan["before_id"], old_text=old_text,
            boundary_words=plan["boundary_words"], actor=self.actor,
            journal_path=self._journal_path)
        pos_r = view.split_local(i, plan["left_text"], plan["split_s"],
                                 {"id": ids["insert_id"],
                                  "payload": {"operation": "chunk_insert",
                                              "after_segment_id": plan["after_id"],
                                              "start_time": plan["split_s"],
                                              "end_time": plan["end_s"],
                                              "label": None,
                                              "text": plan["right_text"]}})
        view.split_groups[ids["insert_id"]] = {
            "group_ids": [ids["text_id"], ids["nudge_id"]],
            "target_id": plan["segment_id"], "old_text": old_text,
            "old_end": plan["end_s"]}
        if pos_r is not None:
            self._marks = {(k + 1 if k >= pos_r else k): v
                           for k, v in self._marks.items()}
        iplan = plan_chunk_insert(view.segments, i,
                                  inserted_ids=view.inserted_ids,
                                  insert_ranks=view.insert_ranks)
        if iplan is None:
            return {"status": "accept: split landed but the between-insert "
                              "refused — i inserts manually"}
        insert_id = await commit_chunk_insert_correction(
            view.queue, view.graph_id, view.source_id,
            iplan["after_id"], ps, pe, self.session_id,
            before_segment_id=iplan["before_id"], label=p.get("label"),
            rank=iplan["rank"], actor=self.actor,
            journal_path=self._journal_path)
        pos = view.add_insert_local(
            {"id": insert_id,
             "payload": {"operation": "chunk_insert",
                         "after_segment_id": iplan["after_id"],
                         "start_time": ps, "end_time": pe,
                         "label": p.get("label"), "text": "",
                         "rank": iplan["rank"]}})
        right_first = ((plan["right_text"] or "").split() or [None])[0]
        await self._commit_span_nudge(ids["insert_id"], "start", ps, pe,
                                      {"left": None, "right": right_first})
        if pos is not None:
            self._marks = {(k + 1 if k >= pos else k): v
                           for k, v in self._marks.items()}
            self.cursor = pos
        view.refresh_event_proposals()
        return {"play": ("span", ps, pe,
                         f" · ✓ {p.get('label')} isolated (split + insert)")}

    async def _do_accept_bookend(self, i: int, p: Dict[str, Any], edge: str):
        view = self.view
        seg = view.segments[i]
        ps, pe = float(p["start_time"]), float(p["end_time"])
        seam = i if edge == "end" else i - 1
        if seam < 0:
            return {"status": "accept: no seam before the first segment — "
                              "i inserts manually"}
        plan = plan_chunk_insert(view.segments, seam,
                                 inserted_ids=view.inserted_ids,
                                 insert_ranks=view.insert_ranks)
        if plan is None:
            return {"status": "accept: refused (missing times, or an overlapping "
                              "boundary — nudge the overlap first)"}
        words = (seg.text or "").split() or [None]
        if edge == "end":
            await self._commit_span_nudge(seg.id, "end", float(seg.end_time),
                                          ps, {"left": words[-1], "right": None})
        else:
            await self._commit_span_nudge(seg.id, "start",
                                          float(seg.start_time), pe,
                                          {"left": None, "right": words[0]})
        insert_id = await commit_chunk_insert_correction(
            view.queue, view.graph_id, view.source_id,
            plan["after_id"], ps, pe, self.session_id,
            before_segment_id=plan["before_id"], label=p.get("label"),
            rank=plan["rank"], actor=self.actor,
            journal_path=self._journal_path)
        pos = view.add_insert_local(
            {"id": insert_id,
             "payload": {"operation": "chunk_insert",
                         "after_segment_id": plan["after_id"],
                         "start_time": ps, "end_time": pe,
                         "label": p.get("label"), "text": "",
                         "rank": plan["rank"]}})
        if pos is not None:
            self._marks = {(k + 1 if k >= pos else k): v
                           for k, v in self._marks.items()}
            self.cursor = pos
        view.refresh_event_proposals()
        return {"play": ("span", ps, pe,
                         f" · ✓ {p.get('label')} accepted · anchor {edge} pulled")}

    async def _commit_span_nudge(self, segment_id: str, edge: str, old_t: float,
                                 new_t: float, words: Dict[str, Any]) -> None:
        plan = [{"segment_id": segment_id, "edge": edge,
                 "old_time": old_t, "new_time": new_t}]
        await commit_time_nudge_correction(
            self.view.queue, self.view.graph_id, self.view.source_id, plan,
            self.session_id, boundary_words=words, step_s=new_t - old_t,
            actor=self.actor, journal_path=self._journal_path)
        seg = next((s for s in self.view.segments if s.id == segment_id), None)
        if seg is not None:
            if edge == "start":
                seg.start_time = new_t
            else:
                seg.end_time = new_t

    # ---- inserts / splits / relabel / remove -----------------------------

    def _insert_label_menu(self) -> List[str]:
        return list(RECOMMENDED_INSERT_LABELS) + [
            c for c in self.view.seen_insert_labels
            if c not in RECOMMENDED_INSERT_LABELS]

    def _plan_insert(self) -> Optional[Dict[str, Any]]:
        view, i = self.view, self.cursor
        plan = plan_chunk_insert(view.segments, i, inserted_ids=view.inserted_ids,
                                 insert_ranks=view.insert_ranks)
        if plan is None:
            self._paint_status("insert: refused (missing times, or an overlapping "
                               "boundary — nudge the overlap first)")
            return None
        return plan

    def action_insert_labeled(self) -> None:
        if self._plan_insert() is None:
            return
        menu = self._insert_label_menu()
        self._open_editor("insert", f"{self._insert_label} ",
                          status="insert label: class-or-# · "
                                 + " ".join(f"{i + 1}:{c}"
                                            for i, c in enumerate(menu)))

    async def _do_insert_chunk(self, label: Optional[str]):
        view = self.view
        plan = plan_chunk_insert(view.segments, self.cursor,
                                 inserted_ids=view.inserted_ids,
                                 insert_ranks=view.insert_ranks)
        if plan is None:
            return {"status": "insert: refused (missing times, or an overlapping "
                              "boundary — nudge the overlap first)"}
        insert_id = await commit_chunk_insert_correction(
            view.queue, view.graph_id, view.source_id,
            plan["after_id"], plan["start_s"], plan["end_s"], self.session_id,
            before_segment_id=plan["before_id"], label=label,
            rank=plan["rank"], actor=self.actor,
            journal_path=self._journal_path)
        pos = view.add_insert_local(
            {"id": insert_id,
             "payload": {"operation": "chunk_insert",
                         "after_segment_id": plan["after_id"],
                         "start_time": plan["start_s"],
                         "end_time": plan["end_s"],
                         "label": label, "text": "", "rank": plan["rank"]}})
        if pos is not None:
            self._marks = {(k + 1 if k >= pos else k): v
                           for k, v in self._marks.items()}
            self.cursor = pos
        lab = f" [{label}]" if label else ""
        if plan["welded"]:
            return {"status": f"⊕ zero-width insert{lab} at "
                              f"{plan['start_s']:.2f}s — grow it with ,/. </>"}
        return {"status": f"⊕ inserted{lab} {plan['start_s']:.2f}"
                          f"–{plan['end_s']:.2f}s · playing source · e types its text",
                "status_first": True,
                "play": ("span", plan["start_s"], plan["end_s"], "")}

    async def _do_submit_insert(self, raw: str):
        raw, err = resolve_mark_class_token(raw, self._insert_label_menu())
        if err:
            return {"status": f"insert: {err}"}
        tokens = (raw or "").split()
        if not tokens:
            return {}
        label = tokens[0].strip('`"\'')
        if not label or not label[:1].isalnum():
            return {"status": "insert: label must start with a letter or digit"}
        self._insert_label = label
        save_tui_state(self._graph_db_path, self.view.source_id, self.cursor,
                       insert_label=label)
        return await self._do_insert_chunk(label)

    def action_split_chunk(self) -> None:
        seg = self.view.segments[self.cursor]
        if seg.id in self.view.pruned_ids:
            self._paint_status("split: pruned position — e-edit text first "
                               "(rescue), then split")
            return
        if len((seg.text or "").split()) < 2:
            self._paint_status("split: needs at least two words (both halves "
                               "must keep text)")
            return
        self._open_editor("split", seg.text, caret=0,
                          status="split: place the caret at the cut point · "
                                 "enter splits · esc cancels")

    async def _do_submit_split(self, value: str, caret: int):
        view, i = self.view, self.cursor
        seg = view.segments[i]
        plan = plan_chunk_split(view.segments, i, caret, text=value,
                                inserted_ids=view.inserted_ids)
        if plan is None:
            return {"status": "split: refused (the caret must leave words on "
                              "both sides of the cut, and the chunk needs "
                              "audio times)"}
        old_text = seg.text
        ids = await commit_chunk_split_correction(
            view.queue, view.graph_id, view.source_id, plan["segment_id"],
            plan["split_s"], plan["left_text"], plan["right_text"],
            plan["end_s"], self.session_id, plan["after_id"],
            before_segment_id=plan["before_id"], old_text=old_text,
            boundary_words=plan["boundary_words"], actor=self.actor,
            journal_path=self._journal_path)
        pos = view.split_local(i, plan["left_text"], plan["split_s"],
                               {"id": ids["insert_id"],
                                "payload": {"operation": "chunk_insert",
                                            "after_segment_id": plan["after_id"],
                                            "start_time": plan["split_s"],
                                            "end_time": plan["end_s"],
                                            "label": None,
                                            "text": plan["right_text"]}})
        view.split_groups[ids["insert_id"]] = {
            "group_ids": [ids["text_id"], ids["nudge_id"]],
            "target_id": plan["segment_id"], "old_text": old_text,
            "old_end": plan["end_s"]}
        if pos is not None:
            self._marks = {(k + 1 if k >= pos else k): v
                           for k, v in self._marks.items()}
        return {"status": f"✂ split #{seg.index} at {plan['split_s']:.2f}s "
                          "(caret-seeded) — ,/. tunes the new seam · g auditions it"}

    def action_relabel_insert(self) -> None:
        view = self.view
        seg = view.segments[self.cursor]
        if seg.id not in view.inserted_ids:
            self._paint_status("relabel: only inserted (⊕) chunks carry labels")
            return
        if seg.id in view.split_groups:
            self._paint_status("relabel: a split right half has no class label "
                               "(x unsplits)")
            return
        menu = self._insert_label_menu()
        self._open_editor(
            "relabel", f"{view.insert_labels.get(seg.id) or self._insert_label} ",
            status="relabel: class-or-# · "
                   + " ".join(f"{i + 1}:{c}" for i, c in enumerate(menu)))

    async def _do_submit_relabel(self, raw: str):
        view = self.view
        raw, err = resolve_mark_class_token(raw, self._insert_label_menu())
        if err:
            return {"status": f"relabel: {err}"}
        tokens = (raw or "").split()
        if not tokens:
            return {}
        label = tokens[0].strip('`"\'')
        if not label or not label[:1].isalnum():
            return {"status": "relabel: label must start with a letter or digit"}
        i = self.cursor
        seg = view.segments[i]
        if seg.id not in view.inserted_ids or seg.start_time is None:
            return {"status": "relabel: cursor moved off the insert — try again"}
        old_label = view.insert_labels.get(seg.id)
        if label == old_label:
            return {"status": f"relabel: already [{label}]"}
        start_s, end_s = float(seg.start_time), float(seg.end_time)
        rank = view.insert_ranks.get(seg.id, 0.0)
        text = seg.text or ""
        after_id = next((view.segments[j].id for j in range(i - 1, -1, -1)
                         if view.segments[j].id not in view.inserted_ids), None)
        before_id = next((view.segments[j].id for j in range(i + 1, view.size)
                          if view.segments[j].id not in view.inserted_ids), None)
        if after_id is None:
            return {"status": "relabel: no layer-0 anchor left of the insert"}
        await commit_chunk_insert_removal(
            view.queue, view.graph_id, view.source_id, seg.id,
            self.session_id, actor=self.actor, journal_path=self._journal_path)
        view.remove_insert_local(seg.id)
        insert_id = await commit_chunk_insert_correction(
            view.queue, view.graph_id, view.source_id,
            after_id, start_s, end_s, self.session_id,
            before_segment_id=before_id, label=label,
            rank=rank, actor=self.actor, journal_path=self._journal_path)
        pos = view.add_insert_local(
            {"id": insert_id,
             "payload": {"operation": "chunk_insert",
                         "after_segment_id": after_id,
                         "start_time": start_s, "end_time": end_s,
                         "label": label, "text": text, "rank": rank}})
        if pos is not None:
            self.cursor = pos
        view.refresh_event_proposals()
        return {"status": f"↺ relabeled [{old_label or '∅'}] → [{label}]"
                          f" ({start_s:.2f}–{end_s:.2f}s)"}

    async def _do_remove_insert(self):
        view = self.view
        seg = view.segments[self.cursor]
        if seg.id not in view.inserted_ids:
            return {"status": "remove: only inserted (⊕) chunks can be removed"}
        info = view.split_groups.get(seg.id)
        if info:
            await commit_chunk_split_removal(
                view.queue, view.graph_id, view.source_id, seg.id,
                info["group_ids"], self.session_id, actor=self.actor,
                journal_path=self._journal_path)
            pos = view.unsplit_local(seg.id)
        else:
            await commit_chunk_insert_removal(
                view.queue, view.graph_id, view.source_id, seg.id,
                self.session_id, actor=self.actor,
                journal_path=self._journal_path)
            pos = view.remove_insert_local(seg.id)
        if pos is not None:
            self._marks = {(k - 1 if k > pos else k): v
                           for k, v in self._marks.items() if k != pos}
            self.cursor = max(0, min(view.size - 1, self.cursor))
        view.refresh_event_proposals()
        if info:
            return {"status": f"⊖ unsplit: right half removed, target restored"
                              f" (text + end back to {seg.end_time:.2f}s)"}
        return {"status": f"⊖ removed inserted chunk"
                          f" ({seg.start_time:.2f}–{seg.end_time:.2f}s)"}

    # ---- marks -----------------------------------------------------------

    def _mark_class_menu(self) -> List[str]:
        return list(RECOMMENDED_MARK_CLASSES) + [
            c for c in self.view.seen_mark_classes
            if c not in RECOMMENDED_MARK_CLASSES]

    async def _do_mark_quick(self):
        seg = self.view.segments[self.cursor]
        return await self._do_commit_mark(
            {"kind": "segment", "segment_id": seg.id}, self._mark_class, None)

    async def _do_mark_boundary(self):
        view, i = self.view, self.cursor
        if i + 1 >= view.size:
            return {"status": "boundary mark: no segment after the cursor"}
        return await self._do_commit_mark(
            {"kind": "boundary", "boundary_after": view.segments[i].id,
             "right_segment_id": view.segments[i + 1].id},
            self._mark_class, None)

    def action_mark_editor(self) -> None:
        menu = self._mark_class_menu()
        self._open_editor(
            "mark", f"{self._mark_class} ",
            status='mark: class-or-# ["snippet"] [note] · - dismiss · '
                   + " ".join(f"{i + 1}:{c}" for i, c in enumerate(menu)))

    async def _do_submit_mark(self, raw: str):
        seg = self.view.segments[self.cursor]
        tokens = raw.split()
        if not tokens:
            return {}
        first = tokens[0].strip('`"\'')
        if first.startswith("-") or not first:
            marks = self.view.marks_for(seg.id)
            if not marks:
                return {"status": f"no open mark on #{seg.index}"}
            for m in marks:
                await commit_mark_dismissal(
                    self.view.queue, self.view.graph_id, self.view.source_id,
                    m["id"], self.session_id, actor=self.actor,
                    journal_path=self._journal_path)
                self.view.dismiss_mark_local(m["id"])
            classes = ", ".join(str((m.get("payload") or {}).get("mark_class"))
                                for m in marks)
            return {"status": f"dismissed {len(marks)} mark(s) on "
                              f"#{seg.index} [{classes}]"}
        raw, err = resolve_mark_class_token(raw, self._mark_class_menu())
        if err:
            return {"status": f"mark: {err}"}
        parsed = parse_mark_input(raw, seg.text)
        if parsed is None:
            return {}
        mark_class, span, note = parsed
        if span is not None:
            start, end, snapshot = span
            anchor = {"kind": "span", "segment_id": seg.id, "char_start": start,
                      "char_end": end, "text_snapshot": snapshot}
        else:
            anchor = {"kind": "segment", "segment_id": seg.id}
        return await self._do_commit_mark(anchor, mark_class, note)

    async def _do_commit_mark(self, anchor: Dict[str, Any], mark_class: str,
                              note: Optional[str]):
        try:
            mark_id = await commit_mark_correction(
                self.view.queue, self.view.graph_id, self.view.source_id,
                anchor, mark_class, self.session_id, actor=self.actor,
                note=note, journal_path=self._journal_path)
        except ValueError as e:
            return {"status": f"mark refused: {e}"}
        self._mark_class = mark_class
        save_tui_state(self._graph_db_path, self.view.source_id, self.cursor,
                       mark_class=mark_class)
        self.view.add_mark_local({"id": mark_id, "correction_type": "mark",
                                  "payload": {"operation": "mark",
                                              "anchor": dict(anchor),
                                              "mark_class": mark_class}})
        seg = self.view.segments[self.cursor]
        suffix = f" — {note}" if note else ""
        return {"status": f"⚑ #{seg.index} [{mark_class}] "
                          f"({anchor['kind']}){suffix}"}

    # ---- the extraction gate ---------------------------------------------

    def action_gate_editor(self) -> None:
        seg = self.view.segments[self.cursor]
        value = (f"w {float(seg.end_time):.1f}"
                 if seg.end_time is not None else "w ")
        self._open_editor(
            "gate", value,
            status="gate: w [sec] watermark-at-pause · signoff · exclude · resume"
                   + f" · now: {panes.gate_chip(self.view) or 'in_progress (default), no watermark'}")

    async def _do_submit_gate(self, raw: str):
        view = self.view
        ends = [float(s.end_time) for s in view.segments
                if s.end_time is not None]
        seg = view.segments[self.cursor]
        plan = plan_gate(raw,
                         float(seg.end_time) if seg.end_time is not None else None,
                         max(ends) if ends else None,
                         (view.gate or {}).get("annotated_through"))
        if plan is None:
            return {"status": "gate: w [sec] · signoff · exclude · resume "
                              "(refused — unknown verb or no time to anchor)"}
        new_status, watermark = plan
        gate_id = await commit_extraction_gate(
            view.queue, view.graph_id, view.source_id, view.skeleton_hash,
            new_status, watermark, session_id=self.session_id,
            actor=self.actor, journal_path=self._journal_path)
        view.set_gate_local({"id": gate_id, "source_id": view.source_id,
                             "skeleton_hash": view.skeleton_hash,
                             "extraction_status": new_status,
                             "annotated_through": watermark,
                             "actor": self.actor, "created_at": time.time()})
        wm_txt = f"{float(watermark):.1f}s" if watermark is not None else "none"
        return {"status": f"⛭ gate asserted: {new_status} · "
                          f"annotated_through {wm_txt}"}

    # ---- annotate lane ---------------------------------------------------

    def _resolve_fa_cache(self) -> Optional[Path]:
        if self._fa_cache_arg:
            p = Path(self._fa_cache_arg)
            return p if p.is_file() else None
        ws = resolve_workspace(explicit=None)
        if ws is None:
            return None
        p = (ws.substrate_data_dir / "data" / "cjm-capability-qwen3-forced-aligner"
             / "forced_alignments.db")
        return p if p.is_file() else None

    def _overlay_label_menu(self) -> List[str]:
        return list(RECOMMENDED_OVERLAY_LABELS) + [
            c for c in self.view.seen_overlay_labels
            if c not in RECOMMENDED_OVERLAY_LABELS]

    async def _fa_words_for(self, seg) -> Optional[List[Dict[str, Any]]]:
        tid = getattr(seg, "text_from", None)
        if not tid or self._fa_cache_db is None:
            return None
        if tid not in self._fa_words_cache:
            self._fa_words_cache[tid] = await fa_words_for_transcript(
                self.view.queue, self.view.graph_id, tid, self._fa_cache_db)
        return self._fa_words_cache[tid]

    async def _snap_selection(self, seg) -> Tuple[Optional[Dict[str, Any]],
                                                  Optional[str]]:
        """Derive the selection's FA-snapped record; (None, status) = refused."""
        toks = segment_word_tokens(seg.text)
        sel = panes.selection_range(self._word_cursor, self._word_anchor,
                                    len(toks))
        if sel is None:
            return None, ("annotate: segment has no words (e-edit text lands "
                          "in the walk lane)")
        if seg.start_time is None or seg.end_time is None:
            return None, "annotate: segment has no audio times to snap against"
        a, b = sel
        snapped = snap_word_span(toks, a, b, float(seg.start_time),
                                 float(seg.end_time), len(seg.text),
                                 await self._fa_words_for(seg))
        if snapped is None:
            return None, "annotate: selection refused (word range invalid)"
        start_s, end_s, snap, words = snapped
        char_start, char_end = toks[a][0], toks[b][1]
        return ({"char_start": char_start, "char_end": char_end,
                 "text": seg.text[char_start:char_end],
                 "start_time": start_s, "end_time": end_s,
                 "snap": snap, "words": words}, None)

    def _word_move(self, delta: int) -> None:
        seg = self.view.segments[self.cursor]
        n = len(segment_word_tokens(seg.text))
        if n == 0:
            self._paint_status("annotate: no words on this segment — j/k to "
                               "a text-bearing one")
            return
        self._word_cursor = max(0, min(n - 1, self._word_cursor + delta))
        self._render()

    def action_word_select(self) -> None:
        seg = self.view.segments[self.cursor]
        n = len(segment_word_tokens(seg.text))
        if n == 0:
            self._paint_status("annotate: no words to select")
            return
        self._word_anchor = None if self._word_anchor is not None \
            else max(0, min(n - 1, self._word_cursor))
        self._render()

    async def _do_annotate_audition(self):
        seg = self.view.segments[self.cursor]
        if self._word_anchor is None:
            ov = self._overlay_at_cursor(seg, covering_only=True)
            if ov is not None:
                p = ov.get("payload") or {}
                return {"play": ("span", float(p["start_time"]),
                                 float(p["end_time"]),
                                 f" · ◈ {p.get('label')} "
                                 f"“{str(p.get('text') or '')[:24]}”"
                                 f" ({p.get('snap')}) · ,./<> nudges · x removes")}
        rec, refusal = await self._snap_selection(seg)
        if rec is None:
            return {"status": refusal}
        return {"play": ("span", rec["start_time"], rec["end_time"],
                         f" · ◈? “{rec['text'][:24]}” ({rec['snap']})"
                         " · space/1-9 commits")}

    def action_annotate_quick(self) -> None:
        if self._overlay_pick is not None:
            self._paint_status("annotate: ◈ pick live — o/O cycle · 1-9 jump "
                               "· esc returns to commit keys")
            return
        self._submit_gesture(self._do_commit_overlay(self._overlay_label, None))

    def action_annotate_pick(self, n: int) -> None:
        if self._overlay_pick is not None:
            seg = self.view.segments[self.cursor]
            overlays = self._segment_overlays_by_time(seg)
            if 1 <= n <= len(overlays):
                self._overlay_pick_set(overlays, n - 1)
            else:
                self._paint_status(
                    f"annotate: ◈ pick live — only {len(overlays)} on this "
                    f"segment (o/O cycle · esc returns to commit keys)")
            return
        menu = self._overlay_label_menu()
        if not (1 <= n <= len(menu)):
            self._paint_status(f"annotate: no label #{n} — menu has "
                               f"{len(menu)} (A types a new one)")
            return
        self._submit_gesture(self._do_commit_overlay(menu[n - 1], None))

    def action_annotate_editor(self) -> None:
        if self._overlay_pick is not None:
            self._paint_status("annotate: ◈ pick live — o/O cycle · 1-9 jump "
                               "· esc returns to commit keys")
            return
        menu = self._overlay_label_menu()
        self._open_editor(
            "annotate", f"{self._overlay_label} ",
            status="annotate label: class-or-# [note] · "
                   + " ".join(f"{i + 1}:{c}" for i, c in enumerate(menu)))

    async def _do_submit_annotate(self, raw: str):
        raw, err = resolve_mark_class_token(raw, self._overlay_label_menu())
        if err:
            return {"status": f"annotate: {err}"}
        tokens = (raw or "").split()
        if not tokens:
            return {}
        label = tokens[0].strip('`"\'')
        if not label or not label[:1].isalnum():
            return {"status": "annotate: label must start with a letter or digit"}
        return await self._do_commit_overlay(label, " ".join(tokens[1:]) or None)

    async def _do_commit_overlay(self, label: str, note: Optional[str]):
        view = self.view
        seg = view.segments[self.cursor]
        rec, refusal = await self._snap_selection(seg)
        if rec is None:
            return {"status": refusal}
        anchor = {"kind": "span", "segment_id": seg.id,
                  "char_start": rec["char_start"], "char_end": rec["char_end"],
                  "text_snapshot": rec["text"]}
        try:
            overlay_id = await commit_speech_overlay_correction(
                view.queue, view.graph_id, view.source_id, anchor, label,
                rec["start_time"], rec["end_time"], rec["text"],
                self.session_id, words=rec["words"], snap=rec["snap"],
                actor=self.actor, note=note, journal_path=self._journal_path)
        except ValueError as e:
            return {"status": f"annotate refused: {e}"}
        view.add_overlay_local({"id": overlay_id, "correction_type": "annotation",
                                "payload": {"operation": "speech_overlay",
                                            "anchor": dict(anchor),
                                            "label": label,
                                            "start_time": rec["start_time"],
                                            "end_time": rec["end_time"],
                                            "text": rec["text"],
                                            "snap": rec["snap"]}})
        self._overlay_label = label
        save_tui_state(self._graph_db_path, view.source_id, self.cursor,
                       overlay_label=label)
        self._word_anchor = None
        self._overlay_pick = None
        return {"play": ("span", rec["start_time"], rec["end_time"],
                         f" · ◈ {label} “{rec['text'][:24]}” ({rec['snap']})")}

    def _overlay_at_cursor(self, seg,
                           covering_only: bool = False) -> Optional[Dict[str, Any]]:
        overlays = self.view.overlays_for(seg.id)
        if not overlays:
            return None
        if self._overlay_pick is not None:
            for o in overlays:
                if o.get("id") == self._overlay_pick:
                    return o
            self._overlay_pick = None
        toks = segment_word_tokens(seg.text)
        if toks:
            c = max(0, min(len(toks) - 1, self._word_cursor))
            cs, ce = toks[c][0], toks[c][1]
            for o in reversed(overlays):
                a = (o.get("payload") or {}).get("anchor") or {}
                if a.get("char_start") is not None \
                        and a.get("char_end") is not None \
                        and int(a["char_start"]) <= cs and ce <= int(a["char_end"]):
                    return o
        return None if covering_only else overlays[-1]

    def _segment_overlays_by_time(self, seg) -> List[Dict[str, Any]]:
        return sorted(
            self.view.overlays_for(seg.id),
            key=lambda o: (float((o.get("payload") or {}).get("start_time") or 0.0),
                           float((o.get("payload") or {}).get("end_time") or 0.0)))

    def _overlay_pick_set(self, overlays: List[Dict[str, Any]], i: int) -> None:
        pick = overlays[i]
        self._overlay_pick = pick.get("id")
        p = pick.get("payload") or {}
        self.player.stop()
        self._play_span_source(
            float(p["start_time"]), float(p["end_time"]),
            note=f" · ◈ pick {i + 1}/{len(overlays)} {p.get('label')}"
                 f" “{str(p.get('text') or '')[:24]}” ({p.get('snap')})"
                 f" · R/x/,./<> target it · 1-9 jump · esc clears")

    def action_overlay_cycle(self, direction: int = 1) -> None:
        seg = self.view.segments[self.cursor]
        overlays = self._segment_overlays_by_time(seg)
        if not overlays:
            self._paint_status("annotate: no ◈ overlay on this segment to cycle")
            return
        ids = [o.get("id") for o in overlays]
        i = ((ids.index(self._overlay_pick) + direction) % len(overlays)
             if self._overlay_pick in ids
             else (0 if direction > 0 else len(overlays) - 1))
        self._overlay_pick_set(overlays, i)

    def _overlay_nudge(self, edge: str, sign: int) -> None:
        self._submit_gesture(self._do_overlay_nudge(edge, sign))

    async def _do_overlay_nudge(self, edge: str, sign: int):
        view = self.view
        seg = view.segments[self.cursor]
        target = self._overlay_at_cursor(seg)
        if target is None:
            return {"status": "annotate: no ◈ overlay here to nudge (v+label "
                              "commits one first)"}
        p = target.get("payload") or {}
        start, end = float(p["start_time"]), float(p["end_time"])
        delta = sign * self._nudge_step
        if edge == "end":
            new_start, new_end = start, end + delta
        else:
            new_start, new_end = max(0.0, start + delta), end
        if new_end - new_start < 0.005:
            return {"status": f"annotate: nudge refused ({edge} {delta:+.3f}s "
                              "would collapse the span)"}
        anchor = dict(p.get("anchor") or {})
        warn = ""
        toks = segment_word_tokens(seg.text)
        if toks and seg.start_time is not None and seg.end_time is not None:
            nb = neighbor_word_bound(
                toks, int(anchor.get("char_start") or 0),
                int(anchor.get("char_end") or 0),
                "next" if edge == "end" else "prev",
                float(seg.start_time), float(seg.end_time), len(seg.text),
                await self._fa_words_for(seg))
            if nb is not None:
                over = (new_end - nb[1]) if edge == "end" else (nb[1] - new_start)
                if over > 1e-3:
                    warn = f" · ⚠ into “{nb[0]}” +{over * 1000:.0f}ms"
        overlay_id = await commit_speech_overlay_correction(
            view.queue, view.graph_id, view.source_id, anchor,
            str(p.get("label")), new_start, new_end, str(p.get("text") or ""),
            self.session_id, words=list(p.get("words") or []), snap="nudged",
            supersedes_id=target["id"], actor=self.actor,
            journal_path=self._journal_path)
        view.remove_overlay_local(target["id"])
        view.add_overlay_local({"id": overlay_id, "correction_type": "annotation",
                                "payload": {**p, "anchor": anchor,
                                            "start_time": new_start,
                                            "end_time": new_end,
                                            "snap": "nudged"}})
        if self._overlay_pick == target["id"]:
            self._overlay_pick = overlay_id
        return {"play": ("span", new_start, new_end,
                         f" · ◈ {p.get('label')} {edge} {delta:+.3f}s{warn}")}

    async def _do_overlay_remove(self):
        view = self.view
        seg = view.segments[self.cursor]
        target = self._overlay_at_cursor(seg)
        if target is None:
            return {"status": "annotate: no ◈ overlay on this segment"}
        await commit_speech_overlay_removal(
            view.queue, view.graph_id, view.source_id, target["id"],
            self.session_id, actor=self.actor, journal_path=self._journal_path)
        view.remove_overlay_local(target["id"])
        if self._overlay_pick == target["id"]:
            self._overlay_pick = None
        p = target.get("payload") or {}
        return {"status": f"⊘ removed ◈ [{p.get('label')}] "
                          f"“{str(p.get('text') or '')[:24]}”"}

    # ---- fold / pickers / flywheel ---------------------------------------

    def action_toggle_wordless_fold(self) -> None:
        if self.view is None or self.stage in ("select", "spine"):
            return
        self.fold_wordless = not self.fold_wordless
        moved = ""
        if panes.folded(self, self.cursor):
            for j in (*range(self.cursor + 1, self.view.size),
                      *range(self.cursor - 1, -1, -1)):
                if not panes.folded(self, j):
                    self.cursor = j
                    moved = f" · cursor → #{self.view.segments[j].index}"
                    break
        save_tui_state(self._graph_db_path, self.view.source_id, self.cursor,
                       fold_wordless=self.fold_wordless)
        n = sum(1 for p in range(self.view.size) if panes.folded(self, p))
        self._render()
        self._paint_status(
            f"wordless inserts folded ({n} collapsed) · z unfolds{moved}"
            if self.fold_wordless else f"wordless inserts unfolded{moved}")

    def action_open_source(self) -> None:
        if self.stage == "spine":
            if not self._spines or self._spine_source is None:
                return
            sid, title = self._spine_source
            selector = selector_for_spine(self._spines[self.cursor])
            save_tui_state(self._graph_db_path, sid, None,
                           skeleton=selector, spines=len(self._spines))
            self._open_spine(sid, title, selector)
            return
        if self.stage != "select" or not self._sources:
            return
        sid, title = self._sources[self.cursor]
        self._open_source(sid, title)

    def action_flywheel_page(self) -> None:
        if self.stage == "flywheel":
            self.stage = self._flywheel_return
            self._render()
            self._paint_status("")   # stage landing claims the readout (f27f2b99)
            return
        if self.view is not None and self.stage == "correct":
            # From a lane: audio down before the page swap; the seat stays
            # (open_spine re-points it — session.py), so returning F lands
            # back on the intact lane.
            self._autoplay_timer.stop()
            if self.player is not None:
                self.player.stop()
            self._stop_ticker()
        self._flywheel_return = self.stage
        self._paint_status("")   # leaving the stage: its readout is done
        self._load_datasets()
        self._load_runs()
        self._fly_cursor = min(self._fly_cursor,
                               max(0, len(self._datasets)
                                   + len(self._runs) - 1))
        fut = self.sess.purposes()

        def done(f):
            try:
                self._purposes = f.result()
            except Exception:
                pass
            self._purpose_vocab = sorted(
                {p for mix in self._purposes.values() for p in mix}
                - {"genuine"})
            self.stage = "flywheel"
        fut.add_done_callback(lambda f: (done(f), self.progress_note.emit("")))

    # ---- navigation (f27f2b99: pickers/flywheel stop being a dead end) ----

    def _build_menubar(self) -> None:
        """Menus mirror the key table's SHELL verbs. Keys stay on the table
        walk (one gate — DEC cc55a7b5), so items carry the key as display
        text only (the tab column), never a QAction shortcut that would race
        the walk. No QStatusBar exists, so menu-hover status tips stay inert
        (the workbench hover-eviction class, dead by construction)."""
        bar = self.menuBar()
        fm = bar.addMenu("&File")
        fm.addAction("Quit\tq", self.close)
        nav = bar.addMenu("&Navigate")
        self._nav_actions = {
            "back": nav.addAction("Back\tB", self.action_back),
            "sources": nav.addAction("Source picker", self.action_nav_sources),
            "spines": nav.addAction("Spine picker", self.action_nav_spines),
            "flywheel": nav.addAction("Flywheel page\tF",
                                      self.action_flywheel_page)}
        nav.aboutToShow.connect(self._refresh_nav_menu)
        vm = bar.addMenu("&View")
        vm.addAction("Keyboard hints\t?", self.hints_overlay.toggle)

    def _refresh_nav_menu(self) -> None:
        """Enablement at menu-open time — a read of the same stage legality
        the key walk enforces."""
        a = self._nav_actions
        a["back"].setEnabled(self.stage != "select")
        a["sources"].setEnabled(self.stage != "select")
        a["spines"].setEnabled(self._spine_source is not None
                               and self.stage != "spine")
        a["flywheel"].setEnabled(self.stage != "flywheel"
                                 and not self._extract_busy)

    def action_back(self) -> None:
        """One step back: open editor/pick states cancel first (a modal IS a
        step), the flywheel returns where it came from, a lane unwinds to
        the spine picker, the spine picker to the sources."""
        if (self.editor.isVisible() or self._word_anchor is not None
                or self._overlay_pick is not None):
            self.action_cancel()
            return
        if self.stage == "flywheel":
            self.action_flywheel_page()
            return
        if self.stage == "correct" and self.view is not None:
            self.action_nav_spines()
            return
        if self.stage == "spine":
            self.action_nav_sources()
            return
        self._paint_status("front door — enter opens · F flywheel")

    def action_forward(self) -> None:
        """Mouse-forward: re-descend the path back just unwound."""
        if self.stage == "select" and self._spine_source is not None:
            self.action_nav_spines()
        elif self.stage == "spine" and self._last_spine is not None:
            self._open_spine(*self._last_spine)

    def action_nav_sources(self) -> None:
        """Re-enter the source picker from anywhere. The CLI --source
        pre-pick is consumed (auto-open would bounce straight back), and
        the discovery ladder re-runs so the status chips reflect the work
        just done."""
        if self.view is not None:
            self._leave_lane()
        self._nav_browsing = True
        self._open_kwargs["source"] = None
        self.stage = "select"
        self._discovered = False
        self.cursor = 0
        self._paint_status("reading correction status…")
        fut = self.sess.list_sources()
        fut.add_done_callback(self.sources_listed.emit)

    def action_nav_spines(self) -> None:
        """Back to the chosen source's spine picker (fresh listing). Browse
        mode always shows the picker, single-spine sources included."""
        if self._spine_source is None:
            return
        if self.view is not None:
            self._leave_lane()
        self._nav_browsing = True
        sid, title = self._spine_source
        self._paint_status(f"spines · {title or sid[:12]}…")
        fut = self.sess.list_spines(sid, self._open_kwargs["rendition"])
        fut.add_done_callback(self.spines_listed.emit)

    def _leave_lane(self) -> None:
        """Lane teardown-lite: bookmark + audio down — the closeEvent half
        that leaves the stack alive. The seat itself is just dropped:
        open_spine re-points it (session.py) and a fresh CorrectionSession
        is minted on the next open, exactly like the old quit-and-relaunch."""
        self._autoplay_timer.stop()
        if self.player is not None:
            self.player.stop()
        self._stop_ticker()
        if self.editor.isVisible():
            self._close_editor()
        if self.view is not None:
            save_tui_state(self._graph_db_path, self.view.source_id,
                           self.cursor, speed=self.speed)
        self.view = None
        self.session_id = None
        self._marks = {}
        self._pending_proposal = None
        self._accept_cluster = None
        self._active_entity = None
        self._word_anchor = None
        self._overlay_pick = None
        self.cursor = 0

    def action_purpose_pick(self, n: int) -> None:
        if self.stage != "flywheel" or self._extract_busy:
            return
        if not (1 <= n <= len(self._purpose_vocab)):
            return
        p = self._purpose_vocab[n - 1]
        if p in self._include_purposes:
            self._include_purposes.discard(p)
        else:
            self._include_purposes.add(p)
        self._render()

    def _load_datasets(self) -> None:
        ws = resolve_workspace()
        root = (ws.root / "datasets") if ws is not None else Path("datasets")
        rows: List[Dict[str, Any]] = []
        try:
            files = sorted(root.glob("*/manifest.json"))
        except OSError:
            files = []
        for f in files:
            try:
                m = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if not (isinstance(m, dict) and m.get("format")
                    == "cjm-transcript-correction-core/dataset-manifest"):
                continue
            m["_path"] = str(f)
            rows.append(m)
        rows.sort(key=lambda m: float(m.get("created_at") or 0.0), reverse=True)
        self._datasets = rows

    def _load_runs(self) -> None:
        """Training-run manifests, newest first — manifest-driven discovery
        over <workspace>/training-runs/ (the PropsetIndex pattern named in
        79d1ab29 rung 2; format-tag routed, capability-agnostic)."""
        ws = resolve_workspace()
        root = ((ws.root / "training-runs") if ws is not None
                else Path("training-runs"))
        rows: List[Dict[str, Any]] = []
        try:
            files = sorted(root.glob("*/manifest.json"))
        except OSError:
            files = []
        for f in files:
            try:
                m = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if not (isinstance(m, dict) and m.get("run_id")
                    and str(m.get("format") or "")
                    .endswith("/training-run-manifest")):
                continue
            m["_path"] = str(f)
            rows.append(m)
        rows.sort(key=lambda m: float(m.get("created_at") or 0.0),
                  reverse=True)
        self._runs = rows

    def action_train_dataset(self) -> None:
        """T on the selected row: the modal run-config form (DEC 99280f79)
        over the adapter's manifest-carried schema (DEC 48eff28b). A DATASET
        row seeds schema defaults; a RUN row RE-RUNS THE RECIPE (df0b72c2 —
        the run's consumed dataset + its config snapshot adopted, so the
        modified dots show exactly how the recipe differs from defaults;
        the a1326d5b default-config trap dies here)."""
        if self.stage != "flywheel" or self._finetune_busy:
            return
        if not self._datasets:
            self._paint_status("no datasets — X extracts one first")
            return
        schema = adapter_config_schema(self.sess.manifests_dir,
                                       "audio_event_detection_finetune")
        i = self._fly_cursor
        if i < len(self._datasets):
            self.finetune_form.open_for(self._datasets[i], schema)
            return
        run = self._runs[min(i - len(self._datasets),
                             len(self._runs) - 1)]
        did = str(run.get("dataset_id") or "")
        dataset = next((m for m in self._datasets
                        if m.get("dataset_id") == did), None)
        if dataset is None:
            self._paint_status(f"run {run.get('run_id', '?')}: consumed "
                               f"dataset {did or '?'} is not in the list — "
                               "pick a dataset row instead")
            return
        self.finetune_form.open_for(
            dataset, schema, adopt=dict(run.get("config") or {}),
            adopt_label=str(run.get("run_id") or ""))

    def _launch_finetune(self, config: Dict[str, Any]) -> None:
        """The form's launch gesture: ONE finetune task through the
        capability seat (session.finetune_run — the task channel, not an
        in-window fold); the run manifest lands in the runs section when
        the Future resolves."""
        dataset = self.finetune_form.dataset
        path = str(dataset.get("_path") or "")
        self.finetune_form.close()
        if not path or self._finetune_busy:
            return
        self._finetune_busy = True
        self._render()
        fut = self.sess.finetune_run(self.event_capability, path,
                                     config or None,
                                     progress=self.progress_note.emit)
        fut.add_done_callback(self.finetune_done.emit)

    def _on_finetune_done(self, fut) -> None:
        self._finetune_busy = False
        try:
            res = fut.result() or {}
        except Exception as e:
            res = {"manifest": None, "error": str(e)}
        self._load_runs()
        self._render()
        if res.get("error"):
            self._paint_status(f"⚠ finetune failed: {res['error']}")
            return
        m = res.get("manifest") or {}
        self._paint_status(f"✓ finetune run {m.get('run_id', '?')} — "
                           "manifest landed")

    def action_extract_dataset(self) -> None:
        if self.stage != "flywheel" or self._extract_busy:
            return
        self._extract_busy = True
        self._flywheel_log = []
        self._render()
        self._submit_gesture(self._do_run_extract())

    async def _do_run_extract(self):
        def log(line: Any) -> None:
            self._flywheel_log.extend(str(line).splitlines() or [""])
            self.progress_note.emit("")
        try:
            manifest = await run_extract(self.sess.queue, self._graph_cap,
                                         ws=resolve_workspace(),
                                         manager=self.sess.manager,
                                         graph_db_path=self._graph_db_path,
                                         include_purposes=sorted(self._include_purposes),
                                         log=log)
            if manifest is None:
                log("nothing to extract")
        except (Exception, SystemExit) as e:
            # a library exit must paint, never take the window with it
            log(f"extract FAILED: {e}")
        finally:
            self._extract_busy = False
        self._load_datasets()
        return {}

    # ---- cancel / quit ---------------------------------------------------

    def action_cancel(self) -> None:
        if self.editor.isVisible():
            self._accept_cluster = None
            self._pending_proposal = None
            self._close_editor()
            self._render()
        elif self._word_anchor is not None:
            self._word_anchor = None
            self._render()
        elif self._overlay_pick is not None:
            self._overlay_pick = None
            self._render()
        else:
            self._autoplay_timer.stop()   # esc also cancels a pending debounced play
            if self.player is not None:
                self.player.stop()
            self._stop_ticker()
            self._render()

    def closeEvent(self, event) -> None:
        """ANY exit path: sidecar bookmark, audio down, seat + loop torn down
        blocking (the Textual action_quit_app contract)."""
        self._autoplay_timer.stop()
        if self.view is not None:
            save_tui_state(self._graph_db_path, self.view.source_id,
                           self.cursor, speed=self.speed)
        if self.player is not None:
            self.player.close()
            self.player = None
        self.sess.close()
        super().closeEvent(event)
