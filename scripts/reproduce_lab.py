"""Prepare or run the official one-task LAB workflow. Default: offline preparation.

Paid stages require --approve-paid. Refinement additionally requires a verified
agent launcher; the bundled default-deny launcher intentionally has no network.
No Harness² core or vendored runner files are changed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from harness2 import config

ROOT = config.ROOT
SPEC = ROOT / "experiments/lab_one_task.json"
COMMON = ["--bench", "lab", "--substrate", "oc", "--k", "1", "--mode", "parallel"]
RUN = COMMON + ["--only-domains", "antitrust-competition", "--max-tasks", "1", "--workers", "1"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def persist_manifest(output: Path, identity: dict) -> None:
    path = output / "manifest.json"
    if path.exists() and json.loads(path.read_text()) != identity:
        raise ValueError("Models, inputs, or source changed; use a fresh --output directory")
    dump(path, identity)
    (output / "prompts").mkdir(exist_ok=True)
    (output / "prompts/task.md").write_text(identity["task_prompt"])
    dump(output / "prompts/profile.json", identity["prompt_profile"])
    dump(output / "prompts/base-harness.json", identity["base_harness_snapshot"])


def require_cloud_audit(path: Path) -> None:
    audit = json.loads(path.read_text())
    age = datetime.now(timezone.utc) - datetime.fromisoformat(audit["checked_at_utc"])
    if age.total_seconds() < 0 or age.total_seconds() > 86400:
        raise ValueError(
            "Refresh the read-only cloud audit; the current report is older than one day"
        )
    cloud = audit.get("cloud", {})
    candidates = cloud.get("projects", []) + [cloud.get("configured_project", {})]
    ready = any(
        project.get("project_id") == config.VERTEX_PROJECT
        and project.get("vertex_api") == "ENABLED"
        and project.get("billing_enabled") is True
        and {"aiplatform.endpoints.predict", "serviceusage.services.use"}.issubset(
            project.get("granted_permissions") or []
        )
        for project in candidates
    )
    if cloud.get("adc") != "PASS" or not ready:
        raise ValueError(
            "Cloud audit does not verify billing, enabled Vertex API, and prediction permissions for the configured project"
        )


def manifest(output: Path, spec: dict) -> dict:
    from harness2.benchmarks.lab import LabAdapter
    from harness2.core.schedule import task_stream

    adapter = LabAdapter()
    tasks = task_stream(adapter, only_domains=(spec["domain"],), max_tasks=1, seed=None)
    if tasks != {spec["domain"]: [spec["task_id"]]}:
        raise ValueError(f"Task selection changed: {tasks}")
    paths = [
        ROOT / "pyproject.toml",
        SPEC,
        *sorted((ROOT / "harness2").rglob("*.py")),
        *[
            ROOT / "scripts" / name
            for name in (
                "reproduce_lab.py",
                "record_agent_usage.py",
                "lab_agent_sandbox.py",
                "lab_agent_live_sandbox.py",
                "vertex_gateway.py",
            )
        ],
    ]
    dependencies = {}
    dependency_diffs = {}
    for name in ("harvey-labs", "opencode"):
        repo = config.DEPENDENCIES / name
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True)
        if head.strip() != config.DEPENDENCY_PINS[name]:
            raise ValueError(f"{name} revision differs from the supported pin")
        dependencies[name] = head.strip()
        diff = subprocess.check_output(["git", "-C", str(repo), "diff", "--binary", "HEAD"])
        dependency_diffs[name] = hashlib.sha256(diff).hexdigest()
    assets = json.loads((ROOT / "dependencies/ASSETS.json").read_text())
    paths += [ROOT / name for name in sorted(assets)]
    for directory in ("harness", "evaluation", "opencode", "utils"):
        paths += sorted((config.lab_repo() / directory).rglob("*.py"))
    sources = config.lab_repo() / "tasks" / spec["task_id"]
    # Materialize the official starting harness without executing it or a model.
    with tempfile.TemporaryDirectory(prefix="harness2-base-snapshot-") as tmp:
        adapter.spec = replace(adapter.spec, runs_root=Path(tmp))
        base = adapter.base_harness()
        base_tree = {
            p.relative_to(base).as_posix(): p.read_text()
            for p in sorted(base.rglob("*"))
            if p.is_file()
        }
    external_inputs = {}
    models_snapshot = os.environ.get("HARNESS2_MODELS_SNAPSHOT")
    if models_snapshot:
        snapshot = Path(models_snapshot).expanduser().resolve(strict=True)
        external_inputs["opencode_models_snapshot"] = {
            "path": str(snapshot),
            "sha256": sha(snapshot),
        }
    return {
        "experiment": spec,
        "output": str(output),
        "models": {
            "solver": config.SOLVER_MODEL_OC,
            "improver": config.IMPROVER_MODEL,
            "judge": config.JUDGE_MODEL,
        },
        "project": config.VERTEX_PROJECT,
        "location": config.VERTEX_REGION,
        "method_version": config.METHOD_VERSION,
        "git_commit": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip(),
        "dependencies": dependencies,
        "dependency_diff_sha256": dependency_diffs,
        "external_inputs": external_inputs,
        "source_hashes": {str(p.relative_to(ROOT)): sha(p) for p in paths},
        "task_hashes": {
            str(p.relative_to(sources)): sha(p) for p in sorted(sources.rglob("*")) if p.is_file()
        },
        "task_prompt": adapter.task_prompt(spec["task_id"]),
        "prompt_profile": asdict(adapter.prompts_for(spec["task_id"])),
        "base_harness_snapshot": base_tree,
        "python": sys.version,
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("harness2", "openpyxl", "python-pptx")
        },
        "commands": {
            "run": "harness2 " + shlex.join(RUN),
            "dry_run": "harness2 " + shlex.join(RUN + ["--dry-run"]),
            "refined": "harness2-judge " + shlex.join(COMMON),
            "initial": "harness2-judge " + shlex.join(COMMON + ["--bases"]),
            "report": "harness2-report " + shlex.join(COMMON),
        },
    }


def check_isolation(launcher: Path, output: Path, task_id: str) -> dict:
    """Negative controls are necessary checks, not proof against every possible bypass."""
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise ValueError("--agent-launcher must be an absolute executable file")
    with tempfile.TemporaryDirectory(prefix="harness2-isolation-") as tmp:
        parent = Path(tmp)
        workspace = parent / "workspace"
        workspace.mkdir()
        canary = parent / "outside-workspace.txt"
        canary.write_text("isolation canary")
        protected = [
            ROOT / ".env",
            Path.home() / ".config/gcloud/application_default_credentials.json",
            config.lab_repo() / "tasks" / task_id / "task.json",
            canary,
        ]
        probe = """import json, os, socket, ssl, urllib.request, urllib.error
from pathlib import Path
def readable(path):
    try:
        with open(path, "rb") as file: file.read(1)
        return True
    except OSError: return False
def reachable(host):
    try:
        with socket.create_connection((host,443), timeout=3): return True
    except OSError: return False
def https(host):
    try:
        urllib.request.urlopen("https://"+host+"/", timeout=4).close()
        return True
    except urllib.error.HTTPError: return True
    except OSError: return False
def unix_gateway():
    path = os.environ.get("HARNESS2_VERTEX_UNIX_SOCKET")
    if not path: return False
    raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    raw.settimeout(4)
    try:
        raw.connect(path)
        context = ssl.create_default_context(cafile=os.environ.get("NODE_EXTRA_CA_CERTS"))
        wrapped = context.wrap_socket(raw, server_hostname="aiplatform.googleapis.com")
        wrapped.close()
        return True
    except OSError:
        raw.close()
        return False
paths = PROTECTED
Path("write-probe.txt").write_text("ok")
print(json.dumps({"workspace_writable": True,
 "protected_readable": {p:readable(p) for p in paths},
 "forbidden_https": {h:https(h) for h in ["github.com","raw.githubusercontent.com","huggingface.co","hf.co"]},
 "direct_ip_egress": {h:reachable(h) for h in ["1.1.1.1","8.8.8.8"]},
 "model_transport_reachable": unix_gateway() or https("aiplatform.googleapis.com")}))
""".replace("PROTECTED", repr([str(p) for p in protected]))
        result = subprocess.run(
            [str(launcher), "--workspace", str(workspace), "--", sys.executable, "-c", probe],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode:
            record = {
                "status": "BLOCKED",
                "exit_code": result.returncode,
                "reason": "sandbox probe failed to execute; inspect launcher locally",
            }
        else:
            record = json.loads(result.stdout)
            safe = (
                record["workspace_writable"]
                and not any(record["protected_readable"].values())
                and not any(record["forbidden_https"].values())
                and not any(record["direct_ip_egress"].values())
            )
            record["status"] = "PASS" if safe else "FAIL"
        record.update(launcher=str(launcher), launcher_sha256=sha(launcher))
        dump(output / "isolation.json", record)
        return record


def install_launcher(launcher: Path, output: Path) -> None:
    """Override the Bun executable in this invocation, leaving the framework untouched."""
    actual_bun = config.BUN
    wrapper = output / "instrumented-bun"
    args = [
        sys.executable,
        str(ROOT / "scripts/record_agent_usage.py"),
        "--launcher",
        str(launcher),
        "--bun",
        str(actual_bun),
        "--telemetry",
        str(output / "agent-usage"),
        "--",
    ]
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys\nargs={args!r}\nos.execv(args[0],args+sys.argv[1:])\n"
    )
    wrapper.chmod(0o700)
    config.BUN = wrapper


def collect(output: Path) -> None:
    def records(pattern):
        return {str(p.relative_to(output)): json.loads(p.read_text()) for p in output.glob(pattern)}

    results = {
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "executor_metrics": records("lab/results/oc/**/metrics.json"),
        "agent_usage": records("agent-usage/*.json"),
        "summaries": records("lab/adapt/**/summary.json"),
        "refined_scores": records("lab/adapt/**/judged.json"),
        "initial_scores": records("lab/adapt/**/base_judged.json"),
        "judge_usage": None,
        "limitations": [
            "Judge token usage and cost are not exposed by the unmodified LAB judge.",
            "OpenCode cost fields are runtime estimates, not billing records; zero may mean unknown.",
            "Missing scores and token counts remain unknown, never zero-scored successes.",
        ],
    }
    events = [
        event for session in results["agent_usage"].values() for event in session["usage_events"]
    ]
    results["agent_token_totals"] = None
    results["agent_token_cost_estimate_usd"] = None
    if events:
        totals = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
        for event in events:
            tokens = event.get("tokens") or {}
            for name in ("input", "output", "reasoning"):
                totals[name] += tokens.get(name) or 0
            for name in ("read", "write"):
                totals["cache_" + name] += (tokens.get("cache") or {}).get(name) or 0
        results["agent_token_totals"] = totals
        identity = json.loads((output / "manifest.json").read_text())
        prices = identity["experiment"]["pricing"]
        if all(m.split("/")[-1] == prices["model"] for m in identity["models"].values()):
            results["agent_token_cost_estimate_usd"] = round(
                (
                    (totals["input"] + totals["cache_read"] + totals["cache_write"])
                    * prices["input_usd_per_million"]
                    + (totals["output"] + totals["reasoning"])
                    * prices["output_and_reasoning_usd_per_million"]
                )
                / 1_000_000,
                6,
            )
            results["limitations"].append(
                "Agent token estimate treats cached inputs at full input price; excludes all judge usage and other services."
            )
    dump(output / "results.json", results)
    print(f"Collected metrics and scores: {output / 'results.json'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        nargs="?",
        default="prepare",
        choices=("prepare", "check-isolation", "run", "judge", "judge-bases", "report", "collect"),
    )
    parser.add_argument("--output", type=Path, default=ROOT / "runs/reproduction/lab-one-task-v1")
    parser.add_argument(
        "--agent-launcher", type=Path, default=ROOT / "scripts/lab_agent_sandbox.py"
    )
    parser.add_argument("--approve-paid", action="store_true")
    parser.add_argument("--cloud-audit", type=Path, default=ROOT / "runs/audit-20261031/audit.json")
    args = parser.parse_args(argv)
    if args.stage in ("run", "judge", "judge-bases") and not args.approve_paid:
        parser.error("this stage may incur costs; user approval and --approve-paid are required")
    output = args.output.expanduser().resolve()
    launcher = args.agent_launcher.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    config.RUNS = output
    os.environ["HARNESS2_RUNS_DIR"] = str(output)
    spec = json.loads(SPEC.read_text())
    try:
        identity = manifest(output, spec)
        persist_manifest(output, identity)
        if args.stage in ("run", "judge", "judge-bases"):
            require_cloud_audit(args.cloud_audit.expanduser().resolve())
        if args.stage == "prepare":
            from harness2.cli.run_sweep import main as dry_run

            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = dry_run(RUN + ["--dry-run"])
            (output / "dry-run.txt").write_text(stream.getvalue())
            print(stream.getvalue(), end="")
            collect(output)
            return code
        if args.stage in ("check-isolation", "run"):
            record = check_isolation(launcher, output, spec["task_id"])
            print(json.dumps(record, indent=2))
            if record["status"] != "PASS":
                return 1
            if args.stage == "check-isolation":
                return 0
            if not record.get("model_transport_reachable"):
                raise RuntimeError(
                    "Sandbox blocks model traffic. Provision a reviewed model/auth gateway first."
                )
            install_launcher(launcher, output)
        from harness2.cli import judge, report, run_sweep

        operation, flags = {
            "run": (run_sweep.main, RUN),
            "judge": (judge.main, COMMON),
            "judge-bases": (judge.main, COMMON + ["--bases"]),
            "report": (report.main, COMMON),
            "collect": (None, []),
        }[args.stage]
        started = time.monotonic()
        code = operation(flags) if operation else 0
        dump(
            output / f"{args.stage}-timing-{time.time_ns()}.json",
            {
                "stage": args.stage,
                "wall_s": round(time.monotonic() - started, 3),
                "exit_code": code,
            },
        )
        collect(output)
        return code
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
