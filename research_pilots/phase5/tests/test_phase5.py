"""Zero-network acceptance coverage for Phase 5 safety and classification."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_pilots.phase4.decision import classify_completion
from research_pilots.phase5 import FALLBACK_MODEL, PREFERRED_MODEL
from research_pilots.phase5.live import ZeroBudget, _classify_gate
from research_pilots.phase5.provider_audit import AuditBlocked, validate_zero_pricing
from research_pilots.phase5.zero_cost_gateway import (
    State,
    constrain_payload,
    response_telemetry,
)


def model(**updates):
    value = {
        "id": "vendor/code:free",
        "name": "Code Free",
        "pricing": {"prompt": "0", "completion": "0", "request": "0"},
        "supported_parameters": ["tools", "tool_choice", "max_tokens"],
    }
    value.update(updates)
    return value


class Phase5Tests(unittest.TestCase):
    def test_exact_free_model_passes(self):
        got = validate_zero_pricing(model(), expected_id="vendor/code:free")
        self.assertTrue(got["all_advertised_prices_zero"])

    def test_paid_price_fails_closed(self):
        with self.assertRaises(AuditBlocked):
            validate_zero_pricing(
                model(pricing={"prompt": "0", "completion": "0.0001"}),
                expected_id="vendor/code:free",
            )

    def test_unknown_price_fails_closed(self):
        with self.assertRaises(AuditBlocked):
            validate_zero_pricing(
                model(pricing={"prompt": "0", "completion": None}),
                expected_id="vendor/code:free",
            )

    def test_non_free_identifier_fails(self):
        with self.assertRaises(AuditBlocked):
            validate_zero_pricing(model(id="vendor/code"), expected_id="vendor/code")

    def test_tool_support_is_required(self):
        with self.assertRaises(AuditBlocked):
            validate_zero_pricing(
                model(supported_parameters=["max_tokens"]), expected_id="vendor/code:free"
            )

    def test_gateway_forces_zero_ceiling_and_no_fallback(self):
        got = constrain_payload({"model": "vendor/code:free"}, "vendor/code:free")
        self.assertFalse(got["provider"]["allow_fallbacks"])
        self.assertEqual(got["provider"]["max_price"]["prompt"], 0)
        self.assertTrue(got["usage"]["include"])

    def test_gateway_rejects_model_level_fallback(self):
        with self.assertRaisesRegex(ValueError, "fallback"):
            constrain_payload(
                {"model": "vendor/code:free", "models": ["vendor/paid"]},
                "vendor/code:free",
            )

    def test_gateway_rejects_model_mismatch(self):
        with self.assertRaisesRegex(ValueError, "allowlist"):
            constrain_payload({"model": "vendor/paid"}, "vendor/code:free")

    def test_usage_and_cost_are_parsed_from_sse(self):
        body = (
            'data: {"model":"vendor/code:free","usage":{"prompt_tokens":4,'
            '"completion_tokens":2,"cost":0}}\n\ndata: [DONE]\n'
        ).encode()
        got = response_telemetry(body)
        self.assertEqual(got["actual_models"], ["vendor/code:free"])
        self.assertEqual(got["input_tokens"], 4)
        self.assertEqual(got["cost_usd"], 0)

    def test_positive_cost_stops_gateway(self):
        with tempfile.TemporaryDirectory() as root:
            state = State("vendor/code:free", 2, "unused", Path(root) / "events.jsonl")
            self.assertTrue(state.reserve())
            state.record({"cost_usd": 0.01})
            self.assertFalse(state.reserve())

    def test_zero_budget_rejects_positive_cost(self):
        budget = ZeroBudget(max_calls=1)
        with self.assertRaisesRegex(RuntimeError, "positive"):
            budget.record("x", 0.01)

    def test_gate_classification_separates_interface_failure(self):
        completion = classify_completion(
            response="", tree_changed=False, tree_parseable=False, tree_valid=False,
            fell_back=True, evidence_accessed=False, step_exhausted=False,
        )
        result = {
            "valid_research_result": False,
            "tool_trace": {"step_exhausted": False},
            "transport_error": "empty reply",
            "completion": completion,
        }
        self.assertEqual(_classify_gate(result), "INTERFACE_FAILURE")

    def test_exact_configured_models_are_fixed(self):
        self.assertEqual(PREFERRED_MODEL, "openrouter/qwen/qwen3-coder:free")
        self.assertEqual(FALLBACK_MODEL, "openrouter/cohere/north-mini-code:free")
        self.assertNotEqual(FALLBACK_MODEL, "openrouter/free")

    def test_saved_audit_has_no_secret_fields(self):
        path = Path(__file__).parents[1] / "results/model_availability.json"
        if not path.is_file():
            self.skipTest("read-only audit has not been run")
        serialized = json.dumps(json.loads(path.read_text())).lower()
        for marker in ("authorization", "bearer ", "sk-or-"):
            self.assertNotIn(marker, serialized)


if __name__ == "__main__":
    unittest.main()
