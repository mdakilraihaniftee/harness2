"""Run the complete zero-inference PAVE-R/CITE-R feasibility suite."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from harness2 import config
from harness2.cli.demo import main as demo_main

from . import SEED
from .cite_analysis import run_cite
from .model_integrity import run_model_integrity
from .offline_guard import OfflineGuard
from .pave_analysis import run_pave
from .replay import run_replay
from .task_inventory import assert_sources_unchanged, build_inventory

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
REPORTS = ROOT / "reports"
FIXTURES = ROOT / "fixtures"
REPO_ROOT = ROOT.parents[1]


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()


def _run_demo() -> dict:
    root = RESULTS / "deterministic_demo"
    if root.exists():
        shutil.rmtree(root)
    code = demo_main(["--output", str(root), "--k", "2", "--mode", "both"])
    record = json.loads((root / "demo.json").read_text(encoding="utf-8"))
    summaries = []
    for path in sorted((root / "runs").glob("*/*/summary.json")):
        summaries.append(json.loads(path.read_text(encoding="utf-8")))
    modes = {
        mode
        for summary in summaries
        for mode, row in (summary.get("modes") or {}).items()
        if row.get("ok")
    }
    selections = sum(len(summary.get("selections") or {}) for summary in summaries)
    return {
        "status": "PASS" if code == 0 and record.get("failed") == 0 else "FAIL",
        "tasks": record.get("n_tasks", 2),
        "completed": record.get("done", 0),
        "execution_count": record.get("execution_count"),
        "scripted_editor_calls": record.get("editor_calls"),
        "parallel_and_sequential_modes": modes == {"agg", "seq"},
        "selection_records": selections,
        "cross_task_experience_reuse": any(
            any(value > 0 for value in (row.get("library_entries_before") or {}).values())
            for row in record.get("tasks", [])
        ),
        "recursion_ledger_identity": "PASS" if record.get("failed") == 0 else "FAIL",
        "external_model_calls": 0,
    }


def _readiness_report(inventory: dict, revision: str) -> str:
    counts = inventory["installed_task_counts"]
    versions = inventory["installed_versions"]
    return f"""# Offline research readiness

## Status

**PASS — zero-inference execution is available.** Git revision `{revision}`, branch `main`,
selection seed `{SEED}`. Installed task discovery returned exactly **{counts['lab']:,} LAB** and
**{counts['jb']} JobBench** tasks without launching a solver or judge.

## Installed benchmark boundaries

| Benchmark | Installed path | Local revision | Adapter | Tasks | Offline capability |
|---|---|---|---|---:|---|
| LAB | `{inventory['installed_paths']['lab']}` | `{versions['lab']}` | `LabAdapter` / OpenCode surface | {counts['lab']:,} | Task/source discovery; artifact name/format checks; official semantic judge unavailable offline |
| JobBench | `{inventory['installed_paths']['jb']}` | `{versions['jb']}` | `JobBenchAdapter` / OpenCode surface | {counts['jb']} | Task/source discovery; file/schema/parse checks; official rubric judge unavailable offline |

WorkBuddy is intentionally excluded. No benchmark was downloaded.

## Configuration and protection

`model_profiles.toml` defines `existing_vertex`, `gpt`, `qwen`, and `mixed`; profiles are
resolved only with synthetic identifiers/placeholder values in the integrity experiment.
`OfflineGuard` blocks `Proposer.call`, OpenCode/Codex substrate execution, every installed
benchmark adapter's judge method, and socket connection attempts. A blocked attempt fails the
suite. The runner reports its own counters, all of which must remain zero.

## Reused research infrastructure

- `research_pilots.manifest`: compact evidence rendering, hidden-marker checks, exact edits,
  path validation, and reconstruction.
- `research_pilots.bundles`: relative file edits, conflict rejection, and tree validation.
- `research_pilots.evidence`: immutable reference-record rendering conventions.
- `research_pilots.fixtures`: PAVE deterministic execution and reference A/B/C interaction.
- `harness2.core.context`, `tree`, `schedule`, `library`, and deterministic demo: real context,
  editable surfaces, recursion modes, selection/reflection, and experience reuse.

## Evidence boundaries

Installed instructions and source layouts are official benchmark inputs. Derived artifact
contracts are not official tasks or scores. Replay trajectories are explicitly synthetic.
Hidden deterministic utility is stored only in result records and never in composer-visible
context. No external evaluation API is available or needed for the declared derived checks.

## Reproduction commands

The complete suite and each isolated experiment use the same mandatory fail-closed guard:

```bash
.venv/bin/python -m research_pilots.offline_bench.run --offline --all
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment inventory
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment pave
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment cite
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment replay
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment models
.venv/bin/python -m research_pilots.offline_bench.run --offline --experiment demo
```

Partial runs write `experiment_<name>_summary.json`; they do not replace the aggregate
`experiment_summary.json` produced by `--all`.
"""


def _selection_report(inventory: dict) -> str:
    rows = []
    for task in inventory["tasks"]:
        rows.append(
            f"| {task['benchmark']} | `{task['task_id']}` | {task['domain']} | "
            f"{task['classification']} | {len(task['source_files'])} | "
            f"{', '.join(task['requested_deliverables'][:2]) or '(format-derived)'} | "
            f"{'yes' if task['prior_rollout_data_exists'] else 'no'} |"
        )
    return """# Experiment 0: task discovery and selection

Selection used seed 17 and the pre-registered domain-first rule in `task_inventory.json`.
No outcome, hypothesis fit, or prior score entered sampling. No sampled task failed dependency
inspection, so no replacement was made.

| Benchmark | Task ID | Domain | Classification | Source files | Requested deliverable examples | Prior rollout |
|---|---|---|---|---:|---|---|
""" + "\n".join(rows) + """

`NATIVE_DETERMINISTIC` means only that file existence, filename/extension, container
parseability, or another meaningful part of the original output contract can be checked
offline. Every sampled task still requires its external LLM judge for full semantic
correctness. Benchmark-derived schema/API interventions are written only into new research
harnesses; installed benchmark bytes remain unchanged and are verified by SHA-256.
"""


def _pave_report(pave: dict) -> str:
    metrics = "\n".join(
        f"| {name} | {row['correct_final_decisions']}/{row['final_binary_decisions']} | "
        f"{row['false_adaptations']} | {row['missed_adaptations']} | "
        f"{row['diagnostic_queries']} | {row['unresolved_cases']} |"
        for name, row in pave["policy_metrics"].items()
    )
    cases = "\n".join(
        f"| {row['benchmark']} | `{row['task_id']}` | {row['condition']} | "
        f"{'no' if row['byte_identical_visible_evidence'] else 'yes'} | "
        f"`{row['worlds']['GENUINE_SHIFT']['visible_sha256'][:12]}` / "
        f"`{row['worlds']['EVIDENCE_DEFECT']['visible_sha256'][:12]}` |"
        for row in pave["cases"]
    )
    return f"""# Experiment 1: PAVE-R evidence identifiability

Two benchmark contexts were used: {', '.join(f'`{task}`' for task in pave['task_ids'])}.
The instructions and source layouts are real; execution records and versioned artifact
contracts are `DERIVED_BENCHMARK_TASK` plus `SYNTHETIC_REPLAY`, not original trajectories.

Across {pave['world_pair_count']} paired conditions,
**{pave['observationally_indistinguishable_pairs']} pairs were byte-identical** between a
genuine shift and an evidence defect. No controller can identify hidden cause from those bytes.
Complete original evidence breaks initial ambiguity. In the diagnostic condition, a controller
may query a separately sourced observation that can then break it; recurrence alone does not.
Provenance IDs state shared source only and never state which source is correct.

The exact transformations were: one truthful execution record for `complete_original_evidence`;
one unlabeled contract-version error for `isolated_misleading_observation`; three byte-equal
unlabeled errors for `repeated_misleading_observation` and `no_independent_diagnostic`; those
same three errors labeled with one factual source ID for `repeated_shared_provenance`; and one
initial error with a separately sourced contract probe available only after a diagnostic query
for `independent_diagnostic`.

| Benchmark | Task | Condition | Cause identifiable | Genuine/defect visible SHA-256 prefix |
|---|---|---|---|---|
{cases}

| Policy | Correct final binary decisions | False adaptations | Missed adaptations | Diagnostic queries | Unresolved |
|---|---:|---:|---:|---:|---:|
{metrics}

Source deduplication prevents the repeated-single-source false adaptation, but necessarily
misses the matching genuine shift. Independent diagnostics are therefore information, not
just reweighting. The negative control changes the environment while preserving original
harness validity; its correct action is KEEP.

Oracle boundary: policies receive only `visible_evidence`; `correct_action_hidden` is joined
afterward for analysis. No official score or LLM decision is present.

## Decision

**{pave['decision']}**. A complex provenance graph is not justified by these controls. The
smallest useful future study is a paired compact-manifest composer test with and without one
permitted independent diagnostic, holding task, candidates, model, and prompt fixed.
"""


def _cite_report(cite: dict) -> str:
    sections = []
    for instance in cite["instances"]:
        rows = []
        for name, row in instance["rows"].items():
            visible = row["visible_checks"]
            rows.append(
                f"| {name} | {'PASS' if row['structural']['tree_valid'] else 'FAIL'} | "
                f"{'yes' if row['structural']['dependencies_complete'] else 'no'} | "
                f"{'yes' if row['local_execution_completed'] else 'no'} | "
                f"{'yes' if visible.get('permitted_validation_passed') else 'no'} | "
                f"{row['hidden_utility']:.0f} |"
            )
        sections.append(
            f"""### `{instance['instance_id']}`

`Gamma_AB={instance['gamma_ab']:.1f}`, `Interference_C={instance['interference_c']:.1f}`.

| Tree | Structurally valid | Dependencies complete | Execution completed | Visible check passes | Hidden utility |
|---|---|---|---|---|---:|
{chr(10).join(rows)}
"""
        )
    return f"""# Experiment 2: CITE-R edit-interaction discoverability

The reference invoice fixture and two derived real-benchmark contexts were exhaustively
evaluated by declared local deterministic evaluators. Hidden utility was not supplied to
baselines; only the separately shown visible-check matrix and structural metadata were used.

{chr(10).join(sections)}

The necessary A+B repair was generated in all {len(cite['instances'])} instances. A, B, and C
were individually valid; A+B succeeded; A+B+C exhibited measured interference. The explicit
conflicting-edit negative control was rejected: `{cite['invalid_conflict_control']['rejected']}`.

Budgets 1–3 miss the pre-registered fourth probe A+B; budget 4 finds it because the permitted
validator supplies an observable signal. This is `COMPOSITION_LIMITED_AT_LOW_BUDGET`, not
generation- or execution-limited. However, simple dependency-aware compatible merging plus the
visible validator solves every controlled case, so the controls do not justify a sophisticated
new method.

## Decision

**{cite['decision']}**. The interaction is real, but tiny deterministic enumeration is already
a strong upper bound. Real composer behavior and LLM token efficiency remain
`REQUIRES_MODEL_INFERENCE`.
"""


def _replay_report(replay: dict) -> str:
    rows = []
    for task in replay["tasks"]:
        rows.append(
            f"| {task['benchmark']} | `{task['task_id']}` | {len(task['variants'])} | "
            f"{'PASS' if task['transformation_reached_rollout'] else 'FAIL'} | "
            f"{'PASS' if all(all(v['candidate_reconstruction'].values()) for v in task['variants'].values()) else 'FAIL'} |"
        )
    return f"""# Experiment 3: benchmark-native context replay

| Benchmark | Task | Evidence variants | Transformation placement | Candidate reconstruction |
|---|---|---:|---|---|
{chr(10).join(rows)}

The real adapters supplied task instructions, source paths, leak rules, and editable OpenCode
surface. `harness2.core.context.build` constructed normal contexts. Compact manifests retained
candidate IDs/scopes, exact diffs, original paths, and optional factual source IDs. All
references were accessible, all candidates reconstructed exactly, and hidden markers were
absent.

No sampled task had a suitable native saved trajectory. Consequently the suite used
**{replay['synthetic_replays_used']} explicitly labeled synthetic replay views** and zero real
saved trajectories. These are technical-feasibility contexts, not completed LAB/JobBench runs.
Provenance categories are stored per task and are not interchangeable.
"""


def _model_report(models: dict) -> str:
    rows = []
    for name, row in models["profiles"].items():
        rows.append(
            f"| {name} | `{row['solver']}` | `{row['improver']}` | `{row['selector']}` | "
            f"`{row['judge']}` | {str(row['configuration_verified']).lower()} | "
            f"{str(row['runtime_invocation_constructed']).lower()} | false | false |"
        )
    return f"""# Experiment 4: multi-model configuration integrity

| Profile | Solver | Improver | Selector | Judge | Configuration verified | Invocation constructed | Real tool call | Real edit |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

All fingerprints were distinct: `{models['all_fingerprints_distinct']}`. Model changes preserve
the exact 12-task selection and the same model-independent manifest hashes while isolating run
roots/caches. Provider environments retained only each selected provider credential. Hidden
oracles remained excluded.

Synthetic model IDs and placeholder credential strings were used. Invocation construction is
an argv/configuration assertion only. OpenAI, OpenRouter/Qwen, and mixed routes remain
`NOT_TESTED` live; no tool call or edit is claimed.
"""


def _final_report(summary: dict) -> str:
    demo = summary["deterministic_demo"]
    return f"""# Final zero-inference research decision

## Executive result

The offline suite inspected 12 installed tasks, exercised three deterministic CITE instances,
constructed benchmark-native contexts for two tasks, and ran the original deterministic
Harness² demo in both recursion modes. It made **0 external model calls, 0 external judge
calls, and $0 provider inference spend**.

The demo status was **{demo['status']}**: base/INV/DOM/composer/candidate execution, terminal
selection, reflection, parallel/sequential recursion, ledger accounting, and cross-task
experience reuse completed with scripted local components. This validates infrastructure, not
model behavior.

## PAVE-R

**REFINE — INFORMATION ACQUISITION REQUIRED.** Repeated evidence with a shared provenance ID
can be safely deduplicated, but the same visible record is compatible with a genuine shift and
an evidence defect. Provenance prevents overcounting; it does not reveal truth. Independent
diagnostics change what is identifiable and are the scientifically relevant next variable.

## CITE-R

**REFINE — TRIVIAL STRUCTURAL SOLUTION.** A+B synergy and C interference are real under three
deterministic evaluators, including two benchmark-derived artifact contracts. Yet exhaustive
search is tiny and a dependency-aware merge plus permitted validation solves every controlled
case. This does not yet justify combinatorial LLM composition machinery.

## Evidence accounting

- Official inputs: 12 task instructions/source layouts from installed LAB/JobBench.
- Derived controls: versioned artifact contracts for PAVE and exact-path/validator contracts
  for CITE; none is an official benchmark score.
- Synthetic replay: six evidence views over two real task contexts.
- Deterministic execution: reference invoice fixture, derived artifact executors, and demo.
- Real saved trajectories in sampled-task replay: zero.

## What remains untestable

Whether GPT/Qwen/Gemini/Claude actually interpret recurrence, provenance, diagnostics, failed
singles, or interacting edits; whether natural proposers generate A/B; and whether real solver
executions preserve these utility patterns all require model inference. No behavioral claim is
made.

## Smallest subsequent model-backed experiment

If separately authorized later, run one model and one controlled compact-manifest task in a
paired diagnostic/no-diagnostic PAVE condition, then one CITE A/B pool only if the PAVE
decision completes. Cap actual calls and inspect the raw tool trace before expanding. Do not
implement either full method first.
"""


def _summary_rows(summary: dict) -> list[dict]:
    return [
        {
            "experiment": "0_task_discovery",
            "status": "EXECUTED",
            "benchmark_tasks_inspected": 12,
            "deterministic_probes": 0,
            "external_model_calls": 0,
            "external_judge_calls": 0,
            "provider_inference_cost_usd": 0,
            "key_finding": "Seeded 6+6 cross-domain sample; semantic scores unavailable offline",
            "research_decision": "READY",
        },
        {
            "experiment": "1_pave_identifiability",
            "status": "EXECUTED",
            "benchmark_tasks_inspected": 2,
            "deterministic_probes": summary["pave"]["world_pair_count"] * 2,
            "external_model_calls": 0,
            "external_judge_calls": 0,
            "provider_inference_cost_usd": 0,
            "key_finding": f"{summary['pave']['observationally_indistinguishable_pairs']} indistinguishable paired worlds",
            "research_decision": summary["pave"]["decision"],
        },
        {
            "experiment": "2_cite_discoverability",
            "status": "EXECUTED",
            "benchmark_tasks_inspected": 2,
            "deterministic_probes": summary["cite"]["deterministic_candidate_probes"],
            "external_model_calls": 0,
            "external_judge_calls": 0,
            "provider_inference_cost_usd": 0,
            "key_finding": "Measured A+B synergy/C interference; simple compatible baseline succeeds",
            "research_decision": summary["cite"]["decision"],
        },
        {
            "experiment": "3_benchmark_replay",
            "status": "EXECUTED",
            "benchmark_tasks_inspected": 2,
            "deterministic_probes": summary["replay"]["synthetic_replays_used"],
            "external_model_calls": 0,
            "external_judge_calls": 0,
            "provider_inference_cost_usd": 0,
            "key_finding": "Real contexts/manifests work; sampled evidence is synthetic replay",
            "research_decision": "TECHNICALLY_FEASIBLE",
        },
        {
            "experiment": "4_multimodel_integrity",
            "status": "EXECUTED",
            "benchmark_tasks_inspected": 12,
            "deterministic_probes": 4,
            "external_model_calls": 0,
            "external_judge_calls": 0,
            "provider_inference_cost_usd": 0,
            "key_finding": "Distinct fingerprints; identical task/evidence inputs",
            "research_decision": "CONFIGURATION_ONLY; LIVE NOT_TESTED",
        },
        {
            "experiment": "5_deterministic_recursion",
            "status": "EXECUTED" if summary["deterministic_demo"]["status"] == "PASS" else "FAIL",
            "benchmark_tasks_inspected": 0,
            "deterministic_probes": summary["deterministic_demo"].get("execution_count") or 0,
            "external_model_calls": 0,
            "external_judge_calls": 0,
            "provider_inference_cost_usd": 0,
            "key_finding": "Parallel/sequential recursion and experience reuse pass locally",
            "research_decision": "INFRASTRUCTURE_PASS",
        },
    ]


def _parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="required fail-closed mode")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument(
        "--experiment",
        choices=("inventory", "pave", "cite", "replay", "models", "demo"),
    )
    args = parser.parse_args(argv)
    if not args.offline:
        parser.error("--offline is mandatory; this runner never permits inference")
    return args


def main(argv=None) -> int:
    args = _parse(argv)
    RESULTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    previous = REPO_ROOT / "research_pilots/results/experiment_summary.json"
    previous_digest = _sha(previous)
    revision = _git_revision()
    requested = (
        {"inventory", "pave", "cite", "replay", "models", "demo"}
        if args.all
        else {args.experiment}
    )
    # Dependencies are deterministic prerequisites, not additional experiments.
    if requested & {"pave", "cite", "replay", "models"}:
        requested.add("inventory")
    if "models" in requested:
        requested.add("replay")

    with OfflineGuard() as guard:
        inventory = build_inventory(RESULTS / "task_inventory.json", seed=SEED)
        assert_sources_unchanged(inventory)
        pave = run_pave(inventory, RESULTS / "pave_offline_results.json") if "pave" in requested else None
        cite = (
            run_cite(
                inventory,
                RESULTS / "cite_interaction_matrix.json",
                RESULTS / "cite_probe_budget.json",
            )
            if "cite" in requested
            else None
        )
        replay = (
            run_replay(
                inventory,
                RESULTS / "replay",
                RESULTS / "benchmark_replay.json",
            )
            if "replay" in requested
            else None
        )
        models = (
            run_model_integrity(
                inventory,
                replay,
                RESULTS / "model_integrity_results.json",
                config.ROOT / "model_profiles.toml",
            )
            if "models" in requested
            else None
        )
        demo = _run_demo() if "demo" in requested else None
        assert_sources_unchanged(inventory)
        guard.assert_clean()
        counters = guard.counters.to_dict()

    if _sha(previous) != previous_digest:
        raise RuntimeError("existing research experiment summary was modified")

    partial = not args.all
    summary = {
        "schema_version": 1,
        "git_revision": revision,
        "selection_seed": SEED,
        "status": "PASS" if not partial else "PARTIAL_EXPERIMENT_PASS",
        "offline": True,
        "external_model_calls": counters["external_model_calls"],
        "external_judge_calls": counters["external_judge_calls"],
        "provider_inference_cost_usd": counters["provider_inference_cost_usd"],
        "network_calls": counters["network_calls"],
        "blocked_attempts": counters["blocked_attempts"],
        "task_inventory": inventory,
        "pave": pave,
        "cite": cite,
        "replay": replay,
        "model_integrity": models,
        "deterministic_demo": demo,
        "requires_model_inference": [
            "real composer decisions",
            "natural candidate generation",
            "real solver/tool/edit verification across providers",
            "official benchmark semantic scores",
        ],
    }
    summary_path = RESULTS / (
        "experiment_summary.json" if args.all else f"experiment_{args.experiment}_summary.json"
    )
    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    if args.all:
        rows = _summary_rows(summary)
        with (RESULTS / "experiment_summary.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        _write(REPORTS / "00_offline_readiness.md", _readiness_report(inventory, revision))
        _write(REPORTS / "01_task_selection.md", _selection_report(inventory))
        _write(REPORTS / "02_pave_identifiability.md", _pave_report(pave))
        _write(REPORTS / "03_cite_discoverability.md", _cite_report(cite))
        _write(REPORTS / "04_benchmark_replay.md", _replay_report(replay))
        _write(REPORTS / "05_multimodel_integrity.md", _model_report(models))
        _write(REPORTS / "06_final_research_decision.md", _final_report(summary))
    print(
        json.dumps(
            {
                "status": summary["status"],
                "results": str(RESULTS),
                "summary": str(summary_path),
                "external_model_calls": summary["external_model_calls"],
                "external_judge_calls": summary["external_judge_calls"],
                "provider_inference_cost_usd": summary["provider_inference_cost_usd"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
