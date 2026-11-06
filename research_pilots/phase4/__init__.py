"""Controlled composer-only replay preparation for Phase 4 research."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
CONTEXTS = ROOT / "contexts"
FIXTURES = ROOT / "fixtures"
REPORTS = ROOT / "reports"
RESULTS = ROOT / "results"

SCHEMA_VERSION = 1
SEED = 17

