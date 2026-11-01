"""Read-only reproduction audit. Never invokes a model or changes cloud resources.

    python scripts/audit_reproduction.py --upstream --cloud

Only safe configuration fields and HTTP status codes are recorded. ADC tokens
stay in process memory. Raw .env and credential files are never copied.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from harness2 import config

ROOT = config.ROOT
UPSTREAM = "https://github.com/google-research/harness2"
DOCS = ("README.md", "docs/SETUP.md", "docs/BENCHMARKS.md", "docs/EXPERIMENTS.md")
PERMISSIONS = (
    "aiplatform.endpoints.predict",
    "serviceusage.services.use",
    "serviceusage.services.get",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def request(url: str, *, token: str = "", body: dict | None = None) -> tuple[int, dict]:
    headers = {"User-Agent": "harness2-read-only-audit"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not retain API error bodies, request headers, or credential diagnostics.
        return exc.code, {}


def local_audit() -> dict:
    keys = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, _, value = line.removeprefix("export ").partition("=")
                keys[key.strip()] = "set (redacted)" if value.strip(" \"'") else "empty"
    safe = {
        "project": config.VERTEX_PROJECT,
        "location": config.VERTEX_REGION,
        "solver": config.SOLVER_MODEL_OC,
        "improver": config.IMPROVER_MODEL,
        "judge": config.JUDGE_MODEL,
    }
    missing = []
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", safe["project"] or ""):
        missing.append("GOOGLE_CLOUD_PROJECT missing or not a standard project ID")
        safe["project"] = "missing or invalid (redacted)"
    for key in ("solver", "improver"):
        if not re.fullmatch(r"[\w.-]+/[\w.@:/-]+", safe[key] or ""):
            missing.append(f"{key} must use provider/model syntax")
            safe[key] = "invalid (redacted)"
    if not re.fullmatch(r"[\w.@:/-]+", safe["judge"] or ""):
        missing.append("HARNESS2_JUDGE_MODEL missing or invalid")
        safe["judge"] = "missing or invalid (redacted)"
    if not re.fullmatch(r"[a-z0-9-]+", safe["location"] or ""):
        missing.append("GOOGLE_CLOUD_LOCATION invalid")
        safe["location"] = "invalid (redacted)"
    ignore_paths = (
        ".env",
        ".env.local",
        "runs/example.json",
        ".aws/credentials",
        ".codex/auth.json",
        "credentials.json",
        "application_default_credentials.json",
        "example.pem",
        "dependencies/codex/home/auth.json",
    )
    ignored = {
        name: subprocess.run(
            ["git", "check-ignore", "-q", name], cwd=ROOT, capture_output=True
        ).returncode
        == 0
        for name in ignore_paths
    }
    tracked = git("ls-files").splitlines()
    tracked_sensitive = [
        name
        for name in tracked
        if name == ".env"
        or (Path(name).name.startswith(".env.") and Path(name).name != ".env.example")
        or name.startswith((".aws/", ".codex/", "credentials/"))
        or Path(name).name
        in ("credentials.json", "application_default_credentials.json", "auth.json")
        or name.endswith((".pem", ".key"))
    ]
    credential_path = Path.home() / ".config/gcloud/application_default_credentials.json"
    adc_metadata = {}
    if credential_path.is_file():
        credential_data = json.loads(credential_path.read_text())
        adc_metadata = {
            "type": credential_data.get("type"),
            "quota_project_id": credential_data.get("quota_project_id"),
        }
    return {
        "commit": git("rev-parse", "HEAD"),
        "working_tree": git("status", "--short").splitlines(),
        "effective_configuration": safe,
        "env_keys_only": keys,
        "configuration_issues": missing,
        "git_ignored": ignored,
        "tracked_sensitive_paths": tracked_sensitive,
        "adc_metadata_only": adc_metadata,
    }


def upstream_audit(output: Path) -> dict:
    revision = subprocess.check_output(
        ["git", "ls-remote", UPSTREAM + ".git", "HEAD"], text=True, timeout=45
    ).split()[0]
    results = {"repository": UPSTREAM, "commit": revision, "documents": {}}
    for name in DOCS:
        url = f"https://raw.githubusercontent.com/google-research/harness2/{revision}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            upstream = response.read()
        local = (ROOT / name).read_bytes()
        destination = output / "upstream" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(upstream)
        diff = "".join(
            difflib.unified_diff(
                upstream.decode().splitlines(keepends=True),
                local.decode().splitlines(keepends=True),
                fromfile=f"upstream/{name}",
                tofile=f"local/{name}",
            )
        )
        destination.with_suffix(destination.suffix + ".diff").write_text(diff)
        results["documents"][name] = {
            "identical": local == upstream,
            "local_sha256": hashlib.sha256(local).hexdigest(),
            "upstream_sha256": hashlib.sha256(upstream).hexdigest(),
            "source": url,
        }
    return results


def cloud_audit() -> dict:
    result = {"adc": "BLOCKED", "projects": [], "model_calls": 0}
    credentials = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if credentials.returncode or not credentials.stdout.strip():
        result["reason"] = "ADC refresh failed; diagnose locally (raw diagnostics suppressed)"
        return result
    token = credentials.stdout.strip()
    result["adc"] = "PASS"
    url = "https://cloudresourcemanager.googleapis.com/v1/projects?pageSize=100"
    while url:
        status, payload = request(url, token=token)
        result["project_list_http_status"] = status
        if status != 200:
            result["reason"] = "Project discovery unavailable to this ADC principal"
            break
        for project in payload.get("projects", []):
            result["projects"].append(
                {
                    "project_id": project["projectId"],
                    "number": project["projectNumber"],
                    "state": project.get("lifecycleState"),
                }
            )
        page = payload.get("nextPageToken")
        url = (
            "https://cloudresourcemanager.googleapis.com/v1/projects?pageSize=100&pageToken="
            + urllib.parse.quote(page)
            if page
            else ""
        )
    if config.VERTEX_PROJECT:
        status, data = request(
            "https://cloudresourcemanager.googleapis.com/v1/projects/" + config.VERTEX_PROJECT,
            token=token,
        )
        result["configured_project"] = {
            "project_id": config.VERTEX_PROJECT,
            "metadata_http_status": status,
            "state": data.get("lifecycleState"),
        }
        if status == 200 and not any(
            p["project_id"] == config.VERTEX_PROJECT for p in result["projects"]
        ):
            result["projects"].append(
                {
                    "project_id": config.VERTEX_PROJECT,
                    "number": data["projectNumber"],
                    "state": data.get("lifecycleState"),
                }
            )
    # Read metadata for visible projects; do not activate services or modify IAM/billing.
    targets = list(result["projects"][:20])
    if config.VERTEX_PROJECT and not any(p["project_id"] == config.VERTEX_PROJECT for p in targets):
        targets.append(result["configured_project"])
    for project in targets:
        project_id = project["project_id"]
        number = project.get("number", project_id)
        status, data = request(
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}:testIamPermissions",
            token=token,
            body={"permissions": list(PERMISSIONS)},
        )
        project["permission_check_http_status"] = status
        project["granted_permissions"] = data.get("permissions", []) if status == 200 else None
        status, data = request(
            f"https://serviceusage.googleapis.com/v1/projects/{number}/services/aiplatform.googleapis.com",
            token=token,
        )
        project["vertex_api"] = data.get("state") if status == 200 else f"UNKNOWN (HTTP {status})"
        status, data = request(
            f"https://cloudbilling.googleapis.com/v1/projects/{project_id}/billingInfo", token=token
        )
        project["billing_enabled"] = (
            data.get("billingEnabled") if status == 200 else f"UNKNOWN (HTTP {status})"
        )
    result["model_availability"] = "BLOCKED: no generateContent, predict, or model calls authorized"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/audit-20261031")
    parser.add_argument("--upstream", action="store_true")
    parser.add_argument("--cloud", action="store_true")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "local": local_audit()}
    for enabled, name, operation in (
        (args.upstream, "upstream", lambda: upstream_audit(output)),
        (args.cloud, "cloud", cloud_audit),
    ):
        if enabled:
            try:
                report[name] = operation()
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                report[name] = {"status": "BLOCKED", "error_type": type(exc).__name__}
    path = output / "audit.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Audit written: {path}. No model calls or cloud resource changes.")
    return int(
        any(report.get(name, {}).get("status") == "BLOCKED" for name in ("upstream", "cloud"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
