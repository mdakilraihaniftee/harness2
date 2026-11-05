#!/usr/bin/env python3
"""Retry only the two inconclusive live composer conditions once."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from harness2.core.proposer import Proposer
from harness2.core.spec import resolve_channel_model
from harness2.model_config import resolve_run_model_config
from research_pilots.accounting import LiveBudget
from research_pilots.run_live import LIVE, RESULTS, cite_case, pave_case, readiness
from scripts.reproduce_lab import install_launcher


def update(result_pave: dict, result_cite: dict, budget: LiveBudget) -> None:
    path = RESULTS / "experiment_summary.json"
    summary = json.loads(path.read_text())
    replacement = {
        ("PAVE-R", "A2_systematic"): {
            "idea": "PAVE-R",
            "experiment": "controlled_composer",
            "condition": "A2_systematic",
            "evidence_kind": "REAL_LLM_COMPOSER",
            "status": "COMPLETED"
            if not result_pave["stage"]["fell_back"]
            else "INCONCLUSIVE",
            "utility": result_pave["hidden_evaluation"]["hidden_utility"],
            "notes": result_pave["stage"]["notes"],
        },
        ("CITE-R", "controlled_A_B_pool"): {
            "idea": "CITE-R",
            "experiment": "controlled_composer",
            "condition": "controlled_A_B_pool",
            "evidence_kind": "REAL_LLM_COMPOSER",
            "status": "COMPLETED"
            if not result_cite["stage"]["fell_back"]
            else "INCONCLUSIVE",
            "utility": result_cite["hidden_evaluation"]["utility"],
            "notes": result_cite["stage"]["notes"],
        },
    }
    rows = []
    for row in summary["experiments"]:
        key = (row.get("idea"), row.get("condition"))
        rows.append(replacement.pop(key, row))
    rows.extend(replacement.values())
    summary["experiments"] = rows
    summary["live"] = {"status": "COMPLETED_WITH_TARGETED_RETRIES", **budget.to_dict()}
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
        writer.writerows({key: row.get(key, "") for key in fields} for row in rows)
    (RESULTS / "live_budget.json").write_text(json.dumps(budget.to_dict(), indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-paid", action="store_true")
    parser.add_argument("--launcher", type=Path, default=Path("scripts/lab_agent_live_sandbox.py"))
    parser.add_argument("--trial", default="retry1")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--max-calls", type=int, default=5)
    parser.add_argument("--model-profile")
    parser.add_argument("--improver-model")
    args = parser.parse_args(argv)
    if not args.approve_paid:
        parser.error("targeted retries require --approve-paid")
    if args.steps < 1 or args.max_calls < 1:
        parser.error("--steps and --max-calls must be positive")
    readiness()
    prior = json.loads((RESULTS / "live_budget.json").read_text())
    budget = LiveBudget(max_usd=20.0, max_calls=args.max_calls, calls=list(prior["calls"]))
    install_launcher(args.launcher.resolve(), LIVE)
    models = resolve_run_model_config(
        profile=args.model_profile, improver_model=args.improver_model
    )
    channel = resolve_channel_model(
        "opencode", models.improver.runtime_id("opencode"), steps=args.steps, timeout=600
    )
    channel = channel.__class__(**{**channel.__dict__, "model_spec": models.improver})
    prop = Proposer(channel, audit_dir=LIVE / f"audit_{args.trial}", attempts=1)
    pave = pave_case(prop, budget, "A2_systematic", args.trial)
    cite = cite_case(prop, budget, args.trial)
    update(pave, cite, budget)
    print(json.dumps({"pave": pave, "cite": cite, "budget": budget.to_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
