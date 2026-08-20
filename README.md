# cjm-transcript-correction-qt

<!-- generated from the context graph by `cjm-context-graph readme` — do not edit by hand; edit the graph (the urge to hand-edit = move it on-graph) -->

Qt shell for the transcript-correction workbench — the third workflow TUI migrated to the PySide6 lane (DEC c4b0d6e5 as amended by 2030586d; architecture 0f11683d — a DIRECT PORT). Imports the pure spine of cjm-transcript-correction-tui (SpineView + local-echo mutators, every gesture planner, the sidecar state module) and shares its CLI ladder (build_parser/resolve_settings), so both shells resolve the same stack and record indistinguishable corrections. The graph stack + JobQueue + SpineView seat run under Qt via CorrectionShellSession — a kit LoopThreadSession whose gesture lock serializes commit coroutines to completion (the donor's message-queue semantics); every gesture composes core commit calls + the local echo into one Future resolving through queued Signals. Paint = pure span-line builders (panes.py, the net-new extraction of the donor's self-bound rich.Text methods) materialized as HTML on a monospace QTextBrowser, center-pin math in character cells. Audio = SpanPlayer on QMediaPlayer for BOTH decode paths: model-input WAV chunk spans and the ORIGINAL media at source coordinates (seams, synthetic inserts, proposal auditions, overlay spans) — the sounddevice/WSOLA/ffmpeg-pipe stack retired on the lane.

## Modules

- **`cjm_transcript_correction_qt.__init__`** — Qt shell for the transcript-correction workbench — a DIRECT PORT of
- **`cjm_transcript_correction_qt.app`** — The Qt correction workbench: the same center-pinned segment walk, lane
- **`cjm_transcript_correction_qt.cli`** — Console-script driver for the Qt shell: the SAME argument surface and
- **`cjm_transcript_correction_qt.panes`** — Pure paint builders for the correction Qt shell — the Textual paint logic,
- **`cjm_transcript_correction_qt.session`** — The correction shell's jobs seam: graph stack + JobQueue + the SpineView

## API

### `cjm_transcript_correction_qt.app`

- `CorrectionWindow` _class_ — The correction loop under Qt — one window, the donor's stages/lanes.

### `cjm_transcript_correction_qt.cli`

- `main` _function_ — Resolve the shared launch surface, run the Qt correction window.

### `cjm_transcript_correction_qt.panes`

- `annotate_body` _function_ — The focused card's word-level paint in the annotate lane: the word
- `card_lines` _function_ — One segment card as styled span lines + the offset of its first body
- `cluster_style` _function_ — Stable per-cluster tint (dim — a proposal reads quieter than an
- `entity_name` _function_ — Display name for an entity id; provisional handles read with a leading
- `flywheel_lines` _function_ — The cross-source flywheel page paint (DEC 82c463fe): dataset manifests
- `flywheel_status` _function_
- `folded` _function_ — Is this position folded away right now? (z toggle; never in the
- `gate_chip` _function_ — The status-strip gate chip: empty when never asserted (the quiet
- `gutter_w` _function_ — The source-wide gutter width: sized ONCE from the last segment (the
- `lines_to_html` _function_ — Materialize span lines as one <pre> block for a monospace
- `picker_lines` _function_ — The 2ce81638 discovery stage: the graph's Sources with correction
- `picker_status` _function_
- `render_rows` _function_ — Center-pinned paint: the focused card's first body line pinned to the
- `selection_range` _function_ — The selected token range (inclusive), clamped: the v-anchor..cursor
- `spine_picker_lines` _function_ — The spine picker (DEC f1024568): one row per coexisting SKELETON.
- `status_line` _function_ — The unified status strip (DEC cc55a7b5): lane badge + purpose badge +
- `wordless_insert` _function_ — A certified-wordless inserted chunk: wordless CLASS and empty text
- `wrap_spans` _function_ — Word-wrap styled spans at a cell width (the Textual Text.wrap stand-in):

### `cjm_transcript_correction_qt.session`

- `CorrectionShellSession` _class_ — The loop-thread seat for the correction shell.

## Dependencies

**Depends on:** `PySide6`, `cjm-substrate`, `cjm-substrate-qt-kit`, `cjm-transcript-correction-core`
