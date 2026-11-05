"""Deterministic no-oracle-in-context fixtures for PAVE-R and CITE-R warm-ups."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from harness2.core import tree as harness_tree
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.bundles import combine

TASK_PAVE_NO_FAULT = "invoice/no-fault"
TASK_PAVE_SHIFT = "invoice/schema-shift"
TASK_CITE = "invoice/compound-shift"


def base_tree() -> dict[str, str]:
    tree = {path: "" for path in OPENCODE_SURFACE.always_on}
    tree["systemprompt.md"] = (
        "Submit each invoice once with the legacy `amount` field. "
        "When invoice calculation rules apply, load the `invoice_rules` skill.\n"
    )
    tree["guardrails.md"] = "Never submit the same invoice twice.\n"
    tree["skills/invoice_rules/SKILL.md"] = (
        "---\nname: invoice_rules\ndescription: Calculate invoice request values\n---\n"
        "Use the raw dollar amount as supplied.\n"
    )
    harness_tree.validate(OPENCODE_SURFACE, tree, allow_subagents=False)
    return tree


def pave_retry_tree() -> dict[str, str]:
    tree = base_tree()
    tree["guardrails.md"] = (
        "Verification rule: after every invoice submission, resubmit the identical invoice once "
        "to confirm persistence, even if the first call reports success.\n"
    )
    harness_tree.validate(OPENCODE_SURFACE, tree, allow_subagents=False)
    return tree


def cite_candidates() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    base = base_tree()
    a = dict(base)
    a["systemprompt.md"] = (
        "Submit each invoice once with `schema_version=2` and the `amount_cents` field. "
        "When invoice calculation rules apply, load the `invoice_rules` skill.\n"
    )
    b = dict(base)
    b["skills/invoice_rules/SKILL.md"] = (
        "---\nname: invoice_rules\ndescription: Calculate invoice request values\n---\n"
        "For amount_cents, multiply dollars by 100 exactly once and round to an integer.\n"
    )
    c = dict(base)
    c["LongTermMEMORY.md"] = (
        "Compatibility rule: multiply any computed amount_cents by 100 again before submission.\n"
    )
    for tree in (a, b, c):
        harness_tree.validate(OPENCODE_SURFACE, tree, allow_subagents=False)
    return base, {"A": a, "B": b, "C": c}


def _has(tree: dict[str, str], phrase: str) -> bool:
    return phrase in "\n".join(tree.values())


def cite_request(tree: dict[str, str], amount: str = "12.34") -> dict:
    schema_two = _has(tree, "schema_version=2") and _has(tree, "amount_cents")
    cents_rule = _has(tree, "multiply dollars by 100 exactly once")
    value = round(float(amount) * 100) if cents_rule else float(amount)
    if _has(tree, "multiply any computed amount_cents by 100 again"):
        value *= 100
    return (
        {"invoice_id": "INV-7", "schema_version": 2, "amount_cents": value}
        if schema_two
        else {"invoice_id": "INV-7", "amount": value}
    )


def hidden_cite_score(request: dict) -> dict:
    expected = {"invoice_id": "INV-7", "schema_version": 2, "amount_cents": 1234}
    checks = {
        "schema_version": request.get("schema_version") == 2,
        "field": "amount_cents" in request and "amount" not in request,
        "value": request.get("amount_cents") == 1234,
        "no_extra_fields": set(request) == set(expected),
    }
    return {"utility": float(all(checks.values())), "checks": checks, "request": request}


def evaluate_cite(tree: dict[str, str]) -> dict:
    return hidden_cite_score(cite_request(tree))


def cite_matrix() -> dict:
    base, candidates = cite_candidates()
    trees = {
        "H0": base,
        "HA": candidates["A"],
        "HB": candidates["B"],
        "HC": candidates["C"],
        "HAB": combine(OPENCODE_SURFACE, base, candidates, ["A", "B"]),
        "HABC": combine(OPENCODE_SURFACE, base, candidates, ["A", "B", "C"]),
    }
    scores = {name: evaluate_cite(tree) for name, tree in trees.items()}
    u = {name: row["utility"] for name, row in scores.items()}
    return {
        "scores": scores,
        "gamma_ab": u["HAB"] - u["HA"] - u["HB"] + u["H0"],
        "interference_c": u["HAB"] - u["HABC"],
        "trees": trees,
    }


def execute_pave(label: str, tree: dict[str, str], *, shifted: bool = False) -> dict:
    retry = "resubmit the identical invoice once" in tree.get("guardrails.md", "")
    schema_two = "schema_version=2" in tree.get("systemprompt.md", "")
    events = []
    committed = 0
    duplicate_attempts = 0
    attempts = 2 if retry else 1
    for index in range(attempts):
        if shifted and not schema_two:
            actual = "schema_rejected"
        elif committed:
            actual = "duplicate_rejected"
            duplicate_attempts += 1
        else:
            actual = "recorded"
            committed += 1
        events.append({"action": f"submit_invoice attempt={index + 1}", "actual": actual})
    utility = float(committed == 1 and duplicate_attempts == 0)
    return {
        "label": label,
        "task": TASK_PAVE_SHIFT if shifted else TASK_PAVE_NO_FAULT,
        "events": events,
        "actual_state": {"transactions": committed, "duplicate_attempts": duplicate_attempts},
        "hidden_utility": utility,
        "artifact": "Invoice processing attempted; see the transaction system for final state.",
    }


def reference_shift_tree() -> dict[str, str]:
    tree = base_tree()
    tree["systemprompt.md"] = (
        "Submit each invoice once with `schema_version=2` and the `amount_cents` field. "
        "When invoice calculation rules apply, load the `invoice_rules` skill.\n"
    )
    tree["skills/invoice_rules/SKILL.md"] = (
        "---\nname: invoice_rules\ndescription: Calculate invoice request values\n---\n"
        "For amount_cents, multiply dollars by 100 exactly once and round to an integer.\n"
    )
    harness_tree.validate(OPENCODE_SURFACE, tree, allow_subagents=False)
    return tree


def write_execution(root: Path, record: dict) -> Path:
    run_dir = Path(root) / record["label"]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "execution.json").write_text(json.dumps(record, indent=2) + "\n")
    (run_dir / "artifact.txt").write_text(record["artifact"] + "\n")
    return run_dir


def execute_script(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Used by tests to prove fixture scripts run in an isolated subprocess."""
    return subprocess.run(
        [sys.executable, str(path), *args], capture_output=True, text=True, timeout=10
    )
