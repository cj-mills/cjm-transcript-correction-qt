"""The correction app's chunk-escalation gesture (ruling 0b4d5cfa (6), work item
7a5e9c84), pure and Qt-free: the cursor segment resolves to its coarse chunk by
SOURCE TIME (the verb's --at-time; the same bisect the ChunkRef join uses), the
respine-chunk argv the app shells out with, the refusal classes it answers, the
pending-escalation record E keeps between its two phases, and the cursor the reload
lands on (the same source time the walk stood at).

ONE key, two phases: `E` on a chunk with no pending escalation RENDERS the prompt
(clipboard + the chunk's audio folder); `E` again on that chunk IMPORTS the model's
transcript through the verb. The ratified `I` is the walk lane's insert_labeled
already, so the import rides the second E instead of shadowing an existing gesture
(recorded on the build decision)."""

import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DECOMP_CORE_SCRIPT = "cjm-transcript-decomp-core"   # The verb host's console script
DECOMP_CORE_ENV = "cjm-transcript-decomp-core"      # Its conda env (env name = core repo name)
CHUNK_TOLERANCE_S = 0.5  # A pending escalation still matches the cursor's chunk within this much of its bounds


def resolve_decomp_core(
    envs_root: Optional[str] = None,  # Conda envs dir override (tests; None = derive from this interpreter)
) -> Optional[str]:  # Absolute executable path, or None
    """This env's bin first (the correction env installs decomp-core beside the
    correction core — env truth), then PATH, then the sibling env's bin under the
    envs root derived from sys.prefix's parent (never hardcoded, 6dfe00e9)."""
    own = Path(sys.executable).parent / DECOMP_CORE_SCRIPT
    if own.exists():
        return str(own)
    found = shutil.which(DECOMP_CORE_SCRIPT)
    if found:
        return found
    root = Path(envs_root) if envs_root else Path(sys.prefix).parent
    cand = root / DECOMP_CORE_ENV / "bin" / DECOMP_CORE_SCRIPT
    return str(cand) if cand.exists() else None


def respine_argv(
    source_id: str,               # The open spine's Source id
    at_time: float,               # A source time inside the chunk (the cursor segment's start)
    skeleton_hash: Optional[str], # The open spine's skeleton hash (None = the source's default live spine)
    text_file: str,               # The paste on disk
    model_id: str,                # The external model id
    prompt_hash: str,             # The prompt template's hash the E render printed
    graph_db_path: Optional[str], # The app's effective graph db (explicit-db-path rule 027bbe56)
    manifests_dir: str,           # Capability manifests directory
    strand: bool = False,         # Strand the non-transferable dependents (after the operator said so)
) -> List[str]:  # The respine-chunk argv (without the executable)
    """The verb's argv for the correction seat: --at-time from the cursor, the spine
    pinned by its hash, the explicit db path."""
    argv = ["respine-chunk", "--source", str(source_id), "--at-time", f"{float(at_time):.3f}",
            "--text-file", str(text_file), "--model-id", str(model_id), "--prompt-hash", str(prompt_hash),
            "--text-source", "paste", "--reason", "escalation", "--manifests-dir", str(manifests_dir)]
    if skeleton_hash:
        argv += ["--skeleton", str(skeleton_hash)]
    if graph_db_path:
        argv += ["--graph-db-path", str(graph_db_path)]
    if strand:
        argv.append("--strand")
    return argv


def refusal_line(stdout: str) -> Optional[str]:  # The verb's 'REFUSED: …' line, or None
    for line in (stdout or "").splitlines():
        if line.startswith("REFUSED:"):
            return line[len("REFUSED:"):].strip()
    return None


def classify_refusal(stdout: str) -> Optional[str]:  # "dependents" | "other" | None
    """DEPENDENTS = ask the operator to strand and re-run; OTHER = show it verbatim."""
    r = refusal_line(stdout)
    if r is None:
        return None
    low = r.lower()
    if "carry dependents" in low or "would strand" in low or "no chunk-scoped transfer" in low:
        return "dependents"
    return "other"


def pending_matches(
    pending: Optional[Dict[str, Any]],  # The E render's record ({"chunk_range": (s, e), ...}) or None
    t: Optional[float],                 # The cursor segment's start time
    tol: float = CHUNK_TOLERANCE_S,
) -> bool:  # True when the cursor still stands in the escalated chunk (second E = import)
    """Whether the pending escalation is the cursor's chunk (pure)."""
    if not pending or t is None:
        return False
    s, e = pending.get("chunk_range") or (None, None)
    if s is None or e is None:
        return False
    return float(s) - tol <= float(t) <= float(e) + tol


def cursor_for_time(
    segments: List[Any],  # The reloaded spine's segments (start_time attr; inserts included)
    t: Optional[float],   # The source time the walk stood at
) -> int:  # The cursor index to land on (the first segment starting at or after t; the last when t is past the end)
    """Where the reload lands (pure; 0b4d5cfa (6): the walk resumes where it stood)."""
    if not segments or t is None:
        return 0
    want = float(t) - 1e-3
    for i, s in enumerate(segments):  # a linear scan: an insert without times must not break a bisect
        if s.start_time is not None and float(s.start_time) >= want:
            return i
    return len(segments) - 1


def readout_from(stdout: str) -> str:  # The verb's headline for the status strip
    """The 'respined chunk …' line, else the last non-empty line."""
    lines = [l for l in (stdout or "").splitlines() if l.strip()]
    for l in lines:
        if l.startswith("respined chunk") or l.startswith("chunk "):
            return l
    return lines[-1] if lines else "done"
