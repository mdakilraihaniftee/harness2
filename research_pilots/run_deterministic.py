#!/usr/bin/env python3
"""Generate and validate all no-model warm-up artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

from harness2.core import context
from harness2.core.ledger import Ledger
from harness2.core.spec import RunView
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.adapter import PilotAdapter
from research_pilots.bundles import combine
from research_pilots.evidence import CONDITIONS, condition, materialize_views, record_digest
from research_pilots.fixtures import (
    TASK_PAVE_NO_FAULT,
    base_tree,
    cite_candidates,
    cite_matrix,
    evaluate_cite,
    execute_pave,
    pave_retry_tree,
    reference_shift_tree,
    write_execution,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "research_pilots/results"
RUNS = ROOT / "research_pilots/runs/deterministic"
CONFIG = {"seed": 17, "live_model_calls": 0, "conditions": list(CONDITIONS)}


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def run_view(label: str, run_dir: Path) -> RunView:
    return RunView(label, f"research/{label}", run_dir, ok=True, delivered=True)


def write_summary(rows: list[dict]) -> None:
    payload = {
        "schema_version": 1,
        "configuration": CONFIG,
        "experiments": rows,
        "live": {"status": "NOT_RUN", "reason": "deterministic phase only", "calls": []},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "experiment_summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    fields = [
        "idea",
        "experiment",
        "condition",
        "evidence_kind",
        "status",
        "utility",
        "notes",
    ]
    with (RESULTS / "experiment_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fields} for row in rows)


def main() -> int:
    shutil.rmtree(RUNS, ignore_errors=True)
    RUNS.mkdir(parents=True)
    (RESULTS / "config.json").parent.mkdir(parents=True, exist_ok=True)
    (RESULTS / "config.json").write_text(json.dumps(CONFIG, indent=2) + "\n")

    raw_root = RESULTS / "pave/raw"
    shutil.rmtree(raw_root, ignore_errors=True)
    labels = ["base1", "base2", "base3", "inv1", "dom1"]
    trees = {
        "base1": base_tree(),
        "base2": base_tree(),
        "base3": base_tree(),
        "inv1": pave_retry_tree(),
        "dom1": base_tree(),
    }
    records = {label: execute_pave(label, trees[label]) for label in labels}
    run_dirs = {label: write_execution(raw_root, record) for label, record in records.items()}
    raw_digests = {label: record_digest(record) for label, record in records.items()}

    conditions = [condition(name, labels) for name in CONDITIONS]
    views = materialize_views(records, conditions, RESULTS / "pave/evidence_views")
    if raw_digests != views["record_digests"]:
        raise AssertionError("raw record digests changed during rendering")

    base_dir = RUNS / "harnesses/base"
    inv_dir = RUNS / "harnesses/inv1"
    dom_dir = RUNS / "harnesses/dom1"
    from harness2.core import tree as harness_tree

    harness_tree.write_tree(OPENCODE_SURFACE, base_tree(), base_dir, stubs=False)
    harness_tree.write_tree(OPENCODE_SURFACE, pave_retry_tree(), inv_dir, stubs=False)
    harness_tree.write_tree(OPENCODE_SURFACE, base_tree(), dom_dir, stubs=False)
    base_views = [run_view(label, run_dirs[label]) for label in labels[:3]]
    pool = [
        ("inv1", inv_dir, run_view("inv1", run_dirs["inv1"])),
        ("dom1", dom_dir, run_view("dom1", run_dirs["dom1"])),
    ]
    context_digests = {}
    for evidence in conditions:
        adapter = PilotAdapter(RUNS / evidence.name, TASK_PAVE_NO_FAULT, base_tree(), evidence)
        built = context.build(
            RUNS / "contexts" / evidence.name,
            adapter,
            TASK_PAVE_NO_FAULT,
            base_views,
            harness_dir=base_dir,
            pool=pool,
        )
        context.assert_no_leak_paths(built.root, adapter.spec.leak_globs)
        context_digests[evidence.name] = tree_digest(built.root)
    if context_digests["A2_systematic"] != context_digests["A2_matched_independent"]:
        raise AssertionError("matched visible evidence unexpectedly differs")

    shift_base = execute_pave("shift_base", base_tree(), shifted=True)
    shift_repair = execute_pave("shift_repair", reference_shift_tree(), shifted=True)
    (RESULTS / "pave/positive_control.json").write_text(
        json.dumps({"base": shift_base, "reference_repair": shift_repair}, indent=2) + "\n"
    )
    if shift_base["hidden_utility"] >= shift_repair["hidden_utility"]:
        raise AssertionError("positive-control repair has no advantage")

    cite = cite_matrix()
    cite_result = {key: value for key, value in cite.items() if key != "trees"}
    cite_root = RESULTS / "cite"
    cite_root.mkdir(parents=True, exist_ok=True)
    (cite_root / "interaction_matrix.json").write_text(json.dumps(cite_result, indent=2) + "\n")
    for name, tree in cite["trees"].items():
        harness_tree.write_tree(OPENCODE_SURFACE, tree, cite_root / "harnesses" / name, stubs=False)
    oracle = ROOT / "research_pilots/oracles"
    oracle.mkdir(parents=True, exist_ok=True)
    (oracle / "cite_reference.json").write_text(
        json.dumps({"required_bundle": ["A", "B"], "expected_utility": 1.0}, indent=2) + "\n"
    )
    (oracle / "pave_hidden_state.json").write_text(
        json.dumps({"success": "one committed transaction and zero duplicate attempts"}, indent=2)
        + "\n"
    )
    if any("oracle" in path.name for path in (RUNS / "contexts").rglob("*")):
        raise AssertionError("oracle path entered an improver context")

    ledger = Ledger("agg", "synthetic", 1)
    for label in ("base1", "inv1", "dom1", "agg1"):
        ledger.rollout(label)
    for label in ("inv1", "dom1", "agg1"):
        ledger.session(label)
    ledger.assert_identity()
    (RESULTS / "baseline_budget.json").write_text(json.dumps(ledger.to_dict(), indent=2) + "\n")

    base, candidates = cite_candidates()
    hab = combine(OPENCODE_SURFACE, base, candidates, ["A", "B"])
    rows = [
        {
            "idea": "PAVE-R",
            "experiment": "evidence_intervention",
            "condition": name,
            "evidence_kind": "SIMULATED_RENDERING",
            "status": "PASS",
            "utility": "",
            "notes": f"context_sha256={context_digests[name]}",
        }
        for name in CONDITIONS
    ]
    rows += [
        {
            "idea": "PAVE-R",
            "experiment": "positive_control",
            "condition": "schema_shift",
            "evidence_kind": "DETERMINISTIC_EXECUTION",
            "status": "PASS",
            "utility": shift_repair["hidden_utility"],
            "notes": "reference repair beats base",
        },
        {
            "idea": "CITE-R",
            "experiment": "joint_bundle",
            "condition": "HAB",
            "evidence_kind": "DETERMINISTIC_EXECUTION",
            "status": "PASS",
            "utility": evaluate_cite(hab)["utility"],
            "notes": f"gamma_ab={cite['gamma_ab']}",
        },
        {
            "idea": "CITE-R",
            "experiment": "interference",
            "condition": "HABC",
            "evidence_kind": "DETERMINISTIC_EXECUTION",
            "status": "PASS",
            "utility": cite["scores"]["HABC"]["utility"],
            "notes": f"interference_c={cite['interference_c']}",
        },
    ]
    write_summary(rows)
    (RESULTS / "rejected_fixtures.json").write_text(
        json.dumps(
            [
                {
                    "name": "receipt_reveals_state_v0",
                    "status": "REJECTED_BEFORE_EXECUTION",
                    "reason": "artifact exposed commit state, making trajectory corruption trivial to refute",
                },
                {
                    "name": "single_natural_language_hint_v0",
                    "status": "REJECTED_BEFORE_LIVE_EXECUTION",
                    "reason": "an unconstrained LLM could compensate without a harness change",
                },
            ],
            indent=2,
        )
        + "\n"
    )
    print(f"Deterministic pilots passed. Results: {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
