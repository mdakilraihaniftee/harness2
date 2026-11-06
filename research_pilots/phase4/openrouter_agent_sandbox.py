#!/usr/bin/env python3
"""Networkless agent sandbox that can reach only the mounted OpenRouter gateway socket."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def provider_overlay(original: str) -> str:
    """Route only OpenRouter's fetch implementation through the mounted Unix socket."""
    old = '''    openrouter: () =>
      Effect.succeed({
        autoload: false,
        options: {
          headers: {
            "HTTP-Referer": "https://opencode.ai/",
            "X-Title": "opencode",
          },
        },
      }),'''
    new = '''    openrouter: () =>
      Effect.succeed({
        autoload: false,
        options: {
          apiKey: "harness2-gateway",
          fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
            const headers = new Headers(init?.headers)
            headers.set("Authorization", "Bearer harness2-gateway")
            return fetch(input, { ...init, headers, unix: "/run/harness2-gateway/openrouter.sock" } as any)
          },
          headers: {
            "HTTP-Referer": "https://opencode.ai/",
            "X-Title": "opencode",
          },
        },
      }),'''
    source = original.replace(old, new)
    if source == original or "openrouter.sock" not in source:
        raise ValueError("OpenRouter provider overlay could not be generated")
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    workspace = args.workspace.resolve(strict=True)
    root = Path(__file__).resolve().parents[2]
    if not (workspace.is_relative_to(root / "runs") or workspace.is_relative_to("/tmp")):
        parser.error("workspace must be staged under runs/ or /tmp/")
    ca = Path(os.environ["HARNESS2_GATEWAY_CA"]).resolve(strict=True)
    gateway_socket = Path(os.environ["HARNESS2_GATEWAY_SOCKET"]).resolve(strict=True)
    models_snapshot = Path(os.environ["HARNESS2_MODELS_SNAPSHOT"]).resolve(strict=True)
    bwrap = shutil.which("bwrap")
    if not bwrap:
        parser.exit(1, "BLOCKED: Bubblewrap is required.\n")

    provider_source = root / "dependencies/opencode/packages/opencode/src/provider/provider.ts"
    provider_overlay_path = workspace / ".harness2-openrouter-provider.ts"
    original = provider_source.read_text(encoding="utf-8")
    try:
        source = provider_overlay(original)
    except ValueError as exc:
        parser.exit(1, f"BLOCKED: {exc}.\n")
    provider_overlay_path.write_text(source, encoding="utf-8")

    bubblewrap = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--cap-drop",
        "ALL",
    ]
    readonly = [Path(p) for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc/ssl/certs")]
    readonly += [
        Path(sys.base_prefix).resolve(),
        root / ".venv",
        root / "dependencies/opencode",
        root / "dependencies/tools",
    ]
    for source_path in dict.fromkeys(readonly):
        if source_path.exists():
            bubblewrap += ["--ro-bind", str(source_path), str(source_path)]
    bubblewrap += [
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/home/sandbox",
        "--ro-bind",
        str(ca),
        "/etc/harness2-gateway-ca.pem",
        "--ro-bind",
        str(models_snapshot),
        "/etc/harness2-models.json",
        "--dir",
        "/run/harness2-gateway",
        "--bind",
        str(gateway_socket),
        "/run/harness2-gateway/openrouter.sock",
        "--ro-bind",
        str(provider_overlay_path),
        str(provider_source),
        "--bind",
        str(workspace),
        str(workspace),
        "--chdir",
        str(workspace),
        "--clearenv",
    ]
    environment = {
        "HOME": "/home/sandbox",
        "PATH": f"{root}/.venv/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "XDG_DATA_HOME": str(workspace / ".ocdata"),
        "XDG_STATE_HOME": str(workspace / ".ocstate"),
        "NODE_EXTRA_CA_CERTS": "/etc/harness2-gateway-ca.pem",
        "OPENROUTER_API_KEY": "harness2-gateway",
        "OPENCODE_MODELS_PATH": "/etc/harness2-models.json",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
    }
    for key in ("OPENCODE_PERMISSION", "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX"):
        if key in os.environ:
            environment[key] = os.environ[key]
    for key, value in environment.items():
        bubblewrap += ["--setenv", key, value]
    return subprocess.call([*bubblewrap, "--", *command])


if __name__ == "__main__":
    raise SystemExit(main())

