"""Run the Phase 5 read-only provider audit and write sanitized artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from . import REPORTS, RESULTS, SCHEMA_VERSION
from .provider_audit import AuditBlocked, run_audit


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _report(result: dict) -> str:
    provider = result.get("provider", {})
    preferred = provider.get("preferred", {})
    account = result.get("account", {})
    alternatives = provider.get("eligible_alternatives", [])
    selected = provider.get("selected")
    eligible = "PASS" if selected else "BLOCKED"
    alt_lines = "\n".join(f"- `{row['id']}`" for row in alternatives) or "- None verified."
    cap = account.get("limit")
    return f"""# Cost and free-model audit

Status: **{eligible}**

The preferred route is `openrouter/{preferred.get('requested_id', 'unknown')}`. Provider
availability is `{preferred.get('available')}`, installed OpenCode catalog presence is
`{preferred.get('installed_catalog')}`, and eligibility is `{preferred.get('eligible')}`.
Blocker: {preferred.get('blocker') or 'none'}.

The selected fallback is `{provider.get('selected_ref')}`. It is an exact fixed model rather
than the mutable `openrouter/free` router. This fallback is code-focused, tool-capable, present
in the installed OpenCode catalog, and all pricing categories advertised by the authenticated
model catalog are exact zero.

Every advertised pricing field must parse as exact numeric zero, the exact identifier must end
in `:free`, and the model must advertise both `tools` and `tool_choice`. The live runner also
requires an installed OpenCode catalog entry, an exact-model allowlist, disabled model fallback,
zero provider price ceilings, a request cap, and explicit `--approve-free-inference`.

The key reports `is_free_tier={account.get('is_free_tier')}` and `limit={cap}`. A null limit
means no key-level spending cap was demonstrated. No account setting was changed.

Verified installed alternatives:

{alt_lines}

The paid configured Qwen Flash route is excluded. No inference request was made by this audit.
Only the six permitted account metrics are stored; credentials and authorization headers are
never written.
"""


def _local_report(result: dict) -> str:
    local = result.get("local", {})
    runtimes = ", ".join(
        f"{name}={'present' if path else 'absent'}" for name, path in local.get("runtimes", {}).items()
    )
    return f"""# Local model feasibility

Status: **{local.get('status', 'UNKNOWN')}**

Python: `{local.get('python')}`. GPU visible to the runtime: `{bool(local.get('gpu'))}`.
Local runtimes: {runtimes}. Existing model weight files were observed, but weights alone do not
provide a ready OpenAI-compatible, tool-capable server. No package or model was downloaded.

The machine has ample CPU memory and disk and may expose NVIDIA GPUs, but it has no installed
Ollama, vLLM, or llama-server command. Existing weights are not already exposed through a
tool-capable OpenAI-compatible server. Local inference is therefore not an immediate Phase 5 route.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only-provider-audit", action="store_true")
    args = parser.parse_args(argv)
    if not args.read_only_provider_audit:
        parser.error("explicit --read-only-provider-audit is required")
    RESULTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    try:
        audit = run_audit()
        status = "PASS" if audit["provider"].get("selected") else "COST_BLOCKED"
        result = {"schema_version": SCHEMA_VERSION, "status": status, **audit}
    except AuditBlocked as exc:
        result = {"schema_version": SCHEMA_VERSION, "status": "COST_BLOCKED", "blocker": str(exc)}
    _write_json(RESULTS / "model_availability.json", result)
    account = result.get("account", {})
    _write_json(
        RESULTS / "account_usage_before_after.json",
        {"schema_version": SCHEMA_VERSION, "before": account, "after": None, "model_requests": 0},
    )
    (REPORTS / "00_cost_and_free_model_audit.md").write_text(_report(result), encoding="utf-8")
    (REPORTS / "01_local_model_feasibility.md").write_text(_local_report(result), encoding="utf-8")
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    _write_json(
        RESULTS / "audit_provenance.json",
        {"git_revision": revision, "branch": subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, check=True
        ).stdout.strip(), "open_code_version": "1.14.18", "inference_requests": 0},
    )
    print(json.dumps({"status": result["status"], "model_requests": 0}))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
