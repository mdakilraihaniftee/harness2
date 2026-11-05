"""Benchmark-native context replay without solver, proposer, or judge invocation."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from harness2.benchmarks.jobbench import JobBenchAdapter
from harness2.benchmarks.lab import LabAdapter
from harness2.core import context
from harness2.core import tree as harness_tree
from harness2.core.spec import RunView
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.manifest import (
    assert_references_accessible,
    build_manifest,
    manifest_edits,
    reconstruct,
)

from .cite_analysis import benchmark_candidates

_FORBIDDEN = (
    "hidden_utility",
    "required_bundle",
    "candidate a+b is correct",
    "reference repair",
)


class ReplayAdapter:
    """Use a real task/source boundary and explicit local replay files for evidence readers."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.spec = delegate.spec
        self.substrate = delegate.substrate

    def task_prompt(self, task_id):
        return self.delegate.task_prompt(task_id)

    def task_files(self, task_id):
        return self.delegate.task_files(task_id)

    def trajectory(self, run_dir, *, obs_trunc):
        del obs_trunc
        return (Path(run_dir) / "replay.md").read_text(encoding="utf-8")

    def deliverable_text(self, run_dir):
        return (Path(run_dir) / "artifact.txt").read_text(encoding="utf-8")

    def deliverable_files(self, run_dir):
        return {"artifact.txt": self.deliverable_text(run_dir)}

    def delivered(self, run_dir):
        return (Path(run_dir) / "artifact.txt").is_file()


def _write_run(root: Path, label: str, trajectory: str) -> RunView:
    run_dir = root / label
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "replay.md").write_text(trajectory.rstrip() + "\n", encoding="utf-8")
    (run_dir / "artifact.txt").write_text(
        "Synthetic replay artifact: format-only, not an official task solution.\n",
        encoding="utf-8",
    )
    return RunView(label, f"offline-replay/{label}", run_dir, ok=True, delivered=True)


def _tree_files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file()
    }


def _assert_no_hidden(path: Path) -> None:
    text = "\n".join(
        item.read_text(encoding="utf-8", errors="replace").lower()
        for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in {".md", ".txt", ".json", ".diff"}
    )
    leaked = [marker for marker in _FORBIDDEN if marker in text]
    if leaked:
        raise AssertionError(f"hidden oracle marker leaked into visible replay: {leaked}")


def _manifest_case(
    root: Path,
    adapter,
    task_id: str,
    base: dict,
    candidates: dict,
    base_rollout: RunView,
    candidate_runs: dict[str, RunView],
    *,
    token: str,
    source_ids: dict[str, str] | None,
) -> dict:
    base_dir = harness_tree.write_tree(OPENCODE_SURFACE, base, root / "trees/base", stubs=False)
    pool = []
    scope_map = {}
    for name, label in (("A", "inv1"), ("B", "dom1")):
        tree_dir = harness_tree.write_tree(
            OPENCODE_SURFACE, candidates[name], root / f"trees/{label}", stubs=False
        )
        pool.append((label, tree_dir, candidate_runs[label]))
        scope_map[label] = "INV" if name == "A" else "DOM"
    ctx = context.build(
        root / "context",
        adapter,
        task_id,
        [base_rollout],
        harness_dir=base_dir,
        pool=pool,
    )
    build = build_manifest(
        ctx.root,
        candidate_scopes=scope_map,
        condition_token=token,
        source_ids=source_ids,
    )
    assert_references_accessible(build)
    parsed = manifest_edits(build.path.read_text(encoding="utf-8"))
    base_files = _tree_files(ctx.root / "harness")
    reconstructed = {}
    for label, edits in parsed.items():
        expected = _tree_files(ctx.root / "pool" / label / "harness")
        reconstructed[label] = reconstruct(base_files, edits) == expected
    _assert_no_hidden(ctx.root)
    return {
        **build.to_dict(),
        "context_root": str(ctx.root),
        "source_files_copied": ctx.source_files,
        "candidate_reconstruction": reconstructed,
        "hidden_oracle_excluded": True,
    }


def run_replay(inventory: dict, output_root: Path, result_path: Path) -> dict:
    if output_root.exists():
        shutil.rmtree(output_root)
    adapters = {"jb": ReplayAdapter(JobBenchAdapter()), "lab": ReplayAdapter(LabAdapter())}
    selected = [
        next(row for row in inventory["tasks"] if row["benchmark"] == benchmark)
        for benchmark in ("jb", "lab")
    ]
    records = []
    for task in selected:
        benchmark, task_id = task["benchmark"], task["task_id"]
        adapter = adapters[benchmark]
        deliverable = Path((task["requested_deliverables"] or ["offline_result.txt"])[0]).name
        base, candidates = benchmark_candidates(task_id, deliverable)
        task_root = output_root / benchmark / task_id.replace("/", "__")
        raw_record = {
            "task_id": task_id,
            "action": f"validate requested artifact {deliverable}",
            "actual": "local format check completed",
            "provenance_category": "SYNTHETIC_REPLAY",
        }
        raw_bytes = json.dumps(raw_record, sort_keys=True).encode()
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        run_root = task_root / "runs"
        candidate_runs = {
            "inv1": _write_run(
                run_root,
                "inv1",
                "[ACTION] Apply exact-path guidance\n[OBSERVATION]\nERROR: validator unavailable",
            ),
            "dom1": _write_run(
                run_root,
                "dom1",
                "[ACTION] Run artifact validator\n[OBSERVATION]\nERROR: output path unavailable",
            ),
        }
        variants = {}
        for name, trajectory, source_ids in (
            (
                "clean",
                "[ACTION] Validate artifact contract\n[OBSERVATION]\nlocal format check completed",
                None,
            ),
            (
                "degraded_no_provenance",
                "[ACTION] Validate artifact contract\n[OBSERVATION]\nERROR: contract version unavailable",
                None,
            ),
            (
                "degraded_with_provenance",
                "[ACTION] Validate artifact contract\n[OBSERVATION]\nERROR: contract version unavailable",
                {
                    "base1": "renderer-source-01",
                    "inv1": "candidate-source-inv",
                    "dom1": "candidate-source-dom",
                },
            ),
        ):
            base_run = _write_run(run_root / name, "base1", trajectory)
            variants[name] = _manifest_case(
                task_root / name,
                adapter,
                task_id,
                base,
                candidates,
                base_run,
                candidate_runs,
                token=hashlib.sha256(f"{task_id}:{name}".encode()).hexdigest()[:16],
                source_ids=source_ids,
            )
        clean_text = Path(variants["clean"]["context_root"]) / "rollouts/base1.md"
        degraded_text = (
            Path(variants["degraded_no_provenance"]["context_root"]) / "rollouts/base1.md"
        )
        records.append(
            {
                "benchmark": benchmark,
                "task_id": task_id,
                "reference_record_sha256": raw_sha,
                "variants_derive_from_same_reference": True,
                "transformation_reached_rollout": clean_text.read_bytes()
                != degraded_text.read_bytes(),
                "variants": variants,
                "provenance_categories": [
                    "OFFICIAL_BENCHMARK_TASK",
                    "DERIVED_BENCHMARK_TASK",
                    "SYNTHETIC_REPLAY",
                ],
                "not_a_solver_run": True,
            }
        )
    result = {
        "schema_version": 1,
        "tasks": records,
        "real_saved_trajectories_used": 0,
        "synthetic_replays_used": len(records) * 3,
        "hidden_oracle_excluded": all(
            variant["hidden_oracle_excluded"]
            for row in records
            for variant in row["variants"].values()
        ),
        "all_candidates_reconstruct": all(
            all(variant["candidate_reconstruction"].values())
            for row in records
            for variant in row["variants"].values()
        ),
        "limitations": "No saved native trajectory existed for the sampled tasks; all execution evidence is labeled synthetic replay.",
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

