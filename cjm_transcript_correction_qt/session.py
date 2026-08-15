"""The correction shell's jobs seam: graph stack + JobQueue + the SpineView
seat behind a private asyncio loop thread (DEC 0f11683d — the
CapabilitySession/DecompSession pattern with correction verbs).

The Textual shell opened the stack INSIDE the app "so the JobQueue lives on
Textual's event loop"; under Qt that loop is this session's daemon thread.
Named class CorrectionShellSession, NOT CorrectionSession — correction-core
already uses "CorrectionSession" for the graph-node concept every commit is
stamped with, and the seam must not shadow the vocabulary it drives.

Verbs cover the open ladder (stack -> discovery -> spine seat); every
correction GESTURE instead composes core commit calls + the SpineView local
echo into ONE coroutine the shell submits through the inherited `submit()` —
the echo runs loop-side before the Future resolves, so the repaint that
follows resolution always sees the echoed view. No blocked-reason poll:
correction loads no heavy model stack (the open cost is the graph capability
worker + the query batch). Deliberately Qt-free (stdlib + spine imports
only): testable headless, openers injectable."""

import asyncio
from concurrent.futures import Future
from typing import Any, Callable, Dict, List, Optional

from cjm_substrate_qt_kit.loopthread import LoopThreadSession
from cjm_transcript_correction_core.graph import (list_source_spines, list_speaker_entities,
                                                  session_purposes_by_source, start_session)
from cjm_transcript_correction_tui.spine import list_sources, open_stack, source_status, SpineView


class CorrectionShellSession(LoopThreadSession):
    """The loop-thread seat for the correction shell.

    start() spins the loop (kit LoopThreadSession); open_stack() bootstraps
    the graph capability + JobQueue and resolves the effective db;
    discovery verbs feed the pickers; open_spine() re-points the SpineView
    seat, mints the graph CorrectionSession, and loads the speaker registry —
    one Future each. close() runs on_close() on the loop (seat/queue
    teardown), then stops the thread. One instance per window."""

    thread_name = "correction-session"

    def __init__(self, manifests_dir: str,   # Capability manifests directory
                 *, graph_capability: str = "cjm-capability-graph-sqlite",
                 timeout: float = 600.0,     # graph worker may cold-start
                 stack_opener: Callable[..., Any] = open_stack,
                 view_opener: Callable[..., Any] = SpineView.open_on):
        super().__init__(timeout=timeout)
        self.manifests_dir = manifests_dir
        self.graph_capability = graph_capability
        self._stack_opener = stack_opener
        self._view_opener = view_opener
        self.manager: Optional[Any] = None   # the open stack (loop-owned)
        self.queue: Optional[Any] = None
        self.db: Optional[str] = None        # effective graph db path
        self.view: Optional[Any] = None      # the SpineView seat (loop-owned)
        self.session_id: Optional[str] = None
        self._gesture_lock: Optional[asyncio.Lock] = None  # minted on the loop

    # ---- gesture serialization ------------------------------------------

    def run_serial(self, coro) -> Future:
        """Submit one GESTURE coroutine, serialized to completion before the
        next runs. Bare submit() interleaves at await points (asyncio tasks),
        but the donor's Textual message queue ran each action handler to
        completion before dispatching the next key — the commit-then-echo
        consistency every gesture assumes. The lock restores exactly that."""
        return self.submit(self._serial(coro))

    async def _serial(self, coro):
        if self._gesture_lock is None:
            self._gesture_lock = asyncio.Lock()
        async with self._gesture_lock:
            return await coro

    # ---- the open ladder -------------------------------------------------

    def open_stack(self, graph_db_path: Optional[str]) -> Future:
        """Bootstrap the graph capability stack + JobQueue (2ce81638 db
        resolution: explicit path wins, else the workspace-scoped persisted
        config answers). Resolves to {"db": effective_path}."""
        return self.submit(self._open_stack(graph_db_path))

    async def _open_stack(self, graph_db_path):
        try:
            self.manager, self.queue, db = await self._stack_opener(
                graph_db_path, manifests_dir=self.manifests_dir,
                graph_capability=self.graph_capability)
        except SystemExit as e:
            # load_capabilities exits on a missing capability, and a library
            # exit must resolve the Future, never kill the loop thread.
            raise RuntimeError(str(e) or "capability load failed") from e
        self.db = str(db)
        return {"db": self.db}

    def list_sources(self) -> Future:
        """The graph's Source nodes — the discovery corpus (2ce81638)."""
        return self.submit(list_sources(self.queue, self.graph_capability))

    def statuses(self, source_ids: List[str]) -> Future:
        """Picker chrome in one Future: per-source correction status at a
        glance + the session-purpose mix by source (d915d545 a)."""
        return self.submit(self._statuses(source_ids))

    async def _statuses(self, source_ids):
        status: Dict[str, Dict[str, int]] = {}
        for sid in source_ids:
            status[sid] = await source_status(self.queue,
                                              self.graph_capability, sid)
        purposes = await session_purposes_by_source(self.queue,
                                                    self.graph_capability)
        return {"status": status, "purposes": purposes}

    def purposes(self) -> Future:
        """A FRESH purpose-mix read (the flywheel page re-reads on entry —
        the mount-time read is skipped by unique --source opens, 2026-08-09)."""
        return self.submit(session_purposes_by_source(self.queue,
                                                      self.graph_capability))

    def list_spines(self, source_id: str,
                    rendition: Optional[str]) -> Future:
        """The source's coexisting skeleton spines (DEC f1024568)."""
        return self.submit(list_source_spines(self.queue,
                                              self.graph_capability, source_id,
                                              rendition_selector=rendition))

    # ---- the spine seat --------------------------------------------------

    def open_spine(self, source_id: str, title: str,
                   *, rendition: Optional[str], skeleton: Optional[str],
                   journal_path: Any, purpose: Optional[str],
                   actor_sources: Optional[List[str]] = None) -> Future:
        """Open one Source's CHOSEN spine on the already-open stack, mint the
        graph CorrectionSession every commit stamps, and load the speaker
        Entity registry (source-spanning, people-scale). Resolves to
        {"view", "session_id", "entities"}; the view stays loop-owned — the
        shell reads it for paint, mutates it only through submitted verbs."""
        return self.submit(self._open_spine(source_id, title, rendition,
                                            skeleton, journal_path, purpose,
                                            actor_sources))

    async def _open_spine(self, source_id, title, rendition, skeleton,
                          journal_path, purpose, actor_sources):
        view = await self._view_opener(self.manager, self.queue,
                                       self.graph_capability, source_id, title,
                                       rendition=rendition, skeleton=skeleton)
        sess = await start_session(view.queue, view.graph_id,
                                   actor_sources or [view.source_id],
                                   journal_path=journal_path, purpose=purpose)
        entities = await list_speaker_entities(view.queue, view.graph_id)
        self.view = view
        self.session_id = sess.id
        return {"view": view, "session_id": sess.id, "entities": entities}

    # ---- teardown --------------------------------------------------------

    async def on_close(self) -> None:
        """Kit close() hook: the seat owns stack teardown once a spine opened
        (view.close()); a picker-stage quit stops the bare queue instead —
        the Textual action_quit_app contract, verbatim."""
        try:
            if self.view is not None:
                await self.view.close()
            elif self.queue is not None:
                await self.queue.stop()
        except Exception:
            pass
        self.view = None
        self.queue = None
        self.manager = None
