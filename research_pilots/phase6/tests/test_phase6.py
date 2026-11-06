"""No-network Phase 6 acceptance tests."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from research_pilots.fixtures import base_tree, cite_candidates, pave_retry_tree
from research_pilots.phase6 import MODEL_CANDIDATES, NAVIGATION_POLICY, RESULTS
from research_pilots.phase6.live import (
    _assert_gateway,
    _cite_classification,
    _gate_status,
    _pave_classification,
    _provider_usage,
)


class Phase6Tests(unittest.TestCase):
    def test_model_selection_order_is_fixed(self):
        self.assertEqual(
            MODEL_CANDIDATES,
            (
                "openrouter/google/gemma-4-26b-a4b-it:free",
                "openrouter/nvidia/nemotron-3.5-lightning:free",
                "openrouter/recursive/flint-v1.0:free",
            ),
        )

    def test_navigation_policy_is_neutral_and_hashed(self):
        lowered = NAVIGATION_POLICY.lower()
        self.assertIn("navigation and protocol formatting only", lowered)
        self.assertIn("adoption rule remains unchanged", lowered)
        for oracle in ("hidden_utility", "a+b", "correct candidate", "keep base"):
            self.assertNotIn(oracle, lowered)
        self.assertEqual(len(hashlib.sha256(NAVIGATION_POLICY.encode()).hexdigest()), 64)

    def test_navigation_policy_names_authoritative_manifest(self):
        self.assertIn("context/EVIDENCE_MANIFEST.md", NAVIGATION_POLICY)
        self.assertIn("do not read referenced trajectories", NAVIGATION_POLICY)
        self.assertIn("must literally start with `<notes>`", NAVIGATION_POLICY)

    def test_cite_classification_recognizes_base_and_singles(self):
        base, candidates = cite_candidates()
        self.assertEqual(_cite_classification(base, True), "BASE_UNCHANGED")
        self.assertEqual(_cite_classification(candidates["A"], True), "A_ONLY")
        self.assertEqual(_cite_classification(candidates["B"], True), "B_ONLY")

    def test_pave_classification_recognizes_harmful_retry(self):
        self.assertEqual(_pave_classification(base_tree(), True), "BASE_UNCHANGED")
        self.assertEqual(_pave_classification(pave_retry_tree(), True), "HARMFUL_RETRY_EDIT")

    def test_gate_status_distinguishes_step_exhaustion(self):
        result = {
            "valid_research_result": False,
            "tool_trace": {"step_exhausted": True},
            "transport_error": "",
        }
        self.assertEqual(_gate_status(result), "STEP_BUDGET_EXHAUSTED")

    def test_provider_usage_counts_actual_requests(self):
        got = _provider_usage(
            [
                {"cost_usd": 0, "input_tokens": 4, "actual_models": ["m:free"]},
                {"cost_usd": 0, "input_tokens": 6, "actual_models": ["m:free"]},
            ]
        )
        self.assertEqual(got["input_tokens"], 10)
        self.assertEqual(got["actual_models"], ["m:free"])

    def test_gateway_assertion_rejects_actual_model_mismatch(self):
        import tempfile

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "events.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "requested_model": "vendor/model:free",
                        "actual_models": ["vendor/paid"],
                        "cost_usd": 0,
                    }
                )
                + "\n"
            )
            with self.assertRaisesRegex(RuntimeError, "model mismatch"):
                _assert_gateway(path, "openrouter/vendor/model:free")

    def test_audited_selected_model_is_zero_price_and_installed(self):
        path = RESULTS / "model_audit.json"
        if not path.is_file():
            self.skipTest("read-only Phase 6 audit has not run")
        audit = json.loads(path.read_text())
        selected = next(
            row for row in audit["candidates"] if row["model_ref"] == audit["selected_model"]
        )
        self.assertTrue(selected["eligible"])
        self.assertTrue(selected["installed_catalog"])
        self.assertTrue(selected["endpoint_metadata"]["eligible"])

    def test_audit_contains_no_credentials(self):
        path = RESULTS / "model_audit.json"
        if not path.is_file():
            self.skipTest("read-only Phase 6 audit has not run")
        text = path.read_text().lower()
        for marker in ("authorization", "bearer ", "sk-or-"):
            self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
