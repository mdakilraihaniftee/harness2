"""Explicitly authorized Qwen composer-only CITE interface gate."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from harness2 import config
from harness2.core import prompts
from harness2.core import tree as harness_tree
from harness2.core.proposer import Proposer, ProposerError
from harness2.core.spec import resolve_channel_model, resolve_prompts
from harness2.model_config import resolve_run_model_config
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.accounting import LiveBudget
from research_pilots.adapter import PilotAdapter
from research_pilots.evidence import condition
from research_pilots.fixtures import TASK_CITE, base_tree, cite_candidates, evaluate_cite
from research_pilots.manifest import INTERFACE_NOTE
from research_pilots.run_phase2_live import install_trace_launcher

from . import REPO_ROOT, RESULTS
from .decision import classify_completion
from .replay import repetition_identity

_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "model_steps",
)


def _required_path(name: str) -> Path:
    value = os.environ.get(name, "")
    if not value:
        raise config.ConfigError(f"{name} is required for the isolated Qwen live gate")
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise config.ConfigError(f"{name} does not exist: {path}")
    return path


def _trace_summary(telemetry: Path, *, steps: int) -> dict:
    records = []
    for path in sorted(telemetry.glob("*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    tools = [event for record in records for event in record.get("tool_events", [])]
    serialized = json.dumps(records).lower()
    reads = [
        event
        for event in tools
        if str(event.get("tool", "")).lower() in {"read", "glob", "grep", "list"}
    ]
    writes = [
        event
        for event in tools
        if str(event.get("tool", "")).lower() in {"write", "edit", "patch", "apply_patch"}
    ]
    errors = [event for event in tools if event.get("error")]
    return {
        "trace_files": [str(path) for path in sorted(telemetry.glob("*.json"))],
        "tool_names": [str(event.get("tool", "")) for event in tools],
        "tool_call_count": len(tools),
        "file_read_count": len(reads),
        "file_write_count": len(writes),
        "tool_error_count": len(errors),
        "evidence_manifest_accessed": "evidence_manifest.md" in serialized,
        "step_exhausted": any(
            marker in serialized
            for marker in ("step limit", "steps exhausted", "maximum steps", "max steps")
        ),
        "configured_step_limit": steps,
    }


def _usage(reply) -> dict:
    usage = {key: 0 for key in _USAGE_FIELDS}
    if reply:
        for key, value in reply.usage.items():
            if key in usage and isinstance(value, (int, float)):
                usage[key] = value
    return usage


def _run_frozen_cite_gate(
    *,
    controlled: dict,
    models,
    identity: str,
    budget: LiveBudget,
    steps: int,
    output: Path,
    launcher: Path,
) -> dict:
    telemetry = output / "telemetry"
    telemetry.mkdir(parents=True)
    install_trace_launcher(launcher, telemetry)
    context_root = Path(controlled["context_root"])
    base = harness_tree.read_tree(OPENCODE_SURFACE, context_root / "harness")
    adapter = PilotAdapter(
        output / "adapter",
        TASK_CITE,
        base_tree(),
        condition("A0_clean", []),
    )
    mission = prompts.aggregate(resolve_prompts(adapter, TASK_CITE), OPENCODE_SURFACE, k=1)
    mission += "\n\n" + INTERFACE_NOTE
    if controlled["prompt_hash"] != __import__("hashlib").sha256(mission.encode()).hexdigest():
        raise RuntimeError("frozen prompt hash does not match the live composer mission")
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
            f"phase4-cite-e1.{identity}",
            harvest="context/harness",
            max_attempts=1,
        )
        budget.record(
            f"phase4-cite-e1:{identity}",
            reply.cost_usd,
            status="CACHE_HIT" if reply.cached else "COMPLETED",
            attempts=reply.attempts,
        )
    except ProposerError as exc:
        transport_error = str(exc)
        budget.record(
            f"phase4-cite-e1:{identity}",
            exc.cost_usd,
            status="TRANSPORT_FAILURE",
            attempts=exc.attempts,
        )

    trace = _trace_summary(telemetry, steps=steps)
    rejected: list[str] = []
    final_tree: dict[str, str] = {}
    tree_parseable = bool(reply and reply.workspace)
    if tree_parseable:
        final_tree = harness_tree.read_tree(
            OPENCODE_SURFACE, reply.workspace, rejected=rejected
        )
        tree_parseable = bool(final_tree) and not rejected
    tree_valid = False
    validation_error = ""
    if tree_parseable:
        try:
            harness_tree.validate(OPENCODE_SURFACE, final_tree, allow_subagents=False)
            tree_valid = True
        except ValueError as exc:
            validation_error = str(exc)
    tree_changed = tree_valid and final_tree != base
    completion = classify_completion(
        response=reply.text if reply else "",
        tree_changed=tree_changed,
        tree_parseable=tree_parseable,
        tree_valid=tree_valid,
        fell_back=reply is None,
        evidence_accessed=trace["evidence_manifest_accessed"],
        step_exhausted=trace["step_exhausted"],
    )
    candidate_base, candidates = cite_candidates()
    if completion["valid_completed_decision"] and final_tree == candidate_base:
        decision = "KEEP_BASE"
    elif completion["valid_completed_decision"] and final_tree in candidates.values():
        decision = "EDIT"
    elif completion["valid_completed_decision"] and len(
        harness_tree.diff_summary(OPENCODE_SURFACE, candidate_base, final_tree)["modified"]
    ) > 1:
        decision = "MERGE"
    else:
        decision = completion["decision"]
    diff = (
        harness_tree.diff_summary(OPENCODE_SURFACE, candidate_base, final_tree)
        if tree_valid
        else {"added": [], "removed": [], "modified": []}
    )
    return {
        "phase": 4,
        "idea": "CITE-R",
        "experiment": "E1_FROZEN_COMPOSER_GATE",
        "condition_id": controlled["condition_id"],
        "interface": "COMPACT_MANIFEST",
        "prompt_pack": controlled["prompt_pack"],
        "prompt_hash": controlled["prompt_hash"],
        "reference_hash": controlled["reference_hash"],
        "context_hash": controlled["context_hash"],
        "candidate_pool": controlled["candidate_pool"],
        "model": models.improver.ref,
        "actual_runtime_model": models.improver.runtime_id("opencode"),
        "model_configuration_fingerprint": models.fingerprint,
        "recursion_mode": controlled["recursion_mode"],
        "reference_k": controlled["k"],
        "decision": decision,
        "completion": completion,
        "independent_sample": bool(reply and not reply.cached),
        "cache_hit": bool(reply and reply.cached),
        "transport_attempts": reply.attempts if reply else 1,
        "transport_error": transport_error,
        "tree_rejected_paths": rejected,
        "tree_validation_error": validation_error,
        "final_notes": reply.text if reply else "",
        "final_harness_diff": diff,
        "hidden_offline_evaluation": evaluate_cite(final_tree) if tree_valid else None,
        "usage": _usage(reply),
        "cost_usd": reply.cost_usd if reply else budget.spent_usd,
        "wall_s": reply.wall_s if reply else 0.0,
        "tool_trace": trace,
        "external_judge_calls": 0,
        "valid_research_result": completion["valid_completed_decision"]
        and bool(reply and not reply.cached),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=("cite-e1",))
    parser.add_argument("--approve-paid", action="store_true")
    parser.add_argument("--model-profile", default="qwen", choices=("qwen",))
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--max-usd", type=float, required=True)
    parser.add_argument("--max-calls", type=int, required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument(
        "--launcher",
        type=Path,
        default=REPO_ROOT / "research_pilots/phase4/openrouter_agent_sandbox.py",
    )
    args = parser.parse_args(argv)
    if not args.approve_paid:
        parser.error("the Phase 4 live gate requires explicit --approve-paid authorization")
    if not 0 < args.max_usd <= 1:
        parser.error("--max-usd must be in (0, 1]")
    if not 1 <= args.max_calls <= 2:
        parser.error("--max-calls must be 1 or 2")
    if not 1 <= args.steps <= 20:
        parser.error("--steps must be in [1, 20]")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.sample_id):
        parser.error("--sample-id may contain letters, digits, dot, underscore and hyphen")
    runtime_paths = {
        name: _required_path(name)
        for name in (
            "HARNESS2_GATEWAY_CA",
            "HARNESS2_GATEWAY_SOCKET",
            "HARNESS2_MODELS_SNAPSHOT",
        )
    }
    if not os.environ.get("OPENROUTER_API_KEY"):
        parser.error("OPENROUTER_API_KEY is required")
    model_ref = os.environ.get("HARNESS2_QWEN_MODEL", "")
    if not model_ref.startswith("openrouter/qwen/"):
        parser.error("HARNESS2_QWEN_MODEL must be a verified openrouter/qwen/<model-id>")
    snapshot = runtime_paths["HARNESS2_MODELS_SNAPSHOT"].read_text(
        encoding="utf-8", errors="replace"
    )
    if model_ref.removeprefix("openrouter/") not in snapshot:
        parser.error("HARNESS2_QWEN_MODEL is absent from HARNESS2_MODELS_SNAPSHOT")

    conditions_path = RESULTS / "phase4_replay_conditions.json"
    if not conditions_path.is_file():
        parser.error("run `python -m research_pilots.phase4.run --offline` first")
    conditions = json.loads(conditions_path.read_text())
    controlled = next(row for row in conditions if row["condition_id"] == "CITE_V1")
    models = resolve_run_model_config(
        profile=args.model_profile,
        judge_model=model_ref,
    )
    if models.improver.provider != "openrouter" or not models.improver.model_id.startswith("qwen/"):
        parser.error("resolved improver is not Qwen through OpenRouter")
    identity = repetition_identity(
        experiment_id="phase4-cite-live-gate",
        condition_id=controlled["condition_id"],
        task_id=controlled["task_id"],
        sample_id=args.sample_id,
        model_fingerprint=models.fingerprint,
        prompt_hash=controlled["prompt_hash"],
        reference_hash_value=controlled["reference_hash"],
    )
    output = RESULTS / "live" / identity
    output.mkdir(parents=True, exist_ok=False)
    budget = LiveBudget(max_usd=args.max_usd, max_calls=args.max_calls)
    result = _run_frozen_cite_gate(
        controlled=controlled,
        models=models,
        identity=identity,
        budget=budget,
        steps=args.steps,
        output=output,
        launcher=args.launcher.resolve(),
    )
    result.update(
        {
            "sample_id": args.sample_id,
            "repetition_identity": identity,
            "model_configuration_fingerprint": models.fingerprint,
            "prompt_hash": controlled["prompt_hash"],
            "reference_hash": controlled["reference_hash"],
            "condition_id": controlled["condition_id"],
            "independent_sample": not result["cache_hit"],
            "external_judge_calls": 0,
        }
    )
    if result["cache_hit"]:
        result["valid_research_result"] = False
        result["status"] = "CACHE_HIT_NOT_INDEPENDENT"
    elif result["valid_research_result"]:
        result["status"] = "VALID_COMPLETED_DECISION"
    else:
        result["status"] = "OPERATIONAL_FAILURE"
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output / "budget.json").write_text(
        json.dumps(budget.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": result, "budget": budget.to_dict()}, indent=2))
    return 0 if result["valid_research_result"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

