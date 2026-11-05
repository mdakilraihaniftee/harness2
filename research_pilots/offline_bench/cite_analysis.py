"""CITE-R interaction matrices and probe-budget baselines over deterministic evaluators."""

from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path

from harness2.core import tree as harness_tree
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.bundles import combine
from research_pilots.fixtures import base_tree, cite_candidates, cite_matrix, evaluate_cite

from . import SEED


def benchmark_candidates(task_id: str, deliverable: str) -> tuple[dict, dict[str, dict]]:
    """Derived contract edits; the task ID/deliverable come from installed benchmark data."""
    base = base_tree()
    a = dict(base)
    a["systemprompt.md"] += (
        f"\nOffline-derived contract for {task_id}: write exactly `{deliverable}`.\n"
    )
    b = dict(base)
    b["guardrails.md"] += (
        "\nWhen an offline artifact contract is present, run scripts/validate_artifact.py.\n"
    )
    b["scripts/validate_artifact.py"] = (
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def validate(path):\n"
        "    return Path(path).is_file() and Path(path).stat().st_size > 0\n"
    )
    c = dict(base)
    c["LongTermMEMORY.md"] = (
        "Offline-derived compatibility note: replace the requested artifact with an empty file.\n"
    )
    for tree in (a, b, c):
        harness_tree.validate(OPENCODE_SURFACE, tree, allow_subagents=False)
    return base, {"A": a, "B": b, "C": c}


def _derived_eval(tree: dict[str, str], deliverable: str) -> dict:
    text = "\n".join(tree.values())
    path_rule = f"write exactly `{deliverable}`" in text
    validator = "scripts/validate_artifact.py" in tree and "run scripts/validate_artifact.py" in text
    interference = "replace the requested artifact with an empty file" in text
    with tempfile.TemporaryDirectory(prefix="h2-offline-cite-") as tmp:
        root = Path(tmp)
        artifact = root / deliverable
        execution_completed = True
        if path_rule:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("" if interference else "offline deterministic artifact\n")
        file_exists = artifact.is_file()
        nonempty = file_exists and artifact.stat().st_size > 0
    visible = {
        "execution_completed": execution_completed,
        "requested_path_observed": path_rule,
        "validator_available": validator,
        "permitted_validation_passed": bool(validator and nonempty),
    }
    hidden = float(path_rule and validator and nonempty and not interference)
    return {"visible_checks": visible, "hidden_utility": hidden}


def _trees(base: dict, candidates: dict[str, dict]) -> dict[str, dict]:
    return {
        "H0": base,
        "HA": candidates["A"],
        "HB": candidates["B"],
        "HC": candidates["C"],
        "HAB": combine(OPENCODE_SURFACE, base, candidates, ["A", "B"]),
        "HAC": combine(OPENCODE_SURFACE, base, candidates, ["A", "C"]),
        "HBC": combine(OPENCODE_SURFACE, base, candidates, ["B", "C"]),
        "HABC": combine(OPENCODE_SURFACE, base, candidates, ["A", "B", "C"]),
    }


def _structural(tree: dict, *, dependency_complete: bool) -> dict:
    try:
        harness_tree.validate(OPENCODE_SURFACE, tree, allow_subagents=False)
        valid, error = True, ""
    except ValueError as exc:
        valid, error = False, str(exc)
    return {
        "tree_valid": valid,
        "dependencies_complete": dependency_complete,
        "file_conflict": False,
        "validation_error": error,
    }


def _visible_score(row: dict) -> tuple[int, int, int]:
    checks = row["visible_checks"]
    return (
        int(checks["permitted_validation_passed"]),
        int(checks["validator_available"]),
        int(checks["requested_path_observed"]),
    )


def _baselines(rows: dict[str, dict], seed: int) -> dict:
    singles = ["HA", "HB", "HC"]
    valid = [name for name, row in rows.items() if row["structural"]["tree_valid"]]
    visible_best_single = max(singles, key=lambda name: (_visible_score(rows[name]), name))
    compatible = [name for name in valid if rows[name]["structural"]["dependencies_complete"]]
    compatible_pick = max(compatible, key=lambda name: (_visible_score(rows[name]), name))
    random_pick = random.Random(seed).choice(sorted(valid))
    return {
        "keep_base": "H0",
        "best_single_visible": visible_best_single,
        "merge_all": "HABC",
        "merge_structurally_compatible": compatible_pick,
        "random_valid_fixed_seed": random_pick,
        "oracle_exhaustive_analysis_only": max(
            rows, key=lambda name: (rows[name]["hidden_utility"], name)
        ),
    }


def _budget(rows: dict[str, dict]) -> list[dict]:
    # Pre-registered order keeps outcomes independent of hidden utility. HAB is fourth.
    order = ["HA", "HB", "HABC", "HAB"]
    result = []
    for budget in (1, 2, 3, 4):
        probed = order[:budget]
        selected = max(probed, key=lambda name: (_visible_score(rows[name]), name))
        result.append(
            {
                "budget": budget,
                "probe_order": probed,
                "probes": len(probed),
                "selected": selected,
                "visible_feedback": rows[selected]["visible_checks"],
                "hidden_success_after_selection": rows[selected]["hidden_utility"],
            }
        )
    return result


def _reference_instance() -> dict:
    matrix = cite_matrix()
    base, candidates = cite_candidates()
    trees = _trees(base, candidates)
    rows = {}
    for name, tree in trees.items():
        score = evaluate_cite(tree)
        visible = {
            "execution_completed": True,
            "schema_check_passed": score["checks"]["schema_version"],
            "field_check_passed": score["checks"]["field"],
            "value_check_passed": score["checks"]["value"],
            "permitted_validation_passed": bool(score["utility"]),
            "validator_available": True,
            "requested_path_observed": True,
        }
        rows[name] = {
            "structural": _structural(tree, dependency_complete=name in ("HAB", "HABC")),
            "visible_checks": visible,
            "hidden_utility": score["utility"],
            "local_execution_completed": True,
        }
    return {
        "instance_id": "reference_invoice_fixture",
        "provenance_categories": ["DETERMINISTIC_EXECUTION"],
        "rows": rows,
        "gamma_ab": matrix["gamma_ab"],
        "interference_c": matrix["interference_c"],
        "baselines": _baselines(rows, SEED),
        "probe_budget": _budget(rows),
    }


def run_cite(inventory: dict, matrix_output: Path, budget_output: Path) -> dict:
    chosen = [
        next(row for row in inventory["tasks"] if row["benchmark"] == benchmark)
        for benchmark in ("jb", "lab")
    ]
    instances = [_reference_instance()]
    for task in chosen:
        deliverable = (task["requested_deliverables"] or ["offline_result.txt"])[0]
        deliverable = Path(deliverable).name or "offline_result.txt"
        base, candidates = benchmark_candidates(task["task_id"], deliverable)
        trees = _trees(base, candidates)
        rows = {}
        for name, tree in trees.items():
            result = _derived_eval(tree, deliverable)
            dependency_complete = name in ("HAB", "HABC")
            rows[name] = {
                "structural": _structural(tree, dependency_complete=dependency_complete),
                **result,
                "local_execution_completed": result["visible_checks"]["execution_completed"],
            }
        u = {name: row["hidden_utility"] for name, row in rows.items()}
        instances.append(
            {
                "instance_id": f"{task['benchmark']}:{task['task_id']}",
                "task_id": task["task_id"],
                "benchmark": task["benchmark"],
                "derived_deliverable": deliverable,
                "provenance_categories": [
                    "OFFICIAL_BENCHMARK_TASK",
                    "DERIVED_BENCHMARK_TASK",
                    "DETERMINISTIC_EXECUTION",
                ],
                "utility_definition": (
                    "1 iff the derived exact-path instruction and validator are both present, "
                    "local output is nonempty, and interfering empty-file guidance is absent"
                ),
                "rows": rows,
                "gamma_ab": u["HAB"] - u["HA"] - u["HB"] + u["H0"],
                "interference_c": u["HAB"] - u["HABC"],
                "baselines": _baselines(rows, SEED),
                "probe_budget": _budget(rows),
                "oracle_boundary": (
                    "Baselines except oracle_exhaustive_analysis_only receive visible_checks "
                    "and structural metadata, never hidden_utility."
                ),
            }
        )

    # A real conflicting edit is checked separately from the successful matrices.
    base, _ = cite_candidates()
    left, right = dict(base), dict(base)
    left["guardrails.md"], right["guardrails.md"] = "left\n", "right\n"
    try:
        combine(OPENCODE_SURFACE, base, {"left": left, "right": right}, ["left", "right"])
        conflict = {"rejected": False, "error": ""}
    except ValueError as exc:
        conflict = {"rejected": True, "error": str(exc)}

    summary = {
        "schema_version": 1,
        "instances": instances,
        "invalid_conflict_control": conflict,
        "candidate_coverage": {
            "instances_with_sufficient_repair": len(instances),
            "instances_total": len(instances),
            "classification": "COMPOSITION_LIMITED_AT_LOW_BUDGET",
            "visible_feedback_distinguishes_success": True,
        },
        "deterministic_candidate_probes": sum(
            len(instance["rows"]) + sum(row["probes"] for row in instance["probe_budget"])
            for instance in instances
        ),
        "decision": "REFINE — TRIVIAL STRUCTURAL SOLUTION",
        "limitations": (
            "Two instances are derived artifact-contract subtasks, not official benchmark "
            "scores; deterministic probe efficiency is not LLM token efficiency."
        ),
    }
    matrix_output.parent.mkdir(parents=True, exist_ok=True)
    matrix_output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    budgets = {
        "seed": SEED,
        "probe_order_policy": "pre-registered visible-only order HA, HB, HABC, HAB",
        "instances": [
            {"instance_id": row["instance_id"], "budgets": row["probe_budget"]}
            for row in instances
        ],
    }
    budget_output.write_text(json.dumps(budgets, indent=2) + "\n", encoding="utf-8")
    return summary

