"""Small adapter exposing synthetic records through the real Harness² context builder."""

from __future__ import annotations

import json
from pathlib import Path

from harness2.core import tree as harness_tree
from harness2.core.spec import BenchPrompts, BenchSpec, ChannelSpec
from harness2.substrate.opencode import OpencodeSubstrate
from research_pilots.evidence import EvidenceCondition, load_record, render_record


class PilotAdapter:
    def __init__(
        self,
        root: Path,
        task_id: str,
        base: dict[str, str],
        evidence: EvidenceCondition,
    ):
        self.root = Path(root)
        self.task_id = task_id
        self.evidence = evidence
        self.substrate = OpencodeSubstrate()
        local = ChannelSpec("opencode", "local/deterministic")
        self.spec = BenchSpec(
            name="research-pilot",
            runs_root=self.root / "runs",
            install_mode="workspace_config",
            prompts=BenchPrompts(
                work="submit one synthetic invoice through a versioned local API",
                domain_word="invoice-processing domain",
                deliverable_word="submission result",
                inv_levers="use tool outcomes to decide whether submission procedure needs repair",
                dom_levers="apply the documented schema and amount-unit rule exactly once",
                yardstick="A good harness submits exactly once with the required schema and value.",
            ),
            channels={"proposer": local, "selector": local},
            leak_globs=("oracle.json", "hidden_state.json"),
            proposer_deliverables="contents",
        )
        self._base = self.root / "base_harness"
        harness_tree.write_tree(self.substrate.surface(), base, self._base, stubs=False)
        self._source = self.root / "public_source"
        self._source.mkdir(parents=True, exist_ok=True)
        (self._source / "api_contract.md").write_text(
            "Submit invoice INV-7 once. The active API may report schema errors in tool output.\n"
        )

    def tasks(self, split: str = "all") -> list[str]:
        return [self.task_id]

    def domain_of(self, task_id: str) -> str:
        return "invoice-processing"

    def task_prompt(self, task_id: str) -> str:
        return "Submit invoice INV-7 once and produce a short processing report."

    def task_files(self, task_id: str) -> Path:
        return self._source

    def base_harness(self) -> Path:
        return self._base

    def trajectory(self, run_dir: Path, *, obs_trunc: int) -> str:
        del obs_trunc
        return render_record(load_record(run_dir), self.evidence)

    def deliverable_text(self, run_dir: Path) -> str:
        return (Path(run_dir) / "artifact.txt").read_text()

    def deliverable_files(self, run_dir: Path) -> dict[str, str]:
        return {"report.txt": self.deliverable_text(run_dir)}

    def delivered(self, run_dir: Path) -> bool:
        return (Path(run_dir) / "artifact.txt").is_file()

    def validate_tree(self, tree: dict[str, str]) -> None:
        harness_tree.validate(self.substrate.surface(), tree, allow_subagents=False)

    def score(self, run_dir: Path, task_id: str) -> dict:
        record = json.loads((Path(run_dir) / "execution.json").read_text())
        return {"utility": record["hidden_utility"]}
