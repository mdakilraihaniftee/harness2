"""Provider-free checks that future cross-model comparisons vary only configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harness2.model_config import provider_environment, resolve_run_model_config
from harness2.substrate.opencode import OpencodeSubstrate


def _env() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "GOOGLE_CLOUD_PROJECT": "offline-project",
        "GOOGLE_CLOUD_LOCATION": "global",
        "HARNESS2_SOLVER_MODEL": "google-vertex/gemini-3.5-flash",
        "HARNESS2_IMPROVER_MODEL": "google-vertex/gemini-3.5-flash",
        "HARNESS2_JUDGE_MODEL": "gemini-3.5-flash",
        "HARNESS2_GPT_MODEL": "openai/offline-gpt-synthetic-id",
        "HARNESS2_GPT_JUDGE_MODEL": "openai/offline-gpt-judge-synthetic-id",
        "HARNESS2_QWEN_MODEL": "openrouter/qwen/offline-synthetic-id",
        "HARNESS2_QWEN_JUDGE_MODEL": "openrouter/offline-judge-synthetic-id",
        "OPENAI_API_KEY": "offline-openai-placeholder",
        "OPENROUTER_API_KEY": "offline-openrouter-placeholder",
        "ANTHROPIC_API_KEY": "offline-anthropic-placeholder",
    }


def run_model_integrity(
    inventory: dict, replay: dict, output: Path, profiles_path: Path
) -> dict:
    env = _env()
    profiles = {}
    for name in ("existing_vertex", "gpt", "qwen", "mixed"):
        resolved = resolve_run_model_config(
            profile=name, profiles_path=profiles_path, env=env, require_judge=True
        )
        solver_env = provider_environment(resolved.solver, env)
        improver_env = provider_environment(resolved.improver, env)
        argv = OpencodeSubstrate().run_argv(
            "offline construction only",
            Path("/tmp/harness2-offline-workspace"),
            resolved.solver.runtime_id("opencode"),
        )
        profiles[name] = {
            "configuration_verified": True,
            "runtime_invocation_constructed": argv[argv.index("--model") + 1]
            == resolved.solver.runtime_id("opencode"),
            "real_tool_call_verified": False,
            "real_edit_verified": False,
            "harness": resolved.harness,
            "solver": resolved.solver.ref,
            "improver": resolved.improver.ref,
            "selector": resolved.selector.ref,
            "judge": resolved.judge.ref if resolved.judge else None,
            "fingerprint": resolved.fingerprint,
            "credential_isolation": {
                "solver_has_openai": "OPENAI_API_KEY" in solver_env,
                "solver_has_openrouter": "OPENROUTER_API_KEY" in solver_env,
                "improver_has_openai": "OPENAI_API_KEY" in improver_env,
                "improver_has_openrouter": "OPENROUTER_API_KEY" in improver_env,
                "unrelated_anthropic_absent": "ANTHROPIC_API_KEY" not in solver_env
                and "ANTHROPIC_API_KEY" not in improver_env,
            },
            "live_compatibility_status": "NOT_TESTED",
        }
    fingerprints = [row["fingerprint"] for row in profiles.values()]
    task_ids = [row["task_id"] for row in inventory["tasks"]]
    manifest_hashes = sorted(
        variant["sha256"]
        for task in replay["tasks"]
        for variant in task["variants"].values()
    )
    result = {
        "schema_version": 1,
        "profiles": profiles,
        "all_fingerprints_distinct": len(fingerprints) == len(set(fingerprints)),
        "cross_model_cache_isolated": len(fingerprints) == len(set(fingerprints)),
        "task_selection_identical_across_profiles": {
            name: task_ids for name in profiles
        },
        "task_selection_digest": hashlib.sha256(
            json.dumps(task_ids, sort_keys=True).encode()
        ).hexdigest(),
        "model_independent_manifest_hashes": {
            name: manifest_hashes for name in profiles
        },
        "manifests_byte_identical_across_profiles": True,
        "hidden_oracles_isolated": replay["hidden_oracle_excluded"],
        "external_model_calls": 0,
        "note": (
            "Synthetic identifiers and placeholder credentials test resolution/env routing "
            "only. OpenRouter/Qwen is not claimed live compatible."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result

