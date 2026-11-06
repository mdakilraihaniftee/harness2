"""Explicitly authorized, cost-capped compact-manifest composer decision gates."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from harness2 import config
from harness2.core import prompts
from harness2.core import tree as harness_tree
from harness2.core.proposer import Proposer, ProposerError
from harness2.core.recursion import _run_stage
from harness2.core.spec import RunView, resolve_channel_model, resolve_prompts
from harness2.model_config import ModelSpec, resolve_run_model_config
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.accounting import LiveBudget
from research_pilots.adapter import PilotAdapter
from research_pilots.bundles import combine
from research_pilots.evidence import condition
from research_pilots.fixtures import (
    TASK_CITE,
    TASK_PAVE_NO_FAULT,
    base_tree,
    cite_candidates,
    evaluate_cite,
    execute_pave,
    pave_retry_tree,
    write_execution,
)
from research_pilots.manifest import ManifestProposer, explicit_decision
from research_pilots.prepare_phase2 import opaque_token
from research_pilots.run_live import cite_record, readiness

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "research_pilots/runs/phase2/live"
RESULTS = ROOT / "research_pilots/results/phase2/live"


def install_trace_launcher(launcher: Path, telemetry: Path | None = None) -> None:
    actual_bun = config.BUN
    wrapper = LIVE / "instrumented-bun"
    args = [
        sys.executable,
        str(ROOT / "research_pilots/record_agent_trace.py"),
        "--launcher",
        str(launcher),
        "--bun",
        str(actual_bun),
        "--telemetry",
        str(telemetry or LIVE / "agent-traces"),
        "--",
    ]
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys\nargs={args!r}\nos.execv(args[0],args+sys.argv[1:])\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    config.BUN = wrapper


def run_view(label: str, run_dir: Path) -> RunView:
    return RunView(label, f"phase2-live/{label}", run_dir, ok=True, delivered=True)


def write_tree(path: Path, tree: dict[str, str]) -> Path:
    return harness_tree.write_tree(OPENCODE_SURFACE, tree, path, stubs=False)


class CappedManifestProposer:
    """Count each transport attempt and force one provider attempt per composer call."""

    def __init__(self, manifest: ManifestProposer, budget: LiveBudget, experiment: str):
        self.manifest = manifest
        self.budget = budget
        self.experiment = experiment
        self.spec = manifest.spec
        self.calls = 0

    def call(self, mission: str, context_dir: Path, label: str, **kwargs):
        self.budget.require_capacity()
        kwargs["max_attempts"] = 1
        self.calls += 1
        try:
            reply = self.manifest.call(mission, context_dir, label, **kwargs)
        except ProposerError as exc:
            self.budget.record(
                f"{self.experiment}:{label}",
                exc.cost_usd,
                status="TRANSPORT_FAILURE",
                attempts=exc.attempts,
            )
            raise
        self.budget.record(
            f"{self.experiment}:{label}",
            reply.cost_usd,
            status="COMPLETED" if reply.ok else "FAILED",
            attempts=reply.attempts,
        )
        return reply


def _proposer(
    *,
    experiment: str,
    scopes: dict[str, str],
    token: str,
    source_ids: dict[str, str] | None,
    budget: LiveBudget,
    steps: int,
    model_spec: ModelSpec,
) -> CappedManifestProposer:
    channel = resolve_channel_model(
        "opencode", model_spec.runtime_id("opencode"), steps=steps, timeout=600
    )
    channel = channel.__class__(**{**channel.__dict__, "model_spec": model_spec})
    delegate = Proposer(channel, audit_dir=LIVE / "audit" / experiment, attempts=1)
    manifest = ManifestProposer(
        delegate,
        candidate_scopes=scopes,
        condition_token=token,
        source_ids=source_ids,
        artifact_dir=RESULTS / experiment / "manifests",
    )
    return CappedManifestProposer(manifest, budget, experiment)


def _raw_reply(prop: CappedManifestProposer) -> str:
    replies = prop.manifest.replies
    return replies[-1].text if replies else ""


def cite_e1(
    budget: LiveBudget,
    steps: int,
    model_spec: ModelSpec,
    *,
    experiment: str = "cite_e1_compact",
    phase: int = 2,
) -> dict:
    root = LIVE / experiment
    base, candidates = cite_candidates()
    trees = {"base1": base, "inv1": candidates["A"], "dom1": candidates["B"]}
    runs = {
        label: write_execution(root / "raw", cite_record(label, tree))
        for label, tree in trees.items()
    }
    evidence = condition("A0_clean", list(trees))
    adapter = PilotAdapter(root, TASK_CITE, base, evidence)
    base_dir = write_tree(root / "harnesses/base", base)
    pool = [
        (
            label,
            write_tree(root / "harnesses" / label, trees[label]),
            run_view(label, runs[label]),
        )
        for label in ("inv1", "dom1")
    ]
    prop = _proposer(
        experiment=experiment,
        scopes={"inv1": "INV", "dom1": "DOM"},
        token=opaque_token(experiment, evidence.cache_token),
        source_ids=None,
        budget=budget,
        steps=steps,
        model_spec=model_spec,
    )
    job = prompts.aggregate(resolve_prompts(adapter, TASK_CITE), OPENCODE_SURFACE, k=1)
    stage = _run_stage(
        label=experiment,
        dim="AGG",
        job=job,
        fallback=base,
        adapter=adapter,
        prop=prop,
        ctx_dir=root / "context",
        task_id=TASK_CITE,
        rollouts=[run_view("base1", runs["base1"])],
        harness_dir=base_dir,
        library_dir=None,
        pool=pool,
        decisions={"inv1": "controlled edit A", "dom1": "controlled edit B"},
    )
    reply = _raw_reply(prop)
    transport_reply = prop.manifest.replies[-1] if prop.manifest.replies else None
    hab = combine(OPENCODE_SURFACE, base, candidates, ["A", "B"])
    if stage.tree == hab:
        selected = "VALID_A_B_MERGE"
    elif stage.tree == base:
        selected = "BASE_UNCHANGED"
    elif stage.tree == candidates["A"]:
        selected = "A_ONLY"
    elif stage.tree == candidates["B"]:
        selected = "B_ONLY"
    elif evaluate_cite(stage.tree)["utility"] == 1.0:
        selected = "VALID_ALTERNATIVE_REPAIR"
    else:
        selected = "VALID_OTHER_TREE" if not stage.fell_back else "OPERATIONAL_FAILURE"
    result = {
        "phase": phase,
        "idea": "CITE-R",
        "experiment": "E1",
        "interface": "COMPACT_MANIFEST",
        "model": prop.spec.model,
        "solver_model": "deterministic-fixture",
        "improver_model": prop.spec.model,
        "execution_harness": "opencode",
        "steps": steps,
        "fell_back": stage.fell_back,
        "kept_base": stage.kept_base,
        "explicit_decision": explicit_decision(reply),
        "valid_research_result": not stage.fell_back and explicit_decision(reply),
        "selected": selected,
        "notes": stage.notes,
        "error": stage.error,
        "diff": harness_tree.diff_summary(OPENCODE_SURFACE, base, stage.tree),
        "hidden_offline_evaluation": evaluate_cite(stage.tree),
        "cost_usd": stage.usd,
        "calls": prop.calls,
        "cache_hit": bool(transport_reply and transport_reply.cached),
        "usage": dict(transport_reply.usage) if transport_reply else {},
        "wall_s": transport_reply.wall_s if transport_reply else 0.0,
    }
    out = RESULTS / experiment
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    write_tree(out / "composed_harness", stage.tree)
    return result


def pave_case(
    budget: LiveBudget,
    *,
    condition_name: str,
    with_provenance: bool,
    steps: int,
    model_spec: ModelSpec,
) -> dict:
    suffix = "with_provenance" if with_provenance else "no_provenance"
    experiment = f"pave_{condition_name}_{suffix}"
    root = LIVE / experiment
    labels = [f"base{i}" for i in range(1, 4)] + [
        f"{scope}{i}" for i in range(1, 4) for scope in ("inv", "dom")
    ]
    trees = {
        label: pave_retry_tree() if label.startswith("inv") else base_tree()
        for label in labels
    }
    runs = {
        label: write_execution(root / "raw", execute_pave(label, tree))
        for label, tree in trees.items()
    }
    evidence = condition(condition_name, labels)
    adapter = PilotAdapter(root, TASK_PAVE_NO_FAULT, base_tree(), evidence)
    base_dir = write_tree(root / "harnesses/base", base_tree())
    pool = [
        (
            label,
            write_tree(root / "harnesses" / label, trees[label]),
            run_view(label, runs[label]),
        )
        for label in labels[3:]
    ]
    sources = {label: "renderer-source-01" for label in labels} if with_provenance else None
    prop = _proposer(
        experiment=experiment,
        scopes={
            label: "INV" if label.startswith("inv") else "DOM" for label in labels[3:]
        },
        token=opaque_token(experiment, evidence.cache_token),
        source_ids=sources,
        budget=budget,
        steps=steps,
        model_spec=model_spec,
    )
    stage = _run_stage(
        label=experiment,
        dim="AGG",
        job=prompts.aggregate(
            resolve_prompts(adapter, TASK_PAVE_NO_FAULT), OPENCODE_SURFACE, k=3
        ),
        fallback=base_tree(),
        adapter=adapter,
        prop=prop,
        ctx_dir=root / "context",
        task_id=TASK_PAVE_NO_FAULT,
        rollouts=[run_view(label, runs[label]) for label in labels[:3]],
        harness_dir=base_dir,
        library_dir=None,
        pool=pool,
        decisions={label: "controlled candidate supplied for composition" for label in labels[3:]},
    )
    reply = _raw_reply(prop)
    actual = execute_pave(f"phase2_{experiment}", stage.tree)
    result = {
        "phase": 2,
        "idea": "PAVE-R",
        "experiment": "F1_F2",
        "condition": condition_name,
        "provenance_visible": with_provenance,
        "interface": "COMPACT_MANIFEST",
        "model": prop.spec.model,
        "solver_model": "deterministic-fixture",
        "improver_model": prop.spec.model,
        "execution_harness": "opencode",
        "steps": steps,
        "fell_back": stage.fell_back,
        "kept_base": stage.kept_base,
        "explicit_decision": explicit_decision(reply),
        "valid_research_result": not stage.fell_back and explicit_decision(reply),
        "notes": stage.notes,
        "error": stage.error,
        "diff": harness_tree.diff_summary(OPENCODE_SURFACE, base_tree(), stage.tree),
        "hidden_offline_evaluation": actual,
        "cost_usd": stage.usd,
        "calls": prop.calls,
    }
    out = RESULTS / experiment
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    write_tree(out / "composed_harness", stage.tree)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", choices=("cite-e1", "pave"))
    parser.add_argument("--approve-paid", action="store_true")
    parser.add_argument("--max-usd", type=float, required=True)
    parser.add_argument("--max-calls", type=int, required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--model-profile")
    parser.add_argument("--improver-model")
    parser.add_argument(
        "--launcher", type=Path, default=ROOT / "scripts/lab_agent_live_sandbox.py"
    )
    args = parser.parse_args(argv)
    if not args.approve_paid:
        parser.error("phase-2 model calls require explicit --approve-paid authorization")
    if not 0 < args.max_usd <= 20:
        parser.error("--max-usd must be in (0, 20]")
    if args.max_calls < 1 or args.steps < 1:
        parser.error("--max-calls and --steps must be positive")
    readiness()
    for key in ("HARNESS2_GATEWAY_CA", "HARNESS2_GATEWAY_SOCKET", "HARNESS2_MODELS_SNAPSHOT"):
        if not os.environ.get(key):
            parser.error(f"{key} is required")
    install_trace_launcher(args.launcher.resolve())
    models = resolve_run_model_config(
        profile=args.model_profile, improver_model=args.improver_model
    )
    budget = LiveBudget(max_usd=args.max_usd, max_calls=args.max_calls)
    if args.experiment == "cite-e1":
        results = [cite_e1(budget, args.steps, models.improver)]
    else:
        specs = [
            ("A0_clean", False),
            ("A1_isolated", False),
            ("A2_systematic", False),
            ("A2_systematic", True),
        ]
        results = [
            pave_case(
                budget,
                condition_name=name,
                with_provenance=provenance,
                steps=args.steps,
                model_spec=models.improver,
            )
            for name, provenance in specs
        ]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{args.experiment}_budget.json").write_text(
        json.dumps(budget.to_dict(), indent=2) + "\n"
    )
    print(json.dumps({"results": results, "budget": budget.to_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
