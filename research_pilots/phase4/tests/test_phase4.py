"""Acceptance coverage for the zero-inference Phase 4 composer replay."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

from harness2.benchmarks.jobbench import JobBenchAdapter
from harness2.benchmarks.lab import LabAdapter
from harness2.core.proposer import Proposer, Reply
from harness2.core.spec import ChannelSpec
from harness2.model_config import resolve_run_model_config
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.accounting import LiveBudget
from research_pilots.bundles import combine
from research_pilots.fixtures import cite_candidates, evaluate_cite
from research_pilots.manifest import manifest_edits, reconstruct
from research_pilots.offline_bench.offline_guard import OfflineGuard, OfflineViolation

from .. import REPO_ROOT, RESULTS
from ..audit import composer_cache_audit
from ..decision import classify_completion, parse_decision
from ..deliverables import extract_deliverables
from ..live_gate import _run_frozen_cite_gate
from ..live_gate import main as live_gate_main
from ..openrouter_agent_sandbox import provider_overlay
from ..openrouter_gateway import State
from ..replay import prepare_replays, repetition_identity
from ..run import main as phase4_main


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file()
    }


class Phase4AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prior = REPO_ROOT / "research_pilots/results"
        cls.prior_before = _tree_digest(prior)
        cls.exit_code = phase4_main(["--offline"])
        cls.prior_after = _tree_digest(prior)
        cls.validation = json.loads((RESULTS / "phase4_validation_results.json").read_text())
        cls.conditions = json.loads((RESULTS / "phase4_replay_conditions.json").read_text())
        cls.manifest = json.loads((RESULTS / "phase4_experiment_manifest.json").read_text())
        cls.pave = json.loads((RESULTS / "pave_diagnostic_accounting.json").read_text())
        cls.cite = json.loads((RESULTS / "cite_corrected_analysis.json").read_text())
        cls.inventory = json.loads((RESULTS / "corrected_task_inventory.json").read_text())

    def test_01_prompt_pack_identification(self):
        audit = self.manifest["prompt_audit"]
        self.assertEqual(audit["prompt_packs"]["jobbench"]["prompt_pack"], "tts")
        self.assertEqual(audit["prompt_packs"]["lab"]["prompt_pack"], "adapt")
        self.assertEqual(audit["prompt_packs"]["research"]["prompt_pack"], "adapt")
        self.assertTrue(audit["prompt_packs"]["research"]["repeated_base_failure_instruction"])
        self.assertTrue(audit["prompt_packs"]["research"]["failed_candidate_unsafe_instruction"])

    def test_02_prompt_hashes_are_stable(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first = composer_cache_audit(Path(one))["prompt_packs"]
            second = composer_cache_audit(Path(two))["prompt_packs"]
        for adapter in first:
            self.assertEqual(first[adapter]["aggregate_k1_sha256"], second[adapter]["aggregate_k1_sha256"])
            self.assertEqual(first[adapter]["aggregate_k3_sha256"], second[adapter]["aggregate_k3_sha256"])

    def test_03_k1_and_k3_contexts_are_valid(self):
        pave = [row for row in self.conditions if row["condition_id"].startswith("PAVE")]
        self.assertEqual({row["k"] for row in pave}, {1, 3})
        for row in self.conditions:
            root = Path(row["context_root"])
            self.assertTrue((root / "task.md").is_file())
            self.assertTrue((root / "harness").is_dir())
            self.assertTrue((root / "EVIDENCE_MANIFEST.md").is_file())
            self.assertEqual(sorted(row["candidate_pool"]), sorted(row["candidate_scopes"]))

    def test_04_frozen_reference_integrity_is_reproducible(self):
        before = {
            row["condition_id"]: (row["reference_hash"], row["context_hash"], row["manifest_hash"])
            for row in self.conditions
        }
        repeated = prepare_replays()
        after = {
            row["condition_id"]: (row["reference_hash"], row["context_hash"], row["manifest_hash"])
            for row in repeated
        }
        self.assertEqual(before, after)

    def test_05_repetition_identities_are_cache_independent(self):
        row = self.conditions[0]
        kwargs = {
            "experiment_id": row["experiment_id"],
            "condition_id": row["condition_id"],
            "task_id": row["task_id"],
            "model_fingerprint": row["model_configuration_fingerprint"],
            "prompt_hash": row["prompt_hash"],
            "reference_hash_value": row["reference_hash"],
        }
        one = repetition_identity(sample_id="sample-1", **kwargs)
        two = repetition_identity(sample_id="sample-2", **kwargs)
        self.assertNotEqual(one, two)
        self.assertEqual(one, repetition_identity(sample_id="sample-1", **kwargs))

    def test_06_cross_model_configurations_are_isolated(self):
        audit = self.manifest["prompt_audit"]
        self.assertTrue(audit["cross_model_fingerprints_distinct"])
        qwen = audit["model_configurations"]["qwen_target_offline"]["fingerprint"]
        vertex = audit["model_configurations"]["vertex_control_offline"]["fingerprint"]
        self.assertNotEqual(qwen, vertex)

    def test_07_hidden_oracles_are_absent(self):
        forbidden = ("hidden_utility", "required_bundle", "candidate a+b is correct")
        for row in self.conditions:
            root = Path(row["context_root"])
            text = "\n".join(
                path.read_text(encoding="utf-8", errors="replace").lower()
                for path in root.rglob("*")
                if path.is_file()
            )
            self.assertFalse([marker for marker in forbidden if marker in text])

    def test_08_pave_diagnostics_are_intermediate_actions(self):
        expected = {
            "initial_decision",
            "diagnostic_selected",
            "diagnostic_response",
            "final_decision",
            "diagnostic_queries",
            "diagnostic_cost",
            "unresolved",
            "final_correct",
        }
        traces = [
            trace
            for case in self.pave["cases"]
            for world in case["worlds"].values()
            for trace in world["policy_decisions"].values()
        ]
        self.assertTrue(all(expected <= trace.keys() for trace in traces))
        metric = self.pave["policy_metrics"]["diagnostic_first"]
        self.assertGreater(metric["diagnostic_queries"], 0)
        self.assertGreater(metric["unresolved_cases"], 0)
        self.assertEqual(
            metric["final_binary_decisions"] + metric["unresolved_cases"], metric["decisions"]
        )

    def test_09_all_sufficient_cite_repairs_are_accepted(self):
        self.assertEqual(set(self.cite["minimal_sufficient_repairs"]), {"HAB", "HAC"})
        successful = {
            row["harness"] for row in self.cite["rows"] if row["hidden_utility"] == 1
        }
        self.assertEqual(successful, set(self.cite["sufficient_repairs"]))

    def test_10_visible_validator_strength_is_separated(self):
        conditions = self.cite["validation_conditions"]
        self.assertFalse(conditions["V0"]["perfectly_predicts_hidden_success"])
        self.assertFalse(conditions["V1"]["perfectly_predicts_hidden_success"])
        self.assertTrue(conditions["V2"]["perfectly_predicts_hidden_success"])

    def test_11_real_task_deliverables_exclude_source_files(self):
        jb = JobBenchAdapter()
        for task_id in ("data_entry_keyers/task1", "court_clerks/task1"):
            record = extract_deliverables("jb", jb, task_id)
            source_names = {Path(name).name.casefold() for name in record["provided_source_files"]}
            outputs = {Path(name).name.casefold() for name in record["explicit_output_files"]}
            self.assertFalse(source_names & outputs)
        lab = LabAdapter()
        record = extract_deliverables("lab", lab, lab.tasks()[0])
        self.assertTrue(record["explicit_output_files"])
        self.assertTrue(record["deliverable_descriptions"])

    def test_12_manifest_patches_reconstruct_exact_candidates(self):
        for row in self.conditions:
            root = Path(row["context_root"])
            parsed = manifest_edits((root / "EVIDENCE_MANIFEST.md").read_text())
            base = _files(root / "harness")
            for candidate, edits in parsed.items():
                expected = _files(root / "pool" / candidate / "harness")
                self.assertEqual(reconstruct(base, edits), expected)

    def test_13_valid_edit_bundles_apply(self):
        base, candidates = cite_candidates()
        for names in (("A", "B"), ("A", "C")):
            tree = combine(OPENCODE_SURFACE, base, candidates, names)
            self.assertEqual(evaluate_cite(tree)["utility"], 1.0)

    def test_14_operational_fallback_is_not_keep_base(self):
        result = classify_completion(
            response="<notes>KEEP_BASE</notes>",
            tree_changed=False,
            tree_parseable=True,
            tree_valid=True,
            fell_back=True,
            evidence_accessed=True,
            step_exhausted=False,
        )
        self.assertEqual(result["decision"], "OPERATIONAL_FAILURE")
        self.assertFalse(result["valid_completed_decision"])

    def test_15_explicit_composer_decisions_are_parsed(self):
        self.assertEqual(parse_decision("<notes>KEEP_BASE</notes>", tree_changed=False), "KEEP_BASE")
        self.assertEqual(
            parse_decision(
                "<notes>revised -> inv1 -> rollout exposed missing schema</notes>",
                tree_changed=True,
            ),
            "EDIT_OR_MERGE",
        )
        self.assertEqual(parse_decision("done", tree_changed=False), "INVALID")

    def test_16_prompt_and_candidate_provenance_are_recorded(self):
        for row in self.conditions:
            self.assertIn(row["prompt_pack"], {"adapt", "tts"})
            self.assertEqual(len(row["prompt_hash"]), 64)
            self.assertTrue(row["candidate_pool"])
            self.assertIn("DETERMINISTIC_EXECUTION", row["provenance_categories"])
            self.assertIn("SYNTHETIC_REPLAY", row["provenance_categories"])

    def test_17_previous_research_results_are_preserved(self):
        self.assertEqual(self.prior_before, self.prior_after)
        self.assertFalse(self.validation["comparison"]["legacy_inventory_overwritten"])

    def test_18_offline_execution_fails_closed(self):
        proposer = Proposer(ChannelSpec("opencode", "openai/offline-test"))
        with OfflineGuard() as guard, self.assertRaises(OfflineViolation):
            proposer.call("forbidden", None, "forbidden")
        self.assertEqual(guard.counters.external_model_calls, 1)

    def test_19_deterministic_run_makes_no_external_calls(self):
        self.assertEqual(self.exit_code, 0)
        self.assertEqual(self.validation["external_model_calls"], 0)
        self.assertEqual(self.validation["external_judge_calls"], 0)
        self.assertEqual(self.validation["network_calls"], 0)
        self.assertEqual(self.validation["provider_inference_cost_usd"], 0.0)

    def test_20_usage_and_cost_schema_is_complete(self):
        expected = {
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "model_steps",
            "cost_usd",
            "wall_s",
            "cache_hit",
        }
        self.assertEqual(set(self.manifest["usage_schema"]), expected)
        self.assertEqual(self.manifest["usage_schema"]["cost_usd"], 0.0)

    def test_live_gate_is_fail_closed_without_paid_flag(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            live_gate_main(
                [
                    "cite-e1",
                    "--sample-id",
                    "test",
                    "--max-usd",
                    "1",
                    "--max-calls",
                    "2",
                ]
            )

    def test_qwen_gateway_and_agent_overlay_are_allowlisted(self):
        state = State("openrouter/qwen/test-model", 2, "never-written")
        self.assertEqual(state.model, "qwen/test-model")
        self.assertTrue(state.reserve())
        self.assertTrue(state.reserve())
        self.assertFalse(state.reserve())
        provider = (
            REPO_ROOT / "dependencies/opencode/packages/opencode/src/provider/provider.ts"
        ).read_text()
        overlaid = provider_overlay(provider)
        self.assertIn("/run/harness2-gateway/openrouter.sock", overlaid)
        self.assertNotIn("never-written", overlaid)

    def test_live_wrapper_uses_the_frozen_context_without_inference(self):
        controlled = next(row for row in self.conditions if row["condition_id"] == "CITE_V1")
        models = resolve_run_model_config(
            model="openrouter/qwen/test-model",
            judge_model="openrouter/qwen/test-model",
            env={"OPENROUTER_API_KEY": "offline-placeholder"},
        )

        def fake_call(_self, mission, context_dir, label, **kwargs):
            self.assertEqual(Path(context_dir), Path(controlled["context_root"]))
            self.assertIn("RESEARCH EVIDENCE INTERFACE", mission)
            self.assertIn("phase4-cite-e1", label)
            self.assertEqual(kwargs["harvest"], "context/harness")
            return Reply(
                label=label,
                text="<notes>KEEP_BASE</notes>",
                ok=True,
                cost_usd=0.0,
                wall_s=0.1,
                attempts=1,
                workspace=Path(controlled["context_root"]) / "harness",
                usage={"input_tokens": 10, "output_tokens": 2, "model_steps": 1},
            )

        trace = {
            "trace_files": [],
            "tool_names": ["read"],
            "tool_call_count": 1,
            "file_read_count": 1,
            "file_write_count": 0,
            "tool_error_count": 0,
            "evidence_manifest_accessed": True,
            "step_exhausted": False,
            "configured_step_limit": 20,
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "research_pilots.phase4.live_gate.install_trace_launcher"
        ), mock.patch(
            "research_pilots.phase4.live_gate._trace_summary", return_value=trace
        ), mock.patch.object(Proposer, "call", fake_call):
            output = Path(tmp) / "gate"
            output.mkdir()
            result = _run_frozen_cite_gate(
                controlled=controlled,
                models=models,
                identity="offline-test",
                budget=LiveBudget(max_usd=1, max_calls=2),
                steps=20,
                output=output,
                launcher=REPO_ROOT / "research_pilots/phase4/openrouter_agent_sandbox.py",
            )
        self.assertEqual(result["decision"], "KEEP_BASE")
        self.assertTrue(result["valid_research_result"])
        self.assertEqual(result["usage"]["model_steps"], 1)


if __name__ == "__main__":
    unittest.main()
