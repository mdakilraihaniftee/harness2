"""Conditional free-model composer gate and tiny PAVE pilot over frozen Phase 4 contexts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
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
from research_pilots.evidence import condition
from research_pilots.fixtures import base_tree, evaluate_cite, execute_pave
from research_pilots.manifest import INTERFACE_NOTE
from research_pilots.phase4.decision import classify_completion
from research_pilots.phase4.replay import repetition_identity
from research_pilots.run_phase2_live import install_trace_launcher

from . import FALLBACK_MODEL, REPO_ROOT, RESULTS, TRACES
from .provider_audit import account_status

_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "model_steps",
)


@dataclass
class ZeroBudget:
    max_calls: int
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def spent_usd(self) -> float:
        return sum(float(item.get("cost_usd") or 0) for item in self.calls)

    def require_capacity(self) -> None:
        if len(self.calls) >= self.max_calls:
            raise RuntimeError("free composer-session cap reached")
        if self.spent_usd > 0:
            raise RuntimeError("positive provider cost observed")

    def record(self, name: str, cost_usd: float, **metadata: Any) -> None:
        self.calls.append({"name": name, "cost_usd": float(cost_usd), **metadata})
        if float(cost_usd) > 0:
            raise RuntimeError("positive provider cost observed")


def _gateway_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _assert_zero_gateway(path: Path) -> list[dict[str, Any]]:
    events = _gateway_events(path)
    expected = FALLBACK_MODEL.removeprefix("openrouter/")
    for event in events:
        if float(event.get("cost_usd") or 0) > 0:
            raise RuntimeError("STOP: provider reported positive cost")
        models = event.get("actual_models") or []
        if models and any(model != expected for model in models):
            raise RuntimeError("STOP: provider returned an unexpected model identity")
    return events


def _trace_summary(telemetry: Path, *, steps: int, response: str = "") -> dict[str, Any]:
    records = []
    for path in sorted(telemetry.glob("*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    tools = [event for record in records for event in record.get("tool_events", [])]
    serialized = json.dumps(records).lower()
    return {
        "trace_files": [str(path) for path in sorted(telemetry.glob("*.json"))],
        "tool_names": [str(event.get("tool", "")) for event in tools],
        "tool_call_count": len(tools),
        "file_read_count": sum(
            str(event.get("tool", "")).lower() in {"read", "glob", "grep", "list"}
            for event in tools
        ),
        "file_write_count": sum(
            str(event.get("tool", "")).lower() in {"write", "edit", "patch", "apply_patch"}
            for event in tools
        ),
        "tool_error_count": sum(bool(event.get("error")) for event in tools),
        "evidence_manifest_accessed": "evidence_manifest.md" in serialized,
        "step_exhausted": any(
            marker in serialized
            for marker in ("step limit", "steps exhausted", "maximum steps", "max steps")
        ) or "maximum steps reached" in response.lower(),
        "configured_step_limit": steps,
    }


def _usage(reply) -> dict[str, int | float]:
    usage = {key: 0 for key in _USAGE_FIELDS}
    if reply:
        for key, value in reply.usage.items():
            if key in usage and isinstance(value, (int, float)):
                usage[key] = value
    return usage


def run_condition(
    *,
    controlled: dict[str, Any],
    models,
    sample_id: str,
    steps: int,
    budget: ZeroBudget,
    evaluator: Callable[[dict[str, str]], dict[str, Any]],
    launcher: Path,
    actual_bun: Path,
) -> dict[str, Any]:
    identity = repetition_identity(
        experiment_id="phase5-free-composer",
        condition_id=controlled["condition_id"],
        task_id=controlled["task_id"],
        sample_id=sample_id,
        model_fingerprint=models.fingerprint,
        prompt_hash=controlled["prompt_hash"],
        reference_hash_value=controlled["reference_hash"],
    )
    output = RESULTS / "live" / identity
    output.mkdir(parents=True, exist_ok=False)
    telemetry = TRACES / identity
    telemetry.mkdir(parents=True, exist_ok=False)
    config.BUN = actual_bun
    install_trace_launcher(launcher, telemetry)
    context_root = Path(controlled["context_root"])
    base = harness_tree.read_tree(OPENCODE_SURFACE, context_root / "harness")
    adapter = PilotAdapter(
        output / "adapter", controlled["task_id"], base_tree(), condition("A0_clean", [])
    )
    mission = prompts.aggregate(
        resolve_prompts(adapter, controlled["task_id"]), OPENCODE_SURFACE, k=controlled["k"]
    )
    mission += "\n\n" + INTERFACE_NOTE
    if hashlib.sha256(mission.encode()).hexdigest() != controlled["prompt_hash"]:
        raise RuntimeError("frozen prompt hash does not match composer mission")
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
            f"phase5.{controlled['condition_id']}.{identity}",
            harvest="context/harness",
            max_attempts=1,
        )
        budget.record(
            controlled["condition_id"], reply.cost_usd,
            status="CACHE_HIT" if reply.cached else "COMPLETED", attempts=reply.attempts,
        )
    except ProposerError as exc:
        transport_error = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", str(exc))
        budget.record(
            controlled["condition_id"], exc.cost_usd, status="TRANSPORT_FAILURE",
            attempts=exc.attempts,
        )

    trace = _trace_summary(telemetry, steps=steps, response=reply.text if reply else "")
    telemetry.chmod(0o700)
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
    decision = completion["decision"]
    if completion["valid_completed_decision"] and not tree_changed:
        decision = "KEEP_BASE"
    elif completion["valid_completed_decision"]:
        decision = "EDIT_OR_MERGE"
    result = {
        "phase": 5,
        "condition_id": controlled["condition_id"],
        "task_id": controlled["task_id"],
        "interface": "COMPACT_MANIFEST",
        "model": models.improver.ref,
        "actual_runtime_model": models.improver.runtime_id("opencode"),
        "model_configuration_fingerprint": models.fingerprint,
        "sample_id": sample_id,
        "repetition_identity": identity,
        "prompt_hash": controlled["prompt_hash"],
        "reference_hash": controlled["reference_hash"],
        "cache_hit": bool(reply and reply.cached),
        "decision": decision,
        "completion": completion,
        "transport_error": transport_error,
        "final_notes": reply.text if reply else "",
        "final_harness_diff": (
            harness_tree.diff_summary(OPENCODE_SURFACE, base, final_tree)
            if tree_valid else {"added": [], "removed": [], "modified": []}
        ),
        "hidden_offline_evaluation": evaluator(final_tree) if tree_valid else None,
        "usage": _usage(reply),
        "cost_usd": reply.cost_usd if reply else 0.0,
        "wall_s": reply.wall_s if reply else 0.0,
        "tool_trace": trace,
        "external_judge_calls": 0,
        "valid_research_result": completion["valid_completed_decision"]
        and bool(reply and not reply.cached),
        "tree_rejected_paths": rejected,
        "tree_validation_error": validation_error,
    }
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def _classify_gate(result: dict[str, Any]) -> str:
    if result["valid_research_result"]:
        return "PASS"
    if result["tool_trace"]["step_exhausted"]:
        return "MODEL_CAPABILITY_FAILURE"
    if result["transport_error"] or not result["completion"]["explicit_decision"]:
        return "INTERFACE_FAILURE"
    return "MODEL_CAPABILITY_FAILURE"


def main(argv: list[str] | None = None) -> int:
    config.load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-free-inference", action="store_true")
    parser.add_argument("--sample-id", default="free-001")
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--max-sessions", type=int, default=4)
    parser.add_argument("--gateway-events", type=Path, required=True)
    parser.add_argument(
        "--launcher", type=Path,
        default=REPO_ROOT / "research_pilots/phase4/openrouter_agent_sandbox.py",
    )
    args = parser.parse_args(argv)
    if not args.approve_free_inference:
        parser.error("explicit --approve-free-inference is required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.sample_id):
        parser.error("invalid sample ID")
    if not 1 <= args.steps <= 8 or args.max_sessions != 4:
        parser.error("steps must be [1,8] and max sessions must remain 4")
    for name in ("HARNESS2_GATEWAY_CA", "HARNESS2_GATEWAY_SOCKET", "HARNESS2_MODELS_SNAPSHOT"):
        if not os.environ.get(name) or not Path(os.environ[name]).exists():
            parser.error(f"{name} is missing or invalid")
    availability_path = RESULTS / "model_availability.json"
    if not availability_path.is_file():
        parser.error("run the Phase 5 read-only audit first")
    availability = json.loads(availability_path.read_text())
    if availability.get("provider", {}).get("selected_ref") != FALLBACK_MODEL:
        parser.error("selected model did not pass the saved zero-price audit")
    if availability.get("status") != "PASS":
        parser.error("provider audit is not PASS")
    snapshot = Path(os.environ["HARNESS2_MODELS_SNAPSHOT"]).read_text(errors="replace")
    if FALLBACK_MODEL.removeprefix("openrouter/") not in snapshot:
        parser.error("selected model is absent from the frozen OpenCode catalog")
    before = account_status(os.environ["OPENROUTER_API_KEY"])
    models = resolve_run_model_config(
        model=FALLBACK_MODEL, judge_model=FALLBACK_MODEL, env=os.environ
    )
    if models.improver.ref != FALLBACK_MODEL:
        parser.error("model resolution changed the exact selected model")
    conditions_path = REPO_ROOT / "research_pilots/phase4/results/phase4_replay_conditions.json"
    if not conditions_path.is_file():
        parser.error("run Phase 4 offline replay preparation first")
    conditions = {row["condition_id"]: row for row in json.loads(conditions_path.read_text())}
    budget = ZeroBudget(max_calls=args.max_sessions)
    TRACES.mkdir(parents=True, exist_ok=True)
    actual_bun = config.BUN
    results: list[dict[str, Any]] = []

    gate = run_condition(
        controlled=conditions["CITE_V1"], models=models, sample_id=args.sample_id,
        steps=args.steps, budget=budget, evaluator=evaluate_cite,
        launcher=args.launcher.resolve(), actual_bun=actual_bun,
    )
    results.append(gate)
    _assert_zero_gateway(args.gateway_events)
    gate_status = _classify_gate(gate)
    if gate_status == "PASS":
        pave_ids = ("PAVE_P0_K3", "PAVE_P2_K3", "PAVE_P3_K3")
        for condition_id in pave_ids:
            result = run_condition(
                controlled=conditions[condition_id], models=models,
                sample_id=args.sample_id, steps=args.steps, budget=budget,
                evaluator=lambda tree: execute_pave("selected", tree, shifted=False),
                launcher=args.launcher.resolve(), actual_bun=actual_bun,
            )
            results.append(result)
            _assert_zero_gateway(args.gateway_events)
            if not result["valid_research_result"] or result["tool_trace"]["step_exhausted"]:
                break
    after = account_status(os.environ["OPENROUTER_API_KEY"])
    gateway = _assert_zero_gateway(args.gateway_events)
    usage = {
        "before": before,
        "after": after,
        "model_requests": len(gateway),
        "provider_cost_usd": sum(float(row.get("cost_usd") or 0) for row in gateway),
    }
    (RESULTS / "account_usage_before_after.json").write_text(
        json.dumps(usage, indent=2) + "\n", encoding="utf-8"
    )
    (RESULTS / "composer_decisions.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "status": "COMPLETED" if gate_status == "PASS" else gate_status,
        "gate_status": gate_status,
        "model": FALLBACK_MODEL,
        "sessions": len(results),
        "model_requests": len(gateway),
        "provider_cost_usd": usage["provider_cost_usd"],
        "conditions": [row["condition_id"] for row in results],
        "external_judge_calls": 0,
    }
    (RESULTS / "experiment_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if gate_status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
