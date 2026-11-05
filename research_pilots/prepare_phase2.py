"""Build compact-manifest contexts without model calls."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from harness2.core import context
from harness2.core import tree as harness_tree
from harness2.core.spec import RunView
from harness2.substrate.opencode import OPENCODE_SURFACE
from research_pilots.adapter import PilotAdapter
from research_pilots.evidence import condition
from research_pilots.fixtures import (
    TASK_CITE,
    TASK_PAVE_NO_FAULT,
    base_tree,
    cite_candidates,
    execute_pave,
    pave_retry_tree,
    write_execution,
)
from research_pilots.manifest import assert_references_accessible, build_manifest
from research_pilots.run_live import cite_record

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "research_pilots/runs/phase2/prepared-v1"
RESULT_ROOT = ROOT / "research_pilots/results/phase2"


def digest_existing(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "EVIDENCE_MANIFEST.md":
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def opaque_token(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]


def run_view(label: str, run_dir: Path) -> RunView:
    return RunView(label, f"phase2/{label}", run_dir, ok=True, delivered=True)


def write_tree(path: Path, tree: dict[str, str]) -> Path:
    return harness_tree.write_tree(OPENCODE_SURFACE, tree, path, stubs=False)


def _save_manifest(name: str, built, semantic_condition: str) -> dict:
    destination = RESULT_ROOT / "manifests" / name
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built.path, destination / "EVIDENCE_MANIFEST.md")
    metadata = built.to_dict() | {"semantic_condition": semantic_condition}
    (destination / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def prepare_cite() -> dict:
    root = RUN_ROOT / "cite"
    base, candidates = cite_candidates()
    trees = {"base1": base, "inv1": candidates["A"], "dom1": candidates["B"]}
    runs = {
        label: write_execution(root / "raw", cite_record(label, tree))
        for label, tree in trees.items()
    }
    evidence = condition("A0_clean", list(trees))
    adapter = PilotAdapter(root, TASK_CITE, base, evidence)
    harness_dir = write_tree(root / "harnesses/base", base)
    pool = [
        (
            label,
            write_tree(root / "harnesses" / label, trees[label]),
            run_view(label, runs[label]),
        )
        for label in ("inv1", "dom1")
    ]
    built_context = context.build(
        root / "context/cite_compact",
        adapter,
        TASK_CITE,
        [run_view("base1", runs["base1"])],
        harness_dir=harness_dir,
        pool=pool,
        decisions={"inv1": "controlled edit A", "dom1": "controlled edit B"},
    )
    before = digest_existing(built_context.root)
    manifest = build_manifest(
        built_context.root,
        candidate_scopes={"inv1": "INV", "dom1": "DOM"},
        condition_token=opaque_token("cite", evidence.cache_token, "compact"),
    )
    assert_references_accessible(manifest)
    after = digest_existing(built_context.root)
    if before != after:
        raise AssertionError("building the CITE manifest changed original evidence")
    return _save_manifest("cite_e1", manifest, "controlled_A_B_pool") | {
        "original_evidence_digest": before
    }


def prepare_pave() -> dict[str, dict]:
    root = RUN_ROOT / "pave"
    labels = [f"base{i}" for i in range(1, 4)] + [
        f"{scope}{i}" for i in range(1, 4) for scope in ("inv", "dom")
    ]
    trees = {
        label: pave_retry_tree() if label.startswith("inv") else base_tree()
        for label in labels
    }
    runs = {
        label: write_execution(root / "raw", execute_pave(label, tree))
        for label, tree in trees.items()
    }
    scopes = {label: "INV" if label.startswith("inv") else "DOM" for label in labels[3:]}
    results = {}
    specs = (
        ("A0_clean", False),
        ("A1_isolated", False),
        ("A2_systematic", False),
        ("A2_systematic", True),
    )
    for condition_name, with_provenance in specs:
        variant = condition_name + ("_with_provenance" if with_provenance else "_no_provenance")
        evidence = condition(condition_name, labels)
        variant_root = root / variant
        adapter = PilotAdapter(variant_root, TASK_PAVE_NO_FAULT, base_tree(), evidence)
        harness_dir = write_tree(variant_root / "harnesses/base", base_tree())
        base_runs = [run_view(label, runs[label]) for label in labels[:3]]
        pool = [
            (
                label,
                write_tree(variant_root / "harnesses" / label, trees[label]),
                run_view(label, runs[label]),
            )
            for label in labels[3:]
        ]
        built_context = context.build(
            variant_root / "context/pave_compact",
            adapter,
            TASK_PAVE_NO_FAULT,
            base_runs,
            harness_dir=harness_dir,
            pool=pool,
            decisions={label: "controlled candidate supplied for composition" for label in labels[3:]},
        )
        source_ids = None
        if with_provenance:
            source_ids = {label: "renderer-source-01" for label in labels}
        before = digest_existing(built_context.root)
        manifest = build_manifest(
            built_context.root,
            candidate_scopes=scopes,
            condition_token=opaque_token("pave", evidence.cache_token, variant),
            source_ids=source_ids,
        )
        assert_references_accessible(manifest)
        after = digest_existing(built_context.root)
        if before != after:
            raise AssertionError(f"building {variant} changed original evidence")
        results[variant] = _save_manifest(variant, manifest, condition_name) | {
            "original_evidence_digest": before
        }
    return results


def main() -> int:
    shutil.rmtree(RUN_ROOT, ignore_errors=True)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    RESULT_ROOT.mkdir(parents=True, exist_ok=True)
    validation = {"cite": prepare_cite(), "pave": prepare_pave()}
    (RESULT_ROOT / "manifest_validation.json").write_text(
        json.dumps(validation, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(validation, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
