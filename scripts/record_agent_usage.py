"""Relay an agent's stdout unchanged and record usage-only JSON events outside its sandbox."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", required=True)
    parser.add_argument("--bun", required=True)
    parser.add_argument("--telemetry", required=True, type=Path)
    args, agent_args = parser.parse_known_args()
    if agent_args[:1] == ["--"]:
        agent_args = agent_args[1:]
    workspace = Path.cwd()
    if "--dir" in agent_args:
        workspace = Path(agent_args[agent_args.index("--dir") + 1]).resolve()
    command = [args.launcher, "--workspace", str(workspace), "--", args.bun, *agent_args]
    started = time.monotonic()
    record = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "workspace": str(workspace),
        "usage_events": [],
    }
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        for line in process.stdout:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
            try:
                event = json.loads(line)
                part = event.get("part") or {}
                if (part.get("type") or event.get("type")) == "step-finish":
                    record["usage_events"].append(
                        {
                            "tokens": part.get("tokens"),
                            "cost_usd": part.get("cost"),
                        }
                    )
            except (ValueError, AttributeError):
                pass
        code = process.wait()
    record.update(exit_code=code, wall_s=round(time.monotonic() - started, 3))
    args.telemetry.mkdir(parents=True, exist_ok=True)
    (args.telemetry / f"{uuid4().hex}.json").write_text(json.dumps(record, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
