# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Offline model-profile inspection. This command never performs inference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import config
from ..harness_registry import HARNESSES, substrate_for
from ..model_config import (
    PROVIDERS,
    credential_status,
    load_profiles,
    resolve_run_model_config,
)


def _runtime_status(run_config) -> tuple[str, str]:
    if run_config.harness == "opencode":
        entry = config.OPENCODE_DIR / "packages" / "opencode" / "src" / "index.ts"
        bun = config.BUN
        if not entry.is_file() or not bun.is_file():
            return "FAIL", "OpenCode checkout or bun is missing"
        provider_source = config.OPENCODE_DIR / "packages" / "opencode" / "src/provider/provider.ts"
        try:
            source = provider_source.read_text(encoding="utf-8")
        except OSError:
            return "FAIL", "OpenCode provider registry is unreadable"
        providers = {
            ("openai" if spec.provider == "custom" else spec.provider)
            for spec in (
                run_config.solver,
                run_config.improver,
                run_config.selector,
                run_config.judge,
            )
            if spec is not None
        }
        missing = sorted(provider for provider in providers if f"{provider}:" not in source and f'"{provider}":' not in source)
        if missing:
            return "FAIL", f"installed OpenCode does not register providers: {missing}"
        return "PASS", "provider syntax accepted; exact model availability is not live-tested"
    binary = Path(config.CODEX_DIST) / "codex"
    if not binary.is_file():
        return "FAIL", "Codex binary is missing"
    return "PASS", "Codex binary present; endpoint/model availability is not live-tested"


def _record(profile: str, *, profiles_path: Path | None = None) -> dict:
    run_config = resolve_run_model_config(profile=profile, profiles_path=profiles_path)
    runtime, limitation = _runtime_status(run_config)
    return {
        "profile": profile,
        "harness": run_config.harness,
        "substrate": substrate_for(run_config.harness),
        "fingerprint": run_config.fingerprint,
        "models": {
            role: (spec.ref if spec else None)
            for role, spec in (
                ("solver", run_config.solver),
                ("improver", run_config.improver),
                ("selector", run_config.selector),
                ("judge", run_config.judge),
            )
        },
        "credentials": {
            role: (credential_status(spec) if spec else "NOT_TESTED")
            for role, spec in (
                ("solver", run_config.solver),
                ("improver", run_config.improver),
                ("selector", run_config.selector),
                ("judge", run_config.judge),
            )
        },
        "runtime_status": runtime,
        "live_test_status": "NOT_TESTED",
        "limitations": limitation,
    }


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness2-models", description=__doc__)
    p.add_argument("--profiles-file", type=Path)
    sub = p.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="list configured profiles and built-in provider routes")
    ls.add_argument("--provider", choices=PROVIDERS)
    val = sub.add_parser("validate", help="validate one profile offline; no API request")
    val.add_argument("--profile", required=True)
    val.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "list":
            profiles = load_profiles(args.profiles_file)
            print("providers:")
            for provider in PROVIDERS:
                if not args.provider or args.provider == provider:
                    print(f"  {provider}: CONFIGURABLE; live status NOT_TESTED")
            print("harnesses:")
            for name, row in HARNESSES.items():
                print(f"  {name} ({row.substrate}): {row.model_mechanism}")
            print("profiles:")
            for name, row in sorted(profiles.items()):
                models = [str(row.get(role, "<inherited>")) for role in ("solver", "improver")]
                if args.provider:
                    hints = {
                        "openrouter": "QWEN",
                        "openai": "GPT",
                        "custom": "CUSTOM",
                        "google-vertex": "VERTEX",
                        "anthropic": "ANTHROPIC",
                    }
                    if not any(
                        m.startswith(args.provider + "/")
                        or hints[args.provider] in m.upper()
                        for m in models
                    ):
                        continue
                print(f"  {name}: CONFIGURED ({', '.join(models)})")
            return 0
        record = _record(args.profile, profiles_path=args.profiles_file)
        if args.json:
            print(json.dumps(record, indent=2))
        else:
            print(f"profile: {record['profile']}")
            print(f"harness: {record['harness']} ({record['runtime_status']})")
            for role, model in record["models"].items():
                print(f"{role}: {model} credentials={record['credentials'][role]}")
            print("live_test_status: NOT_TESTED (this command is offline)")
            print(f"limitations: {record['limitations']}")
        return 0 if record["runtime_status"] == "PASS" else 2
    except (config.ConfigError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
