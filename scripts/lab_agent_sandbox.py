#!/usr/bin/env python3
"""Offline agent sandbox profile: separate namespaces, staged files, NO network.

Contract: lab_agent_sandbox.py --workspace /absolute/workspace -- command args...

This default-deny profile is usable for isolation probes, not live Vertex calls.
A separately reviewed model/auth gateway is required for live operation. No
host ADC, .env, task.json, Git checkout, or Docker socket is mounted.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    workspace = args.workspace.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    if workspace == root or workspace in root.parents or workspace == Path.home():
        parser.error("mount a staged agent workspace, not a repository or home directory")
    if not (workspace.is_relative_to(root / "runs") or workspace.is_relative_to("/tmp")):
        parser.error("this profile only mounts staged workspaces under runs/ or /tmp/")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        parser.exit(1, "BLOCKED: Bubblewrap is unavailable.\n")
    cmd = [bwrap, "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL"]
    readonly = [Path(p) for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc/ssl/certs")]
    readonly += [
        Path(sys.base_prefix).resolve(),
        (root / ".venv/bin/python").resolve().parent.parent,
        (root / ".venv/bin/python").readlink().parent.parent,
        root / ".venv",
        root / "dependencies/harvey-labs/.venv",
        root / "dependencies/opencode",
        root / "dependencies/tools",
    ]
    for source in dict.fromkeys(readonly):
        if source.exists():
            cmd += ["--ro-bind", str(source), str(source)]
    cmd += [
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/home/sandbox",
        "--bind",
        str(workspace),
        str(workspace),
    ]
    if (workspace / "documents").is_dir():
        cmd += ["--ro-bind", str(workspace / "documents"), str(workspace / "documents")]
    cmd += ["--chdir", str(workspace), "--clearenv"]
    environment = {
        "HOME": "/home/sandbox",
        "PATH": f"{root}/.venv/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "XDG_DATA_HOME": str(workspace / ".ocdata"),
        "XDG_STATE_HOME": str(workspace / ".ocstate"),
    }
    for key in (
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_VERTEX_PROJECT",
        "GOOGLE_VERTEX_LOCATION",
        "VERTEXAI_LOCATION",
        "OPENCODE_PERMISSION",
        "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX",
        "LAB_DOC_PARSER",
    ):
        if key in os.environ:
            environment[key] = os.environ[key]
    for key, value in environment.items():
        cmd += ["--setenv", key, value]
    return subprocess.call(cmd + ["--", *command])


if __name__ == "__main__":
    raise SystemExit(main())
