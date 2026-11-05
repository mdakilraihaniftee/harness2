# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Typed, secret-free model routing configuration.

OpenCode remains the provider transport.  This module resolves roles and prepares
provider-scoped subprocess environments; it deliberately does not implement another HTTP
client.  Resolution order is CLI, profile, environment, legacy defaults.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from . import config

SCHEMA_VERSION = 1
ROLES = ("solver", "improver", "selector", "judge")

PROVIDER_ALIASES = {
    "google": "google-vertex",
    "vertex": "google-vertex",
    "google_vertex": "google-vertex",
    "open-router": "openrouter",
}
PROVIDERS = ("openai", "openrouter", "google-vertex", "anthropic", "custom")
DEFAULT_CREDENTIAL_ENV = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "custom": "HARNESS2_CUSTOM_API_KEY",
    "google-vertex": None,
}
DEFAULT_BASE_URL_ENV = {
    "openai": "OPENAI_BASE_URL",
    "custom": "HARNESS2_CUSTOM_BASE_URL",
}

# These values are removed before a provider-specific subprocess environment is built.
# ADC is file/OAuth based and is intentionally not replaced with a dummy global key.
SECRET_ENV_NAMES = frozenset(
    {
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "HARNESS2_CUSTOM_API_KEY",
        "HARNESS2_CODEX_API_KEY",
        "HARNESS2_JUDGE_API_KEY",
        "VERTEX_PROXY_KEY",
        "JUDGE_API_KEY",
    }
)
ENDPOINT_ENV_NAMES = frozenset(
    {
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_BEDROCK_BASE_URL",
        "HARNESS2_CUSTOM_BASE_URL",
    }
)
_MODEL_PART = re.compile(r"^[^\s\x00-\x1f]+$")
_PROFILE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _canonical_provider(value: str) -> str:
    out = PROVIDER_ALIASES.get(value.strip().lower(), value.strip().lower())
    if out not in PROVIDERS:
        raise config.ConfigError(
            f"unknown provider {value!r}; expected one of {', '.join(PROVIDERS)}"
        )
    return out


def _endpoint_identity(url: str | None) -> str:
    """Stable endpoint identity with credentials, query strings and paths undisclosed."""
    if not url:
        return "default"
    try:
        parsed = urlsplit(url)
        normalized = f"{parsed.scheme.lower()}://{(parsed.hostname or '').lower()}:{parsed.port or ''}{parsed.path}"
    except (TypeError, ValueError):
        normalized = url
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"configured#{digest}"


@dataclass(frozen=True)
class ModelSpec:
    """One role's provider route. Values are identifiers or environment references, not keys."""

    provider: str
    model_id: str
    base_url: str | None = None
    credential_env: str | None = None
    options: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        provider = _canonical_provider(self.provider)
        object.__setattr__(self, "provider", provider)
        model_id = self.model_id.strip().strip("/")
        if not model_id or not _MODEL_PART.fullmatch(model_id) or model_id.startswith("."):
            raise config.ConfigError(f"invalid {provider} model identifier {self.model_id!r}")
        object.__setattr__(self, "model_id", model_id)
        if self.base_url:
            parsed = urlsplit(self.base_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise config.ConfigError("base_url must be an HTTP(S) endpoint")
            if parsed.username or parsed.password:
                raise config.ConfigError(
                    "base_url must not embed credentials; use credential_env instead"
                )
        cred = self.credential_env
        if cred is None:
            cred = DEFAULT_CREDENTIAL_ENV[provider]
        if cred and not re.fullmatch(r"[A-Z][A-Z0-9_]*", cred):
            raise config.ConfigError(f"credential_env must name an environment variable, got {cred!r}")
        object.__setattr__(self, "credential_env", cred)
        object.__setattr__(self, "options", tuple(sorted((str(k), str(v)) for k, v in self.options)))

    @property
    def ref(self) -> str:
        return f"{self.provider}/{self.model_id}"

    def runtime_id(self, harness: str) -> str:
        """Identifier handed to the actual runtime, not merely recorded in metadata."""
        if harness == "opencode":
            # OpenCode custom OpenAI-compatible routes use its OpenAI provider with a scoped URL.
            return f"openai/{self.model_id}" if self.provider == "custom" else self.ref
        if harness == "codex":
            return self.model_id
        raise config.ConfigError(f"unsupported execution harness {harness!r}")

    def safe_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "base_url_identity": _endpoint_identity(self.base_url),
            "credential_env": self.credential_env,
            "options": dict(self.options),
        }


def parse_model_ref(
    value: str,
    *,
    base_url: str | None = None,
    credential_env: str | None = None,
    options: Mapping[str, object] | None = None,
) -> ModelSpec:
    """Parse only the first slash; OpenRouter/Qwen IDs may contain further slashes."""
    raw = str(value or "").strip()
    if "/" not in raw:
        raise config.ConfigError(
            f"model {raw!r} must use provider/model syntax (the model portion may contain slashes)"
        )
    provider, model_id = raw.split("/", 1)
    return ModelSpec(
        provider,
        model_id,
        base_url=base_url,
        credential_env=credential_env,
        options=tuple((str(k), str(v)) for k, v in (options or {}).items()),
    )


@dataclass(frozen=True)
class RunModelConfig:
    harness: str
    solver: ModelSpec
    improver: ModelSpec
    selector: ModelSpec
    judge: ModelSpec | None
    profile: str = ""
    schema_version: int = SCHEMA_VERSION

    def role(self, name: str) -> ModelSpec | None:
        if name not in ROLES:
            raise KeyError(name)
        return getattr(self, name)

    def safe_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "harness": self.harness,
            "profile": self.profile or None,
            "roles": {
                role: (self.role(role).safe_dict() if self.role(role) else None) for role in ROLES
            },
        }

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.safe_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    @property
    def boundary(self) -> str:
        return f"model-config-{self.fingerprint}"


def _profile_path(path: Path | None = None, env: Mapping[str, str] = os.environ) -> Path:
    raw = path or env.get("HARNESS2_MODEL_PROFILES") or config.ROOT / "model_profiles.toml"
    return Path(raw).expanduser()


def load_profiles(path: Path | None = None, *, env: Mapping[str, str] = os.environ) -> dict[str, dict]:
    source = _profile_path(path, env)
    if not source.is_file():
        return {}
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise config.ConfigError(f"cannot read model profiles {source}: {exc}") from exc
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise config.ConfigError(f"{source}: [profiles] must be a table")
    for name, row in profiles.items():
        if not _PROFILE_NAME.fullmatch(name) or not isinstance(row, dict):
            raise config.ConfigError(f"{source}: invalid profile {name!r}")
    return profiles


def _spec_from_value(
    value: object, row: Mapping[str, object], role: str, env: Mapping[str, str]
) -> ModelSpec:
    if not isinstance(value, str):
        raise config.ConfigError(f"profile role {role!r} must be a provider/model string")
    if value.startswith("env:"):
        variable = value.removeprefix("env:").strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", variable):
            raise config.ConfigError(f"profile role {role!r} has invalid env reference {value!r}")
        value = env.get(variable, "")
        if not value:
            raise config.ConfigError(
                f"profile role {role!r} requires {variable}; set it to a verified provider/model id"
            )
    base_url = row.get(f"{role}_base_url") or row.get("base_url")
    base_env = row.get(f"{role}_base_url_env") or row.get("base_url_env")
    if base_url and base_env:
        raise config.ConfigError(f"profile {role}: use base_url or base_url_env, not both")
    if base_env:
        base_url = env.get(str(base_env))
    provider_name = _canonical_provider(value.split("/", 1)[0]) if "/" in value else ""
    if not base_url and provider_name:
        default_url_env = DEFAULT_BASE_URL_ENV.get(provider_name)
        if default_url_env:
            base_url = env.get(default_url_env)
    credential_env = row.get(f"{role}_credential_env") or row.get("credential_env")
    raw_options = row.get(f"{role}_options") or {}
    if raw_options and not isinstance(raw_options, dict):
        raise config.ConfigError(f"profile {role}_options must be a table")
    options = {str(k): str(v) for k, v in raw_options.items()}
    if provider_name == "google-vertex":
        options.setdefault("project", env.get("GOOGLE_CLOUD_PROJECT") or config.VERTEX_PROJECT)
        options.setdefault("location", env.get("GOOGLE_CLOUD_LOCATION") or config.VERTEX_REGION)
    return parse_model_ref(
        value,
        base_url=str(base_url) if base_url else None,
        credential_env=str(credential_env) if credential_env else None,
        options=options,
    )


def resolve_run_model_config(
    *,
    harness: str | None = None,
    substrate: str | None = None,
    model: str | None = None,
    solver_model: str | None = None,
    improver_model: str | None = None,
    selector_model: str | None = None,
    judge_model: str | None = None,
    profile: str | None = None,
    profiles_path: Path | None = None,
    env: Mapping[str, str] = os.environ,
    require_judge: bool = False,
) -> RunModelConfig:
    """Resolve CLI > profile > legacy environment/defaults without changing ``os.environ``."""
    from .harness_registry import resolve_harness

    profiles = load_profiles(profiles_path, env=env)
    selected: Mapping[str, object] = {}
    if profile:
        if profile not in profiles:
            raise config.ConfigError(
                f"unknown model profile {profile!r}; configured profiles: {sorted(profiles)}"
            )
        selected = profiles[profile]

    resolved_harness = resolve_harness(harness, substrate, str(selected.get("harness") or ""))
    legacy_solver = env.get("HARNESS2_SOLVER_MODEL") or config.SOLVER_MODEL_OC
    if resolved_harness == "codex":
        legacy_solver = env.get("HARNESS2_CODEX_MODEL") or config.SOLVER_MODEL_CX
        if legacy_solver and "/" not in legacy_solver:
            # The legacy Codex variable is intentionally bare; its endpoint is the existing
            # OpenAI-compatible bridge and its upstream provider is not inferable.
            legacy_solver = f"custom/{legacy_solver}"
    legacy_improver = env.get("HARNESS2_IMPROVER_MODEL") or config.IMPROVER_MODEL
    legacy_judge = env.get("HARNESS2_JUDGE_MODEL") or config.JUDGE_MODEL
    if legacy_judge and "/" not in legacy_judge:
        legacy_judge = f"google-vertex/{legacy_judge}"

    same = model
    values = {
        "solver": solver_model or same or selected.get("solver") or legacy_solver,
        "improver": improver_model or same or selected.get("improver") or legacy_improver,
    }
    values["selector"] = (
        selector_model or selected.get("selector") or values["improver"]
    )
    values["judge"] = judge_model or selected.get("judge") or legacy_judge or None
    for role in ("solver", "improver", "selector"):
        if not values[role]:
            raise config.ConfigError(
                f"no {role} model configured; use --{role}-model, --model-profile, or the "
                f"legacy HARNESS2_{role.upper()}_MODEL environment setting"
            )

    specs = {
        role: _spec_from_value(values[role], selected, role, env)
        for role in values
        if values[role]
    }
    if resolved_harness == "codex":
        solver = specs["solver"]
        options = dict(solver.options)
        options["codex_endpoint"] = _endpoint_identity(
            env.get("HARNESS2_CODEX_BASE_URL") or config.CODEX_BASE_URL
        )
        specs["solver"] = replace(solver, options=tuple(options.items()))
    if require_judge and "judge" not in specs:
        raise config.ConfigError(
            "no judge model configured; use --judge-model or HARNESS2_JUDGE_MODEL"
        )
    result = RunModelConfig(
        resolved_harness,
        specs["solver"],
        specs["improver"],
        specs["selector"],
        specs.get("judge"),
        profile=profile or "",
    )
    from .harness_registry import validate_run_config

    validate_run_config(result)
    return result


def provider_environment(
    spec: ModelSpec,
    base_env: Mapping[str, str] = os.environ,
    *,
    require_credential: bool = False,
) -> dict[str, str]:
    """Return a provider-scoped environment, stripping every unrelated provider secret."""
    out = {
        k: v
        for k, v in base_env.items()
        if k not in SECRET_ENV_NAMES and k not in ENDPOINT_ENV_NAMES
    }
    credential = base_env.get(spec.credential_env or "") if spec.credential_env else None
    if require_credential and spec.credential_env and not credential:
        raise config.ConfigError(
            f"{spec.credential_env} is required for {spec.provider}/{spec.model_id}; "
            "set it in .env or the shell"
        )
    if spec.provider == "custom":
        if not spec.base_url:
            raise config.ConfigError(
                "custom provider requires base_url or base_url_env in its model profile"
            )
        if credential:
            out["OPENAI_API_KEY"] = credential
        out["OPENAI_BASE_URL"] = spec.base_url
    else:
        if spec.credential_env and credential:
            out[spec.credential_env] = credential
        if spec.base_url:
            env_name = DEFAULT_BASE_URL_ENV.get(spec.provider)
            if not env_name:
                raise config.ConfigError(f"{spec.provider} does not support a profile base_url")
            out[env_name] = spec.base_url
    if spec.provider == "google-vertex":
        project = base_env.get("GOOGLE_CLOUD_PROJECT") or config.VERTEX_PROJECT
        region = base_env.get("GOOGLE_CLOUD_LOCATION") or config.VERTEX_REGION
        if project:
            out["GOOGLE_CLOUD_PROJECT"] = project
            out["GOOGLE_VERTEX_PROJECT"] = project
        if region:
            out["GOOGLE_CLOUD_LOCATION"] = region
            out["GOOGLE_VERTEX_LOCATION"] = region
            out["VERTEXAI_LOCATION"] = region
    return out


def credential_status(spec: ModelSpec, env: Mapping[str, str] = os.environ) -> str:
    if spec.provider == "google-vertex":
        project = env.get("GOOGLE_CLOUD_PROJECT") or config.VERTEX_PROJECT
        explicit = env.get("GOOGLE_APPLICATION_CREDENTIALS")
        adc = (
            Path(explicit).expanduser()
            if explicit
            else Path.home() / ".config/gcloud/application_default_credentials.json"
        )
        return "PASS" if project and adc.is_file() else "FAIL"
    return "PASS" if spec.credential_env and env.get(spec.credential_env) else "FAIL"


def redact(value: object) -> object:
    """Recursively redact common token/header/URL secret shapes for reports and diagnostics."""
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if re.search(r"key|token|secret|authorization", str(k), re.I) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<redacted>", value)
        value = re.sub(r"([?&](?:token|key|signature|sig)=)[^&\s]+", r"\1<redacted>", value, flags=re.I)
    return value


__all__ = [
    "ModelSpec",
    "RunModelConfig",
    "PROVIDERS",
    "ROLES",
    "SECRET_ENV_NAMES",
    "credential_status",
    "load_profiles",
    "parse_model_ref",
    "provider_environment",
    "redact",
    "resolve_run_model_config",
]
