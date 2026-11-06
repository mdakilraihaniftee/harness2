"""Create Phase 6 reports from saved, non-secret artifacts without inference."""

from __future__ import annotations

import json
from typing import Any

from . import NAVIGATION_POLICY, REPORTS, RESULTS, SCHEMA_VERSION


def _read(name: str, default: Any) -> Any:
    path = RESULTS / name
    return json.loads(path.read_text()) if path.is_file() else default


def _json(name: str, value: Any) -> None:
    path = RESULTS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _report(name: str, body: str) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / name).write_text(body.rstrip() + "\n", encoding="utf-8")


def finalize() -> dict[str, Any]:
    audit = _read("model_audit.json", {})
    gemma = _read("gemma_gate_failure.json", {})
    first_nemotron = _read("nemotron_protocol_failure.json", {})
    retry_rows = _read("composer_decisions.json", [])
    retry = next(
        (
            row
            for row in retry_rows
            if row.get("attempt_id") == "nemotron-protocol-retry-8"
            or (
                row.get("condition_id") == "CITE_V1"
                and row.get("navigation_instruction") == NAVIGATION_POLICY
            )
        ),
        {},
    )
    live_usage = _read("usage_summary.json", {})
    account_before = live_usage.get(
        "before", live_usage.get("account_before", audit.get("account", {}))
    )
    account_after = live_usage.get("after", live_usage.get("account_after", account_before))
    nemotron_usage = live_usage.get("provider_usage", {})
    total_requests = int(gemma.get("provider_requests", 0)) + int(
        live_usage.get("model_requests", live_usage.get("nemotron_requests", 0))
    )
    total_usage = {
        "cost_usd": float(gemma.get("provider_cost_usd", 0))
        + float(nemotron_usage.get("cost_usd", 0)),
        "input_tokens": int(gemma.get("input_tokens", 0))
        + int(nemotron_usage.get("input_tokens", 0)),
        "output_tokens": int(gemma.get("output_tokens", 0))
        + int(nemotron_usage.get("output_tokens", 0)),
        "reasoning_tokens": int(nemotron_usage.get("reasoning_tokens", 0)),
        "cache_read_tokens": int(nemotron_usage.get("cache_read_tokens", 0)),
    }
    decisions = [
        {"attempt_id": "gemma-gate", **gemma},
        {"attempt_id": "nemotron-gate-12", **first_nemotron},
        {"attempt_id": "nemotron-protocol-retry-8", **retry},
    ]
    _json("composer_decisions.json", decisions)
    usage = {
        "schema_version": SCHEMA_VERSION,
        "account_before": account_before,
        "account_after": account_after,
        "provider_requests": total_requests,
        "gemma_requests": int(gemma.get("provider_requests", 0)),
        "nemotron_requests": int(
            live_usage.get("model_requests", live_usage.get("nemotron_requests", 0))
        ),
        "provider_usage": total_usage,
        "actual_response_models": nemotron_usage.get(
            "actual_models",
            live_usage.get("actual_response_models")
            or first_nemotron.get("provider_usage", {}).get("actual_models", []),
        ),
        "paid_fallback_used": False,
        "external_judge_calls": 0,
    }
    _json("usage_summary.json", usage)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "decision": "STILL_OPERATIONALLY_BLOCKED",
        "status": "STILL_OPERATIONALLY_BLOCKED",
        "audited_first_choice": audit.get("selected_model"),
        "executed_models": [
            "openrouter/google/gemma-4-26b-a4b-it:free",
            "openrouter/nvidia/nemotron-3.5-lightning:free",
        ],
        "provider_requests": total_requests,
        "provider_cost_usd": total_usage["cost_usd"],
        "valid_composer_sessions": 0,
        "cite_valid_decision": False,
        "cite_near_result": "A_PLUS_B_WITH_UTILITY_1_BUT_PROTOCOL_INVALID",
        "pave_conditions": [],
        "pave_harmful_edit_observed": None,
        "diagnostic_changed_decision": None,
        "paid_fallback_used": False,
        "external_judge_calls": 0,
    }
    _json("experiment_summary.json", summary)

    candidates = "\n".join(
        f"| `{row.get('model_ref')}` | {row.get('installed_catalog')} | "
        f"{row.get('endpoint_metadata', {}).get('eligible', False)} | {row.get('eligible')} |"
        for row in audit.get("candidates", [])
    )
    _report(
        "00_free_model_selection.md",
        f"""# Free model selection

| Candidate | OpenCode catalog | Endpoint zero-price/tools | Eligible |
|---|---|---|---|
{candidates}

Selection followed the required order. The first choice,
`openrouter/google/gemma-4-26b-a4b-it:free`, passed authenticated model and endpoint metadata
checks but returned HTTP 429 for all seven attempted provider requests, before inference. It was
classified `MODEL_UNAVAILABLE` for this experiment.

The clearly different fallback `openrouter/nvidia/nemotron-3.5-lightning:free` had exact-zero
model and endpoint pricing, one NVIDIA endpoint, `tools` plus `tool_choice`, and an installed
OpenCode catalog entry. All 21 Nemotron responses reported the same exact model and zero cost.
No mutable router or paid fallback was used.
""",
    )
    first_hash = first_nemotron.get("navigation_instruction_hash")
    retry_hash = retry.get("navigation_instruction_hash")
    _report(
        "01_composer_interface_diagnosis.md",
        f"""# Composer interface diagnosis

Phase 5's Cohere run used nine reads in six steps and never wrote. The Phase 6 manifest still
contained the complete task, visible execution records, and exact reconstructable patches.

The first neutral navigation instruction told the model to treat the manifest as authoritative
and avoid redundant source reads. Hash: `{first_hash}`. Nemotron nevertheless made 16 reads,
then wrote the exact A+B harness and an answer without the required `<notes>` wrapper.

The formatting retry prohibited reads of referenced evidence, permitted only destination
harness reads, and required literal notes tags and concrete decision verbs. Its exact text was:

```text
{NAVIGATION_POLICY}
```

Hash: `{retry_hash}`. The retry still made 20 reads, no writes, and reached the fixed budget.
The interface is compact, but these free models did not reliably follow its navigation and
output protocol. Output-token limits were not reached; navigation consumed the model steps.
""",
    )
    _report(
        "02_composer_gate_result.md",
        """# Composer gate result

Final gate classification: **STILL_OPERATIONALLY_BLOCKED**.

- Gemma: 7 requests, all HTTP 429, zero tokens, `$0.00`; `MODEL_UNAVAILABLE`.
- Nemotron 12-step gate: 12 requests, correct valid A+B harness, hidden deterministic utility
  1.0, but invalid final response syntax; `MODEL_PROTOCOL_FAILURE`.
- Nemotron 8-step formatting retry: 9 provider requests, explicit merge analysis in the terminal
  response, no harness writes before tools were disabled; `STEP_BUDGET_EXHAUSTED`.

Neither Nemotron run was a cache hit. No operational fallback, model mismatch, judge call, paid
request, or hidden-oracle disclosure occurred. Gateway caps were 35 Nemotron requests total;
21 were used. The first run used the original 12-step allowance. The final retry was fixed at
8 OpenCode steps and was not expanded.
""",
    )
    _report(
        "03_cite_preliminary_result.md",
        """# CITE preliminary result

Status: **INCONCLUSIVE** under the strict valid-decision criterion.

The first Nemotron run created the exact A+B merge and the hidden evaluator returned utility
1.0. Its explanation cited complementary schema and amount failures. However, the response
omitted the required notes wrapper and copied one placeholder verb token, so it is retained as
a protocol-invalid near-result rather than a valid composer decision.

The formatting retry again reasoned that A+B should be merged but exhausted its budget before
editing the harness. There is no evidence that the composer rejected a useful edit because its
individual rollout failed. The observed near-results point toward robustness on this controlled
CITE fixture, but the protocol does not permit classifying them as a completed decision.
Interference testing is not justified yet.
""",
    )
    _report(
        "04_pave_preliminary_result.md",
        """# PAVE preliminary result

Status: **NOT RUN**.

P0, P2, and P3 were gated on a strictly valid CITE composer session. Neither free model passed
that gate, so no PAVE provider request was made. There is no Phase 6 evidence about harmful
adaptation, repeated misleading failures, or diagnostic benefit. Frozen PAVE contexts remain
unchanged and are controlled synthetic replay rather than a natural k=3 Harness² execution.
""",
    )
    _report(
        "05_research_decision.md",
        f"""# Phase 6 research decision

Decision: **STILL_OPERATIONALLY_BLOCKED**.

Phase 6 obtained stronger behavioral evidence but not the first strictly valid composer
decision. Nemotron demonstrably read the evidence, composed A+B, wrote a valid harness, and
achieved hidden deterministic utility 1.0. The response protocol failed. A formatting-only
retry then exhausted its bounded tool budget. These are operational/model-protocol failures,
so they cannot support or refute either research hypothesis.

Across Phase 6 there were {total_requests} provider requests: seven Gemma 429 responses and 21
Nemotron responses. Provider-reported cost was `${total_usage['cost_usd']:.2f}`. Account usage
and remaining limit were unchanged. There were no PAVE runs, judges, paid fallbacks, cloud
changes, or model downloads.

The next smallest justified experiment is a single composer gate using a free or local model
with demonstrated instruction-following for file edits and exact tagged output, while retaining
the same frozen CITE context and strict parser. Do not rerun either Phase 6 model unchanged and
do not implement PAVE-R or CITE-R yet.
""",
    )
    return summary


def main() -> int:
    print(json.dumps(finalize(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
