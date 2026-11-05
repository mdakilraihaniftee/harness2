"""End-to-end safeguards for the zero-inference research experiments."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from harness2.benchmarks.jobbench import JobBenchAdapter
from harness2.core.proposer import Proposer
from harness2.core.spec import ChannelSpec
from research_pilots.offline_bench.cite_analysis import _baselines
from research_pilots.offline_bench.offline_guard import OfflineGuard, OfflineViolation
from research_pilots.offline_bench.run import RESULTS
from research_pilots.offline_bench.run import main as offline_main
from research_pilots.offline_bench.task_inventory import assert_sources_unchanged

REPO_ROOT = Path(__file__).resolve().parents[3]
PREVIOUS_SUMMARY = REPO_ROOT / "research_pilots/results/experiment_summary.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OfflineBenchTests(unittest.TestCase):
    """The suite is cheap enough to reproduce once for the whole test class."""

    @classmethod
    def setUpClass(cls):
        cls.previous_digest_before = _sha(PREVIOUS_SUMMARY)
        cls.exit_code = offline_main(["--offline", "--all"])
        cls.previous_digest_after = _sha(PREVIOUS_SUMMARY)
        cls.summary = json.loads((RESULTS / "experiment_summary.json").read_text())
        cls.inventory = cls.summary["task_inventory"]
        cls.pave = cls.summary["pave"]
        cls.cite = cls.summary["cite"]
        cls.replay = cls.summary["replay"]
        cls.models = cls.summary["model_integrity"]

    def test_offline_runner_blocks_provider_model_invocation(self):
        proposer = Proposer(ChannelSpec("opencode", "openai/offline-test"))
        with OfflineGuard() as guard, self.assertRaisesRegex(
            OfflineViolation, "model invocation"
        ):
            proposer.call("forbidden", None, "forbidden")
        self.assertEqual(guard.counters.external_model_calls, 1)

    def test_offline_runner_blocks_external_judge(self):
        with OfflineGuard() as guard, self.assertRaisesRegex(
            OfflineViolation, "judge invocation"
        ):
            JobBenchAdapter().score(Path("/not-used"), "not-used")
        self.assertEqual(guard.counters.external_judge_calls, 1)

    def test_completed_runner_has_zero_external_calls(self):
        self.assertEqual(self.exit_code, 0)
        self.assertEqual(self.summary["external_model_calls"], 0)
        self.assertEqual(self.summary["external_judge_calls"], 0)
        self.assertEqual(self.summary["network_calls"], 0)
        self.assertEqual(self.summary["provider_inference_cost_usd"], 0.0)

    def test_task_discovery_uses_installed_datasets(self):
        self.assertEqual(self.inventory["installed_task_counts"], {"jb": 65, "lab": 1143})
        self.assertEqual(self.inventory["sample_size"], {"jb": 6, "lab": 6})
        self.assertFalse(self.inventory["replacements"])
        self.assertTrue(all(Path(path).is_dir() for path in self.inventory["installed_paths"].values()))
        self.assertTrue(
            all(value != "UNKNOWN_LOCAL_REVISION" for value in self.inventory["installed_versions"].values())
        )

    def test_installed_task_inputs_remain_unchanged(self):
        assert_sources_unchanged(self.inventory)

    def test_existing_research_artifact_is_not_overwritten(self):
        self.assertEqual(self.previous_digest_before, self.previous_digest_after)

    def test_paired_worlds_use_identical_policy_inputs_when_intended(self):
        same = 0
        for case in self.pave["cases"]:
            if not case["byte_identical_visible_evidence"]:
                continue
            same += 1
            worlds = case["worlds"]
            self.assertEqual(
                worlds["GENUINE_SHIFT"]["visible_sha256"],
                worlds["EVIDENCE_DEFECT"]["visible_sha256"],
            )
            self.assertEqual(
                worlds["GENUINE_SHIFT"]["policy_decisions"],
                worlds["EVIDENCE_DEFECT"]["policy_decisions"],
            )
        self.assertEqual(same, self.pave["observationally_indistinguishable_pairs"])
        self.assertGreater(same, 0)

    def test_replay_variants_share_one_reference_record(self):
        for task in self.replay["tasks"]:
            self.assertTrue(task["variants_derive_from_same_reference"])
            self.assertEqual(len(task["reference_record_sha256"]), 64)

    def test_provenance_is_visible_only_in_intended_replay(self):
        for task in self.replay["tasks"]:
            variants = task["variants"]
            for name, record in variants.items():
                manifest = Path(record["context_root"]) / "EVIDENCE_MANIFEST.md"
                visible = "Evidence source identifier:" in manifest.read_text()
                self.assertEqual(visible, name == "degraded_with_provenance")
        shared = [
            case for case in self.pave["cases"]
            if case["condition"] == "repeated_shared_provenance"
        ]
        unlabelled = [
            case for case in self.pave["cases"]
            if case["condition"] == "repeated_misleading_observation"
        ]
        self.assertTrue(
            all(
                all(item.get("source_id") for item in case["worlds"]["GENUINE_SHIFT"]["visible_evidence"])
                for case in shared
            )
        )
        self.assertTrue(
            all(
                all("source_id" not in item for item in case["worlds"]["GENUINE_SHIFT"]["visible_evidence"])
                for case in unlabelled
            )
        )

    def test_hidden_oracles_are_excluded_and_candidates_reconstruct(self):
        self.assertTrue(self.replay["hidden_oracle_excluded"])
        self.assertTrue(self.replay["all_candidates_reconstruct"])
        for task in self.replay["tasks"]:
            for variant in task["variants"].values():
                self.assertTrue(all(variant["candidate_reconstruction"].values()))

    def test_invalid_edit_bundle_is_rejected(self):
        self.assertTrue(self.cite["invalid_conflict_control"]["rejected"])
        self.assertIn("conflicting edits", self.cite["invalid_conflict_control"]["error"])

    def test_hidden_utility_does_not_affect_deployable_baselines(self):
        for instance in self.cite["instances"]:
            original = _baselines(instance["rows"], 17)
            altered_rows = copy.deepcopy(instance["rows"])
            for index, row in enumerate(altered_rows.values()):
                row["hidden_utility"] = float(index % 2)
            altered = _baselines(altered_rows, 17)
            for name in original:
                if name != "oracle_exhaustive_analysis_only":
                    self.assertEqual(original[name], altered[name])

    def test_model_profiles_have_distinct_isolated_identities(self):
        self.assertTrue(self.models["all_fingerprints_distinct"])
        self.assertTrue(self.models["cross_model_cache_isolated"])
        selections = list(self.models["task_selection_identical_across_profiles"].values())
        manifests = list(self.models["model_independent_manifest_hashes"].values())
        self.assertTrue(all(value == selections[0] for value in selections))
        self.assertTrue(all(value == manifests[0] for value in manifests))

    def test_deterministic_demo_exercises_both_recursion_modes(self):
        demo = self.summary["deterministic_demo"]
        self.assertEqual(demo["status"], "PASS")
        self.assertTrue(demo["parallel_and_sequential_modes"])
        self.assertTrue(demo["cross_task_experience_reuse"])
        self.assertGreater(demo["selection_records"], 0)

    def test_output_provenance_categories_are_explicit(self):
        observed = {
            category
            for task in self.inventory["tasks"]
            for category in task["provenance_categories"]
        }
        observed.update(
            category
            for task in self.replay["tasks"]
            for category in task["provenance_categories"]
        )
        observed.update(
            category
            for instance in self.cite["instances"]
            for category in instance["provenance_categories"]
        )
        self.assertTrue(
            {
                "OFFICIAL_BENCHMARK_TASK",
                "DERIVED_BENCHMARK_TASK",
                "SYNTHETIC_REPLAY",
                "DETERMINISTIC_EXECUTION",
            }.issubset(observed)
        )


if __name__ == "__main__":
    unittest.main()
