#!/usr/bin/env python3
"""Live LAB sandbox: staged filesystem plus localhost-only network access."""

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
    if not (workspace.is_relative_to(root / "runs") or workspace.is_relative_to("/tmp")):
        parser.error("workspace must be staged under runs/ or /tmp/")
    ca = Path(os.environ["HARNESS2_GATEWAY_CA"]).resolve(strict=True)
    gateway_socket = Path(os.environ["HARNESS2_GATEWAY_SOCKET"]).resolve(strict=True)
    models_snapshot = Path(os.environ["HARNESS2_MODELS_SNAPSHOT"]).resolve(strict=True)
    bwrap = shutil.which("bwrap")
    if not bwrap:
        parser.exit(1, "BLOCKED: Bubblewrap is required.\n")
    provider_source = root / "dependencies/opencode/packages/opencode/src/provider/provider.ts"
    provider_overlay = workspace / ".harness2-provider.ts"
    original = provider_source.read_text()
    source = original.replace(
        'if (model.providerID === "google-vertex" && !model.api.npm.includes("@ai-sdk/openai-compatible")) {\n'
        "          delete options.fetch\n        }",
        'if (model.providerID === "google-vertex" && !model.api.npm.includes("@ai-sdk/openai-compatible") '
        '&& false) {\n'
        "          delete options.fetch\n        }",
    )
    source = source.replace(
        '            const { GoogleAuth } = await import("google-auth-library")\n'
        "            const auth = new GoogleAuth()\n"
        "            const client = await auth.getApplicationDefault()\n"
        "            const token = await client.credential.getAccessToken()\n"
        "\n"
        "            const headers = new Headers(init?.headers)\n"
        '            headers.set("Authorization", `Bearer ${token.token}`)\n'
        "\n"
        "            return fetch(input, { ...init, headers })",
        '            const gateway = "/run/harness2-gateway/vertex.sock"\n'
        "            const headers = new Headers(init?.headers)\n"
        '            headers.set("Authorization", "Bearer harness2-gateway")\n'
        "            return fetch(input, { ...init, headers, unix: gateway } as any)",
    )
    source = source.replace(
        "          project,\n          location,\n          fetch: async",
        "          project,\n"
        "          location,\n"
        '          apiKey: "harness2-gateway",\n'
        "          baseURL: `https://${location === \"global\" ? \"\" : location + \"-\"}aiplatform.googleapis.com/"
        "v1beta1/projects/${project}/locations/${location}/publishers/google`,\n"
        "          fetch: async",
    )
    if (
        source == original
        or "apiKey: \"harness2-gateway\"" not in source
        or "unix: gateway" not in source
        or "&& false" not in source
    ):
        parser.exit(1, "BLOCKED: OpenCode provider overlay could not be generated.\n")
    provider_overlay.write_text(source)
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
        (root / ".venv/bin/python").resolve().parent.parent,
        (root / ".venv/bin/python").readlink().parent.parent,
        root / ".venv",
        root / "dependencies/harvey-labs/.venv",
        root / "dependencies/opencode",
        root / "dependencies/tools",
    ]
    for source in dict.fromkeys(readonly):
        if source.exists():
            bubblewrap += ["--ro-bind", str(source), str(source)]
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
        "/run/harness2-gateway/vertex.sock",
        "--ro-bind",
        str(provider_overlay),
        str(provider_source),
        "--bind",
        str(workspace),
        str(workspace),
    ]
    if (workspace / "documents").is_dir():
        bubblewrap += ["--ro-bind", str(workspace / "documents"), str(workspace / "documents")]
    bubblewrap += ["--chdir", str(workspace), "--clearenv"]
    environment = {
        "HOME": "/home/sandbox",
        "PATH": f"{root}/.venv/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "XDG_DATA_HOME": str(workspace / ".ocdata"),
        "XDG_STATE_HOME": str(workspace / ".ocstate"),
        "NODE_EXTRA_CA_CERTS": "/etc/harness2-gateway-ca.pem",
        "HARNESS2_VERTEX_UNIX_SOCKET": "/run/harness2-gateway/vertex.sock",
        "GOOGLE_VERTEX_API_KEY": "harness2-gateway",
        "OPENCODE_MODELS_PATH": "/etc/harness2-models.json",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
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
        bubblewrap += ["--setenv", key, value]
    return subprocess.call([*bubblewrap, "--", *command])


if __name__ == "__main__":
    raise SystemExit(main())
