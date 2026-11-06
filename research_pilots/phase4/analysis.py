"""Corrected deterministic analyses used to qualify composer-only replay conditions."""

from __future__ import annotations

import itertools
from copy import deepcopy

from harness2.core import tree as harness_tree
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.bundles import combine
from research_pilots.fixtures import cite_candidates, evaluate_cite


def _name(parts: tuple[str, ...]) -> str:
    return "H0" if not parts else "H" + "".join(parts)


def _visible(score: dict, condition: str) -> dict:
    checks = score["checks"]
    if condition == "V0":
        return {"tree_valid": True, "execution_completed": True}
    if condition == "V1":
        return {
            "tree_valid": True,
            "execution_completed": True,
            "schema_version_present": checks["schema_version"],
            "required_field_present": checks["field"],
        }
    if condition == "V2":
        return {
            "tree_valid": True,
            "execution_completed": True,
            "schema_version_present": checks["schema_version"],
            "required_field_present": checks["field"],
            "amount_value_check": checks["value"],
            "no_extra_fields": checks["no_extra_fields"],
        }
    raise ValueError(condition)


def _perfect(rows: list[dict], condition: str) -> bool:
    buckets: dict[tuple, set[float]] = {}
    for row in rows:
        signature = tuple(sorted(row["visible_feedback"][condition].items()))
        buckets.setdefault(signature, set()).add(row["hidden_utility"])
    return all(len(values) == 1 for values in buckets.values())


def cite_corrected_analysis() -> dict:
    """Enumerate every A/B/C bundle and accept every verified minimal repair."""
    base, candidates = cite_candidates()
    rows = []
    for size in range(4):
        for parts in itertools.combinations(("A", "B", "C"), size):
            tree = base if not parts else combine(OPENCODE_SURFACE, base, candidates, parts)
            score = evaluate_cite(tree)
            harness_tree.validate(OPENCODE_SURFACE, tree, allow_subagents=False)
            changed = harness_tree.diff_summary(OPENCODE_SURFACE, base, tree)
            rows.append(
                {
                    "harness": _name(parts),
                    "edit_set": list(parts),
                    "structural_validity": True,
                    # This is declared dependency metadata, not a success gate. HAC is allowed
                    # to succeed even though it differs from the intended A+B dependency story.
                    "dependency_complete": "A" in parts and "B" in parts,
                    "file_conflict": False,
                    "execution_completed": True,
                    "visible_feedback": {
                        condition: _visible(score, condition)
                        for condition in ("V0", "V1", "V2")
                    },
                    "hidden_utility": score["utility"],
                    "modified_components": sorted(
                        changed["added"] + changed["removed"] + changed["modified"]
                    ),
                    "probe_cost": len(parts),
                }
            )

    sufficient = [
        row for row in rows
        if row["structural_validity"] and not row["file_conflict"] and row["hidden_utility"] == 1
    ]
    sufficient_sets = {frozenset(row["edit_set"]) for row in sufficient}
    minimal = [
        row["harness"]
        for row in sufficient
        if not any(other < frozenset(row["edit_set"]) for other in sufficient_sets)
    ]
    conditions = {}
    for condition in ("V0", "V1", "V2"):
        conditions[condition] = {
            "description": {
                "V0": "structural validation and execution completion only",
                "V1": "partial schema/field checks; amount correctness remains hidden",
                "V2": "full deterministic diagnostic, retained as high-information control",
            }[condition],
            "perfectly_predicts_hidden_success": _perfect(rows, condition),
            "ambiguous_visible_groups": len(
                {
                    tuple(sorted(row["visible_feedback"][condition].items()))
                    for row in rows
                }
            ) < len(rows),
        }
    return {
        "schema_version": 1,
        "utility_definition": (
            "request uses schema_version=2, amount_cents only, exact value 1234, and no extras"
        ),
        "acceptance_rule": (
            "any structurally valid, conflict-free tree with verified utility 1 is sufficient; "
            "declared dependency metadata does not override measured success"
        ),
        "rows": rows,
        "sufficient_repairs": [row["harness"] for row in sufficient],
        "minimal_sufficient_repairs": minimal,
        "validation_conditions": conditions,
        "main_label_free_conditions": ["V0", "V1"],
        "high_information_control": "V2",
        "oracle_boundary": (
            "hidden_utility is joined after selection and is absent from every composer context"
        ),
    }


def visible_only_copy(analysis: dict, condition: str) -> list[dict]:
    """Return exactly the feedback a deployable policy may inspect."""
    return [
        {
            key: deepcopy(row[key])
            for key in (
                "harness",
                "edit_set",
                "structural_validity",
                "dependency_complete",
                "file_conflict",
                "modified_components",
                "probe_cost",
            )
        }
        | {"visible_feedback": deepcopy(row["visible_feedback"][condition])}
        for row in analysis["rows"]
    ]

