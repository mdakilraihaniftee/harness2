"""Strictly separate explicit composer decisions from operational fallback states."""

from __future__ import annotations

import re

from research_pilots.manifest import explicit_decision


def parse_decision(text: str, *, tree_changed: bool) -> str:
    notes = re.search(r"<notes>(.*?)</notes>", text or "", re.I | re.S)
    if not notes:
        return "INVALID"
    body = notes.group(1).strip()
    if not tree_changed and re.search(r"\bKEEP_BASE\b", body, re.I):
        return "KEEP_BASE"
    if tree_changed and explicit_decision(text):
        return "EDIT_OR_MERGE"
    return "INVALID"


def classify_completion(
    *,
    response: str,
    tree_changed: bool,
    tree_parseable: bool,
    tree_valid: bool,
    fell_back: bool,
    evidence_accessed: bool,
    step_exhausted: bool,
) -> dict:
    decision = parse_decision(response, tree_changed=tree_changed)
    operational_failure = bool(
        fell_back
        or not tree_parseable
        or not tree_valid
        or not evidence_accessed
        or step_exhausted
    )
    valid = not operational_failure and decision != "INVALID"
    return {
        "decision": decision if not operational_failure else "OPERATIONAL_FAILURE",
        "explicit_decision": decision != "INVALID",
        "valid_completed_decision": valid,
        "operational_fallback": fell_back,
        "step_exhausted": step_exhausted,
    }

