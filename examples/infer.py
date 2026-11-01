"""Make a small model-backed inference through Harness²'s OpenCode channel.

    python examples/infer.py --check-only
    python examples/infer.py --prompt "What is 17 + 25? Reply with just the number."

Loads the repository's .env through harness2.config. A real run uses the model API
and saves the prompt, response, and metadata under runs/inference/ by default.
For a credential-free workflow, run examples/quickstart.py custom instead.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from harness2 import config
from harness2.core.proposer import Proposer, ProposerError
from harness2.core.spec import resolve_channel_model
from harness2.substrate.opencode import OpencodeSubstrate


def check_ready(model: str) -> None:
    """Check the channel and Vertex credentials without calling a model."""
    if not re.fullmatch(r"[^/\s]+/\S+", model):
        raise ValueError("Set HARNESS2_SOLVER_MODEL in .env or pass --model provider/model")
    vertex = model.startswith("google-vertex/")
    if vertex and not config.VERTEX_PROJECT:
        raise config.ConfigError("Set GOOGLE_CLOUD_PROJECT in .env to your Google Cloud project ID")
    OpencodeSubstrate().preflight()
    if vertex:
        # Never print or save the access token. gcloud can refresh existing ADC here.
        result = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode:
            raise config.ConfigError(
                "Google ADC refresh failed. Check network access and run "
                "gcloud auth application-default login in your terminal."
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--prompt", default="What is 17 + 25? Reply with just the number.")
    parser.add_argument("--model", default=config.SOLVER_MODEL_OC, help="OpenCode provider/model")
    parser.add_argument("--check-only", action="store_true", help="check setup without model calls")
    parser.add_argument("--timeout", type=int, default=120, help="session timeout in seconds")
    parser.add_argument("--steps", type=int, default=8, help="maximum agent steps")
    parser.add_argument("--output", type=Path, help="directory for the response and audit files")
    args = parser.parse_args(argv)
    if args.timeout < 1 or args.steps < 1:
        parser.error("--timeout and --steps must be positive")
    if not args.prompt.strip():
        parser.error("--prompt must not be empty")
    try:
        check_ready(args.model)
        if args.check_only:
            print(f"Ready for inference: {args.model}. Model availability has not been tested.")
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = (
            (args.output or config.RUNS / "inference" / f"{stamp}-{uuid4().hex[:8]}")
            .expanduser()
            .resolve()
        )
        channel = resolve_channel_model(
            "opencode", args.model, steps=args.steps, timeout=args.timeout
        )
        # A failed smoke test should return promptly rather than retry a paid session.
        proposer = Proposer(channel, audit_dir=output / "audit", attempts=1)
        reply = proposer.call(args.prompt, None, "inference")
        output.mkdir(parents=True, exist_ok=True)
        (output / "response.txt").write_text(reply.text + "\n", encoding="utf-8")
        (output / "result.json").write_text(
            json.dumps(
                {
                    "model": args.model,
                    "prompt": args.prompt,
                    "response": reply.text,
                    "cost_usd": reply.cost_usd,
                    "wall_s": reply.wall_s,
                    "attempts": reply.attempts,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(reply.text)
        print(f"Saved response and audit: {output}", file=sys.stderr)
        return 0
    except (OSError, ValueError, RuntimeError, ProposerError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
