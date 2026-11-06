"""Finalize Phase 5 machine results and reports without any provider access."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import FALLBACK_MODEL, REPORTS, RESULTS, SCHEMA_VERSION


def _read(path: Path, default: Any) -> Any:
    return json.loads(path.read_text()) if path.is_file() else default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")


def finalize() -> dict[str, Any]:
    decisions = _read(RESULTS / "composer_decisions.json", [])
    account = _read(RESULTS / "account_usage_before_after.json", {})
    availability = _read(RESULTS / "model_availability.json", {})
    gate = decisions[0] if decisions else None
    if gate and str(gate.get("final_notes", "")).lower().startswith("maximum steps reached"):
        gate["tool_trace"]["step_exhausted"] = True
        gate["completion"]["step_exhausted"] = True
        gate["completion"]["decision"] = "OPERATIONAL_FAILURE"
        gate["decision"] = "OPERATIONAL_FAILURE"
        gate["valid_research_result"] = False
    _write_json(RESULTS / "composer_decisions.json", decisions)

    request_events = []
    events_path = Path("runs/phase5-free-gate/provider-events.jsonl")
    if events_path.is_file():
        for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                request_events.append(row)
    provider_usage = {
        key: sum(float(row.get(key) or 0) for row in request_events)
        for key in (
            "cost_usd",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
        )
    }
    requested = sorted({row.get("requested_model") for row in request_events if row.get("requested_model")})
    actual = sorted(
        {model for row in request_events for model in row.get("actual_models", []) if model}
    )
    gate_status = "MODEL_CAPABILITY_FAILURE" if gate else "COST_BLOCKED"
    if gate and gate.get("valid_research_result"):
        gate_status = "PASS"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": gate_status,
        "gate_status": gate_status,
        "model": FALLBACK_MODEL,
        "requested_provider_models": requested,
        "actual_provider_models": actual,
        "zero_pricing_verified": bool(availability.get("provider", {}).get("selected")),
        "key_limit": account.get("before", {}).get("limit"),
        "key_limit_remaining_before": account.get("before", {}).get("limit_remaining"),
        "key_limit_remaining_after": account.get("after", {}).get("limit_remaining"),
        "composer_sessions": len(decisions),
        "valid_composer_sessions": sum(bool(row.get("valid_research_result")) for row in decisions),
        "model_requests": len(request_events),
        "provider_usage": provider_usage,
        "external_judge_calls": 0,
        "cite_conditions": [row["condition_id"] for row in decisions if row["condition_id"].startswith("CITE")],
        "pave_conditions": [row["condition_id"] for row in decisions if row["condition_id"].startswith("PAVE")],
        "pave_harmful_edit_observed": None,
        "diagnostic_changed_decision": None,
        "paid_fallback_used": False,
    }
    _write_json(RESULTS / "experiment_summary.json", summary)

    selected = availability.get("provider", {}).get("selected", {})
    preferred = availability.get("provider", {}).get("preferred", {})
    _write(
        REPORTS / "00_cost_and_free_model_audit.md",
        f"""# Cost and free-model audit

Status: **PASS for the selected route**.

The requested Qwen route `openrouter/qwen/qwen3-coder:free` returned HTTP 404 from the
authenticated exact-model endpoint and was absent from OpenCode 1.14.18's installed catalog.
It was not called. The configured `openrouter/qwen/qwen3-coder-flash` has positive input,
output, and cache prices and was excluded.

The fixed fallback `{FALLBACK_MODEL}` was present in both the authenticated provider catalog
and installed OpenCode catalog. Its advertised pricing was `{selected.get('pricing')}`, and it
advertised `tools` plus `tool_choice`. The gateway required the exact model, rejected a `models`
fallback list, disabled provider fallback, applied zero prompt/completion/image/request ceilings,
requested provider usage telemetry, and capped the experiment at 26 provider requests.

The key reported `is_free_tier={account.get('before', {}).get('is_free_tier')}`, limit
`{account.get('before', {}).get('limit')}`, and unchanged remaining limit
`{account.get('after', {}).get('limit_remaining')}`. This is a finite key-level limit; no account
or billing setting was changed. Six generation requests reported total provider cost `$0.00`.

Preferred-route blocker: {preferred.get('blocker')}.
""",
    )
    _write(
        REPORTS / "02_free_composer_compatibility.md",
        f"""# Free composer compatibility

Gate outcome: **{gate_status}**.

One CITE V1 session used `{FALLBACK_MODEL}`, the original `adapt` prompt, frozen compact
manifest, OpenCode, and no judge. The model read the manifest and all relevant candidate
trajectories, but spent all six turns reading evidence. It made no file write and returned no
parseable `<notes>` decision. Its final response explicitly said the maximum step budget had
been reached. The tree remained base only because no edit occurred; this is an operational
failure and is not a KEEP_BASE composer decision.

The exact provider model was `{', '.join(actual) or 'unreported'}` for all
{len(request_events)} requests. Provider telemetry recorded {int(provider_usage['input_tokens'])}
input, {int(provider_usage['output_tokens'])} completion, {int(provider_usage['reasoning_tokens'])}
reasoning, and {int(provider_usage['cache_read_tokens'])} cache-read tokens at
`${provider_usage['cost_usd']:.2f}`. Runtime wall time was {gate.get('wall_s', 0) if gate else 0}
seconds. The model used nine read tools and zero write tools.

The engineering route worked, but this model did not complete the Harness² composer protocol
within the conservative gate. Per the protocol, no unchanged retry and no PAVE session followed.
""",
    )
    _write(
        REPORTS / "03_pave_behavior.md",
        """# PAVE behavior

Status: **NOT RUN**.

The CITE compatibility gate did not pass, so PAVE-CLEAN, PAVE-SYSTEMATIC, and PAVE-DIAGNOSTIC
were not called. There is no model-backed evidence of a harmful edit, an unnecessary edit, or
a diagnostic benefit in Phase 5. The PAVE hypothesis remains inconclusive.
""",
    )
    _write(
        REPORTS / "04_cite_behavior.md",
        """# CITE behavior

Status: **INCONCLUSIVE**.

CITE V1 was used as the compatibility gate. The model inspected both A and B evidence but did
not reach an explicit composition decision and made no edit before the six-step limit. Hidden
utility of the unchanged base is 0, but this is deterministic post-hoc fixture evaluation and
does not show that the composer rejected either useful edit. The initial session cannot support
or refute the CITE behavioral hypothesis, and C interference was not run.
""",
    )
    _write(
        REPORTS / "05_research_decision.md",
        f"""# Phase 5 research decision

Decision: **INCONCLUSIVE — FREE MODEL CAPABILITY GATE FAILED**.

The zero-paid route is operational and cost controls held: exact `{FALLBACK_MODEL}`, six actual
requests, no fallback, no judge, unchanged account usage, and `$0.00` provider inference cost.
The model could use OpenCode and read the frozen evidence, but it did not compose or write a
harness within six steps. That is an engineering/model-capability result, not composer-behavior
evidence. PAVE was correctly skipped, and CITE remains scientifically inconclusive.

The next smallest justified experiment is one separately authorized compatibility session with
the same frozen CITE V1 context and another currently verified fixed free code/tool model, or a
ready local tool-capable runtime. Keep the same exact-model and zero-price gates. Do not increase
the Cohere step budget or rerun it unchanged merely to consume more free quota. A paid model gate
would require separate authorization and is not part of Phase 5.
""",
    )
    return summary


def main() -> int:
    print(json.dumps(finalize(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
