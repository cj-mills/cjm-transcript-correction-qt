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
import json
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from cjm_substrate.core.manager import CapabilityManager
from cjm_substrate_qt_kit.loopthread import LoopThreadSession
from cjm_transcript_correction_core.cli import (commit_wordless_transfer, load_capabilities,
                                                plan_wordless_export, plan_wordless_transfer,
                                                resolve_source_node, write_wordless_propset)
from cjm_transcript_correction_core.graph import (list_source_spines, list_speaker_entities,
                                                  session_purposes_by_source, start_session)
from cjm_transcript_correction_core.spine import list_sources, open_stack, source_status, SpineView
from cjm_transcription_core.curation import collection_members, collection_order, list_collections


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
                 view_opener: Callable[..., Any] = SpineView.open_on,
                 seat_manager_factory: Callable[..., Any] = CapabilityManager,
                 seat_loader: Callable[..., Any] = load_capabilities):
        super().__init__(timeout=timeout)
        self.manifests_dir = manifests_dir
        self.graph_capability = graph_capability
        self._stack_opener = stack_opener
        self._view_opener = view_opener
        self._seat_manager_factory = seat_manager_factory
        self._seat_loader = seat_loader
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

    def collections(self) -> Future:
        """The graph's Collections + membership + order (the hub's grouping
        corpus): the source picker groups its rows under these (8d29f0f0).
        Resolves to {"collections", "members", "order"} — curation.py shapes."""
        return self.submit(self._collections())

    async def _collections(self):
        cols = await list_collections(self.queue, self.graph_capability)
        members: Dict[str, List[Any]] = {}
        order: Dict[str, List[str]] = {}
        for c in cols:
            ms = await collection_members(self.queue, self.graph_capability,
                                          c["id"])
            members[c["id"]] = ms
            ordered, _ = await collection_order(self.queue,
                                                self.graph_capability, c["id"],
                                                [m for m, _ in ms])
            order[c["id"]] = ordered
        return {"collections": cols, "members": members, "order": order}

    # ---- the finetune seat (DEC 48eff28b) --------------------------------

    def finetune_run(self, event_capability: str, dataset_manifest: str,
                     config: Optional[Dict[str, Any]] = None,
                     progress: Optional[Callable[[str], None]] = None) -> Future:
        """One finetune run through the capability task channel: load the
        event capability on a FRESH manager (the graph stack stays
        untouched), execute audio_event_detection_finetune/finetune —
        dataset manifest pointer in, TrainingRunManifest dict out — and
        tear the seat down in finally (the decomp propose-seat recipe,
        1cfe6d0f). Resolves to {"manifest": dict|None, "error": str|None} —
        a library exit resolves the Future, never kills the loop."""
        return self.submit(self._finetune_run(event_capability,
                                              dataset_manifest, config,
                                              progress))

    async def _finetune_run(self, event_capability, dataset_manifest,
                            config, progress):
        manager = None
        manifest: Optional[Dict[str, Any]] = None
        error: Optional[str] = None
        try:
            if progress:
                progress("finetune: opening capability seat…")
            manager = self._seat_manager_factory(
                search_paths=[Path(self.manifests_dir)])
            await asyncio.to_thread(self._seat_loader, manager,
                                    [event_capability])
            if progress:
                progress("finetune: training… (worker run — the manifest "
                         "lands when it finishes)")
            manifest = await manager.execute_capability_task_async(
                event_capability, "audio_event_detection_finetune",
                "finetune", dataset_manifest=dataset_manifest,
                **({"config": config} if config else {}))
        except (Exception, SystemExit) as e:
            error = str(e)
        finally:
            if manager is not None:
                try:
                    await asyncio.to_thread(manager.unload_capability,
                                            event_capability)
                except Exception:
                    pass
        return {"manifest": manifest, "error": error}

    # ---- the spine seat --------------------------------------------------

    def open_spine(self, source_id: str, title: str,
                   *, rendition: Optional[str], skeleton: Optional[str],
                   journal_path: Any, purpose: Optional[str],
                   actor_sources: Optional[List[str]] = None,
                   actor: str = "human") -> Future:
        """Open one Source's CHOSEN spine on the already-open stack, mint the
        graph CorrectionSession every commit stamps, and load the speaker
        Entity registry (source-spanning, people-scale). Resolves to
        {"view", "session_id", "entities"}; the view stays loop-owned — the
        shell reads it for paint, mutates it only through submitted verbs.
        `actor` stamps the session-start journal row (finding ac878d68)."""
        return self.submit(self._open_spine(source_id, title, rendition,
                                            skeleton, journal_path, purpose,
                                            actor_sources, actor))

    async def _open_spine(self, source_id, title, rendition, skeleton,
                          journal_path, purpose, actor_sources, actor="human"):
        view = await self._view_opener(self.manager, self.queue,
                                       self.graph_capability, source_id, title,
                                       rendition=rendition, skeleton=skeleton)
        sess = await start_session(view.queue, view.graph_id,
                                   actor_sources or [view.source_id],
                                   journal_path=journal_path, purpose=purpose,
                                   actor=actor)
        entities = await list_speaker_entities(view.queue, view.graph_id)
        self.view = view
        self.session_id = sess.id
        return {"view": view, "session_id": sess.id, "entities": entities}

    # ---- the respine seat (9af9793a: spine picker x / t) ------------------

    def export_wordless(self, source_id: str, *, rendition: Optional[str],
                        from_skeleton: str, out_root: Any, ws: Any) -> Future:
        """x on the spine picker: export one spine's effective wordless
        layer as a proposal set under out_root (<workspace>/proposals) —
        the export-wordless-propset engine in-process on the open stack
        (plan_wordless_export + write_wordless_propset). Resolves to the
        write receipt + {"donors","word_bearing"}; a library exit resolves
        the Future as RuntimeError, never kills the loop."""
        return self.submit(self._export_wordless(source_id, rendition,
                                                 from_skeleton, out_root, ws))

    async def _export_wordless(self, source_id, rendition, from_skeleton,
                               out_root, ws):
        try:
            sid, _title, media_path = await resolve_source_node(
                self.queue, self.graph_capability, source_id)
            plan = await plan_wordless_export(
                self.queue, self.graph_capability, sid,
                from_skeleton=from_skeleton, rendition=rendition)
            res = write_wordless_propset(
                plan, out_root=Path(out_root), source_id=sid,
                media_path=media_path, from_skeleton=from_skeleton,
                rendition=rendition, ws=ws)
        except SystemExit as e:
            raise RuntimeError(str(e) or "export refused") from e
        res["donors"] = len(plan["donors"])
        res["word_bearing"] = plan["word_bearing"]
        return res

    def transfer_plan(self, source_id: str, *, rendition: Optional[str],
                      from_skeleton: str, to_skeleton: str,
                      tolerance: float = 0.05) -> Future:
        """t on the spine picker, phase 1: the transfer-wordless DRY-RUN
        plan (plan_wordless_transfer — reads only; the same dict the CLI
        prints) for the TransferDialog to render before anything commits."""
        return self.submit(self._transfer_plan(source_id, rendition,
                                               from_skeleton, to_skeleton,
                                               tolerance))

    async def _transfer_plan(self, source_id, rendition, from_skeleton,
                             to_skeleton, tolerance):
        try:
            return await plan_wordless_transfer(
                self.queue, self.graph_capability, source_id,
                from_skeleton=from_skeleton, to_skeleton=to_skeleton,
                rendition=rendition, tolerance=tolerance)
        except SystemExit as e:
            raise RuntimeError(str(e) or "transfer refused") from e

    def transfer_commit(self, source_id: str, plan: Dict[str, Any], *,
                        journal_path: Any, actor: str) -> Future:
        """t on the spine picker, phase 2: COMMIT the rendered plan
        (commit_wordless_transfer — one CorrectionSession, journaled through
        the sidecar like every walk gesture), serialized through the gesture
        lock so no walk gesture interleaves with the batch."""
        return self.run_serial(commit_wordless_transfer(
            self.queue, self.graph_capability, source_id, plan,
            journal_path=journal_path, actor=actor))

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


def adapter_config_schema(manifests_dir: str,  # Capability manifests directory
                          task_name: str,      # Adapter task, e.g. "audio_event_detection_finetune"
                          ) -> Dict[str, Any]:  # The adapter's config_schema ({} = not found / pre-upgrade)
    """Host-side read of a task adapter's config schema from its REGISTRATION
    manifest (unit=adapter, routed by task_name) — the DEC 48eff28b form-
    generation seam: the launch form renders without importing the worker
    env. A pre-upgrade manifest (no config_schema key) reads as {}."""
    try:
        files = sorted(Path(manifests_dir).glob("*.json"))
    except OSError:
        return {}
    for f in files:
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if (isinstance(data, dict) and data.get("unit") == "adapter"
                and data.get("task_name") == task_name):
            schema = data.get("config_schema")
            return schema if isinstance(schema, dict) else {}
    return {}
