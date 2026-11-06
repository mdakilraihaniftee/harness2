"""Phase 6 free-model composer decisions over frozen research contexts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
REPORTS = ROOT / "reports"
RESULTS = ROOT / "results"
TRACES = ROOT / "traces"

SCHEMA_VERSION = 1
MODEL_CANDIDATES = (
    "openrouter/google/gemma-4-26b-a4b-it:free",
    "openrouter/nvidia/nemotron-3.5-lightning:free",
    "openrouter/recursive/flint-v1.0:free",
)

NAVIGATION_POLICY = """# RESEARCH NAVIGATION POLICY

`context/EVIDENCE_MANIFEST.md` is the authoritative, complete index for this controlled
composer decision. Its candidate patches are exact and reconstructable. After reading that
manifest, do not read referenced trajectories, artifacts, diffs, or candidate harness files;
read only destination files under `context/harness/` that you choose to edit. Proceed directly
to the composition decision and apply any chosen edits. Your final answer and
`output/answer.md` must literally start with `<notes>` and end with `</notes>`. Inside, choose
one literal verb (`kept`, `revised`, or `dropped`) for each line; never copy the placeholder
`kept|revised|dropped`. This controls navigation and protocol formatting only; every original
evidence-weighing and edit adoption rule remains unchanged.
""".strip()

