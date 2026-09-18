# cjm-transcript-correction-qt

<!-- generated from the context graph by `cjm-context-graph readme` — do not edit by hand; edit the graph (the urge to hand-edit = move it on-graph) -->

Qt shell for the transcript-correction workbench — the third workflow TUI migrated to the PySide6 lane (DEC c4b0d6e5 as amended by 2030586d; architecture 0f11683d — a DIRECT PORT). Imports the pure spine of cjm-transcript-correction-tui (SpineView + local-echo mutators, every gesture planner, the sidecar state module) and shares its CLI ladder (build_parser/resolve_settings), so both shells resolve the same stack and record indistinguishable corrections. The graph stack + JobQueue + SpineView seat run under Qt via CorrectionShellSession — a kit LoopThreadSession whose gesture lock serializes commit coroutines to completion (the donor's message-queue semantics); every gesture composes core commit calls + the local echo into one Future resolving through queued Signals. Paint = pure span-line builders (panes.py, the net-new extraction of the donor's self-bound rich.Text methods) materialized as HTML on a monospace QTextBrowser, center-pin math in character cells. Audio = SpanPlayer on QMediaPlayer for BOTH decode paths: model-input WAV chunk spans and the ORIGINAL media at source coordinates (seams, synthetic inserts, proposal auditions, overlay spans) — the sounddevice/WSOLA/ffmpeg-pipe stack retired on the lane.

## Modules

- **`cjm_transcript_correction_qt.__init__`** — Qt shell for the transcript-correction workbench — a DIRECT PORT of
- **`cjm_transcript_correction_qt.app`** — The Qt correction workbench: the same center-pinned segment walk, lane
- **`cjm_transcript_correction_qt.cli`** — Console-script driver for the Qt shell: the SAME argument surface and
- **`cjm_transcript_correction_qt.escalation`** — The correction app's chunk-escalation gesture (ruling 0b4d5cfa (6), work item
- **`cjm_transcript_correction_qt.event_payload`** — The EVENT-SPAN payload of the kit HITL confirm component (55bcc3c5, the
- **`cjm_transcript_correction_qt.filtering`** — The FILTER lane's state + pure builders (work item 55bcc3c5, the filtering
- **`cjm_transcript_correction_qt.finetune_form`** — Modal finetune-launch form (DECs 48eff28b + 99280f79) on the kit
- **`cjm_transcript_correction_qt.panes`** — Pure paint builders for the correction Qt shell — the Textual paint logic,
- **`cjm_transcript_correction_qt.respine_dialog`** — Modal transfer dialog for the spine picker (work item 9af9793a — the
- **`cjm_transcript_correction_qt.session`** — The correction shell's jobs seam: graph stack + JobQueue + the SpineView
- **`cjm_transcript_correction_qt.spanlane`** — The ANNOTATE lane's proposal-driven MODE (DEC d52d105f, design bbf8bafd (h)):

## API

### `cjm_transcript_correction_qt.app`

- `CorrectionWindow` _class_ — The correction loop under Qt — one window, the donor's stages/lanes.

### `cjm_transcript_correction_qt.cli`

- `main` _function_ — Resolve the shared launch surface, run the Qt correction window.

### `cjm_transcript_correction_qt.escalation`

- `classify_refusal` _function_ — DEPENDENTS = ask the operator to strand and re-run; OTHER = show it verbatim.
- `cursor_for_time` _function_ — Where the reload lands (pure; 0b4d5cfa (6): the walk resumes where it stood).
- `pending_matches` _function_ — Whether the pending escalation is the cursor's chunk (pure).
- `readout_from` _function_ — The 'respined chunk …' line, else the last non-empty line.
- `refusal_line` _function_
- `resolve_decomp_core` _function_ — This env's bin first (the correction env installs decomp-core beside the
- `respine_argv` _function_ — The verb's argv for the correction seat: --at-time from the cursor, the spine
- `spine_text_between` _function_ — The escalation prompt's LIVE slot text (finding c63cd2e3, user ruling

### `cjm_transcript_correction_qt.event_payload`

- `accept_shape` _function_ — The shape the a-gesture takes on this row (the propose lane's own
- `event_items` _function_ — Kit worklist items for the pending event proposals.
- `event_key` _function_ — The worklist key: the proposal id when the set carries one, else the
- `event_payload_lines` _function_ — The event PayloadCard: label / tier / span / duration / anchor index /
- `event_provenance` _function_
- `event_rows` _function_ — (anchor position, proposal) pairs for every pending event proposal,
- `event_verdicts` _function_ — The strip's arguments for the propose lane: pending per tier (the

### `cjm_transcript_correction_qt.filtering`

- `FilterLane` _class_ — The lane's state for ONE open spine: the sets found for it (newest
- `load_filter_lane` _function_ — Loop-side loader: the sets for this source + spine, the live strata
- `load_pack` _function_ — The pack a set cites, when the workspace still holds it (None = quote-only).

### `cjm_transcript_correction_qt.finetune_form`

- `FinetuneFormDialog` _class_ — The finetune run-config form: schema-driven rows over a chosen

### `cjm_transcript_correction_qt.panes`

- `annotate_body` _function_ — The focused card's word-level paint in the annotate lane: the word
- `card_lines` _function_ — One segment card as styled span lines + the offset of its first body
- `cluster_style` _function_ — Stable per-cluster tint (dim — a proposal reads quieter than an
- `default_pins` _function_ — The hint line's default 3-5 verbs per stage/lane — what shows before
- `entity_name` _function_ — Display name for an entity id; provisional handles read with a leading
- `flywheel_detail` _function_ — The focused flywheel row's drill block: a dataset's full class
- `flywheel_rows` _function_ — The cross-source flywheel page (DEC 82c463fe; restructured per
- `flywheel_status_chip` _function_ — flywheel_status minus the keybar tail — the chips half only
- `folded` _function_ — Is this position folded away right now? (z toggle; never in the
- `gate_chip` _function_ — The status-strip gate chip: empty when never asserted (the quiet
- `gutter_w` _function_ — The source-wide gutter width: sized ONCE from the last segment (the
- `hint_entries` _function_ — The declarative hint model (DEC 2a42c028): the active stage/lane's
- `lines_to_html` _function_ — Materialize span lines as one <pre> block for a monospace
- `picker_detail` _function_ — The focused source's identity block (2e0928f2 propagated to the
- `picker_rows` _function_ — The 2ce81638 discovery stage as kit PickerList rows (8d29f0f0):
- `picker_status_chip` _function_ — picker_status minus the keybar tail — the chips half only
- `render_rows` _function_ — Center-pinned paint: the focused card's first body line pinned to the
- `selection_range` _function_ — The selected token range (inclusive), clamped: the v-anchor..cursor
- `spine_picker_rows` _function_ — The spine picker (DEC f1024568) as kit rows: one item per coexisting
- `status_chips` _function_ — The strip's permanent chips (DEC 2a42c028): status_line's identity/
- `status_line` _function_ — The unified status strip (DEC cc55a7b5): lane badge + purpose badge +
- `wordless_insert` _function_ — A certified-wordless inserted chunk: wordless CLASS and empty text
- `wrap_spans` _function_ — Word-wrap styled spans at a cell width (the Textual Text.wrap stand-in):

### `cjm_transcript_correction_qt.respine_dialog`

- `TransferDialog` _class_ — The spine picker's transfer verb: phase `pick` (donor list) →
- `plan_lines` _function_ — The plan render (pure): what the CLI's --dry-run prints, shaped for

### `cjm_transcript_correction_qt.session`

- `CorrectionShellSession` _class_ — The loop-thread seat for the correction shell.
- `adapter_config_schema` _function_ — Host-side read of a task adapter's config schema from its REGISTRATION

### `cjm_transcript_correction_qt.spanlane`

- `SpanLane` _class_ — The mode's state for ONE open spine: the span sets found for it (newest
- `gate_echo` _function_ — The local echo of a span-lane watermark assertion.
- `load_span_lane` _function_ — Loop-side loader (the filter lane's mirror, format-gated to SPAN sets):

## Dependencies

**Depends on:** `PySide6`, `cjm-substrate`, `cjm-substrate-qt-kit`, `cjm-transcript-correction-core`, `cjm-transcript-decomp-core`, `cjm-transcription-core`
