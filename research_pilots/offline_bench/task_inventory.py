"""Seeded, non-outcome-based discovery and classification of installed benchmark tasks."""

from __future__ import annotations

import hashlib
import json
import random
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from harness2 import config
from harness2.benchmarks.jobbench import JobBenchAdapter
from harness2.benchmarks.lab import LabAdapter

from . import SEED

_FILE_REF = re.compile(
    r"\b[\w][\w .()\-]{0,100}\.(?:xlsx|xls|docx|pptx|pdf|csv|json|md|txt|py)\b",
    re.I,
)


def _digest_tree(root: Path | None) -> str:
    digest = hashlib.sha256()
    if not root or not root.is_dir():
        return digest.hexdigest()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _installed_revision(root: Path) -> str:
    """Return an immutable local checkout identity without contacting a remote."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else "UNKNOWN_LOCAL_REVISION"


def _sample(adapter, benchmark: str, count: int, seed: int) -> list[str]:
    by_domain: dict[str, list[str]] = defaultdict(list)
    for task_id in adapter.tasks():
        by_domain[adapter.domain_of(task_id)].append(task_id)
    domains = sorted(by_domain)
    random.Random(f"{seed}:{benchmark}:domains").shuffle(domains)
    chosen = []
    for domain in domains:
        tasks = sorted(by_domain[domain])
        chosen.append(random.Random(f"{seed}:{benchmark}:{domain}").choice(tasks))
        if len(chosen) == count:
            break
    return chosen


def _prior_rollout(benchmark: str, task_id: str) -> bool:
    if benchmark == "jb":
        root = config.RUNS / "jb" / "dataset" / task_id / "model_output"
        return root.is_dir() and any(path.is_file() for path in root.rglob("*"))
    safe = task_id.replace("/", "__")
    roots = (config.RUNS / "lab" / "results", config.RUNS / "reproduction")
    return any(root.is_dir() and any(root.rglob(f"*{safe}*")) for root in roots)


def _record(benchmark: str, adapter, task_id: str) -> dict:
    prompt = adapter.task_prompt(task_id)
    source = adapter.task_files(task_id)
    files = []
    if source and source.is_dir():
        for path in sorted(source.rglob("*")):
            if path.is_file():
                files.append(
                    {
                        "path": path.relative_to(source).as_posix(),
                        "bytes": path.stat().st_size,
                        "suffix": path.suffix.lower(),
                    }
                )
    if benchmark == "lab":
        raw = adapter._task_json(task_id)
        deliverables = [str(name) for name in (raw.get("deliverables") or {})]
        benchmark_path = config.lab_repo() / "tasks" / task_id
    else:
        deliverables = sorted(set(match.strip() for match in _FILE_REF.findall(prompt)))
        benchmark_path = adapter._dataset_task(task_id)
    meaningful_format_check = bool(deliverables) or any(
        row["suffix"] in {".csv", ".json", ".xlsx", ".xls", ".docx", ".pptx", ".pdf"}
        for row in files
    )
    classification = "NATIVE_DETERMINISTIC" if meaningful_format_check else "DERIVED_CONTROLLED"
    return {
        "benchmark": benchmark,
        "task_id": task_id,
        "domain": adapter.domain_of(task_id),
        "benchmark_path": str(benchmark_path.resolve()),
        "source_path": str(source.resolve()) if source else None,
        "instruction": prompt,
        "source_files": files,
        "source_digest_sha256": _digest_tree(source),
        "requested_deliverables": deliverables,
        "editable_harness_surface": list(adapter.substrate.surface().always_on),
        "prior_rollout_data_exists": _prior_rollout(benchmark, task_id),
        "deterministic_output_checks": (
            ["file presence", "filename/extension", "container parseability"]
            if meaningful_format_check
            else []
        ),
        "full_correctness_requires_llm_judge": True,
        "controlled_shift_possible": bool(meaningful_format_check),
        "classification": classification,
        "classification_reason": (
            "A requested artifact's presence, name, format, and parseability are meaningful "
            "deterministic parts of the official task; semantic correctness remains unscored."
            if classification == "NATIVE_DETERMINISTIC"
            else "Only a derived local contract can be evaluated without the official judge."
        ),
        "provenance_categories": ["OFFICIAL_BENCHMARK_TASK"],
    }


def build_inventory(output: Path, *, seed: int = SEED) -> dict:
    adapters = {"jb": JobBenchAdapter(), "lab": LabAdapter()}
    counts = {name: len(adapter.tasks()) for name, adapter in adapters.items()}
    selected = []
    for name, adapter in adapters.items():
        selected.extend(_record(name, adapter, task) for task in _sample(adapter, name, 6, seed))
    result = {
        "schema_version": 1,
        "selection_seed": seed,
        "selection_rule": (
            f"shuffle sorted domains with Random('{seed}:<bench>:domains'), then select one "
            f"task per domain with Random('{seed}:<bench>:<domain>') until six"
        ),
        "installed_task_counts": counts,
        "installed_paths": {
            "jb": str(config.jb_repo().resolve()),
            "lab": str(config.lab_repo().resolve()),
        },
        "installed_versions": {
            "jb": _installed_revision(config.jb_repo()),
            "lab": _installed_revision(config.lab_repo()),
        },
        "sample_size": {"jb": 6, "lab": 6},
        "replacements": [],
        "tasks": selected,
        "limitations": (
            "NATIVE_DETERMINISTIC covers only artifact-contract checks, never the official "
            "semantic benchmark score. No task was selected by outcome."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def assert_sources_unchanged(inventory: dict) -> None:
    for row in inventory["tasks"]:
        source = Path(row["source_path"]) if row.get("source_path") else None
        if _digest_tree(source) != row["source_digest_sha256"]:
            raise AssertionError(f"installed task input changed: {row['task_id']}")

