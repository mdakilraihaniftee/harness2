"""Append phase-2 deterministic and authorization-gated records to the result index."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from research_pilots.finalize_results import main as finalize_phase1

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PHASE2 = RESULTS / "phase2"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def live_row(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    result = read_json(path)
    status = "COMPLETED" if result.get("valid_research_result") else "INCONCLUSIVE"
    return default | {
        "status": status,
        "utility": (result.get("hidden_offline_evaluation") or {}).get(
            "utility",
            (result.get("hidden_offline_evaluation") or {}).get("hidden_utility"),
        ),
        "notes": result.get("selected") or result.get("notes") or result.get("error") or "",
    }


def main() -> int:
    finalize_phase1()
    path = RESULTS / "experiment_summary.json"
    summary = read_json(path)
    for row in summary["experiments"]:
        row.setdefault("phase", 1)
        if row.get("evidence_kind") in ("REAL_LLM_COMPOSER", "REAL_LLM_PIPELINE"):
            row.setdefault("interface", "ORIGINAL_FILESYSTEM")
    summary["experiments"] = [
        row for row in summary["experiments"] if int(row.get("phase", 1)) != 2
    ]
    validation = read_json(PHASE2 / "manifest_validation.json")
    rows = [
        {
            "phase": 2,
            "idea": "PAVE-R",
            "experiment": "phase1_forensic_reassessment",
            "condition": "A0_clean",
            "interface": "ORIGINAL_FILESYSTEM",
            "evidence_kind": "AUDIT_REASSESSMENT",
            "status": "INCONCLUSIVE",
            "utility": 1.0,
            "notes": (
                "phase-1 operational record said COMPLETED; forensic review found no "
                "parseable decision and a response ending mid-navigation"
            ),
        },
        {
            "phase": 2,
            "idea": "SHARED",
            "experiment": "compact_manifest_validation",
            "condition": "cite_and_pave_controlled_contexts",
            "interface": "COMPACT_MANIFEST",
            "evidence_kind": "DETERMINISTIC_INTERFACE_TEST",
            "status": "PASS",
            "utility": None,
            "notes": (
                f"CITE={validation['cite']['estimated_tokens']} estimated tokens; "
                "PAVE=1365-1518; exact edits reconstruct; original evidence preserved"
            ),
        },
        live_row(
            PHASE2 / "live/cite_e1_compact/result.json",
            {
                "phase": 2,
                "idea": "CITE-R",
                "experiment": "E1_compact_composer",
                "condition": "controlled_A_B_pool",
                "interface": "COMPACT_MANIFEST",
                "evidence_kind": "REAL_LLM_COMPOSER",
                "status": "PENDING_AUTHORIZATION",
                "utility": None,
                "notes": "no phase-2 paid call made; explicit authorization required",
            },
        ),
        {
            "phase": 2,
            "idea": "CITE-R",
            "experiment": "E2_real_executor_interaction",
            "condition": "H0_HA_HB_HAB",
            "interface": "COMPACT_MANIFEST",
            "evidence_kind": "REAL_LLM_EXECUTOR",
            "status": "NOT_RUN",
            "utility": None,
            "notes": "gated on an interpretable E1 result and explicit paid authorization",
        },
        {
            "phase": 2,
            "idea": "CITE-R",
            "experiment": "E3_interference",
            "condition": "A_B_C",
            "interface": "COMPACT_MANIFEST",
            "evidence_kind": "REAL_LLM_COMPOSER",
            "status": "NOT_RUN",
            "utility": None,
            "notes": "gated on interpretable E1 and E2 results",
        },
    ]
    pave_specs = (
        ("A0_clean", False),
        ("A1_isolated", False),
        ("A2_systematic", False),
        ("A2_systematic", True),
    )
    for condition, provenance in pave_specs:
        suffix = "with_provenance" if provenance else "no_provenance"
        rows.append(
            live_row(
                PHASE2 / f"live/pave_{condition}_{suffix}/result.json",
                {
                    "phase": 2,
                    "idea": "PAVE-R",
                    "experiment": "F1_F2_compact_composer",
                    "condition": condition,
                    "interface": "COMPACT_MANIFEST",
                    "provenance": "VISIBLE" if provenance else "NOT_VISIBLE",
                    "evidence_kind": "REAL_LLM_COMPOSER",
                    "status": "PENDING_AUTHORIZATION",
                    "utility": None,
                    "notes": "no phase-2 paid call made; gated on valid composer interface",
                },
            )
        )
    rows.append(
        {
            "phase": 2,
            "idea": "PAVE-R",
            "experiment": "F3_rollout_scaling",
            "condition": "full_k3_pipeline",
            "interface": "COMPACT_MANIFEST",
            "evidence_kind": "REAL_LLM_PIPELINE",
            "status": "NOT_TESTED",
            "utility": None,
            "notes": "gated on completed F1/F2 decisions and a separate budget decision",
        }
    )
    summary["experiments"].extend(rows)
    completed = [
        row
        for row in rows
        if row["evidence_kind"].startswith("REAL_LLM") and row["status"] == "COMPLETED"
    ]
    budget_paths = (PHASE2 / "live/cite-e1_budget.json", PHASE2 / "live/pave_budget.json")
    budgets = [read_json(budget_path) for budget_path in budget_paths if budget_path.is_file()]
    phase2_calls = [call for budget in budgets for call in budget.get("calls", [])]
    phase2_spend = round(sum(float(call.get("cost_usd") or 0) for call in phase2_calls), 6)
    summary["phase2"] = {
        "status": "LIVE_RESULTS_PRESENT" if completed else "AWAITING_PAID_AUTHORIZATION",
        "incremental_spend_usd": phase2_spend,
        "live_calls": len(phase2_calls),
        "paid_authorization_recorded": bool(phase2_calls),
        "deterministic_manifest_validation": "PASS",
    }
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    fields = [
        "phase",
        "idea",
        "experiment",
        "condition",
        "interface",
        "provenance",
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
        writer.writerows({field: row.get(field, "") for field in fields} for row in summary["experiments"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
