"""Read-only OpenRouter and local-runtime audit with fail-closed free-model checks."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from harness2 import config

from . import FALLBACK_MODEL, PREFERRED_MODEL, REPO_ROOT

OPENROUTER_ORIGIN = "https://openrouter.ai"
SAVED_ACCOUNT_FIELDS = (
    "limit",
    "limit_remaining",
    "usage",
    "usage_daily",
    "usage_monthly",
    "is_free_tier",
)
REQUIRED_TOOL_PARAMETERS = {"tools", "tool_choice"}


class AuditBlocked(RuntimeError):
    """The route cannot be proven zero-cost and must not be called."""


def _get_json(path: str, *, api_key: str = "", timeout: int = 30) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "harness2-phase5-audit/1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(OPENROUTER_ORIGIN + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(10 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        # Never retain provider response bodies: they can contain account details.
        raise AuditBlocked(f"provider metadata request returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AuditBlocked(f"provider metadata request failed: {type(exc).__name__}") from exc
    try:
        value = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuditBlocked("provider metadata response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise AuditBlocked("provider metadata response was not an object")
    return value


def _zero(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return False


def validate_zero_pricing(model: dict[str, Any], *, expected_id: str) -> dict[str, Any]:
    """Require an exact free variant and zero in every advertised billable category."""
    actual = model.get("id")
    if actual != expected_id:
        raise AuditBlocked(f"model identity mismatch: expected {expected_id}, received {actual!r}")
    if not expected_id.endswith(":free"):
        raise AuditBlocked("model identifier is not an explicit :free variant")
    pricing = model.get("pricing")
    if not isinstance(pricing, dict) or not pricing:
        raise AuditBlocked("pricing metadata is missing or empty")
    unknown = {key: value for key, value in pricing.items() if not _zero(value)}
    if unknown:
        raise AuditBlocked("one or more advertised pricing categories are positive or unknown")
    supported = set(model.get("supported_parameters") or [])
    missing_tools = sorted(REQUIRED_TOOL_PARAMETERS - supported)
    if missing_tools:
        raise AuditBlocked("model metadata lacks required tool parameters: " + ", ".join(missing_tools))
    return {
        "id": actual,
        "name": model.get("name"),
        "context_length": model.get("context_length"),
        "pricing": {str(key): str(value) for key, value in sorted(pricing.items())},
        "all_advertised_prices_zero": True,
        "supported_parameters": sorted(supported),
        "tool_compatible": True,
    }


def installed_catalog() -> dict[str, Any]:
    path = Path.home() / ".cache/opencode/models.json"
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file(), "models": {}}
    if not path.is_file():
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data.get("openrouter", {}).get("models", {})
    except (OSError, ValueError, AttributeError):
        return result
    if not isinstance(models, dict):
        return result
    for model_id, metadata in models.items():
        if model_id.endswith(":free") or model_id.startswith("qwen/qwen3-coder"):
            record = metadata if isinstance(metadata, dict) else {}
            result["models"][model_id] = {
                "tool_call": record.get("tool_call"),
                "cost": record.get("cost"),
                "limit": record.get("limit"),
            }
    return result


def account_status(api_key: str) -> dict[str, Any]:
    payload = _get_json("/api/v1/key", api_key=api_key)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise AuditBlocked("key metadata response did not contain data")
    return {field: data.get(field) for field in SAVED_ACCOUNT_FIELDS}


def _safe_model_get(model_id: str, api_key: str) -> tuple[dict[str, Any] | None, str]:
    author, slug = model_id.split("/", 1)
    path = "/api/v1/model/" + urllib.parse.quote(author, safe="") + "/" + urllib.parse.quote(slug, safe=":")
    try:
        payload = _get_json(path, api_key=api_key)
    except AuditBlocked as exc:
        return None, str(exc)
    data = payload.get("data")
    return (data, "") if isinstance(data, dict) else (None, "model response lacked data")


def provider_models(api_key: str, catalog: dict[str, Any]) -> dict[str, Any]:
    preferred_id = PREFERRED_MODEL.removeprefix("openrouter/")
    preferred, preferred_error = _safe_model_get(preferred_id, api_key)
    preferred_result: dict[str, Any] = {
        "requested_id": preferred_id,
        "available": preferred is not None,
        "installed_catalog": preferred_id in catalog.get("models", {}),
        "eligible": False,
        "blocker": preferred_error,
    }
    if preferred is not None:
        try:
            preferred_result.update(validate_zero_pricing(preferred, expected_id=preferred_id))
            preferred_result["eligible"] = preferred_result["installed_catalog"]
            if not preferred_result["installed_catalog"]:
                preferred_result["blocker"] = "exact model is absent from the installed OpenCode catalog"
        except AuditBlocked as exc:
            preferred_result["blocker"] = str(exc)

    # Enumerate alternatives from the authenticated catalog. Store only free, tool-capable
    # records which also exist in the installed OpenCode snapshot.
    alternatives: list[dict[str, Any]] = []
    try:
        listed = _get_json("/api/v1/models", api_key=api_key).get("data", [])
    except AuditBlocked:
        listed = []
    installed = catalog.get("models", {})
    if isinstance(listed, list):
        for item in listed:
            if not isinstance(item, dict) or not str(item.get("id", "")).endswith(":free"):
                continue
            model_id = str(item["id"])
            try:
                safe = validate_zero_pricing(item, expected_id=model_id)
            except AuditBlocked:
                continue
            if model_id not in installed:
                continue
            alternatives.append(safe | {"installed_catalog": True})
    alternatives.sort(key=lambda row: row["id"])
    selected = next(
        (row for row in alternatives if row["id"] == FALLBACK_MODEL.removeprefix("openrouter/")),
        None,
    )
    return {
        "preferred": preferred_result,
        "eligible_alternatives": alternatives,
        "selected": selected,
        "selected_ref": FALLBACK_MODEL if selected else None,
    }


def local_feasibility() -> dict[str, Any]:
    def output(argv: list[str]) -> str:
        try:
            return subprocess.run(
                argv, check=False, capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""

    mem = output(["free", "-h"])
    disk = output(["df", "-h", str(REPO_ROOT)])
    gpu = output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    weights: list[str] = []
    for parent in (Path.home() / ".cache", Path.home() / "ARGUS/checkpoints"):
        if parent.exists():
            weights.extend(str(path) for path in list(parent.rglob("*.gguf"))[:20])
            weights.extend(str(path) for path in list(parent.rglob("*.safetensors"))[:20])
    runtimes = {name: shutil.which(name) for name in ("ollama", "vllm", "llama-server")}
    usable = bool(gpu and any(runtimes.values()) and weights)
    return {
        "python": platform.python_version(),
        "memory_summary": mem.splitlines()[:2],
        "disk_summary": disk.splitlines()[-1:] if disk else [],
        "gpu": gpu or None,
        "runtimes": runtimes,
        "existing_weight_file_count_sampled": len(weights),
        "existing_weight_examples": weights[:5],
        "tool_capable_local_route_ready": usable,
        "status": "AVAILABLE" if usable else "UNAVAILABLE_NO_READY_RUNTIME",
    }


def run_audit() -> dict[str, Any]:
    config.load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    env_presence = {
        name: bool(os.environ.get(name))
        for name in (
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "CODEX_AUTH_MODE",
            "OPENROUTER_API_KEY",
            "OPENROUTER_BASE_URL",
        )
    }
    if not api_key:
        raise AuditBlocked("OPENROUTER_API_KEY is absent")
    catalog = installed_catalog()
    return {
        "environment_presence": env_presence,
        "account": account_status(api_key),
        "catalog": catalog,
        "provider": provider_models(api_key, catalog),
        "local": local_feasibility(),
    }

