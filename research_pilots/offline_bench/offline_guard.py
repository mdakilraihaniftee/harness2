"""Fail-closed protection against inference, benchmark execution, judges, and networking."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from unittest import mock


class OfflineViolation(RuntimeError):
    """An offline experiment attempted a forbidden external operation."""


@dataclass
class OfflineCounters:
    external_model_calls: int = 0
    external_judge_calls: int = 0
    solver_launcher_calls: int = 0
    network_calls: int = 0
    blocked_attempts: int = 0
    provider_inference_cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class OfflineGuard:
    """Patch every provider/benchmark boundary used by Harness² while the suite runs."""

    def __init__(self):
        self.counters = OfflineCounters()
        self._stack = ExitStack()

    def _blocked(self, kind: str):
        def fail(*_args, **_kwargs):
            self.counters.blocked_attempts += 1
            if kind == "model":
                self.counters.external_model_calls += 1
            elif kind == "judge":
                self.counters.external_judge_calls += 1
            elif kind == "solver":
                self.counters.solver_launcher_calls += 1
            elif kind == "network":
                self.counters.network_calls += 1
            raise OfflineViolation(f"offline guard blocked unexpected {kind} invocation")

        return fail

    def __enter__(self):
        from harness2.benchmarks.jobbench import JobBenchAdapter
        from harness2.benchmarks.lab import LabAdapter
        from harness2.benchmarks.workbuddy import WbAdapter
        from harness2.core.proposer import Proposer
        from harness2.substrate.codex import CodexSubstrate
        from harness2.substrate.opencode import OpencodeSubstrate

        patches = (
            mock.patch.object(Proposer, "call", self._blocked("model")),
            mock.patch.object(OpencodeSubstrate, "execute", self._blocked("solver")),
            mock.patch.object(CodexSubstrate, "execute", self._blocked("solver")),
            mock.patch.object(JobBenchAdapter, "score", self._blocked("judge")),
            mock.patch.object(LabAdapter, "score", self._blocked("judge")),
            mock.patch.object(WbAdapter, "score", self._blocked("judge")),
            mock.patch("socket.create_connection", self._blocked("network")),
        )
        for patch in patches:
            self._stack.enter_context(patch)
        return self

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)

    def assert_clean(self) -> None:
        if any(
            (
                self.counters.external_model_calls,
                self.counters.external_judge_calls,
                self.counters.solver_launcher_calls,
                self.counters.network_calls,
                self.counters.blocked_attempts,
            )
        ):
            raise OfflineViolation(f"forbidden call attempted: {self.counters.to_dict()}")

