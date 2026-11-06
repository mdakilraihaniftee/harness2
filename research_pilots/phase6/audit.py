"""Authenticated, read-only selection of an exact zero-price Phase 6 model."""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
from pathlib import Path
from typing import Any

from harness2 import config
from research_pilots.phase5.provider_audit import (
    AuditBlocked,
    _get_json,
    _safe_model_get,
    account_status,
    installed_catalog,
    validate_zero_pricing,
)

from . import MODEL_CANDIDATES, REPORTS, RESULTS, SCHEMA_VERSION


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _endpoint_audit(model_id: str, api_key: str) -> dict[str, Any]:
    author, slug = model_id.split("/", 1)
    path = (
        "/api/v1/models/"
        + urllib.parse.quote(author, safe="")
        + "/"
        + urllib.parse.quote(slug, safe=":")
        + "/endpoints"
    )
    payload = _get_json(path, api_key=api_key)
    data = payload.get("data")
    endpoints = data.get("endpoints", []) if isinstance(data, dict) else []
    safe_endpoints: list[dict[str, Any]] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        pricing = endpoint.get("pricing")
        parameters = set(endpoint.get("supported_parameters") or [])
        prices_zero = bool(pricing) and all(
            str(value) in {"0", "0.0"} for value in pricing.values()
        )
        safe_endpoints.append(
            {
                "name": endpoint.get("name"),
                "provider_name": endpoint.get("provider_name"),
                "pricing": pricing,
                "all_prices_zero": prices_zero,
                "tool_compatible": {"tools", "tool_choice"} <= parameters,
                "supported_parameters": sorted(parameters),
                "status": endpoint.get("status"),
            }
        )
    eligible = bool(safe_endpoints) and all(
        row["all_prices_zero"] and row["tool_compatible"] for row in safe_endpoints
    )
    return {"eligible": eligible, "endpoints": safe_endpoints}


def audit_models() -> dict[str, Any]:
    config.load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise AuditBlocked("OPENROUTER_API_KEY is absent")
    catalog = installed_catalog()
    installed = catalog.get("models", {})
    rows = []
    for model_ref in MODEL_CANDIDATES:
        model_id = model_ref.removeprefix("openrouter/")
        row: dict[str, Any] = {
            "model_ref": model_ref,
            "model_id": model_id,
            "installed_catalog": model_id in installed,
            "eligible": False,
        }
        model, error = _safe_model_get(model_id, api_key)
        if model is None:
            row["blocker"] = error
            rows.append(row)
            continue
        try:
            row["model_metadata"] = validate_zero_pricing(model, expected_id=model_id)
            row["endpoint_metadata"] = _endpoint_audit(model_id, api_key)
            row["eligible"] = bool(
                row["installed_catalog"] and row["endpoint_metadata"]["eligible"]
            )
            if not row["eligible"]:
                row["blocker"] = "catalog or endpoint-level zero-price/tool gate failed"
        except AuditBlocked as exc:
            row["blocker"] = str(exc)
        rows.append(row)
    selected = next((row for row in rows if row["eligible"]), None)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if selected else "FREE_MODEL_UNAVAILABLE",
        "selection_order": list(MODEL_CANDIDATES),
        "candidates": rows,
        "selected_model": selected["model_ref"] if selected else None,
        "account": account_status(api_key),
        "inference_requests": 0,
    }


def _report(audit: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| `{row['model_ref']}` | {row.get('installed_catalog')} | "
        f"{row.get('endpoint_metadata', {}).get('eligible', False)} | "
        f"{row.get('eligible')} | {row.get('blocker', '')} |"
        for row in audit.get("candidates", [])
    )
    account = audit.get("account", {})
    return f"""# Free model selection

Status: **{audit.get('status')}**. Selected exact model: `{audit.get('selected_model')}`.

| Candidate | OpenCode catalog | Endpoint zero-price/tools | Eligible | Blocker |
|---|---|---|---|---|
{rows}

Selection followed the required order. Both authenticated model-level and endpoint-level
records had to advertise exact zero pricing for every reported category, `tools`, and
`tool_choice`. The mutable `openrouter/free` router was excluded.

The key reported `is_free_tier={account.get('is_free_tier')}`, limit
`{account.get('limit')}`, remaining `{account.get('limit_remaining')}`, daily usage
`{account.get('usage_daily')}`, and monthly usage `{account.get('usage_monthly')}`. This audit
made zero inference requests and changed no account setting.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only-provider-audit", action="store_true")
    args = parser.parse_args(argv)
    if not args.read_only_provider_audit:
        parser.error("explicit --read-only-provider-audit is required")
    try:
        audit = audit_models()
    except AuditBlocked as exc:
        audit = {
            "schema_version": SCHEMA_VERSION,
            "status": "FREE_MODEL_UNAVAILABLE",
            "blocker": str(exc),
            "inference_requests": 0,
        }
    _write_json(RESULTS / "model_audit.json", audit)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "00_free_model_selection.md").write_text(_report(audit), encoding="utf-8")
    print(json.dumps({"status": audit["status"], "selected_model": audit.get("selected_model")}))
    return 0 if audit["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())

