"""Zero-paid-inference validation for the frozen Phase 4 composer contexts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
REPORTS = ROOT / "reports"
RESULTS = ROOT / "results"
TRACES = ROOT / "traces"

SCHEMA_VERSION = 1
PREFERRED_MODEL = "openrouter/qwen/qwen3-coder:free"
FALLBACK_MODEL = "openrouter/cohere/north-mini-code:free"

