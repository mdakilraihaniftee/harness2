"""Frozen composer-only replay contexts with cache-independent repetition identities."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from harness2.core import context, prompts
from harness2.core import tree as harness_tree
from harness2.core.spec import RunView, resolve_prompts
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.adapter import PilotAdapter
from research_pilots.evidence import EvidenceCondition, condition
from research_pilots.fixtures import (
    TASK_CITE,
    TASK_PAVE_NO_FAULT,
    TASK_PAVE_SHIFT,
    base_tree,
    cite_candidates,
    execute_pave,
    pave_retry_tree,
    reference_shift_tree,
    write_execution,
)
from research_pilots.manifest import (
    INTERFACE_NOTE,
    assert_references_accessible,
    build_manifest,
)
from research_pilots.run_live import cite_record

from . import CONTEXTS, FIXTURES

_HIDDEN_MARKERS = (
    "hidden_utility",
    "required_bundle",
    "candidate a+b is correct",
    "cite_reference",
    "pave_hidden_state",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def tree_hash(tree: dict[str, str]) -> str:
    return sha256_text(json.dumps(tree, sort_keys=True, separators=(",", ":")))


def reference_hash(records: dict[str, dict], trees: dict[str, dict[str, str]]) -> str:
    body = {
        "records": records,
        "trees": {name: tree_hash(tree) for name, tree in trees.items()},
    }
    return sha256_text(json.dumps(body, sort_keys=True, separators=(",", ":")))


def repetition_identity(
    *,
    experiment_id: str,
    condition_id: str,
    task_id: str,
    sample_id: str,
    model_fingerprint: str,
    prompt_hash: str,
    reference_hash_value: str,
) -> str:
    values = (
        experiment_id,
        condition_id,
        task_id,
        sample_id,
        model_fingerprint,
        prompt_hash,
        reference_hash_value,
    )
    return hashlib.sha256("\0".join(values).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class ReplayCondition:
    experiment_id: str
    condition_id: str
    task_id: str
    environment: str
    k: int
    prompt_pack: str
    prompt_hash: str
    reference_hash: str
    context_hash: str
    manifest_hash: str
    candidate_pool: tuple[str, ...]
    candidate_scopes: dict[str, str]
    evidence_condition: str
    recursion_mode: str
    provenance_categories: tuple[str, ...]
    oracle_boundary: str
    context_root: str

    def to_dict(self) -> dict:
        return {
            **self.__dict__,
            "candidate_pool": list(self.candidate_pool),
            "provenance_categories": list(self.provenance_categories),
        }


class DiagnosticPilotAdapter(PilotAdapter):
    def __init__(self, *args, diagnostic: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.diagnostic = diagnostic

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        body = super().trajectory(run_dir, obs_trunc=obs_trunc)
        if self.diagnostic and Path(run_dir).name.startswith("base"):
            body += (
                "\n[INDEPENDENT_DIAGNOSTIC]\n"
                + self.diagnostic
                + "\nsource_id=independent-ledger-probe"
            )
        return body


class CiteFeedbackAdapter(PilotAdapter):
    def __init__(self, *args, visible_records: dict[str, str], **kwargs):
        super().__init__(*args, **kwargs)
        self.visible_records = visible_records

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        del obs_trunc
        return self.visible_records[Path(run_dir).name]


def _run_view(label: str, path: Path) -> RunView:
    return RunView(label, f"phase4-replay/{label}", path, ok=True, delivered=True)


def _write_tree(path: Path, tree: dict[str, str]) -> Path:
    return harness_tree.write_tree(OPENCODE_SURFACE, tree, path, stubs=False)


def _context_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _assert_no_hidden(root: Path) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt", ".json", ".diff"}:
            continue
        body = path.read_text(encoding="utf-8", errors="replace").lower()
        leaked = [marker for marker in _HIDDEN_MARKERS if marker in body]
        if leaked:
            raise AssertionError(f"hidden marker leaked into {path}: {leaked}")


def _build(
    *,
    root: Path,
    adapter,
    task_id: str,
    base: dict[str, str],
    base_runs: list[RunView],
    candidates: dict[str, dict[str, str]],
    candidate_runs: dict[str, RunView],
    scopes: dict[str, str],
    condition_id: str,
    environment: str,
    k: int,
    evidence_condition: str,
    reference_hash_value: str,
    source_ids: dict[str, str] | None = None,
) -> ReplayCondition:
    harness_dir = _write_tree(root / "harnesses/base", base)
    pool = [
        (
            label,
            _write_tree(root / "harnesses" / label, candidates[label]),
            candidate_runs[label],
        )
        for label in sorted(candidates)
    ]
    built = context.build(
        root / "context",
        adapter,
        task_id,
        base_runs,
        harness_dir=harness_dir,
        pool=pool,
        decisions={label: "frozen controlled candidate" for label in candidates},
    )
    manifest = build_manifest(
        built.root,
        candidate_scopes=scopes,
        condition_token=sha256_text(f"{condition_id}:{reference_hash_value}")[:16],
        source_ids=source_ids,
    )
    assert_references_accessible(manifest)
    _assert_no_hidden(built.root)
    bp = resolve_prompts(adapter, task_id)
    job = prompts.aggregate(bp, OPENCODE_SURFACE, k=k)
    return ReplayCondition(
        experiment_id=condition_id.split("_", 1)[0].lower() + "-composer-replay",
        condition_id=condition_id,
        task_id=task_id,
        environment=environment,
        k=k,
        prompt_pack=bp.prompt_pack,
        prompt_hash=sha256_text(job + "\n\n" + INTERFACE_NOTE),
        reference_hash=reference_hash_value,
        context_hash=_context_digest(built.root),
        manifest_hash=manifest.sha256,
        candidate_pool=tuple(sorted(candidates)),
        candidate_scopes=dict(scopes),
        evidence_condition=evidence_condition,
        recursion_mode="parallel_aggregate",
        provenance_categories=("DETERMINISTIC_EXECUTION", "SYNTHETIC_REPLAY"),
        oracle_boundary="hidden evaluation is outside context_root and joined only after decision",
        context_root=str(built.root),
    )


def _pave_condition(
    condition_id: str,
    *,
    k: int,
    evidence_name: str,
    shifted: bool,
    diagnostic: bool,
) -> ReplayCondition:
    root = CONTEXTS / condition_id
    labels = [f"base{i}" for i in range(1, k + 1)]
    candidates = [f"{scope}{i}" for i in range(1, k + 1) for scope in ("inv", "dom")]
    all_labels = labels + candidates
    base = base_tree()
    if shifted:
        trees = {
            label: reference_shift_tree() if label.startswith("inv") else base
            for label in all_labels
        }
    else:
        trees = {
            label: pave_retry_tree() if label.startswith("inv") else base
            for label in all_labels
        }
    records = {
        label: execute_pave(label, tree, shifted=shifted) for label, tree in trees.items()
    }
    raw = root / "raw"
    runs = {label: write_execution(raw, record) for label, record in records.items()}
    evidence = condition(evidence_name, all_labels)
    diagnostic_text = ""
    if diagnostic:
        diagnostic_text = (
            "Transaction ledger independently confirms one committed transaction and no duplicate "
            "attempt; the original single-submit procedure remains operational."
        )
    adapter = DiagnosticPilotAdapter(
        root,
        TASK_PAVE_SHIFT if shifted else TASK_PAVE_NO_FAULT,
        base,
        evidence,
        diagnostic=diagnostic_text,
    )
    candidate_trees = {label: trees[label] for label in candidates}
    ref_hash = reference_hash(records, trees)
    return _build(
        root=root,
        adapter=adapter,
        task_id=TASK_PAVE_SHIFT if shifted else TASK_PAVE_NO_FAULT,
        base=base,
        base_runs=[_run_view(label, runs[label]) for label in labels],
        candidates=candidate_trees,
        candidate_runs={label: _run_view(label, runs[label]) for label in candidates},
        scopes={label: "INV" if label.startswith("inv") else "DOM" for label in candidates},
        condition_id=condition_id,
        environment="ADAPTATION_NEEDED" if shifted else "NO_ADAPTATION_NEEDED",
        k=k,
        evidence_condition=evidence_name + ("+independent_diagnostic" if diagnostic else ""),
        reference_hash_value=ref_hash,
    )


def _cite_visible(condition_id: str) -> dict[str, str]:
    if condition_id == "CITE_V0":
        return {
            label: "[ACTION] Submit invoice\n[OBSERVATION]\nExecution completed; request rejected."
            for label in ("base1", "inv1", "dom1")
        }
    if condition_id == "CITE_V1":
        return {
            "base1": "[ACTION] Submit invoice\n[OBSERVATION]\nExecution completed; schema check failed.",
            "inv1": "[ACTION] Submit invoice\n[OBSERVATION]\nExecution completed; amount check failed.",
            "dom1": "[ACTION] Submit invoice\n[OBSERVATION]\nExecution completed; schema check failed.",
        }
    return {
        "base1": "[ACTION] Submit invoice\n[OBSERVATION]\nMissing schema_version=2 and amount_cents.",
        "inv1": "[ACTION] Submit invoice\n[OBSERVATION]\nSchema accepted; amount_cents value rejected.",
        "dom1": "[ACTION] Submit invoice\n[OBSERVATION]\nLegacy schema rejected before amount validation.",
    }


def _cite_condition(condition_id: str) -> ReplayCondition:
    root = CONTEXTS / condition_id
    base, edits = cite_candidates()
    trees = {"base1": base, "inv1": edits["A"], "dom1": edits["B"]}
    records = {label: cite_record(label, tree) for label, tree in trees.items()}
    runs = {label: write_execution(root / "raw", record) for label, record in records.items()}
    evidence = EvidenceCondition(condition_id, frozenset(), "deterministic_feedback")
    adapter = CiteFeedbackAdapter(
        root,
        TASK_CITE,
        base,
        evidence,
        visible_records=_cite_visible(condition_id),
    )
    return _build(
        root=root,
        adapter=adapter,
        task_id=TASK_CITE,
        base=base,
        base_runs=[_run_view("base1", runs["base1"])],
        candidates={"inv1": edits["A"], "dom1": edits["B"]},
        candidate_runs={
            "inv1": _run_view("inv1", runs["inv1"]),
            "dom1": _run_view("dom1", runs["dom1"]),
        },
        scopes={"inv1": "INV", "dom1": "DOM"},
        condition_id=condition_id,
        environment="ADAPTATION_NEEDED",
        k=1,
        evidence_condition=condition_id.removeprefix("CITE_"),
        reference_hash_value=reference_hash(records, trees),
    )


def prepare_replays() -> list[dict]:
    if CONTEXTS.exists():
        shutil.rmtree(CONTEXTS)
    CONTEXTS.mkdir(parents=True)
    conditions = [
        _pave_condition("PAVE_P0_K1", k=1, evidence_name="A0_clean", shifted=False, diagnostic=False),
        _pave_condition("PAVE_P1_K1", k=1, evidence_name="A1_isolated", shifted=False, diagnostic=False),
        _pave_condition("PAVE_P0_K3", k=3, evidence_name="A0_clean", shifted=False, diagnostic=False),
        _pave_condition("PAVE_P1_K3", k=3, evidence_name="A1_isolated", shifted=False, diagnostic=False),
        _pave_condition("PAVE_P2_K3", k=3, evidence_name="A2_systematic", shifted=False, diagnostic=False),
        _pave_condition("PAVE_P3_K3", k=3, evidence_name="A2_systematic", shifted=False, diagnostic=True),
        _pave_condition("PAVE_P4_K3", k=3, evidence_name="A2_matched_independent", shifted=False, diagnostic=False),
        _pave_condition("PAVE_POSITIVE_K3", k=3, evidence_name="A0_clean", shifted=True, diagnostic=False),
        _cite_condition("CITE_V0"),
        _cite_condition("CITE_V1"),
        _cite_condition("CITE_V2"),
    ]
    FIXTURES.mkdir(parents=True, exist_ok=True)
    frozen = {
        "schema_version": 1,
        "records": [
            {
                "condition_id": item.condition_id,
                "reference_hash": item.reference_hash,
                "provenance_categories": list(item.provenance_categories),
            }
            for item in conditions
        ],
        "note": "Hashes bind immutable deterministic records and candidate trees; no oracle values.",
    }
    (FIXTURES / "frozen_reference_manifest.json").write_text(
        json.dumps(frozen, indent=2) + "\n", encoding="utf-8"
    )
    return [item.to_dict() for item in conditions]

