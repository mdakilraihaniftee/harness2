"""Run the conditional Phase 6 free-model CITE gate and PAVE comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from harness2 import config
from harness2.core import prompts
from harness2.core import tree as harness_tree
from harness2.core.proposer import Proposer, ProposerError
from harness2.core.spec import resolve_channel_model, resolve_prompts
from harness2.model_config import resolve_run_model_config
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.adapter import PilotAdapter
from research_pilots.bundles import combine
from research_pilots.evidence import condition
from research_pilots.fixtures import (
    base_tree,
    cite_candidates,
    evaluate_cite,
    execute_pave,
    pave_retry_tree,
)
from research_pilots.manifest import INTERFACE_NOTE
from research_pilots.phase4.decision import classify_completion
from research_pilots.phase4.replay import repetition_identity
from research_pilots.phase5.live import ZeroBudget, _gateway_events, _trace_summary, _usage
from research_pilots.phase5.provider_audit import account_status
from research_pilots.run_phase2_live import install_trace_launcher

from . import NAVIGATION_POLICY, REPO_ROOT, RESULTS, SCHEMA_VERSION, TRACES


def _assert_gateway(path: Path, expected_model: str) -> list[dict[str, Any]]:
    events = _gateway_events(path)
    expected = expected_model.removeprefix("openrouter/")
    for event in events:
        if float(event.get("cost_usd") or 0) > 0:
            raise RuntimeError("COST_SAFETY_BLOCK: positive provider cost")
        if event.get("requested_model") != expected:
            raise RuntimeError("COST_SAFETY_BLOCK: unauthorized requested model")
        actual = event.get("actual_models") or []
        if actual and any(model != expected for model in actual):
            raise RuntimeError("COST_SAFETY_BLOCK: actual model mismatch")
    return events


def _provider_usage(events: list[dict[str, Any]]) -> dict[str, int | float | list[str]]:
    fields = (
        "cost_usd",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cache_read_tokens",
    )
    return {
        **{key: sum(float(row.get(key) or 0) for row in events) for key in fields},
        "actual_models": sorted(
            {model for row in events for model in row.get("actual_models", []) if model}
        ),
    }


def _cite_classification(tree: dict[str, str], valid: bool) -> str:
    if not valid:
        return "INVALID_OR_UNRESOLVED"
    base, candidates = cite_candidates()
    hab = combine(OPENCODE_SURFACE, base, candidates, ("A", "B"))
    if tree == base:
        return "BASE_UNCHANGED"
    if tree == candidates["A"]:
        return "A_ONLY"
    if tree == candidates["B"]:
        return "B_ONLY"
    if tree == hab:
        return "A_PLUS_B"
    if evaluate_cite(tree)["utility"] == 1:
        return "ANOTHER_VALID_REPAIR"
    return "OTHER_VALID_TREE"


def _pave_classification(tree: dict[str, str], valid: bool) -> str:
    if not valid:
        return "INVALID_OR_UNRESOLVED"
    if tree == base_tree():
        return "BASE_UNCHANGED"
    if tree == pave_retry_tree():
        return "HARMFUL_RETRY_EDIT"
    return "OTHER_EDIT"


def run_condition(
    *,
    controlled: dict[str, Any],
    models,
    sample_id: str,
    steps: int,
    budget: ZeroBudget,
    evaluator: Callable[[dict[str, str]], dict[str, Any]],
    classifier: Callable[[dict[str, str], bool], str],
    launcher: Path,
    actual_bun: Path,
) -> dict[str, Any]:
    context_root = Path(controlled["context_root"])
    base = harness_tree.read_tree(OPENCODE_SURFACE, context_root / "harness")
    adapter = PilotAdapter(
        RESULTS / "adapters" / controlled["condition_id"],
        controlled["task_id"],
        base_tree(),
        condition("A0_clean", []),
    )
    original_mission = prompts.aggregate(
        resolve_prompts(adapter, controlled["task_id"]), OPENCODE_SURFACE, k=controlled["k"]
    )
    original_mission += "\n\n" + INTERFACE_NOTE
    original_hash = hashlib.sha256(original_mission.encode()).hexdigest()
    if original_hash != controlled["prompt_hash"]:
        raise RuntimeError("frozen Phase 4 prompt hash mismatch")
    mission = original_mission + "\n\n" + NAVIGATION_POLICY
    effective_hash = hashlib.sha256(mission.encode()).hexdigest()
    navigation_hash = hashlib.sha256(NAVIGATION_POLICY.encode()).hexdigest()
    identity = repetition_identity(
        experiment_id="phase6-free-composer",
        condition_id=controlled["condition_id"],
        task_id=controlled["task_id"],
        sample_id=sample_id,
        model_fingerprint=models.fingerprint,
        prompt_hash=effective_hash,
        reference_hash_value=controlled["reference_hash"],
    )
    output = RESULTS / "live" / identity
    output.mkdir(parents=True, exist_ok=False)
    telemetry = TRACES / identity
    telemetry.mkdir(parents=True, exist_ok=False)
    telemetry.chmod(0o700)
    config.BUN = actual_bun
    install_trace_launcher(launcher, telemetry)
    channel = resolve_channel_model(
        "opencode", models.improver.runtime_id("opencode"), steps=steps, timeout=600
    )
    channel = channel.__class__(**{**channel.__dict__, "model_spec": models.improver})
    proposer = Proposer(channel, audit_dir=output / "audit", attempts=1)
    reply = None
    transport_error = ""
    budget.require_capacity()
    try:
        reply = proposer.call(
            mission,
            context_root,
            f"phase6.{controlled['condition_id']}.{identity}",
            harvest="context/harness",
            max_attempts=1,
        )
        budget.record(
            controlled["condition_id"],
            reply.cost_usd,
            status="CACHE_HIT" if reply.cached else "COMPLETED",
            attempts=reply.attempts,
        )
    except ProposerError as exc:
        transport_error = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", str(exc))
        budget.record(
            controlled["condition_id"],
            exc.cost_usd,
            status="TRANSPORT_FAILURE",
            attempts=exc.attempts,
        )

    trace = _trace_summary(telemetry, steps=steps, response=reply.text if reply else "")
    for trace_file in telemetry.glob("*"):
        if trace_file.is_file():
            trace_file.chmod(0o600)
    rejected: list[str] = []
    final_tree: dict[str, str] = {}
    tree_parseable = bool(reply and reply.workspace)
    if tree_parseable:
        final_tree = harness_tree.read_tree(OPENCODE_SURFACE, reply.workspace, rejected=rejected)
        tree_parseable = bool(final_tree) and not rejected
    tree_valid = False
    validation_error = ""
    if tree_parseable:
        try:
            harness_tree.validate(OPENCODE_SURFACE, final_tree, allow_subagents=False)
            tree_valid = True
        except ValueError as exc:
            validation_error = str(exc)
    tree_changed = bool(tree_valid and final_tree != base)
    completion = classify_completion(
        response=reply.text if reply else "",
        tree_changed=tree_changed,
        tree_parseable=tree_parseable,
        tree_valid=tree_valid,
        fell_back=reply is None,
        evidence_accessed=trace["evidence_manifest_accessed"],
        step_exhausted=trace["step_exhausted"],
    )
    valid = completion["valid_completed_decision"] and bool(reply and not reply.cached)
    result = {
        "schema_version": SCHEMA_VERSION,
        "phase": 6,
        "condition_id": controlled["condition_id"],
        "task_id": controlled["task_id"],
        "evidence_condition": controlled["evidence_condition"],
        "provenance_categories": controlled["provenance_categories"],
        "trajectory_kind": "CONTROLLED_SYNTHETIC_REPLAY",
        "interface": "COMPACT_MANIFEST_WITH_NEUTRAL_NAVIGATION",
        "model": models.improver.ref,
        "actual_runtime_model": models.improver.runtime_id("opencode"),
        "model_configuration_fingerprint": models.fingerprint,
        "sample_id": sample_id,
        "repetition_identity": identity,
        "original_prompt_hash": original_hash,
        "navigation_instruction": NAVIGATION_POLICY,
        "navigation_instruction_hash": navigation_hash,
        "effective_prompt_hash": effective_hash,
        "reference_hash": controlled["reference_hash"],
        "context_hash": controlled["context_hash"],
        "cache_hit": bool(reply and reply.cached),
        "configured_step_limit": steps,
        "decision": completion["decision"],
        "selected_harness": classifier(final_tree, tree_valid),
        "completion": completion,
        "transport_error": transport_error,
        "final_notes": reply.text if reply else "",
        "final_harness_diff": (
            harness_tree.diff_summary(OPENCODE_SURFACE, base, final_tree)
            if tree_valid
            else {"added": [], "removed": [], "modified": []}
        ),
        "hidden_offline_evaluation": evaluator(final_tree) if tree_valid else None,
        "runtime_usage": _usage(reply),
        "runtime_cost_usd": reply.cost_usd if reply else 0.0,
        "wall_s": reply.wall_s if reply else 0.0,
        "tool_trace": trace,
        "external_judge_calls": 0,
        "valid_research_result": valid,
        "tree_rejected_paths": rejected,
        "tree_validation_error": validation_error,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def _gate_status(result: dict[str, Any]) -> str:
    if result["valid_research_result"]:
        return "VALID_COMPOSER_DECISION"
    if result["tool_trace"]["step_exhausted"]:
        return "STEP_BUDGET_EXHAUSTED"
    if result["transport_error"]:
        return "INTERFACE_FAILURE"
    return "MODEL_PROTOCOL_FAILURE"


def main(argv: list[str] | None = None) -> int:
    config.load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-free-inference", action="store_true")
    parser.add_argument("--sample-id", default="phase6-001")
    parser.add_argument("--model")
    parser.add_argument("--protocol-retry", action="store_true")
    parser.add_argument("--gate-steps", type=int, default=12)
    parser.add_argument("--pave-steps", type=int, default=7)
    parser.add_argument("--max-sessions", type=int, default=4)
    parser.add_argument("--gateway-events", type=Path, required=True)
    parser.add_argument(
        "--launcher",
        type=Path,
        default=REPO_ROOT / "research_pilots/phase4/openrouter_agent_sandbox.py",
    )
    args = parser.parse_args(argv)
    if not args.approve_free_inference:
        parser.error("explicit --approve-free-inference is required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.sample_id):
        parser.error("invalid sample ID")
    expected_bounds = (8, 5) if args.protocol_retry else (12, 7)
    if (args.gate_steps, args.pave_steps) != expected_bounds or args.max_sessions != 4:
        parser.error(
            f"Phase 6 bounds are fixed at gate={expected_bounds[0]}, "
            f"PAVE={expected_bounds[1]}, sessions=4"
        )
    for name in (
        "HARNESS2_GATEWAY_CA",
        "HARNESS2_GATEWAY_SOCKET",
        "HARNESS2_MODELS_SNAPSHOT",
    ):
        if not os.environ.get(name) or not Path(os.environ[name]).exists():
            parser.error(f"{name} is missing or invalid")
    audit = json.loads((RESULTS / "model_audit.json").read_text())
    if audit.get("status") != "PASS" or not audit.get("selected_model"):
        parser.error("Phase 6 model audit is not PASS")
    model_ref = args.model or audit["selected_model"]
    eligible = {
        row.get("model_ref")
        for row in audit.get("candidates", [])
        if row.get("eligible")
    }
    if model_ref not in eligible:
        parser.error("requested model did not pass the Phase 6 zero-price audit")
    snapshot = Path(os.environ["HARNESS2_MODELS_SNAPSHOT"]).read_text(errors="replace")
    if model_ref.removeprefix("openrouter/") not in snapshot:
        parser.error("selected model is absent from the frozen OpenCode catalog")
    before = account_status(os.environ["OPENROUTER_API_KEY"])
    models = resolve_run_model_config(model=model_ref, judge_model=model_ref, env=os.environ)
    if models.improver.ref != model_ref:
        parser.error("model resolution changed the selected exact model")
    conditions_path = REPO_ROOT / "research_pilots/phase4/results/phase4_replay_conditions.json"
    if not conditions_path.is_file():
        parser.error("Phase 4 frozen contexts are absent")
    conditions = {row["condition_id"]: row for row in json.loads(conditions_path.read_text())}
    budget = ZeroBudget(max_calls=args.max_sessions)
    actual_bun = config.BUN
    results: list[dict[str, Any]] = []

    def execute(condition_id: str, steps: int, evaluator, classifier) -> dict[str, Any]:
        prior = len(_assert_gateway(args.gateway_events, model_ref))
        result = run_condition(
            controlled=conditions[condition_id],
            models=models,
            sample_id=args.sample_id,
            steps=steps,
            budget=budget,
            evaluator=evaluator,
            classifier=classifier,
            launcher=args.launcher.resolve(),
            actual_bun=actual_bun,
        )
        events = _assert_gateway(args.gateway_events, model_ref)[prior:]
        result["provider_request_count"] = len(events)
        result["provider_usage"] = _provider_usage(events)
        results.append(result)
        return result

    gate = execute("CITE_V1", args.gate_steps, evaluate_cite, _cite_classification)
    gate_status = _gate_status(gate)
    if gate_status == "VALID_COMPOSER_DECISION":
        for condition_id in ("PAVE_P0_K3", "PAVE_P2_K3", "PAVE_P3_K3"):
            result = execute(
                condition_id,
                args.pave_steps,
                lambda tree: execute_pave("selected", tree, shifted=False),
                _pave_classification,
            )
            if not result["valid_research_result"]:
                break
    after = account_status(os.environ["OPENROUTER_API_KEY"])
    all_events = _assert_gateway(args.gateway_events, model_ref)
    usage = {
        "schema_version": SCHEMA_VERSION,
        "model": model_ref,
        "before": before,
        "after": after,
        "model_requests": len(all_events),
        "provider_usage": _provider_usage(all_events),
        "gateway_request_cap": 35,
        "gate_step_cap": args.gate_steps,
        "pave_step_cap": args.pave_steps,
        "external_judge_calls": 0,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "composer_decisions.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    (RESULTS / "usage_summary.json").write_text(
        json.dumps(usage, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": gate_status,
        "model": model_ref,
        "gate_status": gate_status,
        "conditions": [row["condition_id"] for row in results],
        "valid_composer_sessions": sum(bool(row["valid_research_result"]) for row in results),
        "model_requests": len(all_events),
        "provider_cost_usd": usage["provider_usage"]["cost_usd"],
        "paid_fallback_used": False,
        "external_judge_calls": 0,
    }
    (RESULTS / "experiment_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    for path in RESULTS.glob("*.json"):
        path.chmod(0o600)
    print(json.dumps(summary, indent=2))
    return 0 if gate_status == "VALID_COMPOSER_DECISION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
