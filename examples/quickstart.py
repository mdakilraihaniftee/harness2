# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run Harness² from Python and inspect what it adopted.

    python examples/quickstart.py demo               # built-in ledger demo, no credentials
    python examples/quickstart.py custom             # a new task family, scripted editor
    python examples/quickstart.py custom --live      # same tasks, real LLM improver from .env
    python examples/quickstart.py inspect runs/quickstart/custom

`custom` is the template for plugging in new work: `WordCountAdapter` implements the
`BenchmarkAdapter` protocol (harness2/core/spec.py) and `ScriptedEditor` stands in for the
model-backed improver. Swap either for your own.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

from harness2.core import tree
from harness2.core.proposer import Proposer, Reply
from harness2.core.schedule import mode_token, run_domain
from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec, resolve_channel_model
from harness2.demo import DemoAdapter, DemoProposer
from harness2.substrate.opencode import OpencodeSubstrate

# A deliberately flawed starting tool: split(" ") miscounts newlines and repeated spaces.
BASE_SCRIPT = """import sys

text = open(sys.argv[1], encoding="utf-8").read()
print(f"Words: {len(text.split(' '))}")
"""

TASKS = {
    "notes-1": "Quarterly review\nRevenue grew  in every region.\n",
    "notes-2": "Action items:\n- hire two engineers\n- close the  audit\n",
}


class WordCountAdapter:
    """A minimal benchmark: count words in a text file with scripts/count_words.py.

    The executor is a plain subprocess so the example runs anywhere. For an agent executor,
    have `execute` materialise `harness_dir` into a workspace and launch the agent there
    (see harness2/benchmarks/*.py for OpenCode- and Codex-backed adapters).
    """

    def __init__(self, root: Path, *, model: str = "local/deterministic"):
        self.root = root
        self.substrate = OpencodeSubstrate()
        channel = (
            ChannelSpec("opencode", model)
            if model == "local/deterministic"
            else resolve_channel_model("opencode", model, steps=60, timeout=900)
        )
        self.spec = BenchSpec(
            name="wordcount",
            runs_root=root / "runs",
            install_mode="workspace_config",
            prompts=BenchPrompts(work="count the words in short business notes"),
            channels={"proposer": channel, "selector": channel},
            leak_globs=("expected.txt",),
        )
        self.execution_count = 0
        base = {name: "" for name in self.substrate.surface().always_on}
        base["systemprompt.md"] = "Count words with python scripts/count_words.py <file>.\n"
        base["scripts/count_words.py"] = BASE_SCRIPT
        tree.write_tree(self.substrate.surface(), base, self.base_harness(), stubs=False)
        for task_id, text in TASKS.items():
            source = self.task_files(task_id)
            source.mkdir(parents=True, exist_ok=True)
            (source / "notes.txt").write_text(text, encoding="utf-8")

    def tasks(self, split: str = "all") -> list[str]:
        return list(TASKS)

    def domain_of(self, task_id: str) -> str:
        return "text-processing"

    def task_prompt(self, task_id: str) -> str:
        return "Count the whitespace-separated words in notes.txt. Return Words: <n>."

    def task_files(self, task_id: str) -> Path:
        return self.root / "sources" / task_id

    def base_harness(self) -> Path:
        return self.root / "base"

    def validate_tree(self, harness: tree.Tree) -> None:
        if "scripts/count_words.py" not in harness:
            raise ValueError("Keep scripts/count_words.py: the executor runs it on notes.txt")

    def execute(
        self, task_id: str, harness_dir: Path | None, run_id: str, *, timeout: int | None = None
    ) -> Path:
        self.execution_count += 1
        run_dir = self.root / "executions" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        script = (harness_dir or self.base_harness()) / "scripts/count_words.py"
        result = subprocess.run(
            [sys.executable, str(script), str(self.task_files(task_id) / "notes.txt")],
            capture_output=True,
            text=True,
            timeout=timeout or 10,
        )
        if result.returncode == 0:
            (run_dir / "answer.txt").write_text(result.stdout, encoding="utf-8")
        (run_dir / "trajectory.md").write_text(
            "[ACTION] python scripts/count_words.py notes.txt\n"
            + (f"[OBSERVATION]\n{result.stdout}" if result.returncode == 0 else "")
            + (f"[ERROR]\n{result.stderr}" if result.returncode else ""),
            encoding="utf-8",
        )
        return run_dir

    def delivered(self, run_dir: Path) -> bool:
        return (run_dir / "answer.txt").is_file()

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        return (run_dir / "trajectory.md").read_text(encoding="utf-8")[:obs_trunc]

    def deliverable_text(self, run_dir: Path) -> str:
        path = run_dir / "answer.txt"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        return {"answer.txt": self.deliverable_text(run_dir)}

    def score(self, run_dir: Path, task_id: str) -> dict | None:
        expected = len(TASKS[task_id].split())
        return {
            "n_passed": int(f"Words: {expected}" in self.deliverable_text(run_dir)),
            "n_criteria": 1,
        }


class ScriptedEditor(DemoProposer):
    """Offline stand-in for the improver; it plays the editor, selector and reflector roles.

    Labels tell the roles apart: `select.*` picks among candidates, `experience.*` writes the
    library lesson, anything else edits the tree under `context/harness/`.
    """

    def call(self, mission, context_dir, label, **kwargs) -> Reply:
        context = Path(context_dir)
        workspace = None
        if label.startswith("select."):
            expected = len((context / "source/notes.txt").read_text().split())
            candidates = sorted((context / "candidates").glob("*.md"))
            chosen = next(
                (p.stem for p in candidates if f"Words: {expected}" in p.read_text()),
                candidates[0].stem,
            )
            text = f"<why>Its count matches the words in notes.txt.</why>\n```choice\n{chosen}\n```"
        elif label.startswith("experience."):
            text = (
                "<edits>\ncomponent: scripts/count_words.py\ncandidates: inv1\n"
                "change: split on any whitespace\nobserved: the count stopped including "
                "empty fragments from line breaks\nverdict: helped\n</edits>\n\n"
                "<experience>\ncue: When notes span several lines or have doubled spaces\n"
                "lesson: Use str.split() with no argument in scripts/count_words.py.\n"
                "evidence: The scripts/count_words.py row -- the base split(' ') count differed "
                "from the probe count on the same notes.txt.\nconfidence: high\n</experience>"
            )
        else:
            workspace = context / "harness"
            script = workspace / "scripts/count_words.py"
            script.write_text(script.read_text().replace("split(' ')", "split()"))
            text = "<notes>Split on any whitespace; split(' ') counted empty fragments.</notes>"
        reply = Reply(label=label, text=text, ok=True, attempts=1, workspace=workspace)
        self._calls.append(reply)
        return reply


def inspect(root: Path, adapter=None) -> None:
    """Print, per task and mode: base vs adopted answer, the harness diff, and the lesson."""
    runs_root = root / "runs"
    surface = OpencodeSubstrate().surface()
    base_tree = tree.read_tree(surface, root / "base")
    for summary_path in sorted(runs_root.glob("*/*/summary.json")):
        summary = json.loads(summary_path.read_text())
        task_id = summary["task_id"]
        base_dir = Path(summary["base"][0]["run_dir"])
        base_answer = read_answer(base_dir)
        print(f"\n=== {task_id}  (domain {summary['domain']}, k={summary['k']})")
        print(f"  base answer:    {base_answer}")
        for mode, sel in summary.get("selections", {}).items():
            chosen_dir = Path(sel["chosen_run_dir"]) if sel.get("chosen_run_dir") else None
            answer = read_answer(chosen_dir)
            grade = ""
            if adapter is not None and chosen_dir and (chosen_dir / "answer.txt").is_file():
                s = adapter.score(chosen_dir, task_id)
                if s is not None:
                    grade = f"  [{s['n_passed']}/{s['n_criteria']} criteria]"
            print(f"  {mode}: adopted {sel['chosen_label']!r} -> {answer}{grade}")
            print(f"       why: {sel.get('why', '')}")
            lesson = (sel.get("experience") or {}).get("lesson")
            if lesson:
                print(f"       lesson: {lesson}")
            if not sel.get("chosen_run_id") or not sel.get("chosen_label"):
                continue
            work = runs_root / sel["chosen_run_id"].split("/")[0] / task_id
            adopted = work / "harnesses" / sel["chosen_label"]
            if adopted.is_dir():
                after = tree.read_tree(surface, adopted)
                for rel in sorted(set(base_tree) | set(after)):
                    if base_tree.get(rel, "") != after.get(rel, ""):
                        diff = difflib.unified_diff(
                            base_tree.get(rel, "").splitlines(),
                            after.get(rel, "").splitlines(),
                            f"base/{rel}",
                            f"{sel['chosen_label']}/{rel}",
                            lineterm="",
                        )
                        print("       " + "\n       ".join(diff))
    for index in sorted((root / "library").glob("*/*/*/INDEX.md")):
        print(f"\nlibrary: {index.relative_to(root)}")


def read_answer(run_dir: Path | None) -> str:
    """Keep partial or failed live runs inspectable."""
    if run_dir is not None and (run_dir / "answer.txt").is_file():
        return (run_dir / "answer.txt").read_text().strip()
    return "(no answer.txt)"


def run(adapter, proposer, root: Path, k: int, mode: str) -> int:
    modes = ("agg", "seq") if mode == "both" else (mode_token(mode),)
    tasks = adapter.tasks()
    result = run_domain(
        adapter.domain_of(tasks[0]),
        tasks,
        k,
        adapter=adapter,
        prop=proposer,
        runs_root=adapter.spec.runs_root,
        library_root=root / "library" / f"k{k}",
        modes=modes,
    )
    print(
        f"\n{result['done']} done, {result['failed']} failed; "
        f"{adapter.execution_count} executions, {len(proposer._calls)} editor calls"
    )
    for row in result["tasks"]:
        if row.get("error"):
            print(f"  {row['task']}: {row['error']}")
    inspect(root, adapter)
    return int(result["failed"] > 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("demo", "custom", "inspect"))
    parser.add_argument("path", nargs="?", type=Path, help="output dir (inspect: dir to read)")
    parser.add_argument("--k", type=int, default=1, help="task-level recursion budget")
    parser.add_argument("--mode", choices=("parallel", "sequential", "both"), default="both")
    parser.add_argument(
        "--live", action="store_true", help="custom only: use HARNESS2_IMPROVER_MODEL via OpenCode"
    )
    args = parser.parse_args(argv)
    if args.k < 1:
        parser.error("--k must be positive")
    if args.live and args.command != "custom":
        parser.error("--live only applies to custom")
    root = (args.path or Path("runs/quickstart") / args.command).expanduser().resolve()

    if args.command == "inspect":
        inspect(root)
        return 0
    if args.command == "demo":
        adapter = DemoAdapter(root)
        return run(
            adapter, DemoProposer(adapter.spec.channels["proposer"]), root, args.k, args.mode
        )
    if not args.live:
        adapter = WordCountAdapter(root)
        return run(
            adapter, ScriptedEditor(adapter.spec.channels["proposer"]), root, args.k, args.mode
        )

    from harness2 import config

    if not re.fullmatch(r"[^/\s]+/\S+", config.IMPROVER_MODEL or ""):
        sys.exit(
            "--live needs HARNESS2_IMPROVER_MODEL (or HARNESS2_SOLVER_MODEL) in .env, "
            "e.g. google-vertex/gemini-3.5-flash, plus GOOGLE_CLOUD_PROJECT"
        )
    if config.IMPROVER_MODEL.startswith("google-vertex/") and not config.VERTEX_PROJECT:
        parser.exit(1, "error: Set GOOGLE_CLOUD_PROJECT in .env before using --live\n")
    try:
        OpencodeSubstrate().preflight()
    except RuntimeError as exc:
        parser.exit(1, f"error: {exc}\n")
    root = root.with_name(root.name + "-live")
    adapter = WordCountAdapter(root, model=config.IMPROVER_MODEL)
    proposer = Proposer(adapter.spec.channels["proposer"], audit_dir=root / "_audit")
    return run(adapter, proposer, root, args.k, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
