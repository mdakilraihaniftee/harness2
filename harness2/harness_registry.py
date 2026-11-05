# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Registry for real execution harnesses shipped by Harness².

An execution harness is not the editable harness tree.  Only adapters implemented in this
checkout are registered; this intentionally contains no speculative Claude Code/OpenClaw rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class HarnessInfo:
    name: str
    substrate: str
    aliases: tuple[str, ...]
    model_mechanism: str
    editable_surface: str
    capabilities: tuple[str, ...]


HARNESSES = {
    "opencode": HarnessInfo(
        "opencode",
        "oc",
        ("opencode", "oc"),
        "--model provider/model",
        "OpenCode c1..c8 tree",
        ("tools", "editing", "events", "multi-provider"),
    ),
    "codex": HarnessInfo(
        "codex",
        "cx",
        ("codex", "cx"),
        "codex exec --model plus configured Responses endpoint",
        "Codex c1..c8 tree",
        ("tools", "editing", "events", "openai-compatible-endpoint"),
    ),
}
_ALIASES = {alias: name for name, info in HARNESSES.items() for alias in info.aliases}


def canonical_harness(value: str) -> str:
    key = str(value or "").strip().lower()
    if key not in _ALIASES:
        raise config.ConfigError(
            f"unknown execution harness {value!r}; available: {', '.join(HARNESSES)}"
        )
    return _ALIASES[key]


def resolve_harness(harness: str | None, substrate: str | None, profile: str = "") -> str:
    named = canonical_harness(harness) if harness else None
    legacy = canonical_harness(substrate) if substrate else None
    profiled = canonical_harness(profile) if profile else None
    if named and legacy and named != legacy:
        raise config.ConfigError(
            f"--harness {harness!r} conflicts with --substrate {substrate!r}"
        )
    if named and profiled and named != profiled:
        # Explicit CLI wins over a profile. This is not an error because the precedence is
        # documented and enables reusing one model profile on both real harnesses.
        return named
    return named or legacy or profiled or "opencode"


def substrate_for(harness: str) -> str:
    return HARNESSES[canonical_harness(harness)].substrate


def validate_run_config(run_config) -> None:
    if run_config.harness == "codex":
        # Codex can target the existing gateway, but it is not a native OpenRouter/Anthropic
        # transport in this repository. Improver/selector still run independently in OpenCode.
        if run_config.solver.provider not in ("openai", "custom", "google-vertex"):
            raise config.ConfigError(
                f"Codex solver does not have a verified {run_config.solver.provider} route in "
                "this checkout; use --harness opencode or a configured custom Responses endpoint"
            )


__all__ = ["HARNESSES", "HarnessInfo", "canonical_harness", "resolve_harness", "substrate_for"]
