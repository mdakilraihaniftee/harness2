#!/usr/bin/env python3
"""Run or inspect the repository's frozen one-task LAB experiment.

Safe examples (no model calls):

    python examples/run_single_lab.py
    python examples/run_single_lab.py --show \
      --output runs/reproduction/lab-approved-005

Paid execution, after starting the documented Vertex gateway:

    python examples/run_single_lab.py --execute --approve-paid \
      --output runs/reproduction/my-single-lab-run

"Single task" means one LAB dataset item. Harness² k=1 parallel recursion still
uses four executor rollouts and three improver stages, followed here by two
judge passes. The explicit approval flag is therefore required.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
REPRODUCE = ROOT / "scripts/reproduce_lab.py"
DEFAULT_OUTPUT = ROOT / "runs/reproduction/lab-single-task"
DEFAULT_LAUNCHER = ROOT / "scripts/lab_agent_live_sandbox.py"
TASK_ID = "antitrust-competition/analyze-antitrust-hsr-strategy"
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.is_file() else default


def first_record(groups: dict) -> dict | None:
    for rows in groups.values():
        if rows:
            return rows[0]
    return None


def score_text(record: dict | None, *, initial: bool = False) -> str:
    if not record:
        return "not available"
    score = record.get("score", {}) if initial else record
    passed = score.get("n_passed")
    total = score.get("n_criteria")
    if not isinstance(passed, int) or not isinstance(total, int) or total < 1:
        return "not available"
    return f"{passed}/{total} ({passed / total:.0%})"


def docx_preview(path: Path, limit: int) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return "(DOCX preview unavailable)"
    paragraphs = []
    for paragraph in root.iter(WORD_NS + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(WORD_NS + "t")).strip()
        if text:
            paragraphs.append(text)
    content = "\n".join(paragraphs)
    return content[:limit] + ("\n…" if len(content) > limit else "")


def preview(path: Path, limit: int) -> str:
    if path.suffix.lower() == ".docx":
        return docx_preview(path, limit)
    if path.suffix.lower() in {".txt", ".md", ".json", ".csv"}:
        return path.read_text(errors="replace")[:limit]
    return f"(binary {path.suffix or 'file'}; open the artifact to inspect it)"


def show_result(output: Path, preview_chars: int) -> int:
    results_path = output / "results.json"
    results = load_json(results_path, {})
    refined = first_record(results.get("refined_scores", {}))
    initial = first_record(results.get("initial_scores", {}))
    summaries = list(results.get("summaries", {}).values())
    summary = summaries[0] if summaries else {}

    print(f"Task: {summary.get('task_id', TASK_ID)}")
    print(f"Run status: {summary.get('status', 'not run')}")
    print(f"Initial score: {score_text(initial, initial=True)}")
    print(f"Refined score: {score_text(refined)}")

    run_id = refined.get("run_id") if refined else None
    artifacts = []
    if run_id:
        artifact_root = output / "lab/results/oc" / run_id / "workspace/output"
        artifacts = sorted(path for path in artifact_root.rglob("*") if path.is_file())
    else:
        artifacts = sorted(output.glob("lab/results/oc/**/workspace/output/**/*"))
        artifacts = [path for path in artifacts if path.is_file()]

    if not artifacts:
        print(f"No deliverable yet. Dry-run selection: {output / 'dry-run.txt'}")
        return 0 if (output / "dry-run.txt").is_file() else 1

    print("Artifacts:")
    for artifact in artifacts:
        print(f"  {artifact}")
    chosen = artifacts[0]
    print(f"\nOutput preview ({chosen.name}):\n")
    print(preview(chosen, preview_chars))
    print(f"\nMachine-readable results: {results_path}")
    return 0


def run_stage(stage: str, output: Path, launcher: Path, *, paid: bool = False) -> int:
    command = [
        sys.executable,
        str(REPRODUCE),
        stage,
        "--output",
        str(output),
        "--agent-launcher",
        str(launcher),
    ]
    if paid:
        command.append("--approve-paid")
    print(f"\n== {stage} ==", flush=True)
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="run refinement and both judges")
    mode.add_argument("--show", action="store_true", help="only display an existing run")
    parser.add_argument("--approve-paid", action="store_true", help="required with --execute")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--agent-launcher", type=Path, default=DEFAULT_LAUNCHER)
    parser.add_argument("--preview-chars", type=int, default=1600)
    args = parser.parse_args(argv)

    if args.approve_paid and not args.execute:
        parser.error("--approve-paid is only valid with --execute")
    if args.execute and not args.approve_paid:
        parser.error("--execute requires explicit --approve-paid")
    if args.preview_chars < 1:
        parser.error("--preview-chars must be positive")

    output = args.output.expanduser().resolve()
    launcher = args.agent_launcher.expanduser().resolve()
    if args.show:
        return show_result(output, args.preview_chars)

    stages = [("prepare", False)]
    if args.execute:
        stages.extend(
            [
                ("check-isolation", False),
                ("run", True),
                ("judge", True),
                ("judge-bases", True),
                ("report", False),
                ("collect", False),
            ]
        )
    for stage, paid in stages:
        code = run_stage(stage, output, launcher, paid=paid)
        if code:
            print(f"Stopped: {stage} exited with status {code}.", file=sys.stderr)
            return code
    return show_result(output, args.preview_chars)


if __name__ == "__main__":
    raise SystemExit(main())
