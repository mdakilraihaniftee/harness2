#!/usr/bin/env python3
"""Cost-capped real-LLM composer micro-experiments over deterministic fixtures."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from harness2 import config
from harness2.core import prompts
from harness2.core import tree as harness_tree
from harness2.core.proposer import Proposer
from harness2.core.recursion import _run_stage
from harness2.core.spec import RunView, resolve_channel_model, resolve_prompts
from harness2.model_config import resolve_run_model_config
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.accounting import LiveBudget
from research_pilots.adapter import PilotAdapter
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
from scripts.reproduce_lab import install_launcher

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "research_pilots/runs/live"
RESULTS = ROOT / "research_pilots/results"


def run_view(label: str, run_dir: Path) -> RunView:
    return RunView(label, f"research-live/{label}", run_dir, ok=True, delivered=True)


def materialize_tree(path: Path, tree: dict[str, str]) -> Path:
    return harness_tree.write_tree(OPENCODE_SURFACE, tree, path, stubs=False)


def pave_case(prop: Proposer, budget: LiveBudget, name: str, trial: str = "initial") -> dict:
    labels = [f"base{i}" for i in range(1, 4)] + [
        f"{dim}{i}" for i in range(1, 4) for dim in ("inv", "dom")
    ]
    corrupt = labels if name == "A2_systematic" else []
    evidence = condition(name, corrupt)
    root = LIVE / "pave" / name / trial
    raw = root / "raw"
    trees: dict[str, dict[str, str]] = {}
    runs = {}
    for label in labels:
        tree = pave_retry_tree() if label.startswith("inv") else base_tree()
        trees[label] = tree
        runs[label] = write_execution(raw, execute_pave(label, tree))
    adapter = PilotAdapter(root, TASK_PAVE_NO_FAULT, base_tree(), evidence)
    base_dir = materialize_tree(root / "harnesses/base", base_tree())
    base_rollouts = [run_view(label, runs[label]) for label in labels[:3]]
    pool = []
    for label in labels[3:]:
        hdir = materialize_tree(root / "harnesses" / label, trees[label])
        pool.append((label, hdir, run_view(label, runs[label])))
    budget.require_capacity()
    stage = _run_stage(
        label=f"pave_{name}_{trial}",
        dim="AGG",
        job=prompts.aggregate(resolve_prompts(adapter, TASK_PAVE_NO_FAULT), OPENCODE_SURFACE, k=3),
        fallback=base_tree(),
        adapter=adapter,
        prop=prop,
        ctx_dir=root / "context",
        task_id=TASK_PAVE_NO_FAULT,
        rollouts=base_rollouts,
        harness_dir=base_dir,
        library_dir=None,
        pool=pool,
        decisions={label: "controlled candidate supplied for composition" for label in labels[3:]},
    )
    actual = execute_pave(f"live_{name}", stage.tree)
    materialize_tree(root / "composed_harness", stage.tree)
    budget.record(
        f"pave_{name}_{trial}",
        stage.usd,
        idea="PAVE-R",
        attempts=stage.attempts,
        fell_back=stage.fell_back,
    )
    result = {
        "condition": name,
        "model": prop.spec.model,
        "solver_model": "deterministic-fixture",
        "improver_model": prop.spec.model,
        "execution_harness": "opencode",
        "stage": {
            "kept_base": stage.kept_base,
            "fell_back": stage.fell_back,
            "attempts": stage.attempts,
            "cost_usd": stage.usd,
            "notes": stage.notes,
            "error": stage.error,
        },
        "hidden_evaluation": actual,
        "diff": harness_tree.diff_summary(OPENCODE_SURFACE, base_tree(), stage.tree),
    }
    (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def cite_record(label: str, tree: dict[str, str]) -> dict:
    score = evaluate_cite(tree)
    failures = [name for name, passed in score["checks"].items() if not passed]
    actual = "accepted" if score["utility"] else "ERROR: " + ", ".join(failures)
    return {
        "label": label,
        "task": TASK_CITE,
        "events": [{"action": f"submit_invoice request={score['request']}", "actual": actual}],
        "actual_state": {"request": score["request"]},
        "hidden_utility": score["utility"],
        "artifact": "Invoice processing attempted; consult API state for acceptance.",
    }


def cite_case(prop: Proposer, budget: LiveBudget, trial: str = "initial") -> dict:
    root = LIVE / "cite/controlled_composer" / trial
    base, candidates = cite_candidates()
    trees = {"base1": base, "inv1": candidates["A"], "dom1": candidates["B"]}
    runs = {
        label: write_execution(root / "raw", cite_record(label, tree))
        for label, tree in trees.items()
    }
    evidence = condition("A0_clean", list(trees))
    adapter = PilotAdapter(root, TASK_CITE, base, evidence)
    base_dir = materialize_tree(root / "harnesses/base", base)
    pool = []
    for label in ("inv1", "dom1"):
        hdir = materialize_tree(root / "harnesses" / label, trees[label])
        pool.append((label, hdir, run_view(label, runs[label])))
    budget.require_capacity()
    stage = _run_stage(
        label=f"cite_controlled_{trial}",
        dim="AGG",
        job=prompts.aggregate(resolve_prompts(adapter, TASK_CITE), OPENCODE_SURFACE, k=1),
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
    hidden = evaluate_cite(stage.tree)
    materialize_tree(root / "composed_harness", stage.tree)
    budget.record(
        f"cite_controlled_composer_{trial}",
        stage.usd,
        idea="CITE-R",
        attempts=stage.attempts,
        fell_back=stage.fell_back,
    )
    result = {
        "condition": "controlled_A_B_pool",
        "model": prop.spec.model,
        "solver_model": "deterministic-fixture",
        "improver_model": prop.spec.model,
        "execution_harness": "opencode",
        "stage": {
            "kept_base": stage.kept_base,
            "fell_back": stage.fell_back,
            "attempts": stage.attempts,
            "cost_usd": stage.usd,
            "notes": stage.notes,
            "error": stage.error,
        },
        "hidden_evaluation": hidden,
        "diff": harness_tree.diff_summary(OPENCODE_SURFACE, base, stage.tree),
        "natural_proposer": {
            "status": "NOT_RUN",
            "reason": "controlled-composer micro-experiment intentionally excludes natural generation",
        },
    }
    (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def update_summary(pave: list[dict], cite: dict, budget: LiveBudget) -> None:
    path = RESULTS / "experiment_summary.json"
    summary = json.loads(path.read_text())
    live_rows = []
    for result in pave:
        live_rows.append(
            {
                "idea": "PAVE-R",
                "experiment": "controlled_composer",
                "condition": result["condition"],
                "evidence_kind": "REAL_LLM_COMPOSER",
                "status": "COMPLETED"
                if not result["stage"]["fell_back"]
                else "INCONCLUSIVE",
                "utility": result["hidden_evaluation"]["hidden_utility"],
                "notes": result["stage"]["notes"],
            }
        )
    live_rows.append(
        {
            "idea": "CITE-R",
            "experiment": "controlled_composer",
            "condition": cite["condition"],
            "evidence_kind": "REAL_LLM_COMPOSER",
            "status": "COMPLETED" if not cite["stage"]["fell_back"] else "INCONCLUSIVE",
            "utility": cite["hidden_evaluation"]["utility"],
            "notes": cite["stage"]["notes"],
        }
    )
    summary["experiments"] = [
        row for row in summary["experiments"] if row.get("evidence_kind") != "REAL_LLM_COMPOSER"
    ] + live_rows
    summary["live"] = {"status": "COMPLETED", **budget.to_dict()}
    path.write_text(json.dumps(summary, indent=2) + "\n")
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
        writer.writerows({key: row.get(key, "") for key in fields} for row in summary["experiments"])
    (RESULTS / "live_budget.json").write_text(json.dumps(budget.to_dict(), indent=2) + "\n")


def readiness() -> None:
    required = {
        "HARNESS2_GATEWAY_CA": os.environ.get("HARNESS2_GATEWAY_CA"),
        "HARNESS2_GATEWAY_SOCKET": os.environ.get("HARNESS2_GATEWAY_SOCKET"),
        "HARNESS2_MODELS_SNAPSHOT": os.environ.get("HARNESS2_MODELS_SNAPSHOT"),
    }
    missing = [key for key, value in required.items() if not value or not Path(value).exists()]
    if missing:
        raise RuntimeError(f"missing live isolation inputs: {', '.join(missing)}")
    if not config.VERTEX_PROJECT or not config.IMPROVER_MODEL:
        raise RuntimeError("configured Vertex project and improver model are required")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-paid", action="store_true")
    parser.add_argument("--max-usd", type=float, default=20.0)
    parser.add_argument("--launcher", type=Path, default=ROOT / "scripts/lab_agent_live_sandbox.py")
    parser.add_argument("--model-profile")
    parser.add_argument("--improver-model")
    args = parser.parse_args(argv)
    if not args.approve_paid:
        parser.error("real LLM micro-experiments require --approve-paid")
    if args.max_usd <= 0 or args.max_usd > 20:
        parser.error("--max-usd must be in (0, 20]")
    readiness()
    LIVE.mkdir(parents=True, exist_ok=True)
    install_launcher(args.launcher.resolve(), LIVE)
    models = resolve_run_model_config(
        profile=args.model_profile, improver_model=args.improver_model
    )
    channel = resolve_channel_model(
        "opencode", models.improver.runtime_id("opencode"), steps=10, timeout=600
    )
    channel = channel.__class__(**{**channel.__dict__, "model_spec": models.improver})
    prop = Proposer(channel, audit_dir=LIVE / "audit", attempts=1)
    budget = LiveBudget(max_usd=args.max_usd, max_calls=3)
    pave = [
        pave_case(prop, budget, "A0_clean"),
        pave_case(prop, budget, "A2_systematic"),
    ]
    cite = cite_case(prop, budget)
    update_summary(pave, cite, budget)
    print(json.dumps({"pave": pave, "cite": cite, "budget": budget.to_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
