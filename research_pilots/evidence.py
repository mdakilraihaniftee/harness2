"""Controlled trajectory rendering over immutable synthetic execution records."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

CONDITIONS = ("A0_clean", "A1_isolated", "A2_systematic", "A2_matched_independent")


@dataclass(frozen=True)
class EvidenceCondition:
    name: str
    corrupt_labels: frozenset[str]
    source_mode: str

    @property
    def cache_token(self) -> str:
        body = json.dumps(
            {"name": self.name, "labels": sorted(self.corrupt_labels), "source": self.source_mode},
            sort_keys=True,
        )
        return hashlib.sha256(body.encode()).hexdigest()[:12]


def condition(name: str, labels: list[str]) -> EvidenceCondition:
    if name not in CONDITIONS:
        raise ValueError(f"unknown evidence condition {name!r}")
    if name == "A0_clean":
        return EvidenceCondition(name, frozenset(), "clean")
    if name == "A1_isolated":
        return EvidenceCondition(name, frozenset(labels[:1]), "one_renderer")
    if name == "A2_systematic":
        return EvidenceCondition(name, frozenset(labels), "one_renderer")
    return EvidenceCondition(name, frozenset(labels), "independent_renderers")


def load_record(run_dir: Path) -> dict:
    return json.loads((Path(run_dir) / "execution.json").read_text())


def record_digest(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def render_event(event: dict, *, corrupt: bool) -> str:
    action = event["action"]
    actual = event["actual"]
    if corrupt and actual == "recorded":
        visible = "ERROR: operation failed before commit"
    elif corrupt and actual == "duplicate_rejected":
        visible = "transaction recorded successfully"
    elif actual == "recorded":
        visible = "transaction recorded successfully"
    elif actual == "duplicate_rejected":
        visible = "ERROR: duplicate operation rejected"
    elif actual == "schema_rejected":
        visible = "ERROR: missing required field amount_cents for schema_version=2"
    else:
        visible = str(actual)
    return f"[ACTION] {action}\n[OBSERVATION]\n{visible}"


def render_record(record: dict, evidence: EvidenceCondition) -> str:
    corrupt = record["label"] in evidence.corrupt_labels
    return "\n".join(render_event(event, corrupt=corrupt) for event in record["events"])


def materialize_views(
    records: dict[str, dict], conditions: list[EvidenceCondition], output: Path
) -> dict:
    """Write visible views without mutating records and return validation metadata."""
    output = Path(output)
    before = {label: record_digest(record) for label, record in records.items()}
    views: dict[str, dict[str, str]] = {}
    for evidence in conditions:
        root = output / evidence.name
        root.mkdir(parents=True, exist_ok=True)
        views[evidence.name] = {}
        for label, record in records.items():
            body = render_record(copy.deepcopy(record), evidence)
            (root / f"{label}.md").write_text(body + "\n")
            views[evidence.name][label] = body
        (root / "metadata.json").write_text(
            json.dumps(
                {
                    "condition": evidence.name,
                    "cache_token": evidence.cache_token,
                    "corrupt_labels": sorted(evidence.corrupt_labels),
                    "source_mode": evidence.source_mode,
                    "record_digests": before,
                },
                indent=2,
            )
            + "\n"
        )
    after = {label: record_digest(record) for label, record in records.items()}
    if before != after:
        raise AssertionError("evidence rendering mutated an execution record")
    return {"record_digests": before, "views": views}
