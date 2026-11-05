"""Deterministic intervention, isolation, bundle, and accounting tests."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from harness2.core import tree as harness_tree
from harness2.core.ledger import Ledger
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.accounting import LiveBudget
from research_pilots.bundles import combine
from research_pilots.evidence import condition, record_digest, render_record
from research_pilots.fixtures import (
    base_tree,
    cite_candidates,
    cite_matrix,
    execute_pave,
)
from research_pilots.manifest import explicit_decision, manifest_edits, reconstruct
from research_pilots.prepare_phase2 import RESULT_ROOT, RUN_ROOT, digest_existing
from research_pilots.prepare_phase2 import main as prepare_phase2
from research_pilots.record_agent_trace import tool_event
from research_pilots.run_phase2_live import main as phase2_live


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.base_record = execute_pave("base1", base_tree())

    def test_clean_evidence_is_truthful(self):
        text = render_record(self.base_record, condition("A0_clean", ["base1"]))
        self.assertIn("transaction recorded successfully", text)
        self.assertNotIn("failed before commit", text)

    def test_corruption_changes_only_selected_label(self):
        a1 = condition("A1_isolated", ["base1", "base2"])
        other = dict(self.base_record, label="base2")
        self.assertIn("failed before commit", render_record(self.base_record, a1))
        self.assertIn("recorded successfully", render_record(other, a1))

    def test_rendering_does_not_mutate_raw_record(self):
        record = copy.deepcopy(self.base_record)
        before = record_digest(record)
        render_record(record, condition("A2_systematic", ["base1"]))
        self.assertEqual(before, record_digest(record))

    def test_condition_cache_tokens_are_distinct(self):
        names = ("A0_clean", "A1_isolated", "A2_systematic", "A2_matched_independent")
        tokens = {condition(name, ["base1", "base2"]).cache_token for name in names}
        self.assertEqual(len(tokens), len(names))

    def test_same_record_can_create_different_views(self):
        clean = render_record(self.base_record, condition("A0_clean", ["base1"]))
        corrupt = render_record(self.base_record, condition("A2_systematic", ["base1"]))
        self.assertNotEqual(clean, corrupt)

    def test_oracle_names_match_leak_guards(self):
        leaks = ("oracle.json", "hidden_state.json")
        self.assertTrue(any("oracle" in item for item in leaks))
        self.assertTrue(any("hidden_state" in item for item in leaks))

    def test_joint_edit_combination_applies_both_files(self):
        base, candidates = cite_candidates()
        merged = combine(OPENCODE_SURFACE, base, candidates, ["A", "B"])
        self.assertIn("schema_version=2", merged["systemprompt.md"])
        self.assertIn("multiply dollars by 100", merged["skills/invoice_rules/SKILL.md"])

    def test_invalid_dependency_incomplete_bundle_is_rejected(self):
        base, _ = cite_candidates()
        invalid = dict(base)
        invalid["skills/untriggered/SKILL.md"] = (
            "---\nname: untriggered\ndescription: Never loaded\n---\nDo something.\n"
        )
        with self.assertRaisesRegex(ValueError, "never named"):
            harness_tree.validate(OPENCODE_SURFACE, invalid, allow_subagents=False)

    def test_bundle_supports_file_addition_and_deletion(self):
        base = base_tree()
        base["scripts/obsolete.py"] = "print('obsolete')\n"
        add = dict(base)
        add["scripts/helper.py"] = "def cents(value):\n    return value * 100\n"
        delete = dict(base)
        del delete["scripts/obsolete.py"]
        merged = combine(
            OPENCODE_SURFACE,
            base,
            {"add": add, "delete": delete},
            ["add", "delete"],
        )
        self.assertIn("scripts/helper.py", merged)
        self.assertNotIn("scripts/obsolete.py", merged)

    def test_conflicting_file_edits_are_rejected(self):
        base = base_tree()
        left = dict(base)
        right = dict(base)
        left["guardrails.md"] = "left\n"
        right["guardrails.md"] = "right\n"
        with self.assertRaisesRegex(ValueError, "conflicting edits"):
            combine(OPENCODE_SURFACE, base, {"left": left, "right": right}, ["left", "right"])

    def test_interaction_and_interference_are_real(self):
        result = cite_matrix()
        self.assertEqual(result["gamma_ab"], 1.0)
        self.assertEqual(result["interference_c"], 1.0)
        self.assertEqual(result["scores"]["HAB"]["utility"], 1.0)
        self.assertEqual(result["scores"]["HABC"]["utility"], 0.0)

    def test_baseline_budget_identity_still_holds(self):
        ledger = Ledger("agg", "fixture", 1)
        for label in ("base1", "inv1", "dom1", "agg1"):
            ledger.rollout(label)
        for label in ("inv1", "dom1", "agg1"):
            ledger.session(label)
        ledger.assert_identity()

    def test_research_live_calls_are_separately_capped(self):
        budget = LiveBudget(max_usd=20, max_calls=1)
        budget.record("one", 0.5, idea="PAVE-R")
        with self.assertRaisesRegex(RuntimeError, "call cap"):
            budget.require_capacity()

    def test_fixed_seed_configuration_round_trips(self):
        from research_pilots.run_deterministic import CONFIG

        self.assertEqual(CONFIG["seed"], 17)
        self.assertEqual(CONFIG["live_model_calls"], 0)

    def test_reference_oracle_is_outside_context_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context_root = root / "context"
            oracle = root / "oracles/oracle.json"
            context_root.mkdir()
            oracle.parent.mkdir()
            oracle.write_text("secret")
            self.assertNotIn(context_root, oracle.parents)


class Phase2ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare_phase2()
        cls.validation = json.loads((RESULT_ROOT / "manifest_validation.json").read_text())

    def test_manifest_has_correct_candidate_ids(self):
        self.assertEqual(self.validation["cite"]["candidate_ids"], ["dom1", "inv1"])

    def test_candidate_file_mapping_is_exact_and_reconstructable(self):
        context_root = RUN_ROOT / "cite/context/cite_compact"
        base = {
            path.relative_to(context_root / "harness").as_posix(): path.read_text()
            for path in (context_root / "harness").rglob("*")
            if path.is_file()
        }
        parsed = manifest_edits((context_root / "EVIDENCE_MANIFEST.md").read_text())
        self.assertEqual(set(parsed), {"dom1", "inv1"})
        for candidate_id, edits in parsed.items():
            expected = {
                path.relative_to(context_root / "pool" / candidate_id / "harness").as_posix(): path.read_text()
                for path in (context_root / "pool" / candidate_id / "harness").rglob("*")
                if path.is_file()
            }
            self.assertEqual(reconstruct(base, edits), expected)

    def test_original_evidence_is_preserved(self):
        root = RUN_ROOT / "cite/context/cite_compact"
        self.assertEqual(
            digest_existing(root), self.validation["cite"]["original_evidence_digest"]
        )

    def test_manifest_has_no_hidden_oracle_markers(self):
        forbidden = (
            "hidden_utility",
            "expected_utility",
            "required_bundle",
            "candidate a+b is correct",
            "reference repair",
        )
        for path in (RESULT_ROOT / "manifests").glob("*/EVIDENCE_MANIFEST.md"):
            text = path.read_text().lower()
            self.assertFalse([marker for marker in forbidden if marker in text])

    def test_condition_tokens_are_distinct(self):
        rows = list(self.validation["pave"].values()) + [self.validation["cite"]]
        tokens = [row["condition_token"] for row in rows]
        self.assertEqual(len(tokens), len(set(tokens)))

    def test_manifest_size_is_bounded_and_reported(self):
        rows = list(self.validation["pave"].values()) + [self.validation["cite"]]
        self.assertTrue(all(0 < row["estimated_tokens"] <= 4_000 for row in rows))

    def test_workspace_can_access_every_reference(self):
        cases = {"cite_e1": RUN_ROOT / "cite/context/cite_compact"}
        cases.update(
            {
                name: RUN_ROOT / "pave" / name / "context/pave_compact"
                for name in self.validation["pave"]
            }
        )
        for name, root in cases.items():
            metadata = json.loads(
                (RESULT_ROOT / "manifests" / name / "metadata.json").read_text()
            )
            for ref in metadata["referenced_paths"]:
                self.assertTrue((root / ref.removeprefix("context/")).exists(), ref)

    def test_provenance_is_only_in_enabled_manifest(self):
        without = (
            RESULT_ROOT / "manifests/A2_systematic_no_provenance/EVIDENCE_MANIFEST.md"
        ).read_text()
        with_provenance = (
            RESULT_ROOT / "manifests/A2_systematic_with_provenance/EVIDENCE_MANIFEST.md"
        ).read_text()
        self.assertNotIn("Evidence source identifier", without)
        self.assertIn("Evidence source identifier: `renderer-source-01`", with_provenance)

    def test_explicit_decision_requires_notes_grammar(self):
        self.assertTrue(explicit_decision("<notes>kept -> A -> failed in 1/1 rollout</notes>"))
        self.assertFalse(explicit_decision("KEEP_BASE"))
        self.assertFalse(explicit_decision("<notes>maybe merge A</notes>"))

    def test_trace_parser_records_tool_and_file_input(self):
        event = {
            "part": {
                "type": "tool",
                "tool": "read",
                "state": {
                    "status": "completed",
                    "input": {"filePath": "/tmp/work/context/EVIDENCE_MANIFEST.md"},
                    "output": "manifest",
                },
            }
        }
        parsed = tool_event(event, Path("/tmp/work"))
        self.assertEqual(parsed["tool"], "read")
        self.assertIn("$WORKSPACE/context/EVIDENCE_MANIFEST.md", parsed["input"])
        self.assertTrue(parsed["had_output"])

    def test_phase2_live_requires_explicit_paid_flag(self):
        with self.assertRaises(SystemExit):
            phase2_live(["cite-e1", "--max-usd", "1", "--max-calls", "1"])


if __name__ == "__main__":
    unittest.main()
