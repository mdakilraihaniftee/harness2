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

"""Shared plumbing for the CLIs: adapter construction and the on-disk conventions.

The conventions are defined here once, because run_sweep writes them and
judge/report read them back.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .. import config
from ..core import library as LIB
from ..core import schedule as SCHED
from ..core.spec import BenchmarkAdapter, ChannelSpec
from ..model_config import RunModelConfig, resolve_run_model_config

BENCHES = ("jb", "wb", "lab")
WB_SUBSETS = ("office", "web", "code")
SUBSTRATES = ("oc", "cx")

MODES_DEFAULT = "parallel"
MODES_HELP = (
    "parallel | sequential (agg / seq accepted: the on-disk tokens); "
    "comma list, e.g. 'parallel' or 'parallel,sequential'"
)


class HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    """Defaults in the help text, module docstring kept verbatim as the description."""


def make_adapter(
    bench: str,
    subset: str | None,
    substrate: str,
    split_file: Path | None = None,
    run_config: RunModelConfig | None = None,
) -> BenchmarkAdapter:
    """The one place a CLI turns (--bench, --subset, --substrate) into an adapter."""
    if bench not in BENCHES:
        raise ValueError(f"unknown bench {bench!r}; expected one of {BENCHES}")
    if substrate not in SUBSTRATES:
        raise ValueError(f"unknown substrate {substrate!r}; expected one of {SUBSTRATES}")
    if bench == "wb":
        if run_config and (
            run_config.solver.provider != "google-vertex"
            or (run_config.judge and run_config.judge.provider != "google-vertex")
        ):
            raise config.ConfigError(
                "WorkBuddy's installed Harbor model route currently supports Vertex only; "
                "use JobBench/LAB for other providers or configure and test a Harbor model adapter"
            )
        if subset not in WB_SUBSETS:
            raise ValueError(f"--bench wb needs --subset from {WB_SUBSETS}, got {subset!r} ")
        from ..benchmarks.workbuddy import WbAdapter

        adapter = WbAdapter(
            subset,
            substrate=substrate,
            split_file=split_file,
            solver_model=(run_config.solver.runtime_id(run_config.harness) if run_config else None),
            solver_spec=(run_config.solver if run_config else None),
            judge_model=(judge_runtime_id(run_config, "wb") if run_config else None),
            judge_spec=(run_config.judge if run_config else None),
        )
        return _configure_adapter(adapter, run_config)
    if subset:
        raise ValueError(f"--subset applies to --bench wb only, got {subset!r} for {bench}")
    if bench == "jb":
        from ..benchmarks.jobbench import JobBenchAdapter

        adapter = JobBenchAdapter(
            substrate=substrate,
            split_file=split_file,
            solver_model=(run_config.solver.runtime_id(run_config.harness) if run_config else None),
            solver_spec=(run_config.solver if run_config else None),
            judge_model=(judge_runtime_id(run_config, "jb") if run_config else None),
            judge_spec=(run_config.judge if run_config else None),
        )
        return _configure_adapter(adapter, run_config)
    from ..benchmarks.lab import LabAdapter

    adapter = LabAdapter(
        substrate=substrate,
        split_file=split_file,
        model=(run_config.solver.runtime_id(run_config.harness) if run_config else None),
        solver_spec=(run_config.solver if run_config else None),
        judge_model=(judge_runtime_id(run_config, "lab") if run_config else None),
        judge_spec=(run_config.judge if run_config else None),
    )
    return _configure_adapter(adapter, run_config)


def judge_runtime_id(run_config: RunModelConfig, bench: str) -> str:
    """Map the independent judge role to each external evaluator's identifier convention."""
    spec = run_config.judge
    if spec is None:
        return ""
    if bench == "lab" and spec.provider == "google-vertex":
        return f"vertex/{spec.model_id}"
    if bench in ("jb", "wb") and spec.provider == "google-vertex":
        return f"google/{spec.model_id}"
    return spec.model_id if spec.provider in ("openai", "custom") else spec.ref


def _configure_adapter(adapter: BenchmarkAdapter, run_config: RunModelConfig | None):
    if run_config is None:
        return adapter
    proposer = ChannelSpec(
        "opencode",
        run_config.improver.runtime_id("opencode"),
        effort="high",
        model_spec=run_config.improver,
    )
    selector = ChannelSpec(
        "opencode",
        run_config.selector.runtime_id("opencode"),
        effort="high",
        model_spec=run_config.selector,
    )
    root = adapter.spec.runs_root / run_config.boundary
    adapter.spec = replace(
        adapter.spec,
        runs_root=root,
        channels={"proposer": proposer, "selector": selector},
    )
    # LAB chooses a result root before its frozen BenchSpec is replaced.
    if adapter.spec.name == "lab":
        adapter._results_root = root / "results" / adapter.substrate.name
    return adapter


def resolve_model_args(args, *, require_judge: bool = False) -> RunModelConfig:
    return resolve_run_model_config(
        harness=getattr(args, "harness", None),
        substrate=getattr(args, "substrate", None),
        model=getattr(args, "model", None),
        solver_model=getattr(args, "solver_model", None),
        improver_model=getattr(args, "improver_model", None),
        selector_model=getattr(args, "selector_model", None),
        judge_model=getattr(args, "judge_model", None),
        profile=getattr(args, "model_profile", None),
        profiles_path=getattr(args, "model_profiles_file", None),
        require_judge=require_judge,
    )


def legacy_compatible(run_config: RunModelConfig) -> bool:
    """Whether a selected config has the same routes as the current legacy environment."""
    try:
        legacy = resolve_run_model_config(harness=run_config.harness, require_judge=True)
    except config.ConfigError:
        return False
    return run_config.harness == legacy.harness and all(
        (run_config.role(role).safe_dict() if run_config.role(role) else None)
        == (legacy.role(role).safe_dict() if legacy.role(role) else None)
        for role in ("solver", "improver", "selector", "judge")
    )


def runs_root_for(adapter: BenchmarkAdapter) -> Path:
    """Scheduler state: summaries, harnesses and selections, not the rollout store."""
    return adapter.spec.runs_root / "adapt"


def library_root_for(adapter: BenchmarkAdapter, k: int, *, seed: int | None, tag: str = "") -> Path:
    """Per-(benchmark, substrate, k, seed, tag) experience-library root (the improver's R).

    Separate seeds and tags keep independent task streams from sharing entries.
    """
    SCHED.validate_tag(tag)
    variant = adapter.substrate.name
    if seed is not None:
        variant += f"-s{int(seed)}"
    if tag:
        variant += f"-{tag}"
    return LIB.root_for(
        adapter.spec.runs_root / "library", benchmark=adapter.spec.name, k=k, variant=variant
    )


def summary_namespace(adapter: BenchmarkAdapter, k: int, *, seed: int | None, tag: str = "") -> str:
    """The namespace whose task dirs hold summary.json for BOTH modes: run_task keeps the
    summary in the parallel mode's namespace (on-disk token "agg") whichever modes ran."""
    return SCHED.ns(adapter.spec.name, adapter.substrate.name, "agg", k, seed=seed, tag=tag)


def add_cell_args(p: argparse._ActionsContainer) -> None:
    """The (benchmark, substrate) cell selectors; `p` may be a parser or an argument group."""
    p.add_argument("--bench", required=True, choices=BENCHES, help="jb | wb | lab")
    p.add_argument(
        "--subset", default=None, choices=WB_SUBSETS, help="WB only: office | web | code"
    )
    p.add_argument(
        "--substrate",
        default=None,
        choices=SUBSTRATES,
        help="legacy task-executor alias: oc | cx (default: profile, then oc)",
    )
    p.add_argument(
        "--harness",
        choices=("opencode", "codex", "oc", "cx"),
        help="execution harness, independently selected from the model",
    )


def add_model_args(p: argparse._ActionsContainer) -> None:
    p.add_argument("--model", help="convenience override for solver and improver")
    p.add_argument("--solver-model", help="provider/model for task execution")
    p.add_argument("--improver-model", help="provider/model for proposals and composition")
    p.add_argument("--selector-model", help="provider/model for selection and reflection")
    p.add_argument("--judge-model", help="independent provider/model benchmark judge")
    p.add_argument("--model-profile", help="profile name from model_profiles.toml")
    p.add_argument(
        "--model-profiles-file",
        type=Path,
        help="alternate TOML profile file (default: HARNESS2_MODEL_PROFILES or repository file)",
    )
    p.add_argument(
        "--print-config",
        action="store_true",
        help="print resolved secret-free model configuration and exit",
    )


def add_modes_arg(p: argparse._ActionsContainer) -> None:
    p.add_argument("--mode", "--modes", dest="modes", default=MODES_DEFAULT, help=MODES_HELP)


def add_run_identity_args(p: argparse._ActionsContainer) -> None:
    """The run-identity knobs that enter the namespace."""
    p.add_argument(
        "--k", type=int, default=1, help="scale: R=4k rollouts, P=3k improver sessions per task"
    )
    p.add_argument(
        "--seed", type=int, default=None, help="stream-order seed; omit for sorted task order"
    )
    add_modes_arg(p)


def parse_modes(raw: str) -> tuple[str, ...]:
    """'parallel,sequential' (or the on-disk tokens 'agg,seq') -> tokens in MODES order."""
    names = [s.strip() for s in raw.split(",") if s.strip()]
    if not names:
        raise ValueError(
            f"--modes takes a comma list of parallel | sequential (agg | seq), got {raw!r}"
        )
    tokens = set()
    for name in names:
        try:
            tokens.add(SCHED.mode_token(name))
        except ValueError as exc:
            raise ValueError(f"--modes: {exc} (got {raw!r})") from None
    return tuple(t for t in SCHED.MODES if t in tokens)


def mode_label(token: str) -> str:
    """Human name for an on-disk token ('agg' -> 'parallel'); unknown tokens pass through."""
    return SCHED.MODE_NAMES.get(token, token)
