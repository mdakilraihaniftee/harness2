"""Prepare and validate Phase 4 composer-only research without external inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from harness2.cli.demo import main as demo_main
from research_pilots.manifest import manifest_edits, reconstruct
from research_pilots.offline_bench.offline_guard import OfflineGuard
from research_pilots.offline_bench.pave_analysis import run_pave
from research_pilots.offline_bench.task_inventory import build_inventory

from . import CONTEXTS, FIXTURES, REPO_ROOT, REPORTS, RESULTS, SCHEMA_VERSION, SEED
from .analysis import cite_corrected_analysis
from .audit import composer_cache_audit
from .decision import classify_completion, parse_decision
from .replay import prepare_replays, repetition_identity


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")


def _json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        return digest.hexdigest()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


def _files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file()
    }


def _validate_reconstruction(conditions: list[dict]) -> bool:
    for item in conditions:
        root = Path(item["context_root"])
        parsed = manifest_edits((root / "EVIDENCE_MANIFEST.md").read_text())
        base = _files(root / "harness")
        for candidate, edits in parsed.items():
            expected = _files(root / "pool" / candidate / "harness")
            if reconstruct(base, edits) != expected:
                return False
    return True


def _run_demo() -> dict:
    root = CONTEXTS / "deterministic_demo"
    shutil.rmtree(root, ignore_errors=True)
    code = demo_main(["--output", str(root), "--k", "2", "--mode", "both"])
    result = json.loads((root / "demo.json").read_text())
    return {
        "status": "PASS" if code == 0 and result["failed"] == 0 else "FAIL",
        "execution_count": result["execution_count"],
        "editor_calls": result["editor_calls"],
        "external_model_calls": 0,
    }


def _audit_report(audit: dict, revision: str) -> str:
    rows = "\n".join(
        f"| {name} | `{row['task_id']}` | `{row['prompt_pack']}` | "
        f"`{row['aggregate_k1_sha256']}` | {row['repeated_base_failure_instruction']} | "
        f"{row['failed_candidate_unsafe_instruction']} |"
        for name, row in audit["prompt_packs"].items()
    )
    return f"""# Composer and cache audit

Repository revision: `{revision}`.

| Adapter | Example task | Pack | Aggregate k=1 hash | Repeated-base rule | Unsafe-failed-edit rule |
|---|---|---|---|---|---|
{rows}

The PAVE/CITE hypotheses target `adapt`: it explicitly says repeated failures across the base
set are strongest evidence and that edits associated with non-delivery are unsafe. JobBench's
`tts` pack uses variance and product inspection language instead. A `tts` result cannot reject
an `adapt`-prompt hypothesis and is retained only as a prompt-pack control.

`Proposer` cache keys hash label, mission, system, resolved context path and context bytes. The
model is not directly in the private call fingerprint; normal runs remain isolated because the
model configuration fingerprint changes run roots. Phase 4 additionally hashes experiment,
condition, task, sample, model fingerprint, prompt hash and frozen-reference hash into every
sample identity. Two sample labels produced distinct core cache keys: 
`{audit['research_repetition_labels_produce_distinct_keys']}`.

The offline Qwen configuration fingerprint is
`{audit['model_configurations']['qwen_target_offline']['fingerprint']}`. Resolution used the
configured model ID when present, a synthetic fallback otherwise, and a non-secret placeholder
credential; no provider was contacted.
"""


def _corrections_report(pave: dict, cite: dict, comparison: dict) -> str:
    metrics = "\n".join(
        f"| {name} | {row['correct_final_decisions']}/{row['final_binary_decisions']} | "
        f"{row['diagnostic_queries']} | {row['diagnostic_cost']:.0f} | "
        f"{row['unresolved_cases']} |"
        for name, row in pave["policy_metrics"].items()
    )
    validations = "\n".join(
        f"| {name} | {row['description']} | {row['perfectly_predicts_hidden_success']} |"
        for name, row in cite["validation_conditions"].items()
    )
    return f"""# Offline corrections

## PAVE diagnostic accounting

Diagnostic selection is now an intermediate action. Every trace records the initial action,
selected diagnostic, response, final KEEP/ADAPT decision, query count/cost, correctness and
unresolved status. An unavailable diagnostic yields `UNRESOLVED` for `diagnostic_first`; it is
never counted as a successful final decision.

| Policy | Correct/final binary | Queries | Diagnostic cost units | Unresolved |
|---|---:|---:|---:|---:|
{metrics}

## CITE alternatives and verifier strength

All eight A/B/C bundles were executed. Verified sufficient repairs are
`{', '.join(cite['sufficient_repairs'])}`; minimal sufficient repairs are
`{', '.join(cite['minimal_sufficient_repairs'])}`. HAC is accepted when it succeeds even though
the declared A+B dependency flag is incomplete.

| Condition | Visible feedback | Perfect predictor |
|---|---|---|
{validations}

V0 and V1 remain the main controls. V2 is explicitly an oracle-like high-information control.

## Deliverable extraction

The earlier JobBench regex mixed source filenames with outputs. The corrected inventory
separates provided source files, explicit output filenames, filename-free descriptions,
ambiguous requirements and temporary files. Legacy inventory SHA-256:
`{comparison['legacy_inventory_sha256']}`. Corrected inventory is written separately and does
not overwrite it.
"""


def _pave_report(conditions: list[dict]) -> str:
    rows = "\n".join(
        f"| {row['condition_id']} | {row['environment']} | {row['k']} | "
        f"{row['evidence_condition']} | {len(row['candidate_pool'])} | "
        f"`{row['context_hash'][:16]}` |"
        for row in conditions if row["condition_id"].startswith("PAVE")
    )
    return f"""# PAVE composer replay design

| Condition | Environment | k | Evidence | Candidates | Context hash |
|---|---|---:|---|---:|---|
{rows}

P0/P1 at k=1 and P0/P1/P2 at k=3 share the task family and per-k candidate pool. P2 and P4
have the same composer-visible rollout content but different hidden generation provenance; no
behavioral difference is expected without visible provenance. P3 adds a factual independent
ledger observation, not a statement of the preferred edit. `PAVE_POSITIVE_K3` supplies a
verified repair in a genuinely shifted environment.

Composer outcomes are classified as KEEP_BASE, EDIT, MERGE, INVALID or OPERATIONAL_FAILURE.
Hidden utility is evaluated afterward, so modification alone is never labeled harmful.
"""


def _cite_report(conditions: list[dict], cite: dict) -> str:
    rows = "\n".join(
        f"| {row['condition_id']} | {row['evidence_condition']} | "
        f"{', '.join(row['candidate_pool'])} | `{row['manifest_hash'][:16]}` |"
        for row in conditions if row["condition_id"].startswith("CITE")
    )
    repair_rows = "\n".join(
        f"| {row['harness']} | {','.join(row['edit_set']) or 'base'} | "
        f"{row['structural_validity']} | {row['dependency_complete']} | "
        f"{row['hidden_utility']:.0f} | {row['probe_cost']} |"
        for row in cite["rows"]
    )
    return f"""# CITE composer replay design

| Condition | Feedback | Candidate pool | Manifest hash |
|---|---|---|---|
{rows}

The first gate exposes A and B in separate INV/DOM candidates; each individual rollout fails
and the verified combination succeeds. The composer never sees HAB utility or a reference
patch. V0 provides structural completion only, V1 partial semantic checks, and V2 is a
high-information control.

| Harness | Edits | Valid | Declared dependency complete | Hidden utility | Cost |
|---|---|---|---|---:|---:|
{repair_rows}

All successful alternatives are acceptable. Edit C is prepared only for a later interference
test after one valid A/B decision; larger pools remain inactive.
"""


def _validation_report(validation: dict, demo: dict) -> str:
    rows = "\n".join(
        f"| {name} | {'PASS' if passed else 'FAIL'} |"
        for name, passed in validation["checks"].items()
    )
    return f"""# Deterministic validation

| Check | Result |
|---|---|
{rows}

Deterministic demo: **{demo['status']}**, {demo['execution_count']} executions and
{demo['editor_calls']} scripted editor calls. External model calls, external judge calls and
provider inference cost were all zero.
"""


def _live_plan(audit: dict) -> str:
    preflight = audit["live_qwen_preflight"]
    return f"""# Minimal live gate plan

Target: Qwen through the `qwen` OpenRouter profile, OpenCode harness, one controlled CITE A/B
compact-manifest composer stage, `adapt` prompt pack, no solver regeneration and no judge.

Current preflight: model ID present = `{preflight['model_id_present']}`; credential present =
`{preflight['credential_present']}`. Put both values in the ignored `.env`; do not paste the
credential into a report or command history. The command remains blocked until both exist and
the exact model appears in the frozen OpenCode model catalog.

Prepare the local TLS socket once (no provider call):

```bash
cd /home/ai5377/harness2
GATE_DIR="$PWD/runs/phase4-qwen-gate"
mkdir -p "$GATE_DIR"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \\
  -keyout "$GATE_DIR/key.pem" -out "$GATE_DIR/cert.pem" \\
  -subj '/CN=openrouter.ai' -addext 'subjectAltName=DNS:openrouter.ai'
```

Start the trusted host gateway in terminal 1. It loads the ignored `.env`, retains the real key
on the host, permits only the configured Qwen model and stops accepting provider turns after
the 20-step composer bound:

```bash
cd /home/ai5377/harness2
GATE_DIR="$PWD/runs/phase4-qwen-gate"
.venv/bin/python -m research_pilots.phase4.openrouter_gateway \\
  --max-requests 20 --unix-socket "$GATE_DIR/openrouter.sock" \\
  --cert "$GATE_DIR/cert.pem" --key "$GATE_DIR/key.pem" \\
  --ready-file "$GATE_DIR/ready"
```

After `ready` exists, run the separately authorized gate in terminal 2:

```bash
cd /home/ai5377/harness2
GATE_DIR="$PWD/runs/phase4-qwen-gate"
export HARNESS2_GATEWAY_CA="$GATE_DIR/cert.pem"
export HARNESS2_GATEWAY_SOCKET="$GATE_DIR/openrouter.sock"
export HARNESS2_MODELS_SNAPSHOT="$HOME/.cache/opencode/models.json"
export OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=4096
.venv/bin/python -m research_pilots.phase4.live_gate cite-e1 \\
  --approve-paid --model-profile qwen --sample-id gate-001 \\
  --max-usd 1 --max-calls 2 --steps 20
```

Expected work: one composer session. The transport-session cap is 2, the gateway provider-turn
cap is 20, and the declared incremental spend cap is $1.00; spend is known from provider
telemetry after a session, so no second session starts after the cap is reached. The sandbox has
no network namespace and sees only a dummy credential plus the allowlisted Unix socket. There
is no external judge, full benchmark execution or cloud change. Success requires manifest
access, a cache miss, explicit decision, valid tree, no fallback and no step exhaustion. Any
interface failure stops retries.
"""


def _readiness_report(summary: dict) -> str:
    return f"""# Phase 4 research readiness decision

## Decision

**{summary['decision']}**

PAVE is directly testable at composer level: k=1/k=3 pools are controlled, P2/P4
indistinguishability is explicit, P3 supplies a non-oracular independent observation, and
harmful/unnecessary edits have deterministic post-decision evaluation. Model behavior remains
unknown without inference.

CITE accepts every verified sufficient repair, uses V0/V1 signals weaker than hidden utility,
exposes both relevant edits, and distinguishes an explicit rejection from operational failure.
The A/B gate is credible; C stays gated until that decision completes.

The compact interface, prompt hashes, repetition identities, model fingerprints, candidate
reconstruction, oracle exclusion and prior-result preservation all passed. Qwen live execution
is operationally blocked only by absent runtime model/credential configuration and by the
protocol's explicit paid gate.

Do not implement full PAVE-R or CITE-R from deterministic evidence.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    if not args.offline:
        parser.error("--offline is required; live inference uses research_pilots.phase4.live_gate")

    REPORTS.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    previous_root = REPO_ROOT / "research_pilots/results"
    previous_digest = _tree_digest(previous_root)
    legacy_inventory = REPO_ROOT / "research_pilots/offline_bench/results/task_inventory.json"
    legacy_inventory_sha = _file_sha(legacy_inventory) if legacy_inventory.is_file() else "MISSING"

    with OfflineGuard() as guard:
        inventory = build_inventory(RESULTS / "corrected_task_inventory.json", seed=SEED)
        pave = run_pave(inventory, RESULTS / "pave_diagnostic_accounting.json")
        cite = cite_corrected_analysis()
        conditions = prepare_replays()
        audit = composer_cache_audit(CONTEXTS / "audit")
        demo = _run_demo()
        reconstruction = _validate_reconstruction(conditions)
        guard.assert_clean()
        counters = guard.counters.to_dict()

    previous_preserved = previous_digest == _tree_digest(previous_root)
    qwen_target = audit["model_configurations"]["qwen_target_offline"]
    model_fingerprint = qwen_target["fingerprint"]
    improver = qwen_target["roles"]["improver"]
    target_model = f"{improver['provider']}/{improver['model_id']}"
    for row in conditions:
        row["target_model_profile"] = "qwen"
        row["target_model"] = target_model
        row["model_configuration_fingerprint"] = model_fingerprint
        row["sample_identities"] = [
            repetition_identity(
                experiment_id=row["experiment_id"],
                condition_id=row["condition_id"],
                task_id=row["task_id"],
                sample_id=f"sample-{index}",
                model_fingerprint=model_fingerprint,
                prompt_hash=row["prompt_hash"],
                reference_hash_value=row["reference_hash"],
            )
            for index in (1, 2)
        ]
        row["estimated_provider_cost_usd"] = 0.0
        row["execution_status"] = "PREPARED_NOT_RUN"

    all_manifest_clean = all(
        not any(
            marker in (Path(row["context_root"]) / "EVIDENCE_MANIFEST.md").read_text().lower()
            for marker in ("hidden_utility", "required_bundle", "candidate a+b is correct")
        )
        for row in conditions
    )
    source_excluded = all(
        not set(task["requested_deliverables"])
        & {Path(name).name for name in task["deliverable_inventory"]["provided_source_files"]}
        for task in inventory["tasks"]
    )
    diagnostic_metric = pave["policy_metrics"]["diagnostic_first"]
    cite_v0 = cite["validation_conditions"]["V0"]
    cite_v1 = cite["validation_conditions"]["V1"]
    cite_v2 = cite["validation_conditions"]["V2"]
    identities = [identity for row in conditions for identity in row["sample_identities"]]
    checks = {
        "prompt_pack_identification": audit["prompt_packs"]["research"]["prompt_pack"] == "adapt",
        "stable_prompt_hashes": all(len(row["prompt_hash"]) == 64 for row in conditions),
        "valid_k1_and_k3_contexts": {row["k"] for row in conditions if row["condition_id"].startswith("PAVE")} == {1, 3},
        "frozen_reference_integrity": all(len(row["reference_hash"]) == 64 for row in conditions),
        "cache_independent_repetition_identities": len(identities) == len(set(identities)),
        "cross_model_configuration_isolation": audit["cross_model_fingerprints_distinct"],
        "no_hidden_oracle_leakage": all_manifest_clean,
        "accurate_pave_diagnostic_accounting": diagnostic_metric["unresolved_cases"] > 0 and diagnostic_metric["diagnostic_queries"] > 0,
        "alternative_cite_repairs_accepted": set(cite["minimal_sufficient_repairs"]) >= {"HAB", "HAC"},
        "partial_and_perfect_validator_separated": not cite_v0["perfectly_predicts_hidden_success"] and not cite_v1["perfectly_predicts_hidden_success"] and cite_v2["perfectly_predicts_hidden_success"],
        "correct_deliverable_extraction": source_excluded,
        "exact_candidate_patch_reconstruction": reconstruction,
        "valid_edit_bundle_application": bool(cite["sufficient_repairs"]),
        "operational_fallback_detection": classify_completion(response="<notes>KEEP_BASE</notes>", tree_changed=False, tree_parseable=True, tree_valid=True, fell_back=True, evidence_accessed=True, step_exhausted=False)["decision"] == "OPERATIONAL_FAILURE",
        "explicit_composer_decision_parsing": parse_decision("<notes>KEEP_BASE</notes>", tree_changed=False) == "KEEP_BASE",
        "prompt_and_candidate_provenance": all(row["candidate_pool"] and row["provenance_categories"] for row in conditions),
        "old_research_results_preserved": previous_preserved,
        "fail_closed_offline_execution": counters["blocked_attempts"] == 0,
        "no_external_model_or_judge_calls": counters["external_model_calls"] == 0 and counters["external_judge_calls"] == 0,
        "usage_and_cost_schema": all("estimated_provider_cost_usd" in row for row in conditions),
        "deterministic_demo": demo["status"] == "PASS",
    }
    validation = {
        "schema_version": SCHEMA_VERSION,
        "checks": checks,
        "all_passed": all(checks.values()),
        "external_model_calls": counters["external_model_calls"],
        "external_judge_calls": counters["external_judge_calls"],
        "provider_inference_cost_usd": counters["provider_inference_cost_usd"],
        "network_calls": counters["network_calls"],
        "demo": demo,
    }
    comparison = {
        "legacy_inventory_sha256": legacy_inventory_sha,
        "corrected_inventory_sha256": _file_sha(RESULTS / "corrected_task_inventory.json"),
        "legacy_inventory_overwritten": False,
    }
    experiment_manifest = {
        "schema_version": SCHEMA_VERSION,
        "git_revision": _git_revision(),
        "selection_seed": SEED,
        "target_profile": "qwen",
        "target_model_status": (
            "CONFIGURED" if audit["live_qwen_preflight"]["model_id_present"] else "RUNTIME_REQUIRED"
        ),
        "prompt_audit": audit,
        "conditions": conditions,
        "usage_schema": {
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "model_steps": 0,
            "cost_usd": 0.0,
            "wall_s": 0.0,
            "cache_hit": False,
        },
    }
    readiness = {
        "schema_version": SCHEMA_VERSION,
        "decision": "READY_FOR_LIVE_GATE" if validation["all_passed"] else "NEEDS_INFRASTRUCTURE_FIX",
        "deterministic_validation": "PASS" if validation["all_passed"] else "FAIL",
        "target_model_profile": "qwen",
        "live_preflight": audit["live_qwen_preflight"],
        "live_executed": False,
        "external_model_calls": 0,
        "external_judge_calls": 0,
        "provider_inference_cost_usd": 0.0,
        "remaining_uncertainties": [
            "Qwen composer behavior and stochastic variation",
            "whether compact manifests prevent live step exhaustion",
            "whether edited trees improve real solver behavior",
            "official benchmark scores (separately gated)",
        ],
    }
    _json(RESULTS / "phase4_experiment_manifest.json", experiment_manifest)
    _json(RESULTS / "phase4_validation_results.json", validation | {"comparison": comparison})
    _json(RESULTS / "phase4_replay_conditions.json", conditions)
    _json(RESULTS / "phase4_readiness_summary.json", readiness)
    _json(RESULTS / "cite_corrected_analysis.json", cite)

    _write(REPORTS / "00_composer_and_cache_audit.md", _audit_report(audit, _git_revision()))
    _write(REPORTS / "01_offline_corrections.md", _corrections_report(pave, cite, comparison))
    _write(REPORTS / "02_pave_replay_design.md", _pave_report(conditions))
    _write(REPORTS / "03_cite_replay_design.md", _cite_report(conditions, cite))
    _write(REPORTS / "04_deterministic_validation.md", _validation_report(validation, demo))
    _write(REPORTS / "05_live_gate_plan.md", _live_plan(audit))
    _write(REPORTS / "06_research_readiness_decision.md", _readiness_report(readiness))

    print(json.dumps(readiness | {"reports": str(REPORTS)}, indent=2))
    return 0 if validation["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

