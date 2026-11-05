"""PAVE-R observability analysis with explicit deterministic policies and hidden worlds."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _visible(items: list[dict]) -> bytes:
    allowed = [
        {
            "kind": item["kind"],
            "message": item["message"],
            **({"source_id": item["source_id"]} if item.get("source_id") else {}),
        }
        for item in items
    ]
    return json.dumps(allowed, sort_keys=True, separators=(",", ":")).encode()


def _condition(world: str, name: str) -> list[dict]:
    shifted = world == "GENUINE_SHIFT"
    if name == "complete_original_evidence":
        message = "ERROR: required output contract version=2" if shifted else "operation succeeded"
        return [{"kind": "execution", "message": message, "source_id": "execution-1"}]
    if name == "isolated_misleading_observation":
        return [{"kind": "error", "message": "ERROR: required output contract version=2"}]
    if name in ("repeated_misleading_observation", "no_independent_diagnostic"):
        return [
            {"kind": "error", "message": "ERROR: required output contract version=2"}
            for _ in range(3)
        ]
    if name == "repeated_shared_provenance":
        return [
            {
                "kind": "error",
                "message": "ERROR: required output contract version=2",
                "source_id": "renderer-source-01",
            }
            for _ in range(3)
        ]
    if name == "independent_diagnostic":
        diagnostic = "adapt_required" if shifted else "original_harness_valid"
        return [
            {"kind": "error", "message": "ERROR: required output contract version=2"},
            {
                "kind": "diagnostic",
                "message": diagnostic,
                "source_id": "independent-contract-probe",
            },
        ]
    raise ValueError(name)


def _decision(policy: str, items: list[dict]) -> tuple[str, int]:
    errors = [item for item in items if item["kind"] == "error"]
    diagnostics = [item["message"] for item in items if item["kind"] == "diagnostic"]
    if policy == "keep":
        return "KEEP", 0
    if policy == "repeat_count":
        return ("ADAPT" if len(errors) >= 3 else "KEEP"), 0
    if policy == "source_deduplication":
        sources = {item.get("source_id") or f"appearance-{i}" for i, item in enumerate(errors)}
        return ("ADAPT" if len(sources) >= 3 else "KEEP"), 0
    if policy == "independent_check":
        return ("ADAPT" if "adapt_required" in diagnostics else "KEEP"), 0
    if policy == "diagnostic_first":
        if not diagnostics:
            return "QUERY_DIAGNOSTIC", 1
        return ("ADAPT" if "adapt_required" in diagnostics else "KEEP"), 1
    raise ValueError(policy)


def run_pave(inventory: dict, output: Path) -> dict:
    tasks = [
        next(row for row in inventory["tasks"] if row["benchmark"] == benchmark)
        for benchmark in ("jb", "lab")
    ]
    conditions = (
        "complete_original_evidence",
        "isolated_misleading_observation",
        "repeated_misleading_observation",
        "repeated_shared_provenance",
        "independent_diagnostic",
        "no_independent_diagnostic",
    )
    policies = (
        "keep",
        "repeat_count",
        "source_deduplication",
        "independent_check",
        "diagnostic_first",
    )
    cases = []
    indistinguishable = 0
    metrics = {
        policy: {
            "correct_keep_or_adapt": 0,
            "false_adaptations": 0,
            "missed_adaptations": 0,
            "diagnostic_queries": 0,
            "decisions": 0,
        }
        for policy in policies
    }
    for task in tasks:
        for condition in conditions:
            worlds = {}
            for world, correct in (("GENUINE_SHIFT", "ADAPT"), ("EVIDENCE_DEFECT", "KEEP")):
                visible = _condition(world, condition)
                body = _visible(visible)
                decisions = {}
                for policy in policies:
                    action, queries = _decision(policy, visible)
                    decisions[policy] = {"action": action, "diagnostic_queries": queries}
                    metric = metrics[policy]
                    metric["diagnostic_queries"] += queries
                    metric["decisions"] += 1
                    if action == correct:
                        metric["correct_keep_or_adapt"] += 1
                    elif action == "ADAPT" and correct == "KEEP":
                        metric["false_adaptations"] += 1
                    elif action == "KEEP" and correct == "ADAPT":
                        metric["missed_adaptations"] += 1
                worlds[world] = {
                    "visible_evidence": visible,
                    "visible_sha256": hashlib.sha256(body).hexdigest(),
                    "correct_action_hidden": correct,
                    "policy_decisions": decisions,
                }
            same = worlds["GENUINE_SHIFT"]["visible_sha256"] == worlds["EVIDENCE_DEFECT"]["visible_sha256"]
            indistinguishable += int(same)
            cases.append(
                {
                    "benchmark": task["benchmark"],
                    "task_id": task["task_id"],
                    "condition": condition,
                    "provenance_category": "DERIVED_BENCHMARK_TASK",
                    "worlds": worlds,
                    "byte_identical_visible_evidence": same,
                    "identifiable_from_visible_evidence": not same,
                    "oracle_boundary": "correct_action_hidden is excluded from policy inputs",
                }
            )

    # Negative control: the environment version changes, but a compatibility path means the
    # original harness remains correct. Drift alone is therefore not an adaptation target.
    negative_items = [
        {
            "kind": "diagnostic",
            "message": "original_harness_valid",
            "source_id": "independent-contract-probe",
        }
    ]
    negative = {
        "task_id": tasks[0]["task_id"],
        "hidden_world": "ENVIRONMENT_CHANGED_COMPATIBLY",
        "correct_action_hidden": "KEEP",
        "visible_evidence": negative_items,
        "policy_decisions": {
            policy: _decision(policy, negative_items)[0] for policy in policies
        },
        "provenance_category": "DERIVED_BENCHMARK_TASK",
    }
    for metric in metrics.values():
        n = metric["decisions"]
        metric["false_adaptation_rate"] = metric["false_adaptations"] / n
        metric["missed_adaptation_rate"] = metric["missed_adaptations"] / n
    result = {
        "schema_version": 1,
        "research_question": "evidence identifiability, not LLM behavior",
        "task_ids": [task["task_id"] for task in tasks],
        "world_pair_count": len(cases),
        "observationally_indistinguishable_pairs": indistinguishable,
        "conditions": list(conditions),
        "policies": list(policies),
        "policy_metrics": metrics,
        "cases": cases,
        "negative_control": negative,
        "provenance_effect": (
            "Source deduplication adapts on three unlabelled appearances but keeps when the "
            "same three appearances truthfully share one source ID. This prevents false "
            "adaptation but also misses a real shift without independent evidence."
        ),
        "decision": "REFINE — INFORMATION ACQUISITION REQUIRED",
        "limitations": (
            "Trajectories are synthetic derived replays over real task instructions/layouts; "
            "no official benchmark score or model decision is claimed."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

