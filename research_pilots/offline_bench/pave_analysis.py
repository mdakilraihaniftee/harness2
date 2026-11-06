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
        return [
            {
                "kind": "error" if shifted else "execution",
                "message": (
                    "ERROR: required output contract version=2"
                    if shifted
                    else "operation succeeded"
                ),
                "source_id": "execution-1",
            }
        ]
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
        return [{"kind": "error", "message": "ERROR: required output contract version=2"}]
    raise ValueError(name)


def _diagnostic_response(world: str) -> dict:
    return {
        "kind": "diagnostic",
        "message": "adapt_required" if world == "GENUINE_SHIFT" else "original_harness_valid",
        "source_id": "independent-contract-probe",
    }


def _binary_decision(policy: str, items: list[dict]) -> str:
    errors = [item for item in items if item["kind"] == "error"]
    diagnostics = [item["message"] for item in items if item["kind"] == "diagnostic"]
    if policy == "keep":
        return "KEEP"
    if policy == "repeat_count":
        return "ADAPT" if len(errors) >= 3 else "KEEP"
    if policy == "source_deduplication":
        sources = {item.get("source_id") or f"appearance-{i}" for i, item in enumerate(errors)}
        return "ADAPT" if len(sources) >= 3 else "KEEP"
    if policy == "independent_check":
        return "ADAPT" if "adapt_required" in diagnostics else "KEEP"
    raise ValueError(policy)


def decision_trace(
    policy: str,
    initial_items: list[dict],
    *,
    diagnostic_available: bool,
    diagnostic_response: dict | None,
) -> dict:
    """Run a policy through an optional information-acquisition step before scoring."""
    initial = None
    selected = None
    response = None
    queries = 0
    cost = 0.0
    final_items = list(initial_items)

    wants_diagnostic = policy in ("independent_check", "diagnostic_first") and any(
        item["kind"] == "error" for item in initial_items
    )
    if wants_diagnostic:
        initial = "QUERY_DIAGNOSTIC"
        if diagnostic_available and diagnostic_response is not None:
            selected = "independent-contract-probe"
            response = dict(diagnostic_response)
            final_items.append(response)
            queries = 1
            cost = 1.0
        elif policy == "diagnostic_first":
            return {
                "initial_decision": initial,
                "diagnostic_selected": None,
                "diagnostic_response": None,
                "final_decision": "UNRESOLVED",
                "diagnostic_queries": 0,
                "diagnostic_cost": 0.0,
                "unresolved": True,
            }
    if policy == "diagnostic_first":
        final = (
            "ADAPT"
            if response and response["message"] == "adapt_required"
            else "KEEP"
        )
    else:
        final = _binary_decision(policy, final_items)
    return {
        "initial_decision": initial or final,
        "diagnostic_selected": selected,
        "diagnostic_response": response,
        "final_decision": final,
        "diagnostic_queries": queries,
        "diagnostic_cost": cost,
        "unresolved": False,
    }


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
            "correct_final_decisions": 0,
            "false_adaptations": 0,
            "missed_adaptations": 0,
            "diagnostic_queries": 0,
            "diagnostic_cost": 0.0,
            "final_binary_decisions": 0,
            "unresolved_cases": 0,
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
                    trace = decision_trace(
                        policy,
                        visible,
                        diagnostic_available=condition == "independent_diagnostic",
                        diagnostic_response=_diagnostic_response(world),
                    )
                    action = trace["final_decision"]
                    trace["final_correct"] = action == correct
                    decisions[policy] = trace
                    metric = metrics[policy]
                    metric["diagnostic_queries"] += trace["diagnostic_queries"]
                    metric["diagnostic_cost"] += trace["diagnostic_cost"]
                    metric["decisions"] += 1
                    if trace["unresolved"]:
                        metric["unresolved_cases"] += 1
                        continue
                    metric["final_binary_decisions"] += 1
                    if trace["final_correct"]:
                        metric["correct_final_decisions"] += 1
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
            policy: decision_trace(
                policy,
                negative_items,
                diagnostic_available=False,
                diagnostic_response=None,
            )
            for policy in policies
        },
        "provenance_category": "DERIVED_BENCHMARK_TASK",
    }
    for metric in metrics.values():
        n = metric["decisions"]
        metric["false_adaptation_rate"] = metric["false_adaptations"] / n
        metric["missed_adaptation_rate"] = metric["missed_adaptations"] / n
        metric["unresolved_rate"] = metric["unresolved_cases"] / n
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

