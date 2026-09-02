"""Qt shell for the transcript-correction workbench — a DIRECT PORT of
cjm-transcript-correction-tui's center-pinned correction loop onto PySide6
(DEC 0f11683d, the c4b0d6e5 lane's third migration): the same stages and
lanes, the same key vocabulary, the same commit-then-echo gestures over
correction-core's operation vocabulary; the graph stack + JobQueue +
SpineView seat live behind a private asyncio loop thread, and BOTH audio
decode paths ride SpanPlayer/QMediaPlayer (model-input WAV chunk spans and
original-media source spans — the sounddevice/WSOLA/ffmpeg-pipe stack
retires on this lane). Born on-graph."""

__version__ = "0.0.8"
