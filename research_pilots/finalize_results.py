"""Build the final, non-duplicated research result index from saved artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def summarize_live_usage() -> dict:
    usage = {
        "usage_files": 0,
        "usage_events": 0,
        "wall_seconds_sum": 0.0,
        "cost_usd": 0.0,
        "tokens": {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache_read": 0,
            "cache_write": 0,
        },
    }
    usage_dir = ROOT / "runs" / "live" / "agent-usage"
    for path in sorted(usage_dir.glob("*.json")):
        record = read_json(path)
        usage["usage_files"] += 1
        usage["wall_seconds_sum"] += float(record.get("wall_s", 0.0))
        for event in record.get("usage_events", []):
            tokens = event.get("tokens", {})
            cache = tokens.get("cache", {})
            usage["usage_events"] += 1
            usage["cost_usd"] += float(event.get("cost_usd", 0.0))
            usage["tokens"]["input"] += int(tokens.get("input", 0))
            usage["tokens"]["output"] += int(tokens.get("output", 0))
            usage["tokens"]["reasoning"] += int(tokens.get("reasoning", 0))
            usage["tokens"]["cache_read"] += int(cache.get("read", 0))
            usage["tokens"]["cache_write"] += int(cache.get("write", 0))
    usage["wall_seconds_sum"] = round(usage["wall_seconds_sum"], 1)
    usage["cost_usd"] = round(usage["cost_usd"], 6)
    usage["note"] = "Raw provider counters summed across all attempts; categories can overlap."
    return usage


def main() -> None:
    config = read_json(RESULTS / "config.json")
    live_budget = read_json(RESULTS / "live_budget.json")
    positive = read_json(RESULTS / "pave" / "positive_control.json")
    interaction = read_json(RESULTS / "cite" / "interaction_matrix.json")

    experiments: list[dict] = []
    for condition in config["conditions"]:
        context_sha256 = tree_digest(
            ROOT / "runs" / "deterministic" / "contexts" / condition
        )
        experiments.append(
            {
                "idea": "PAVE-R",
                "experiment": "evidence_intervention",
                "condition": condition,
                "evidence_kind": "SIMULATED_RENDERING",
                "status": "PASS",
                "utility": None,
                "notes": f"context_sha256={context_sha256}",
            }
        )

    experiments.extend(
        [
            {
                "idea": "PAVE-R",
                "experiment": "positive_control",
                "condition": "schema_shift",
                "evidence_kind": "DETERMINISTIC_EXECUTION",
                "status": "PASS",
                "utility": positive["reference_repair"]["hidden_utility"],
                "notes": "reference repair beats base (1.0 versus 0.0)",
            },
            {
                "idea": "CITE-R",
                "experiment": "joint_bundle",
                "condition": "HAB",
                "evidence_kind": "DETERMINISTIC_EXECUTION",
                "status": "PASS",
                "utility": interaction["scores"]["HAB"]["utility"],
                "notes": f"gamma_ab={interaction['gamma_ab']}",
            },
            {
                "idea": "CITE-R",
                "experiment": "interference",
                "condition": "HABC",
                "evidence_kind": "DETERMINISTIC_EXECUTION",
                "status": "PASS",
                "utility": interaction["scores"]["HABC"]["utility"],
                "notes": f"interference_c={interaction['interference_c']}",
            },
            {
                "idea": "PAVE-R",
                "experiment": "controlled_composer",
                "condition": "A0_clean",
                "evidence_kind": "REAL_LLM_COMPOSER",
                "status": "COMPLETED",
                "utility": 1.0,
                "notes": "kept base; no file modifications; candidate retry edit recognized",
            },
            {
                "idea": "PAVE-R",
                "experiment": "controlled_composer",
                "condition": "A2_systematic",
                "evidence_kind": "REAL_LLM_COMPOSER",
                "status": "INCONCLUSIVE",
                "utility": 1.0,
                "notes": (
                    "all attempts kept/fell back to base, but metadata and tool-step "
                    "failures prevented a substantive composer decision"
                ),
            },
            {
                "idea": "CITE-R",
                "experiment": "controlled_composer",
                "condition": "controlled_A_B_pool",
                "evidence_kind": "REAL_LLM_COMPOSER",
                "status": "INCONCLUSIVE",
                "utility": 0.0,
                "notes": (
                    "kept/fell back to base; tool-step exhaustion occurred before "
                    "a substantive composition decision"
                ),
            },
            {
                "idea": "PAVE-R",
                "experiment": "k3_scaling_and_library_transfer",
                "condition": "systematic_to_clean",
                "evidence_kind": "REAL_LLM_PIPELINE",
                "status": "NOT_RUN",
                "utility": None,
                "notes": "stopped after inconclusive k=1 controlled-composer diagnostics",
            },
            {
                "idea": "CITE-R",
                "experiment": "natural_proposer_and_selector",
                "condition": "original_pipeline",
                "evidence_kind": "REAL_LLM_PIPELINE",
                "status": "NOT_RUN",
                "utility": None,
                "notes": "controlled composer was inconclusive; further paid calls not justified",
            },
        ]
    )

    summary = {
        "schema_version": 1,
        "configuration": {
            **config,
            "live_model_calls": len(live_budget["calls"]),
            "live_model": "google-vertex/gemini-3.5-flash",
        },
        "experiments": experiments,
        "live": {
            "status": "COMPLETED_WITH_INCONCLUSIVE_CONDITIONS",
            **live_budget,
        },
    }
    (RESULTS / "experiment_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (RESULTS / "live_usage_summary.json").write_text(
        json.dumps(summarize_live_usage(), indent=2) + "\n", encoding="utf-8"
    )

    fields = [
        "idea",
        "experiment",
        "condition",
        "evidence_kind",
        "status",
        "utility",
        "notes",
    ]
    with (RESULTS / "experiment_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(experiments)


if __name__ == "__main__":
    main()
